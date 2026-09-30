from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user_optional
from app.core.rbac import ROLE_LABELS, can_read_finance_module, can_write_finance_module, role_name
from app.modules.auth.models import User
from app.modules.condominios.models import Unidad
from app.modules.finanzas import services as finanzas_services
from app.modules.finanzas.models import (
    CuentaBancaria, EstadoImportacion, ImportacionBancaria, MovimientoImportado, TipoMovimiento,
)
from app.web.router import _resolve_condominio, templates

router = APIRouter(prefix="/app/estados-cuenta", tags=["Frontend App"])

EXPORTS_DIR = Path(__file__).resolve().parent.parent / "modules" / "finanzas" / "data" / "exports"


def _guard_read(user: User | None, request: Request):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not can_read_finance_module(user):
        return _forbidden(request, user)
    return None


def _guard_write(user: User | None, request: Request):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not can_write_finance_module(user):
        return _forbidden(request, user)
    return None


def _forbidden(request: Request, user: User):
    return templates.TemplateResponse(
        request, "forbidden.html",
        {"user": user, "active": None, "mi_rol": ROLE_LABELS.get(role_name(user), "sin asignar")},
        status_code=403,
    )


def _opt_int(value: str | None) -> int | None:
    return int(value) if value and str(value).isdigit() else None


def _parse_form_date(val: str | None) -> date | None:
    if not val:
        return None
    val = val.strip()
    try:
        return datetime.strptime(val, "%Y-%m-%d").date()
    except ValueError:
        try:
            return datetime.strptime(val, "%d/%m/%Y").date()
        except ValueError:
            return None


def _parse_form_decimal(val: str | None) -> Decimal | None:
    if not val:
        return None
    val = str(val).replace("$", "").replace(",", "").strip()
    try:
        return Decimal(val).quantize(Decimal("0.01"))
    except Exception:
        return None


@router.get("", response_class=HTMLResponse)
def estados_cuenta_list(
    request: Request, condominio_id: int | None = None,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard_read(user, request)
    if blocked:
        return blocked
    condominios, condominio = _resolve_condominio(db, condominio_id)
    ctx = {"user": user, "active": "app", "condominios": condominios, "condominio": condominio,
           "condominio_id": condominio.id if condominio else None,
           "puede_escribir": can_write_finance_module(user)}

    # Buscar archivos de muestra existentes en el servidor
    archivos_existentes = []
    if EXPORTS_DIR.exists():
        for p in EXPORTS_DIR.iterdir():
            if p.is_file() and p.suffix.lower() in (".xlsx", ".xls", ".csv", ".pdf"):
                archivos_existentes.append({
                    "nombre": p.name,
                    "tamano": f"{p.stat().st_size / 1024:.1f} KB",
                    "extension": p.suffix.lstrip(".").upper(),
                })
    ctx["archivos_existentes"] = archivos_existentes

    if condominio:
        ctx["importaciones"] = (
            db.query(ImportacionBancaria)
            .filter(ImportacionBancaria.condominio_id == condominio.id)
            .order_by(ImportacionBancaria.created_at.desc()).all()
        )
        ctx["cuentas"] = db.query(CuentaBancaria).filter(CuentaBancaria.condominio_id == condominio.id).all()
    return templates.TemplateResponse(request, "app_estados_cuenta_list.html", ctx)


@router.post("")
async def estados_cuenta_subir(
    request: Request,
    condominio_id: int = Form(...), cuenta_bancaria_id: str = Form(""),
    archivo: UploadFile = File(...),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard_write(user, request)
    if blocked:
        return blocked

    nombre = archivo.filename or "estado_de_cuenta.pdf"
    ext = Path(nombre).suffix.lower()
    es_valido = ext in (".pdf", ".xlsx", ".xls", ".csv")
    if not es_valido:
        return RedirectResponse(
            f"/app/estados-cuenta?condominio_id={condominio_id}&error=formato", status_code=303)

    contenido_bytes = await archivo.read()
    try:
        importacion = finanzas_services.crear_importacion(
            db, condominio_id, nombre, contenido_bytes, _opt_int(cuenta_bancaria_id), user.id,
        )
    except Exception as e:
        print(f"[Error importacion] {e}")
        return RedirectResponse(
            f"/app/estados-cuenta?condominio_id={condominio_id}&error=lectura", status_code=303)
    return RedirectResponse(f"/app/estados-cuenta/{importacion.id}", status_code=303)


@router.post("/cargar-existente")
def estados_cuenta_cargar_existente(
    request: Request,
    condominio_id: int = Form(...),
    nombre_archivo: str = Form(...),
    cuenta_bancaria_id: str = Form(""),
    user: User | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    """Carga y procesa un archivo ya presente en el servidor (ej. importacion_1.xlsx)."""
    blocked = _guard_write(user, request)
    if blocked:
        return blocked

    archivo_path = EXPORTS_DIR / nombre_archivo
    if not archivo_path.exists() or not archivo_path.is_file():
        return RedirectResponse(
            f"/app/estados-cuenta?condominio_id={condominio_id}&error=no_encontrado", status_code=303)

    contenido_bytes = archivo_path.read_bytes()
    try:
        importacion = finanzas_services.crear_importacion(
            db, condominio_id, nombre_archivo, contenido_bytes, _opt_int(cuenta_bancaria_id), user.id,
        )
    except Exception as e:
        print(f"[Error cargar existente] {e}")
        return RedirectResponse(
            f"/app/estados-cuenta?condominio_id={condominio_id}&error=lectura", status_code=303)

    return RedirectResponse(f"/app/estados-cuenta/{importacion.id}", status_code=303)


@router.get("/{imp_id}", response_class=HTMLResponse)
def estados_cuenta_revisar(
    imp_id: int, request: Request,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard_read(user, request)
    if blocked:
        return blocked
    importacion = db.query(ImportacionBancaria).get(imp_id)
    if not importacion:
        return RedirectResponse("/app/estados-cuenta", status_code=303)
    unidades = (
        db.query(Unidad).filter(Unidad.condominio_id == importacion.condominio_id)
        .order_by(Unidad.identificador).all()
    )

    movs = importacion.movimientos
    total_abonos = sum((m.monto for m in movs if m.tipo == TipoMovimiento.ABONO), start=Decimal("0"))
    total_cargos = sum((m.monto for m in movs if m.tipo == TipoMovimiento.CARGO), start=Decimal("0"))
    emparejados_count = sum(1 for m in movs if m.tipo == TipoMovimiento.ABONO and m.unidad_id)
    monto_listo = sum((m.monto for m in movs if m.tipo == TipoMovimiento.ABONO and m.aplicar and m.unidad_id and not m.pago_id), start=Decimal("0"))
    aplicados_count = sum(1 for m in movs if m.pago_id)

    propietarios_by_unidad = {
        u.id: (u.propietario.full_name if getattr(u, "propietario", None) else "")
        for u in unidades
    }

    ctx = {
        "user": user, "active": "app", "importacion": importacion,
        "movimientos": movs, "unidades": unidades,
        "unidades_by_id": {u.id: u.identificador for u in unidades},
        "propietarios_by_unidad": propietarios_by_unidad,
        "puede_escribir": can_write_finance_module(user),
        "TipoMovimiento": TipoMovimiento,
        "aplicada": importacion.estado == EstadoImportacion.APLICADA,
        "stats": {
            "total_movimientos": len(movs),
            "total_abonos": total_abonos,
            "total_cargos": total_cargos,
            "emparejados_count": emparejados_count,
            "monto_listo": monto_listo,
            "aplicados_count": aplicados_count,
        }
    }
    return templates.TemplateResponse(request, "app_estados_cuenta_revisar.html", ctx)


def _sync_movimientos_from_form(form, importacion, db: Session):
    """Extrae y persiste todas las modificaciones inline de la vista previa."""
    for mov in importacion.movimientos:
        if mov.pago_id:
            continue
        fecha = _parse_form_date(form.get(f"fecha_{mov.id}"))
        desc = form.get(f"descripcion_{mov.id}")
        monto = _parse_form_decimal(form.get(f"monto_{mov.id}"))
        tipo_str = form.get(f"tipo_{mov.id}")
        tipo = TipoMovimiento(tipo_str) if tipo_str in ("ABONO", "CARGO") else None
        unidad_id = _opt_int(form.get(f"unidad_{mov.id}") or "")
        aplicar = form.get(f"aplicar_{mov.id}") in ("on", "1", "true")

        finanzas_services.actualizar_movimiento_importado(
            db=db,
            movimiento=mov,
            unidad_id=unidad_id,
            aplicar=aplicar,
            fecha=fecha,
            descripcion=desc,
            monto=monto,
            tipo=tipo,
        )


@router.post("/{imp_id}/guardar")
async def estados_cuenta_guardar(
    imp_id: int, request: Request,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard_write(user, request)
    if blocked:
        return blocked
    importacion = db.query(ImportacionBancaria).get(imp_id)
    if not importacion or importacion.estado == EstadoImportacion.APLICADA:
        return RedirectResponse(f"/app/estados-cuenta/{imp_id}", status_code=303)

    form = await request.form()
    _sync_movimientos_from_form(form, importacion, db)
    return RedirectResponse(f"/app/estados-cuenta/{imp_id}?guardado=1", status_code=303)


@router.post("/{imp_id}/aplicar")
async def estados_cuenta_aplicar(
    imp_id: int, request: Request,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard_write(user, request)
    if blocked:
        return blocked
    importacion = db.query(ImportacionBancaria).get(imp_id)
    if not importacion:
        return RedirectResponse("/app/estados-cuenta", status_code=303)

    # Guarda primero cualquier cambio inline enviado con el formulario
    form = await request.form()
    if importacion.estado != EstadoImportacion.APLICADA:
        _sync_movimientos_from_form(form, importacion, db)

    try:
        aplicados = finanzas_services.aplicar_importacion(db, importacion, user.id)
    except finanzas_services.ImportacionError:
        return RedirectResponse(f"/app/estados-cuenta/{imp_id}?error=aplicada", status_code=303)
    return RedirectResponse(f"/app/estados-cuenta/{imp_id}?aplicados={aplicados}", status_code=303)


@router.post("/{imp_id}/movimientos/nuevo")
def estados_cuenta_agregar_movimiento(
    imp_id: int, request: Request,
    fecha: str = Form(...),
    descripcion: str = Form(...),
    monto: str = Form(...),
    tipo: str = Form("ABONO"),
    unidad_id: str = Form(""),
    aplicar: str = Form(""),
    user: User | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    """Inserta un movimiento manual a la importación en borrador."""
    blocked = _guard_write(user, request)
    if blocked:
        return blocked
    importacion = db.query(ImportacionBancaria).get(imp_id)
    if not importacion or importacion.estado == EstadoImportacion.APLICADA:
        return RedirectResponse(f"/app/estados-cuenta/{imp_id}", status_code=303)

    fecha_d = _parse_form_date(fecha) or date.today()
    monto_d = _parse_form_decimal(monto) or Decimal("0.00")
    tipo_enum = TipoMovimiento.ABONO if tipo == "ABONO" else TipoMovimiento.CARGO
    u_id = _opt_int(unidad_id)
    aplica_bool = (aplicar in ("on", "1", "true")) and (u_id is not None) and (tipo_enum == TipoMovimiento.ABONO)

    finanzas_services.agregar_movimiento_manual(
        db=db,
        importacion=importacion,
        fecha=fecha_d,
        descripcion=descripcion,
        monto=monto_d,
        tipo=tipo_enum,
        unidad_id=u_id,
        aplicar=aplica_bool,
    )
    return RedirectResponse(f"/app/estados-cuenta/{imp_id}?nuevo=1", status_code=303)


@router.post("/{imp_id}/movimientos/{mov_id}/eliminar")
def estados_cuenta_eliminar_movimiento(
    imp_id: int, mov_id: int, request: Request,
    user: User | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    """Elimina un movimiento de la importación si no ha sido aplicado."""
    blocked = _guard_write(user, request)
    if blocked:
        return blocked
    mov = db.query(MovimientoImportado).filter(
        MovimientoImportado.id == mov_id,
        MovimientoImportado.importacion_id == imp_id,
    ).first()
    if mov and not mov.pago_id:
        finanzas_services.eliminar_movimiento_importado(db, mov)
    return RedirectResponse(f"/app/estados-cuenta/{imp_id}?eliminado=1", status_code=303)


@router.get("/{imp_id}/excel")
def estados_cuenta_excel(
    imp_id: int, request: Request,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user or not can_read_finance_module(user):
        return RedirectResponse("/login", status_code=303)
    importacion = db.query(ImportacionBancaria).get(imp_id)
    if not importacion:
        return RedirectResponse("/app/estados-cuenta", status_code=303)
    path = finanzas_services.exportar_importacion_excel(db, importacion)
    nombre_limpio = Path(importacion.nombre_archivo).stem or f"importacion_{imp_id}"
    return FileResponse(
        path, filename=f"reporte_detallado_{nombre_limpio}.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.post("/{imp_id}/eliminar")
def estados_cuenta_eliminar(
    imp_id: int, request: Request,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard_write(user, request)
    if blocked:
        return blocked
    importacion = db.query(ImportacionBancaria).get(imp_id)
    condominio_id = importacion.condominio_id if importacion else None
    if importacion and importacion.estado != EstadoImportacion.APLICADA:
        db.delete(importacion)
        db.commit()
    return RedirectResponse(f"/app/estados-cuenta?condominio_id={condominio_id}", status_code=303)

