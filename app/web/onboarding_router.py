from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user_optional
from app.core.rbac import ROLE_LABELS, is_admin, role_name
from app.core.security import get_password_hash
from app.modules.auth.models import User
from app.modules.condominios.models import Unidad
from app.modules.finanzas import services as finanzas_services
from app.modules.finanzas.models import (
    CuentaBancaria,
    Egreso,
    Fondo,
    MetodoPago,
    MovimientoBancario,
    PartidaPresupuestal,
    Pago,
    TipoCargo,
    TipoFondo,
    TipoMovimiento,
    TipoPartida,
)
from app.modules.mantenimiento.models import Proveedor
from app.modules.onboarding import services as onboarding_services
from app.modules.onboarding.models import EstadoPaso, InvitacionResidente, PasoOnboarding
from app.modules.propietarios.models import Propietario
from app.web.router import _resolve_condominio, templates

router = APIRouter(tags=["Frontend Onboarding"])

COMPROBANTES_DIR = Path(__file__).resolve().parent.parent / "modules" / "onboarding" / "data" / "comprobantes"
COMPROBANTES_DIR.mkdir(parents=True, exist_ok=True)


def _forbidden(request: Request, user: User):
    return templates.TemplateResponse(
        request, "forbidden.html",
        {"user": user, "active": None, "mi_rol": ROLE_LABELS.get(role_name(user), "sin asignar")},
        status_code=403,
    )


def _guard(user: User | None, request: Request):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not is_admin(user):
        return _forbidden(request, user)
    return None


def _guard_finance(user: User | None, request: Request, write: bool = True):
    """Como _guard, pero también admite CONTADOR/AUDITOR (módulo Egresos, parte
    de la navegación contable — ver app/core/navigation.py)."""
    from app.core.rbac import can_read_finance_module, can_write_finance_module
    if not user:
        return RedirectResponse("/login", status_code=303)
    permitido = can_write_finance_module(user) if write else can_read_finance_module(user)
    if not permitido:
        return _forbidden(request, user)
    return None


def _to_decimal(value: str, default: str = "0") -> Decimal:
    try:
        return Decimal(value) if value not in (None, "") else Decimal(default)
    except InvalidOperation:
        return Decimal(default)


# ── Checklist principal ──────────────────────────────────────────────────────

@router.get("/onboarding", response_class=HTMLResponse)
def onboarding_index(
    request: Request, condominio_id: int | None = None,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard(user, request)
    if blocked:
        return blocked
    condominios, condominio = _resolve_condominio(db, condominio_id)
    items = onboarding_services.checklist(db, condominio.id) if condominio else []
    return templates.TemplateResponse(
        request, "onboarding_checklist.html",
        {"user": user, "active": "onboarding", "condominios": condominios, "condominio": condominio,
         "condominio_id": condominio.id if condominio else None, "items": items},
    )


@router.post("/onboarding/{paso}/marcar")
def onboarding_marcar_paso(
    paso: PasoOnboarding, request: Request, condominio_id: int = Form(...), estado: str = Form(...),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard(user, request)
    if blocked:
        return blocked
    onboarding_services.establecer_estado(db, condominio_id, paso, EstadoPaso(estado))
    return RedirectResponse(f"/onboarding?condominio_id={condominio_id}", status_code=303)


# ── Paso 1: Presupuesto ──────────────────────────────────────────────────────

@router.get("/onboarding/presupuesto", response_class=HTMLResponse)
def onboarding_presupuesto(
    request: Request, condominio_id: int | None = None, anio: int | None = None,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard(user, request)
    if blocked:
        return blocked
    condominios, condominio = _resolve_condominio(db, condominio_id)
    anio = anio or date.today().year
    ctx = {"user": user, "active": "onboarding", "condominios": condominios, "condominio": condominio,
           "condominio_id": condominio.id if condominio else None, "anio": anio}
    if condominio:
        onboarding_services.marcar_visitado(db, condominio.id, PasoOnboarding.PRESUPUESTO)
        partidas = (
            db.query(PartidaPresupuestal)
            .filter(PartidaPresupuestal.condominio_id == condominio.id, PartidaPresupuestal.anio == anio)
            .order_by(PartidaPresupuestal.tipo, PartidaPresupuestal.nombre).all()
        )
        comparativo = finanzas_services.presupuesto_comparativo(db, condominio.id, anio)
        ctx.update({"partidas": partidas, "comparativo": comparativo})
    return templates.TemplateResponse(request, "onboarding_presupuesto.html", ctx)


@router.post("/onboarding/presupuesto")
def onboarding_presupuesto_create(
    request: Request,
    condominio_id: int = Form(...), nombre: str = Form(...), tipo: str = Form(...),
    anio: int = Form(...), monto_proyectado_anual: str = Form(...),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard(user, request)
    if blocked:
        return blocked
    db.add(PartidaPresupuestal(
        condominio_id=condominio_id, nombre=nombre, tipo=TipoPartida(tipo),
        anio=anio, monto_proyectado_anual=_to_decimal(monto_proyectado_anual),
    ))
    db.commit()
    onboarding_services.marcar_completado(db, condominio_id, PasoOnboarding.PRESUPUESTO)
    return RedirectResponse(f"/onboarding/presupuesto?condominio_id={condominio_id}&anio={anio}", status_code=303)


# ── Paso 2: Bancos ───────────────────────────────────────────────────────────

@router.get("/onboarding/bancos", response_class=HTMLResponse)
def onboarding_bancos(
    request: Request, condominio_id: int | None = None,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard(user, request)
    if blocked:
        return blocked
    condominios, condominio = _resolve_condominio(db, condominio_id)
    ctx = {"user": user, "active": "onboarding", "condominios": condominios, "condominio": condominio,
           "condominio_id": condominio.id if condominio else None}
    if condominio:
        onboarding_services.marcar_visitado(db, condominio.id, PasoOnboarding.BANCOS)
        cuentas = db.query(CuentaBancaria).filter(CuentaBancaria.condominio_id == condominio.id).all()
        fondos = db.query(Fondo).filter(Fondo.condominio_id == condominio.id).order_by(Fondo.nombre).all()
        movimientos = (
            db.query(MovimientoBancario).filter(MovimientoBancario.condominio_id == condominio.id)
            .order_by(MovimientoBancario.fecha.desc()).limit(20).all()
        )
        ctx.update({"cuentas": cuentas, "fondos": fondos, "movimientos": movimientos})
    return templates.TemplateResponse(request, "onboarding_bancos.html", ctx)


@router.post("/onboarding/fondos")
def onboarding_fondo_create(
    request: Request,
    condominio_id: int = Form(...), nombre: str = Form(...), tipo_fondo: str = Form("OPERATIVO"),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard(user, request)
    if blocked:
        return blocked
    db.add(Fondo(condominio_id=condominio_id, nombre=nombre, tipo_fondo=TipoFondo(tipo_fondo)))
    db.commit()
    return RedirectResponse(f"/onboarding/bancos?condominio_id={condominio_id}", status_code=303)


@router.post("/onboarding/bancos")
def onboarding_bancos_create(
    request: Request,
    condominio_id: int = Form(...), banco: str = Form(...), clabe: str = Form(""),
    numero_cuenta: str = Form(""), titular: str = Form(""), tipo_fondo: str = Form("OPERATIVO"),
    saldo_inicial: str = Form("0"),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard(user, request)
    if blocked:
        return blocked
    db.add(CuentaBancaria(
        condominio_id=condominio_id, banco=banco, clabe=clabe or None, numero_cuenta=numero_cuenta or None,
        titular=titular or None, tipo_fondo=TipoFondo(tipo_fondo), saldo_inicial=_to_decimal(saldo_inicial),
    ))
    db.commit()
    onboarding_services.marcar_completado(db, condominio_id, PasoOnboarding.BANCOS)
    return RedirectResponse(f"/onboarding/bancos?condominio_id={condominio_id}", status_code=303)


@router.post("/onboarding/bancos/importar-movimientos")
async def onboarding_importar_movimientos(
    request: Request,
    condominio_id: int = Form(...), cuenta_bancaria_id: str = Form(""),
    archivo: UploadFile = File(...),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard(user, request)
    if blocked:
        return blocked
    content = await archivo.read()
    filas = onboarding_services.parse_tabular_upload(archivo.filename, content)
    creados = 0
    for fila in filas:
        fecha_raw = fila.get("fecha") or fila.get("Fecha")
        monto_raw = fila.get("monto") or fila.get("Monto")
        if not fecha_raw or not monto_raw:
            continue
        try:
            fecha = fecha_raw if isinstance(fecha_raw, date) else datetime.strptime(str(fecha_raw)[:10], "%Y-%m-%d").date()
            monto = _to_decimal(str(monto_raw))
        except ValueError:
            continue
        tipo_raw = str(fila.get("tipo") or fila.get("Tipo") or "ABONO").upper()
        db.add(MovimientoBancario(
            condominio_id=condominio_id,
            cuenta_bancaria_id=int(cuenta_bancaria_id) if cuenta_bancaria_id else None,
            fecha=fecha,
            descripcion=str(fila.get("descripcion") or fila.get("Descripcion") or fila.get("Descripción") or ""),
            monto=abs(monto),
            tipo=TipoMovimiento.ABONO if tipo_raw.startswith("A") else TipoMovimiento.CARGO,
        ))
        creados += 1
    db.commit()
    return RedirectResponse(f"/onboarding/bancos?condominio_id={condominio_id}", status_code=303)


# ── Paso 3: Adeudos iniciales ────────────────────────────────────────────────

@router.get("/onboarding/adeudos-iniciales", response_class=HTMLResponse)
def onboarding_adeudos(
    request: Request, condominio_id: int | None = None,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard(user, request)
    if blocked:
        return blocked
    condominios, condominio = _resolve_condominio(db, condominio_id)
    ctx = {"user": user, "active": "onboarding", "condominios": condominios, "condominio": condominio,
           "condominio_id": condominio.id if condominio else None}
    if condominio:
        onboarding_services.marcar_visitado(db, condominio.id, PasoOnboarding.ADEUDOS_INICIALES)
        unidades = db.query(Unidad).filter(Unidad.condominio_id == condominio.id).all()
        from app.modules.finanzas.models import Cargo
        adeudos = (
            db.query(Cargo).join(Unidad, Cargo.unidad_id == Unidad.id)
            .filter(Unidad.condominio_id == condominio.id, Cargo.tipo == TipoCargo.SALDO_INICIAL)
            .order_by(Cargo.created_at.desc()).all()
        )
        ctx.update({"unidades": unidades, "adeudos": adeudos, "unidades_by_id": {u.id: u.identificador for u in unidades}})
    return templates.TemplateResponse(request, "onboarding_adeudos.html", ctx)


@router.post("/onboarding/adeudos-iniciales")
def onboarding_adeudos_create(
    request: Request,
    condominio_id: int = Form(...), unidad_id: int = Form(...), monto: str = Form(...), descripcion: str = Form(""),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard(user, request)
    if blocked:
        return blocked
    finanzas_services.crear_adeudo_inicial(db, unidad_id, _to_decimal(monto), descripcion or "Saldo inicial deudor")
    onboarding_services.marcar_completado(db, condominio_id, PasoOnboarding.ADEUDOS_INICIALES)
    return RedirectResponse(f"/onboarding/adeudos-iniciales?condominio_id={condominio_id}", status_code=303)


@router.post("/onboarding/adeudos-iniciales/importar")
async def onboarding_adeudos_importar(
    request: Request,
    condominio_id: int = Form(...), archivo: UploadFile = File(...),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard(user, request)
    if blocked:
        return blocked
    content = await archivo.read()
    filas = onboarding_services.parse_tabular_upload(archivo.filename, content)
    unidades_by_ident = {
        u.identificador: u.id
        for u in db.query(Unidad).filter(Unidad.condominio_id == condominio_id).all()
    }
    for fila in filas:
        ident = str(fila.get("identificador") or fila.get("unidad") or fila.get("Unidad") or "").strip()
        monto_raw = fila.get("monto") or fila.get("Monto")
        unidad_id = unidades_by_ident.get(ident)
        if not unidad_id or not monto_raw:
            continue
        descripcion = str(fila.get("descripcion") or fila.get("Descripcion") or "Saldo inicial deudor (importado)")
        finanzas_services.crear_adeudo_inicial(db, unidad_id, _to_decimal(str(monto_raw)), descripcion)
    onboarding_services.marcar_completado(db, condominio_id, PasoOnboarding.ADEUDOS_INICIALES)
    return RedirectResponse(f"/onboarding/adeudos-iniciales?condominio_id={condominio_id}", status_code=303)


# ── Paso 4: Saldos a favor ───────────────────────────────────────────────────

@router.get("/onboarding/saldos-favor", response_class=HTMLResponse)
def onboarding_saldos_favor(
    request: Request, condominio_id: int | None = None,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard(user, request)
    if blocked:
        return blocked
    condominios, condominio = _resolve_condominio(db, condominio_id)
    ctx = {"user": user, "active": "onboarding", "condominios": condominios, "condominio": condominio,
           "condominio_id": condominio.id if condominio else None}
    if condominio:
        onboarding_services.marcar_visitado(db, condominio.id, PasoOnboarding.SALDOS_FAVOR)
        unidades = db.query(Unidad).filter(Unidad.condominio_id == condominio.id).all()
        unidad_ids = [u.id for u in unidades]
        movimientos = (
            db.query(Pago).filter(Pago.unidad_id.in_(unidad_ids), Pago.estado != "CANCELADO")
            .order_by(Pago.created_at.desc()).limit(30).all() if unidad_ids else []
        )
        ctx.update({"unidades": unidades, "movimientos": movimientos, "unidades_by_id": {u.id: u.identificador for u in unidades}})
    return templates.TemplateResponse(request, "onboarding_saldos_favor.html", ctx)


@router.post("/onboarding/saldos-favor")
def onboarding_saldos_favor_create(
    request: Request,
    condominio_id: int = Form(...), unidad_id: int = Form(...), monto: str = Form(...), motivo: str = Form(""),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard(user, request)
    if blocked:
        return blocked
    unidad = db.query(Unidad).get(unidad_id)
    if unidad:
        finanzas_services.registrar_abono_saldo_favor(db, unidad, _to_decimal(monto), motivo or "Saldo a favor inicial")
    onboarding_services.marcar_completado(db, condominio_id, PasoOnboarding.SALDOS_FAVOR)
    return RedirectResponse(f"/onboarding/saldos-favor?condominio_id={condominio_id}", status_code=303)


@router.post("/onboarding/saldos-favor/importar")
async def onboarding_saldos_favor_importar(
    request: Request,
    condominio_id: int = Form(...), archivo: UploadFile = File(...),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard(user, request)
    if blocked:
        return blocked
    content = await archivo.read()
    filas = onboarding_services.parse_tabular_upload(archivo.filename, content)
    unidades_by_ident = {
        u.identificador: u
        for u in db.query(Unidad).filter(Unidad.condominio_id == condominio_id).all()
    }
    for fila in filas:
        ident = str(fila.get("identificador") or fila.get("unidad") or fila.get("Unidad") or "").strip()
        monto_raw = fila.get("monto") or fila.get("Monto")
        unidad = unidades_by_ident.get(ident)
        if not unidad or not monto_raw:
            continue
        motivo = str(fila.get("motivo") or fila.get("descripcion") or "Saldo a favor (importado)")
        finanzas_services.registrar_abono_saldo_favor(db, unidad, _to_decimal(str(monto_raw)), motivo)
    onboarding_services.marcar_completado(db, condominio_id, PasoOnboarding.SALDOS_FAVOR)
    return RedirectResponse(f"/onboarding/saldos-favor?condominio_id={condominio_id}", status_code=303)


# ── Paso 5: Cuotas condominales ──────────────────────────────────────────────
# Reutiliza /finanzas/cuotas (ya soporta tipo FIJA/INDIVISO, mora y descuento por
# pronto pago); aquí solo enlazamos y marcamos el progreso del checklist.

@router.get("/onboarding/cuotas")
def onboarding_cuotas_redirect(condominio_id: int | None = None, db: Session = Depends(get_db)):
    if condominio_id:
        onboarding_services.marcar_visitado(db, condominio_id, PasoOnboarding.CUOTAS)
    url = f"/finanzas/cuotas?condominio_id={condominio_id}" if condominio_id else "/finanzas/cuotas"
    return RedirectResponse(url, status_code=303)


# ── Paso 6: Ingresos del mes ─────────────────────────────────────────────────

@router.get("/onboarding/ingresos", response_class=HTMLResponse)
def onboarding_ingresos(
    request: Request, condominio_id: int | None = None,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard(user, request)
    if blocked:
        return blocked
    condominios, condominio = _resolve_condominio(db, condominio_id)
    ctx = {"user": user, "active": "onboarding", "condominios": condominios, "condominio": condominio,
           "condominio_id": condominio.id if condominio else None}
    if condominio:
        onboarding_services.marcar_visitado(db, condominio.id, PasoOnboarding.INGRESOS)
        unidades = db.query(Unidad).filter(Unidad.condominio_id == condominio.id).all()
        unidad_ids = [u.id for u in unidades]
        from app.modules.finanzas.models import Cargo
        recientes = (
            db.query(Cargo).filter(
                Cargo.unidad_id.in_(unidad_ids),
                Cargo.tipo.in_([TipoCargo.EXTRAORDINARIA, TipoCargo.MULTA, TipoCargo.AMENIDAD, TipoCargo.TAG_VEHICULAR, TipoCargo.OTRO]),
            ).order_by(Cargo.created_at.desc()).limit(20).all() if unidad_ids else []
        )
        ctx.update({"unidades": unidades, "recientes": recientes, "unidades_by_id": {u.id: u.identificador for u in unidades}})
    return templates.TemplateResponse(request, "onboarding_ingresos.html", ctx)


@router.post("/onboarding/ingresos")
def onboarding_ingresos_create(
    request: Request,
    condominio_id: int = Form(...), unidad_id: int = Form(...), tipo: str = Form(...),
    concepto: str = Form(...), monto: str = Form(...), cobrar_de_inmediato: bool = Form(False),
    metodo_pago: str = Form("EFECTIVO"),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard(user, request)
    if blocked:
        return blocked
    finanzas_services.crear_cargo_manual(
        db, unidad_id, TipoCargo(tipo), concepto, _to_decimal(monto), None, None,
        cobrar_de_inmediato, MetodoPago(metodo_pago), user.id,
    )
    onboarding_services.marcar_completado(db, condominio_id, PasoOnboarding.INGRESOS)
    return RedirectResponse(f"/onboarding/ingresos?condominio_id={condominio_id}", status_code=303)


# ── Paso 7: Egresos ──────────────────────────────────────────────────────────

@router.get("/onboarding/egresos", response_class=HTMLResponse)
def onboarding_egresos(
    request: Request, condominio_id: int | None = None,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard_finance(user, request, write=False)
    if blocked:
        return blocked
    condominios, condominio = _resolve_condominio(db, condominio_id)
    ctx = {"user": user, "active": "onboarding", "condominios": condominios, "condominio": condominio,
           "condominio_id": condominio.id if condominio else None}
    if condominio:
        onboarding_services.marcar_visitado(db, condominio.id, PasoOnboarding.EGRESOS)
        proveedores = db.query(Proveedor).order_by(Proveedor.nombre).all()
        cuentas = db.query(CuentaBancaria).filter(CuentaBancaria.condominio_id == condominio.id).all()
        partidas = (
            db.query(PartidaPresupuestal)
            .filter(PartidaPresupuestal.condominio_id == condominio.id, PartidaPresupuestal.tipo == TipoPartida.EGRESO)
            .all()
        )
        egresos = (
            db.query(Egreso).filter(Egreso.condominio_id == condominio.id)
            .order_by(Egreso.fecha.desc()).limit(30).all()
        )
        ctx.update({
            "proveedores": proveedores, "cuentas": cuentas, "partidas": partidas, "egresos": egresos,
            "proveedores_by_id": {p.id: p.nombre for p in proveedores},
            "cuentas_by_id": {c.id: c.banco for c in cuentas},
        })
    return templates.TemplateResponse(request, "onboarding_egresos.html", ctx)


@router.post("/onboarding/egresos")
async def onboarding_egresos_create(
    request: Request,
    condominio_id: int = Form(...), descripcion: str = Form(...), monto: str = Form(...),
    fecha: str = Form(...), proveedor_id: str = Form(""), cuenta_bancaria_id: str = Form(""),
    partida_id: str = Form(""),
    comprobante_pdf: UploadFile | None = File(None), comprobante_xml: UploadFile | None = File(None),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard_finance(user, request, write=True)
    if blocked:
        return blocked

    pdf_path = None
    xml_path = None
    import secrets as _secrets
    if comprobante_pdf and comprobante_pdf.filename:
        pdf_path = f"{_secrets.token_hex(8)}_{comprobante_pdf.filename}"
        (COMPROBANTES_DIR / pdf_path).write_bytes(await comprobante_pdf.read())
    if comprobante_xml and comprobante_xml.filename:
        xml_path = f"{_secrets.token_hex(8)}_{comprobante_xml.filename}"
        (COMPROBANTES_DIR / xml_path).write_bytes(await comprobante_xml.read())

    db.add(Egreso(
        condominio_id=condominio_id,
        proveedor_id=int(proveedor_id) if proveedor_id else None,
        cuenta_bancaria_id=int(cuenta_bancaria_id) if cuenta_bancaria_id else None,
        partida_id=int(partida_id) if partida_id else None,
        descripcion=descripcion, monto=_to_decimal(monto),
        fecha=datetime.strptime(fecha, "%Y-%m-%d").date(),
        comprobante_pdf_path=pdf_path, comprobante_xml_path=xml_path,
    ))
    db.commit()
    onboarding_services.marcar_completado(db, condominio_id, PasoOnboarding.EGRESOS)
    return RedirectResponse(f"/onboarding/egresos?condominio_id={condominio_id}", status_code=303)


@router.get("/onboarding/egresos/{egreso_id}/comprobante/{tipo}")
def onboarding_egreso_comprobante(
    egreso_id: int, tipo: str,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    from app.core.rbac import can_read_finance_module
    if not user or not can_read_finance_module(user):
        return RedirectResponse("/login", status_code=303)
    egreso = db.query(Egreso).get(egreso_id)
    path_str = egreso.comprobante_pdf_path if tipo == "pdf" else egreso.comprobante_xml_path
    if not egreso or not path_str:
        return RedirectResponse("/onboarding/egresos", status_code=303)
    return FileResponse(COMPROBANTES_DIR / path_str, filename=path_str.split("_", 1)[-1])


# ── Paso 8: Invitaciones a residentes ────────────────────────────────────────

@router.get("/onboarding/invitaciones", response_class=HTMLResponse)
def onboarding_invitaciones(
    request: Request, condominio_id: int | None = None,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard(user, request)
    if blocked:
        return blocked
    condominios, condominio = _resolve_condominio(db, condominio_id)
    ctx = {"user": user, "active": "onboarding", "condominios": condominios, "condominio": condominio,
           "condominio_id": condominio.id if condominio else None}
    if condominio:
        onboarding_services.marcar_visitado(db, condominio.id, PasoOnboarding.INVITACIONES)
        unidad_ids = [u.id for u in db.query(Unidad.id).filter(Unidad.condominio_id == condominio.id).all()]
        propietario_ids = {
            p_id for (p_id,) in db.query(Unidad.propietario_id).filter(Unidad.id.in_(unidad_ids)).all() if p_id
        }
        propietarios = db.query(Propietario).filter(Propietario.id.in_(propietario_ids)).all() if propietario_ids else []
        invitaciones = (
            db.query(InvitacionResidente).filter(InvitacionResidente.propietario_id.in_(propietario_ids))
            .order_by(InvitacionResidente.created_at.desc()).all() if propietario_ids else []
        )
        base_url = str(request.base_url).rstrip("/")
        ctx.update({
            "propietarios": propietarios, "invitaciones": invitaciones, "base_url": base_url,
            "propietarios_by_id": {p.id: p.full_name for p in propietarios},
        })
    return templates.TemplateResponse(request, "onboarding_invitaciones.html", ctx)


@router.post("/onboarding/invitaciones")
def onboarding_invitacion_create(
    request: Request,
    condominio_id: int = Form(...), propietario_id: int = Form(...), email: str = Form(""),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard(user, request)
    if blocked:
        return blocked
    propietario = db.query(Propietario).get(propietario_id)
    if propietario:
        db.add(InvitacionResidente(
            propietario_id=propietario.id, email=email or propietario.email or "",
            token=onboarding_services.generar_token(), expires_at=onboarding_services.token_expira_en(),
        ))
        db.commit()
        onboarding_services.marcar_completado(db, condominio_id, PasoOnboarding.INVITACIONES)
    return RedirectResponse(f"/onboarding/invitaciones?condominio_id={condominio_id}", status_code=303)


# ── Activación pública (enlace mágico, sin sesión) ──────────────────────────

@router.get("/activar/{token}", response_class=HTMLResponse)
def activar_page(token: str, request: Request, db: Session = Depends(get_db)):
    invitacion = db.query(InvitacionResidente).filter(InvitacionResidente.token == token).first()
    if not invitacion or invitacion.usado:
        return templates.TemplateResponse(request, "activar.html", {"error": "Este enlace ya no es válido.", "invalido": True})
    if invitacion.expires_at and invitacion.expires_at < datetime.now(timezone.utc):
        return templates.TemplateResponse(request, "activar.html", {"error": "Este enlace expiró.", "invalido": True})
    return templates.TemplateResponse(
        request, "activar.html",
        {"invalido": False, "propietario": invitacion.propietario, "token": token},
    )


@router.post("/activar/{token}", response_class=HTMLResponse)
def activar_submit(
    token: str, request: Request,
    full_name: str = Form(...), password: str = Form(...),
    db: Session = Depends(get_db),
):
    invitacion = db.query(InvitacionResidente).filter(InvitacionResidente.token == token).first()
    if not invitacion or invitacion.usado:
        return templates.TemplateResponse(request, "activar.html", {"error": "Este enlace ya no es válido.", "invalido": True})

    propietario = invitacion.propietario
    existing_user = db.query(User).filter(User.email == invitacion.email).first()
    if existing_user:
        propietario.user_id = existing_user.id
    else:
        from app.core.rbac import default_role_id_for_new_user
        new_user = User(
            email=invitacion.email, hashed_password=get_password_hash(password),
            full_name=full_name, role_id=default_role_id_for_new_user(db),
        )
        db.add(new_user)
        db.flush()
        propietario.user_id = new_user.id

    invitacion.usado = True
    db.commit()
    return RedirectResponse("/login", status_code=303)
