"""Router de la nueva arquitectura de navegación /app/... — Ingresos y Descuentos,
Cuotas y Adeudos, Egresos, Cuentas por Pagar. Ver app/core/navigation.py para el
árbol del menú (navigationConfig) y la matriz de permisos por ruta."""

import secrets as _secrets
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
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
    Cargo, CuentaBancaria, CuentaPorPagar, DescuentoAplicado, EmisionLote, EstadoCargo,
    EstadoCuentaPorPagar, EstadoPago, EstadoPagoProveedor, Factura, Fondo, MetodoPago,
    Pago, PagoProveedor, PartidaPresupuestal, TipoCargo, TipoPartida, TipoRecargo,
)
from app.modules.mantenimiento.models import Proveedor
from app.web.router import _resolve_condominio, templates

router = APIRouter(prefix="/app", tags=["Frontend App"])

CXP_COMPROBANTES_DIR = Path(__file__).resolve().parent.parent / "modules" / "finanzas" / "data" / "comprobantes_cxp"
CXP_COMPROBANTES_DIR.mkdir(parents=True, exist_ok=True)


def _to_decimal(value: str, default: str = "0") -> Decimal:
    try:
        return Decimal(value) if value not in (None, "") else Decimal(default)
    except InvalidOperation:
        return Decimal(default)


def _opt_int(value: str | None) -> int | None:
    return int(value) if value else None


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


# ═══ 1. Ingresos y Descuentos ═══════════════════════════════════════════════

@router.get("/ingresos/capturar", response_class=HTMLResponse)
def ingresos_capturar(
    request: Request, condominio_id: int | None = None,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard_write(user, request)
    if blocked:
        return blocked
    condominios, condominio = _resolve_condominio(db, condominio_id)
    ctx = {"user": user, "active": "app", "condominios": condominios, "condominio": condominio,
           "condominio_id": condominio.id if condominio else None}
    if condominio:
        unidades = db.query(Unidad).filter(Unidad.condominio_id == condominio.id).order_by(Unidad.identificador).all()
        cuentas = db.query(CuentaBancaria).filter(CuentaBancaria.condominio_id == condominio.id).all()
        fondos = db.query(Fondo).filter(Fondo.condominio_id == condominio.id).all()
        ctx.update({"unidades": unidades, "cuentas": cuentas, "fondos": fondos})
    return templates.TemplateResponse(request, "app_ingresos_capturar.html", ctx)


@router.post("/ingresos/capturar")
async def ingresos_capturar_submit(
    request: Request,
    condominio_id: int = Form(...), unidad_id: int = Form(...), monto: str = Form(...),
    metodo: str = Form("EFECTIVO"), referencia: str = Form(""), fecha_pago: str = Form(...),
    cuenta_bancaria_id: str = Form(""), fondo_id: str = Form(""), auto_aplicar: bool = Form(False),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard_write(user, request)
    if blocked:
        return blocked
    unidad = db.query(Unidad).get(unidad_id)
    if not unidad:
        return RedirectResponse(f"/app/ingresos/capturar?condominio_id={condominio_id}", status_code=303)
    pago = finanzas_services.registrar_pago_unidad(
        db, unidad, _to_decimal(monto), MetodoPago(metodo), referencia or None,
        date.fromisoformat(fecha_pago), _opt_int(cuenta_bancaria_id), _opt_int(fondo_id),
        user.id, auto_aplicar,
    )
    return RedirectResponse(f"/finanzas/pagos/{pago.id}", status_code=303)


@router.get("/ingresos/control", response_class=HTMLResponse)
def ingresos_control(
    request: Request, condominio_id: int | None = None,
    desde: str | None = None, hasta: str | None = None,
    unidad_id: str | None = None, cuenta_bancaria_id: str | None = None, fondo_id: str | None = None,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard_read(user, request)
    if blocked:
        return blocked
    condominios, condominio = _resolve_condominio(db, condominio_id)
    ctx = {"user": user, "active": "app", "condominios": condominios, "condominio": condominio,
           "condominio_id": condominio.id if condominio else None,
           "filtros": {"desde": desde or "", "hasta": hasta or "", "unidad_id": unidad_id or "",
                       "cuenta_bancaria_id": cuenta_bancaria_id or "", "fondo_id": fondo_id or ""}}
    if condominio:
        unidades = db.query(Unidad).filter(Unidad.condominio_id == condominio.id).all()
        query = db.query(Pago).join(Unidad, Pago.unidad_id == Unidad.id).filter(
            Unidad.condominio_id == condominio.id, Pago.estado != EstadoPago.CANCELADO,
        )
        if desde:
            query = query.filter(Pago.fecha_pago >= date.fromisoformat(desde))
        if hasta:
            query = query.filter(Pago.fecha_pago <= date.fromisoformat(hasta))
        if unidad_id:
            query = query.filter(Pago.unidad_id == int(unidad_id))
        if cuenta_bancaria_id:
            query = query.filter(Pago.cuenta_bancaria_id == int(cuenta_bancaria_id))
        if fondo_id:
            query = query.filter(Pago.fondo_id == int(fondo_id))
        pagos = query.order_by(Pago.fecha_pago.desc()).all()
        cuentas = db.query(CuentaBancaria).filter(CuentaBancaria.condominio_id == condominio.id).all()
        fondos = db.query(Fondo).filter(Fondo.condominio_id == condominio.id).all()
        ctx.update({
            "pagos": pagos, "unidades": unidades, "cuentas": cuentas, "fondos": fondos,
            "unidades_by_id": {u.id: u.identificador for u in unidades},
            "total": sum((p.monto for p in pagos), start=Decimal("0")),
        })
    return templates.TemplateResponse(request, "app_ingresos_control.html", ctx)


@router.get("/ingresos/reporte", response_class=HTMLResponse)
def ingresos_reporte(
    request: Request, condominio_id: int | None = None, anio: int | None = None,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard_read(user, request)
    if blocked:
        return blocked
    condominios, condominio = _resolve_condominio(db, condominio_id)
    anio = anio or date.today().year
    ctx = {"user": user, "active": "app", "condominios": condominios, "condominio": condominio,
           "condominio_id": condominio.id if condominio else None, "anio": anio}
    if condominio:
        pagos = (
            db.query(Pago).join(Unidad, Pago.unidad_id == Unidad.id)
            .filter(Unidad.condominio_id == condominio.id, Pago.estado != EstadoPago.CANCELADO,
                    Pago.fecha_pago >= date(anio, 1, 1), Pago.fecha_pago <= date(anio, 12, 31))
            .all()
        )
        por_metodo: dict[str, Decimal] = {}
        por_mes: dict[int, Decimal] = {m: Decimal("0") for m in range(1, 13)}
        for p in pagos:
            por_metodo[p.metodo.value] = por_metodo.get(p.metodo.value, Decimal("0")) + p.monto
            por_mes[p.fecha_pago.month] += p.monto
        ctx.update({
            "total": sum(por_mes.values(), start=Decimal("0")),
            "por_metodo": por_metodo, "por_mes": por_mes, "num_pagos": len(pagos),
        })
    return templates.TemplateResponse(request, "app_ingresos_reporte.html", ctx)


@router.get("/ingresos/reporte/excel")
def ingresos_reporte_excel(
    condominio_id: int, anio: int,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user or not can_read_finance_module(user):
        return RedirectResponse("/login", status_code=303)
    import openpyxl
    pagos = (
        db.query(Pago).join(Unidad, Pago.unidad_id == Unidad.id)
        .filter(Unidad.condominio_id == condominio_id, Pago.estado != EstadoPago.CANCELADO,
                Pago.fecha_pago >= date(anio, 1, 1), Pago.fecha_pago <= date(anio, 12, 31))
        .order_by(Pago.fecha_pago).all()
    )
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Ingresos"
    ws.append(["Fecha", "Unidad", "Monto", "Método", "Referencia", "Estatus"])
    for p in pagos:
        ws.append([p.fecha_pago.isoformat(), p.unidad.identificador, float(p.monto), p.metodo.value, p.referencia or "", p.estado.value])
    out_dir = Path(__file__).resolve().parent.parent / "modules" / "finanzas" / "data" / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"ingresos_{condominio_id}_{anio}.xlsx"
    wb.save(path)
    return FileResponse(path, filename=f"ingresos_{anio}.xlsx", media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.get("/ingresos/comprobantes", response_class=HTMLResponse)
def ingresos_comprobantes(
    request: Request, condominio_id: int | None = None,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard_read(user, request)
    if blocked:
        return blocked
    condominios, condominio = _resolve_condominio(db, condominio_id)
    ctx = {"user": user, "active": "app", "condominios": condominios, "condominio": condominio,
           "condominio_id": condominio.id if condominio else None}
    if condominio:
        pagos_con_comprobante = (
            db.query(Pago).join(Unidad, Pago.unidad_id == Unidad.id)
            .filter(Unidad.condominio_id == condominio.id, Pago.comprobante_path.isnot(None))
            .order_by(Pago.fecha_pago.desc()).all()
        )
        facturas = (
            db.query(Factura).join(Cargo, Factura.cargo_id == Cargo.id).join(Unidad, Cargo.unidad_id == Unidad.id)
            .filter(Unidad.condominio_id == condominio.id).order_by(Factura.created_at.desc()).all()
        )
        ctx.update({"pagos_con_comprobante": pagos_con_comprobante, "facturas": facturas})
    return templates.TemplateResponse(request, "app_ingresos_comprobantes.html", ctx)


@router.get("/ingresos/aplicar-descuento", response_class=HTMLResponse)
def ingresos_aplicar_descuento(
    request: Request, condominio_id: int | None = None,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard_write(user, request)
    if blocked:
        return blocked
    condominios, condominio = _resolve_condominio(db, condominio_id)
    ctx = {"user": user, "active": "app", "condominios": condominios, "condominio": condominio,
           "condominio_id": condominio.id if condominio else None, "errors": []}
    if condominio:
        cargos_pendientes = (
            db.query(Cargo).join(Unidad, Cargo.unidad_id == Unidad.id)
            .filter(Unidad.condominio_id == condominio.id, Cargo.estado.in_([EstadoCargo.PENDIENTE, EstadoCargo.PARCIAL, EstadoCargo.VENCIDO]))
            .order_by(Cargo.fecha_vencimiento).all()
        )
        ctx["cargos_pendientes"] = cargos_pendientes
        ctx["unidades_by_id"] = {u.id: u.identificador for u in db.query(Unidad).filter(Unidad.condominio_id == condominio.id).all()}
    return templates.TemplateResponse(request, "app_ingresos_aplicar_descuento.html", ctx)


@router.post("/ingresos/aplicar-descuento")
def ingresos_aplicar_descuento_submit(
    request: Request,
    condominio_id: int = Form(...), cargo_id: int = Form(...), tipo: str = Form("PORCENTAJE"),
    valor: str = Form(...), motivo: str = Form(...),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard_write(user, request)
    if blocked:
        return blocked
    cargo = db.query(Cargo).get(cargo_id)
    if cargo:
        try:
            finanzas_services.aplicar_descuento_manual(db, cargo, TipoRecargo(tipo), _to_decimal(valor), motivo, user.id)
        except ValueError:
            pass
    return RedirectResponse(f"/app/ingresos/aplicar-descuento?condominio_id={condominio_id}", status_code=303)


@router.get("/ingresos/control-descuentos", response_class=HTMLResponse)
def ingresos_control_descuentos(
    request: Request, condominio_id: int | None = None,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard_read(user, request)
    if blocked:
        return blocked
    condominios, condominio = _resolve_condominio(db, condominio_id)
    ctx = {"user": user, "active": "app", "condominios": condominios, "condominio": condominio,
           "condominio_id": condominio.id if condominio else None}
    if condominio:
        descuentos = (
            db.query(DescuentoAplicado).join(Cargo, DescuentoAplicado.cargo_id == Cargo.id)
            .join(Unidad, Cargo.unidad_id == Unidad.id).filter(Unidad.condominio_id == condominio.id)
            .order_by(DescuentoAplicado.created_at.desc()).all()
        )
        ctx["descuentos"] = descuentos
        ctx["total"] = sum((d.monto_descontado for d in descuentos), start=Decimal("0"))
    return templates.TemplateResponse(request, "app_ingresos_control_descuentos.html", ctx)


# ═══ 2. Cuotas y Adeudos ════════════════════════════════════════════════════

@router.get("/cuotas/recurrentes", response_class=HTMLResponse)
def cuotas_recurrentes(
    request: Request, condominio_id: int | None = None,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard_read(user, request)
    if blocked:
        return blocked
    condominios, condominio = _resolve_condominio(db, condominio_id)
    ctx = {"user": user, "active": "app", "condominios": condominios, "condominio": condominio,
           "condominio_id": condominio.id if condominio else None, "puede_escribir": can_write_finance_module(user)}
    if condominio:
        from app.modules.finanzas.models import TipoRecurrencia
        lotes = (
            db.query(EmisionLote)
            .filter(EmisionLote.condominio_id == condominio.id, EmisionLote.recurrencia != TipoRecurrencia.NINGUNA)
            .order_by(EmisionLote.created_at.desc()).all()
        )
        ctx["lotes"] = lotes
    return templates.TemplateResponse(request, "app_cuotas_recurrentes.html", ctx)


@router.post("/cuotas/recurrentes/{lote_id}/pausar")
def cuotas_recurrentes_pausar(
    lote_id: int, condominio_id: int = Form(...),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user or not can_write_finance_module(user):
        return RedirectResponse("/login", status_code=303)
    lote = db.query(EmisionLote).get(lote_id)
    if lote:
        lote.activo = False
        db.commit()
    return RedirectResponse(f"/app/cuotas/recurrentes?condominio_id={condominio_id}", status_code=303)


@router.post("/cuotas/recurrentes/{lote_id}/reanudar")
def cuotas_recurrentes_reanudar(
    lote_id: int, condominio_id: int = Form(...),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user or not can_write_finance_module(user):
        return RedirectResponse("/login", status_code=303)
    lote = db.query(EmisionLote).get(lote_id)
    if lote:
        lote.activo = True
        db.commit()
    return RedirectResponse(f"/app/cuotas/recurrentes?condominio_id={condominio_id}", status_code=303)


@router.get("/cuotas/editar", response_class=HTMLResponse)
def cuotas_editar_list(
    request: Request, condominio_id: int | None = None,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard_write(user, request)
    if blocked:
        return blocked
    condominios, condominio = _resolve_condominio(db, condominio_id)
    ctx = {"user": user, "active": "app", "condominios": condominios, "condominio": condominio,
           "condominio_id": condominio.id if condominio else None}
    if condominio:
        cargos = (
            db.query(Cargo).join(Unidad, Cargo.unidad_id == Unidad.id)
            .filter(Unidad.condominio_id == condominio.id, Cargo.estado == EstadoCargo.PENDIENTE)
            .order_by(Cargo.fecha_vencimiento.desc()).all()
        )
        ctx["cargos"] = cargos
        ctx["unidades_by_id"] = {u.id: u.identificador for u in db.query(Unidad).filter(Unidad.condominio_id == condominio.id).all()}
    return templates.TemplateResponse(request, "app_cuotas_editar.html", ctx)


@router.get("/cuotas/editar/{cargo_id}", response_class=HTMLResponse)
def cuotas_editar_form(
    cargo_id: int, request: Request,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard_write(user, request)
    if blocked:
        return blocked
    cargo = db.query(Cargo).get(cargo_id)
    if not cargo:
        return RedirectResponse("/app/cuotas/editar", status_code=303)
    return templates.TemplateResponse(
        request, "app_cuotas_editar_form.html",
        {"user": user, "active": "app", "cargo": cargo, "unidad": cargo.unidad, "error": None},
    )


@router.post("/cuotas/editar/{cargo_id}")
def cuotas_editar_submit(
    cargo_id: int, request: Request,
    concepto: str = Form(...), monto_base: str = Form(...), fecha_vencimiento: str = Form(...),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard_write(user, request)
    if blocked:
        return blocked
    cargo = db.query(Cargo).get(cargo_id)
    if not cargo:
        return RedirectResponse("/app/cuotas/editar", status_code=303)
    if cargo.estado != EstadoCargo.PENDIENTE:
        return templates.TemplateResponse(
            request, "app_cuotas_editar_form.html",
            {"user": user, "active": "app", "cargo": cargo, "unidad": cargo.unidad,
             "error": "Solo se pueden editar cargos que sigan PENDIENTES (sin ningún pago aplicado)."},
            status_code=400,
        )
    cargo.concepto = concepto
    cargo.monto_base = _to_decimal(monto_base)
    cargo.fecha_vencimiento = date.fromisoformat(fecha_vencimiento)
    db.commit()
    return RedirectResponse(f"/app/cuotas/editar?condominio_id={cargo.unidad.condominio_id}", status_code=303)


@router.get("/cuotas/cobranza", response_class=HTMLResponse)
def cuotas_cobranza(
    request: Request, condominio_id: int | None = None,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard_read(user, request)
    if blocked:
        return blocked
    condominios, condominio = _resolve_condominio(db, condominio_id)
    ctx = {"user": user, "active": "app", "condominios": condominios, "condominio": condominio,
           "condominio_id": condominio.id if condominio else None}
    if condominio:
        matriz = finanzas_services.cartera_vencida(db, condominio.id)
        ctx["matriz"] = matriz
        ctx["total_vencido"] = sum((r["total_vencido"] for r in matriz), start=Decimal("0"))
    return templates.TemplateResponse(request, "app_cuotas_cobranza.html", ctx)


@router.get("/cuotas/recargos", response_class=HTMLResponse)
def cuotas_recargos(
    request: Request, condominio_id: int | None = None,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard_write(user, request)
    if blocked:
        return blocked
    condominios, condominio = _resolve_condominio(db, condominio_id)
    ctx = {"user": user, "active": "app", "condominios": condominios, "condominio": condominio,
           "condominio_id": condominio.id if condominio else None}
    if condominio:
        candidatos = (
            db.query(Cargo).join(Unidad, Cargo.unidad_id == Unidad.id)
            .filter(Unidad.condominio_id == condominio.id, Cargo.estado.in_([EstadoCargo.PENDIENTE, EstadoCargo.PARCIAL]),
                    Cargo.fecha_vencimiento < date.today())
            .all()
        )
        ctx["candidatos"] = candidatos
        ctx["unidades_by_id"] = {u.id: u.identificador for u in db.query(Unidad).filter(Unidad.condominio_id == condominio.id).all()}
        ctx["now"] = date.today()
    return templates.TemplateResponse(request, "app_cuotas_recargos.html", ctx)


@router.post("/cuotas/recargos")
def cuotas_recargos_generar(
    request: Request, condominio_id: int = Form(...),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard_write(user, request)
    if blocked:
        return blocked
    finanzas_services.aplicar_recargos_vencidos(db, condominio_id)
    return RedirectResponse(f"/app/cuotas/recargos?condominio_id={condominio_id}", status_code=303)


@router.get("/cuotas/estado-cuenta-lote", response_class=HTMLResponse)
def cuotas_estado_cuenta_lote(
    request: Request, condominio_id: int | None = None,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard_write(user, request)
    if blocked:
        return blocked
    condominios, condominio = _resolve_condominio(db, condominio_id)
    ctx = {"user": user, "active": "app", "condominios": condominios, "condominio": condominio,
           "condominio_id": condominio.id if condominio else None}
    if condominio:
        ctx["unidades"] = db.query(Unidad).filter(Unidad.condominio_id == condominio.id).order_by(Unidad.identificador).all()
    return templates.TemplateResponse(request, "app_cuotas_estado_cuenta_lote.html", ctx)


@router.post("/cuotas/estado-cuenta-lote")
def cuotas_estado_cuenta_lote_enviar(
    request: Request, condominio_id: int = Form(...),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard_write(user, request)
    if blocked:
        return blocked
    unidades = db.query(Unidad).filter(Unidad.condominio_id == condominio_id).all()
    # El envío real por correo/WhatsApp requiere conectar un proveedor (ver app/utils/mailer.py
    # y whatsapp.py). Por ahora se deja el enlace de impresión de cada unidad listo para compartir.
    return RedirectResponse(
        f"/app/cuotas/estado-cuenta-lote?condominio_id={condominio_id}&enviado={len(unidades)}", status_code=303,
    )


# ═══ 3. Egresos ═════════════════════════════════════════════════════════════
# Captura y Control de Egresos ya viven en /onboarding/egresos (mismo formulario
# y bitácora); aquí solo se agrega el Reporte Detallado por partida que faltaba.

@router.get("/egresos/reporte", response_class=HTMLResponse)
def egresos_reporte(
    request: Request, condominio_id: int | None = None, anio: int | None = None,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard_read(user, request)
    if blocked:
        return blocked
    condominios, condominio = _resolve_condominio(db, condominio_id)
    anio = anio or date.today().year
    ctx = {"user": user, "active": "app", "condominios": condominios, "condominio": condominio,
           "condominio_id": condominio.id if condominio else None, "anio": anio}
    if condominio:
        from app.modules.finanzas.models import Egreso
        egresos = (
            db.query(Egreso).filter(Egreso.condominio_id == condominio.id,
                                     Egreso.fecha >= date(anio, 1, 1), Egreso.fecha <= date(anio, 12, 31))
            .all()
        )
        por_partida: dict[str, Decimal] = {}
        for e in egresos:
            nombre = e.partida.nombre if e.partida else "Sin partida"
            por_partida[nombre] = por_partida.get(nombre, Decimal("0")) + e.monto
        ctx.update({
            "por_partida": sorted(por_partida.items(), key=lambda kv: kv[1], reverse=True),
            "total": sum((e.monto for e in egresos), start=Decimal("0")), "num_egresos": len(egresos),
        })
    return templates.TemplateResponse(request, "app_egresos_reporte.html", ctx)


# ═══ 4. Cuentas por Pagar (Proveedores) ═════════════════════════════════════

@router.get("/cuentas-por-pagar/capturar", response_class=HTMLResponse)
def cxp_capturar(
    request: Request, condominio_id: int | None = None,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard_write(user, request)
    if blocked:
        return blocked
    condominios, condominio = _resolve_condominio(db, condominio_id)
    ctx = {"user": user, "active": "app", "condominios": condominios, "condominio": condominio,
           "condominio_id": condominio.id if condominio else None, "errors": []}
    if condominio:
        ctx["proveedores"] = db.query(Proveedor).order_by(Proveedor.nombre).all()
        ctx["partidas"] = (
            db.query(PartidaPresupuestal)
            .filter(PartidaPresupuestal.condominio_id == condominio.id, PartidaPresupuestal.tipo == TipoPartida.EGRESO)
            .all()
        )
    return templates.TemplateResponse(request, "app_cxp_capturar.html", ctx)


@router.post("/cuentas-por-pagar/capturar")
async def cxp_capturar_submit(
    request: Request,
    condominio_id: int = Form(...), proveedor_id: int = Form(...), partida_id: str = Form(""),
    folio_factura: str = Form(""), concepto: str = Form(...), monto: str = Form(...),
    fecha_factura: str = Form(...), fecha_vencimiento: str = Form(...), notas: str = Form(""),
    comprobante: UploadFile | None = File(None),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard_write(user, request)
    if blocked:
        return blocked
    comprobante_path = None
    if comprobante and comprobante.filename:
        comprobante_path = f"{_secrets.token_hex(8)}_{comprobante.filename}"
        (CXP_COMPROBANTES_DIR / comprobante_path).write_bytes(await comprobante.read())
    try:
        cuenta = finanzas_services.crear_cuenta_por_pagar(
            db, condominio_id, proveedor_id, _opt_int(partida_id), folio_factura or None, concepto,
            _to_decimal(monto), date.fromisoformat(fecha_factura), date.fromisoformat(fecha_vencimiento),
            notas or None, comprobante_path,
        )
    except ValueError:
        return RedirectResponse(f"/app/cuentas-por-pagar/capturar?condominio_id={condominio_id}", status_code=303)
    return RedirectResponse(f"/app/cuentas-por-pagar/control?condominio_id={condominio_id}", status_code=303)


@router.get("/cuentas-por-pagar/control", response_class=HTMLResponse)
def cxp_control(
    request: Request, condominio_id: int | None = None,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard_read(user, request)
    if blocked:
        return blocked
    condominios, condominio = _resolve_condominio(db, condominio_id)
    ctx = {"user": user, "active": "app", "condominios": condominios, "condominio": condominio,
           "condominio_id": condominio.id if condominio else None, "puede_escribir": can_write_finance_module(user)}
    if condominio:
        cuentas = (
            db.query(CuentaPorPagar).filter(CuentaPorPagar.condominio_id == condominio.id)
            .order_by(CuentaPorPagar.fecha_vencimiento).all()
        )
        cuentas_bancarias = db.query(CuentaBancaria).filter(CuentaBancaria.condominio_id == condominio.id).all()
        ctx.update({"cuentas": cuentas, "cuentas_bancarias": cuentas_bancarias})
    return templates.TemplateResponse(request, "app_cxp_control.html", ctx)


@router.post("/cuentas-por-pagar/{cuenta_id}/programar")
def cxp_programar(
    cuenta_id: int, request: Request, monto: str = Form(...), fecha_programada: str = Form(...),
    cuenta_bancaria_id: str = Form(""),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard_write(user, request)
    if blocked:
        return blocked
    cuenta = db.query(CuentaPorPagar).get(cuenta_id)
    if cuenta:
        try:
            finanzas_services.programar_pago_proveedor(
                db, cuenta, _to_decimal(monto), date.fromisoformat(fecha_programada), _opt_int(cuenta_bancaria_id),
            )
        except ValueError:
            pass
        return RedirectResponse(f"/app/cuentas-por-pagar/control?condominio_id={cuenta.condominio_id}", status_code=303)
    return RedirectResponse("/app/cuentas-por-pagar/control", status_code=303)


@router.post("/cuentas-por-pagar/pagos/{pago_id}/marcar-pagado")
def cxp_marcar_pagado(
    pago_id: int, request: Request,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard_write(user, request)
    if blocked:
        return blocked
    pago = db.query(PagoProveedor).get(pago_id)
    condominio_id = None
    if pago:
        finanzas_services.marcar_pago_proveedor_pagado(db, pago)
        condominio_id = pago.cuenta.condominio_id
    return RedirectResponse(f"/app/cuentas-por-pagar/control?condominio_id={condominio_id}", status_code=303)


@router.post("/cuentas-por-pagar/pagos/{pago_id}/cancelar")
def cxp_cancelar_pago(
    pago_id: int, request: Request,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard_write(user, request)
    if blocked:
        return blocked
    pago = db.query(PagoProveedor).get(pago_id)
    condominio_id = None
    if pago:
        finanzas_services.cancelar_pago_proveedor(db, pago)
        condominio_id = pago.cuenta.condominio_id
    return RedirectResponse(f"/app/cuentas-por-pagar/control?condominio_id={condominio_id}", status_code=303)


@router.get("/cuentas-por-pagar/reporte", response_class=HTMLResponse)
def cxp_reporte(
    request: Request, condominio_id: int | None = None,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard_read(user, request)
    if blocked:
        return blocked
    condominios, condominio = _resolve_condominio(db, condominio_id)
    ctx = {"user": user, "active": "app", "condominios": condominios, "condominio": condominio,
           "condominio_id": condominio.id if condominio else None}
    if condominio:
        cuentas = db.query(CuentaPorPagar).filter(CuentaPorPagar.condominio_id == condominio.id).all()
        pendiente_total = sum((c.saldo for c in cuentas if c.saldo > 0), start=Decimal("0"))
        proximos_30 = sum(
            (c.saldo for c in cuentas if c.saldo > 0 and 0 <= (c.fecha_vencimiento - date.today()).days <= 30),
            start=Decimal("0"),
        )
        por_proveedor: dict[str, Decimal] = {}
        for c in cuentas:
            if c.saldo > 0:
                por_proveedor[c.proveedor.nombre] = por_proveedor.get(c.proveedor.nombre, Decimal("0")) + c.saldo
        ctx.update({
            "pendiente_total": pendiente_total, "proximos_30": proximos_30,
            "por_proveedor": sorted(por_proveedor.items(), key=lambda kv: kv[1], reverse=True),
        })
    return templates.TemplateResponse(request, "app_cxp_reporte.html", ctx)


@router.get("/cuentas-por-pagar/antiguedad", response_class=HTMLResponse)
def cxp_antiguedad(
    request: Request, condominio_id: int | None = None,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    blocked = _guard_read(user, request)
    if blocked:
        return blocked
    condominios, condominio = _resolve_condominio(db, condominio_id)
    ctx = {"user": user, "active": "app", "condominios": condominios, "condominio": condominio,
           "condominio_id": condominio.id if condominio else None}
    if condominio:
        finanzas_services.marcar_cuentas_por_pagar_vencidas(db, condominio.id)
        reporte = finanzas_services.reporte_antiguedad_compras(db, condominio.id)
        ctx.update(reporte)
    return templates.TemplateResponse(request, "app_cxp_antiguedad.html", ctx)
