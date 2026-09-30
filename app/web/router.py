from datetime import date, time
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import COOKIE_NAME, get_current_user_optional
from app.core.navigation import visible_nav
from app.core.rbac import (
    ROLE_LABELS,
    can_read_finance_module,
    can_write_finance_module,
    default_role_id_for_new_user,
    is_admin,
    is_guardia,
    is_resident,
    role_name,
)
from app.core.security import create_access_token, get_password_hash, verify_password
from app.modules.auth.models import Role, User, UserRoleEnum
from app.modules.comunicacion.models import Aviso, EstadoTicket, PrioridadTicket, Ticket
from app.modules.condominios.models import Condominio, Unidad
from app.modules.finanzas import services as finanzas_services
from app.modules.finanzas.models import (
    Cargo, CuentaBancaria, CuotaConfig, EmisionLote, EstadoCargo, EstadoPago, Factura, Fondo, MetodoPago,
    MovimientoBancario, Pago, PagoAplicacion, TipoCargo, TipoMovimiento, TipoRecargo, TipoRecurrencia, TipoSeleccionUnidades,
)
from app.modules.finanzas.schemas import EmisionCargosRequest
from pydantic import ValidationError
from app.modules.mantenimiento.models import EstadoOrden, OrdenTrabajo, PrioridadOrden, Proveedor
from app.modules.propietarios.models import Propietario
from app.modules.reportes import services as reportes_services
from app.modules.reservaciones import services as reservaciones_services
from app.modules.reservaciones.models import Amenidad, EstadoReservacion, Reservacion
from app.modules.seguridad import services as seguridad_services
from app.modules.seguridad.models import AccesoQR, Paquete, Visita

router = APIRouter(tags=["Frontend"])
templates = Jinja2Templates(directory="app/templates")

PAGO_COMPROBANTES_DIR = Path(__file__).resolve().parent.parent / "modules" / "finanzas" / "data" / "comprobantes_pago"
PAGO_COMPROBANTES_DIR.mkdir(parents=True, exist_ok=True)
templates.env.globals["is_admin"] = is_admin
templates.env.globals["is_guardia"] = is_guardia
templates.env.globals["is_resident"] = is_resident
templates.env.globals["role_label"] = lambda u: ROLE_LABELS.get(role_name(u), "Sin rol")
templates.env.globals["can_read_finance_module"] = can_read_finance_module
templates.env.globals["finance_nav"] = lambda u: visible_nav(role_name(u))
templates.env.globals["nav_badge"] = lambda key: _nav_badge_value(key)


def _nav_badge_value(key: str) -> int | None:
    """Calcula el valor de un badge dinámico del sidebar (ver app/core/navigation.py).
    Usa una sesión de DB efímera propia porque los globals de Jinja no reciben `db`."""
    from app.core.database import SessionLocal
    from app.modules.finanzas.models import EstadoCargo

    db = SessionLocal()
    try:
        if key == "cartera_vencida":
            n = db.query(Cargo).filter(Cargo.estado == EstadoCargo.VENCIDO).count()
        elif key == "cxp_vencidas":
            from app.modules.finanzas.models import CuentaPorPagar, EstadoCuentaPorPagar
            n = db.query(CuentaPorPagar).filter(CuentaPorPagar.estado == EstadoCuentaPorPagar.VENCIDA).count()
        else:
            return None
        return n or None
    except Exception:
        return None
    finally:
        db.close()

COOKIE_MAX_AGE = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60


def _opt_int(value: str | None) -> int | None:
    return int(value) if value else None


def _resolve_condominio(db: Session, condominio_id: int | None) -> tuple[list[Condominio], Condominio | None]:
    condominios = db.query(Condominio).order_by(Condominio.nombre).all()
    if condominio_id:
        actual = next((c for c in condominios if c.id == condominio_id), None)
    else:
        actual = condominios[0] if condominios else None
    return condominios, actual


def _forbidden(request: Request, user: User):
    return templates.TemplateResponse(
        request, "forbidden.html",
        {"user": user, "active": None, "mi_rol": ROLE_LABELS.get(role_name(user), "sin asignar")},
        status_code=403,
    )


def _mi_propietario(db: Session, user: User) -> Propietario | None:
    return db.query(Propietario).filter(Propietario.user_id == user.id).first()


# ── Home ─────────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
def home(request: Request, user: User | None = Depends(get_current_user_optional)):
    if user:
        return RedirectResponse("/dashboard", status_code=303)
    return RedirectResponse("/login", status_code=303)


# ── Auth: login ──────────────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, user: User | None = Depends(get_current_user_optional)):
    if user:
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse(request, "login.html", {})


@router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.hashed_password) or not user.is_active:
        return templates.TemplateResponse(
            request, "login.html",
            {"error": "Correo o contraseña incorrectos", "email": email},
            status_code=400,
        )

    token = create_access_token(subject=user.id)
    response = RedirectResponse("/dashboard", status_code=303)
    response.set_cookie(
        COOKIE_NAME, token, max_age=COOKIE_MAX_AGE, httponly=True, samesite="lax"
    )
    return response


# ── Auth: register ───────────────────────────────────────────────────────────

@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request, user: User | None = Depends(get_current_user_optional)):
    if user:
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse(request, "register.html", {})


@router.post("/register", response_class=HTMLResponse)
def register_submit(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(""),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        return templates.TemplateResponse(
            request, "register.html",
            {"error": "Ya existe un usuario registrado con este correo",
             "email": email, "full_name": full_name, "phone": phone},
            status_code=400,
        )

    db_user = User(
        email=email,
        hashed_password=get_password_hash(password),
        full_name=full_name,
        phone=phone or None,
        role_id=default_role_id_for_new_user(db),
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    token = create_access_token(subject=db_user.id)
    response = RedirectResponse("/dashboard", status_code=303)
    response.set_cookie(
        COOKIE_NAME, token, max_age=COOKIE_MAX_AGE, httponly=True, samesite="lax"
    )
    return response


# ── Auth: logout ─────────────────────────────────────────────────────────────

@router.post("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response


# ── Dashboard ────────────────────────────────────────────────────────────────

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db)):
    if not user:
        return RedirectResponse("/login", status_code=303)

    if is_guardia(user):
        return RedirectResponse("/seguridad", status_code=303)

    if is_resident(user):
        propietario = _mi_propietario(db, user)
        unidades = propietario.unidades if propietario else []
        return templates.TemplateResponse(
            request, "dashboard_residente.html",
            {
                "user": user, "active": "dashboard", "unidades": unidades,
                "es_propietario": bool(propietario),
                "mi_rol": ROLE_LABELS.get(role_name(user), "Residente"),
                "puede_ver_finanzas": role_name(user) in {"PROPIETARIO", "RESIDENTE"},
            },
        )

    return templates.TemplateResponse(request, "dashboard.html", {"user": user, "active": "dashboard"})


# ── Usuarios (RBAC) ──────────────────────────────────────────────────────────

@router.get("/usuarios", response_class=HTMLResponse)
def usuarios_list(request: Request, user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db)):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not is_admin(user):
        return _forbidden(request, user)
    usuarios = db.query(User).order_by(User.full_name).all()
    roles = [(r.value, ROLE_LABELS[r.value]) for r in UserRoleEnum]
    return templates.TemplateResponse(
        request, "usuarios_list.html",
        {"user": user, "active": "usuarios", "usuarios": usuarios, "roles": roles},
    )


@router.post("/usuarios/{usuario_id}/rol")
def usuarios_update_rol(
    usuario_id: int, request: Request, rol: str = Form(...),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not is_admin(user):
        return _forbidden(request, user)
    target = db.query(User).get(usuario_id)
    role = db.query(Role).filter(Role.name == rol).first()
    if target and role:
        target.role_id = role.id
        db.commit()
    return RedirectResponse("/usuarios", status_code=303)


@router.post("/usuarios/{usuario_id}/estado")
def usuarios_toggle_estado(
    usuario_id: int,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not is_admin(user):
        return RedirectResponse("/dashboard", status_code=303)
    target = db.query(User).get(usuario_id)
    if target and target.id != user.id:
        target.is_active = not target.is_active
        db.commit()
    return RedirectResponse("/usuarios", status_code=303)


# ── Condominios (solo administradores) ──────────────────────────────────────

@router.get("/condominios", response_class=HTMLResponse)
def condominios_list(request: Request, user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db)):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not is_admin(user):
        return _forbidden(request, user)
    condominios = db.query(Condominio).order_by(Condominio.nombre).all()
    return templates.TemplateResponse(request, "condominios_list.html", {"user": user, "active": "condominios", "condominios": condominios})


@router.post("/condominios")
def condominios_create(
    request: Request,
    nombre: str = Form(...), direccion: str = Form(""), ciudad: str = Form(""),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not is_admin(user):
        return _forbidden(request, user)
    db.add(Condominio(nombre=nombre, direccion=direccion or None, ciudad=ciudad or None))
    db.commit()
    return RedirectResponse("/condominios", status_code=303)


@router.get("/condominios/{condominio_id}", response_class=HTMLResponse)
def condominio_detail(
    condominio_id: int, request: Request,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not is_admin(user):
        return _forbidden(request, user)
    condominio = db.query(Condominio).get(condominio_id)
    if not condominio:
        return RedirectResponse("/condominios", status_code=303)
    unidades = db.query(Unidad).filter(Unidad.condominio_id == condominio_id).order_by(Unidad.identificador).all()
    propietarios = db.query(Propietario).order_by(Propietario.full_name).all()
    propietarios_by_id = {p.id: p.full_name for p in propietarios}
    return templates.TemplateResponse(
        request, "condominio_detail.html",
        {"user": user, "active": "condominios", "condominio": condominio, "unidades": unidades,
         "propietarios": propietarios, "propietarios_by_id": propietarios_by_id},
    )


@router.post("/condominios/{condominio_id}/unidades")
def unidad_create(
    condominio_id: int, request: Request,
    identificador: str = Form(...), grupo: str = Form(""), tipo: str = Form("departamento"),
    cuota_mantenimiento: Decimal = Form(...), indiviso_pct: str | None = Form(None),
    propietario_id: str | None = Form(None),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not is_admin(user):
        return _forbidden(request, user)
    db.add(Unidad(
        condominio_id=condominio_id, identificador=identificador, grupo=grupo or None, tipo=tipo,
        cuota_mantenimiento=cuota_mantenimiento,
        indiviso_pct=Decimal(indiviso_pct) if indiviso_pct else None,
        propietario_id=_opt_int(propietario_id),
    ))
    db.commit()
    return RedirectResponse(f"/condominios/{condominio_id}", status_code=303)


# ── Propietarios (solo administradores) ─────────────────────────────────────

@router.get("/propietarios", response_class=HTMLResponse)
def propietarios_list(request: Request, user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db)):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not is_admin(user):
        return _forbidden(request, user)
    propietarios = db.query(Propietario).order_by(Propietario.full_name).all()
    usuarios = db.query(User).order_by(User.email).all()
    return templates.TemplateResponse(
        request, "propietarios_list.html",
        {"user": user, "active": "propietarios", "propietarios": propietarios, "usuarios": usuarios},
    )


@router.post("/propietarios/{propietario_id}/vincular")
def propietarios_vincular(
    propietario_id: int, request: Request, usuario_id: int = Form(...),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not is_admin(user):
        return _forbidden(request, user)
    propietario = db.query(Propietario).get(propietario_id)
    if propietario:
        propietario.user_id = usuario_id
        db.commit()
    return RedirectResponse("/propietarios", status_code=303)


@router.post("/propietarios")
def propietarios_create(
    request: Request,
    full_name: str = Form(...), email: str = Form(""), phone: str = Form(""),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not is_admin(user):
        return _forbidden(request, user)
    db.add(Propietario(full_name=full_name, email=email or None, phone=phone or None))
    db.commit()
    return RedirectResponse("/propietarios", status_code=303)


# ── Finanzas: dashboard (solo administradores) ──────────────────────────────

@router.get("/finanzas", response_class=HTMLResponse)
def finanzas_dashboard(
    request: Request, condominio_id: int | None = None,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not can_read_finance_module(user):
        return _forbidden(request, user)
    condominios, condominio = _resolve_condominio(db, condominio_id)

    ctx = {"user": user, "active": "finanzas", "condominios": condominios, "condominio": condominio,
           "condominio_id": condominio.id if condominio else None}

    if condominio:
        unidades = db.query(Unidad).filter(Unidad.condominio_id == condominio.id).all()
        propietarios_by_id = {p.id: p.full_name for p in db.query(Propietario).all()}
        cargos = db.query(Cargo).join(Unidad, Cargo.unidad_id == Unidad.id).filter(Unidad.condominio_id == condominio.id).all()

        saldos: dict[int, Decimal] = {}
        pendiente = Decimal("0")
        vencido = Decimal("0")
        hoy = date.today()
        for c in cargos:
            saldos[c.unidad_id] = saldos.get(c.unidad_id, Decimal("0")) + c.saldo
            if c.estado == EstadoCargo.VENCIDO:
                vencido += c.saldo
            elif c.saldo > 0:
                pendiente += c.saldo

        pagos_mes = (
            db.query(Pago).join(Unidad, Pago.unidad_id == Unidad.id)
            .filter(
                Unidad.condominio_id == condominio.id, Pago.estado != EstadoPago.CANCELADO,
                func.extract("year", Pago.fecha_pago) == hoy.year,
                func.extract("month", Pago.fecha_pago) == hoy.month,
            ).all()
        )
        cobrado_mes = sum((p.monto for p in pagos_mes), start=Decimal("0"))

        ctx.update({
            "unidades": unidades, "propietarios_by_id": propietarios_by_id, "saldos": saldos,
            "resumen": {"pendiente": pendiente, "vencido": vencido, "cobrado_mes": cobrado_mes},
        })

    return templates.TemplateResponse(request, "finanzas_dashboard.html", ctx)


@router.get("/finanzas/cuotas", response_class=HTMLResponse)
def finanzas_cuotas(
    request: Request, condominio_id: int | None = None,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not can_read_finance_module(user):
        return _forbidden(request, user)
    condominios, condominio = _resolve_condominio(db, condominio_id)
    config = None
    if condominio:
        config = db.query(CuotaConfig).filter(CuotaConfig.condominio_id == condominio.id).first()
        from app.modules.onboarding import services as onboarding_services
        from app.modules.onboarding.models import PasoOnboarding
        onboarding_services.marcar_visitado(db, condominio.id, PasoOnboarding.CUOTAS)
    return templates.TemplateResponse(
        request, "finanzas_cuotas.html",
        {"user": user, "active": "finanzas", "condominios": condominios, "condominio": condominio,
         "condominio_id": condominio.id if condominio else None, "config": config},
    )


@router.post("/finanzas/cuotas")
def finanzas_cuotas_save(
    request: Request,
    condominio_id: int = Form(...), tipo_calculo: str = Form("FIJA"),
    monto_total_prorrateo: str = Form(""),
    dia_limite_pago: int = Form(10), dias_gracia: int = Form(0),
    recargo_tipo: str = Form("PORCENTAJE"), recargo_valor: Decimal = Form(Decimal("0")),
    descuento_pronto_pago_pct: Decimal = Form(Decimal("0")), descuento_pronto_pago_dias: int = Form(0),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not can_write_finance_module(user):
        return _forbidden(request, user)
    from app.modules.finanzas.models import TipoCalculoCuota
    from app.modules.onboarding import services as onboarding_services
    from app.modules.onboarding.models import PasoOnboarding

    config = db.query(CuotaConfig).filter(CuotaConfig.condominio_id == condominio_id).first()
    if not config:
        config = CuotaConfig(condominio_id=condominio_id)
        db.add(config)
    config.tipo_calculo = TipoCalculoCuota(tipo_calculo)
    config.monto_total_prorrateo = Decimal(monto_total_prorrateo) if monto_total_prorrateo else None
    config.dia_limite_pago = dia_limite_pago
    config.dias_gracia = dias_gracia
    config.recargo_tipo = TipoRecargo(recargo_tipo)
    config.recargo_valor = recargo_valor
    config.descuento_pronto_pago_pct = descuento_pronto_pago_pct
    config.descuento_pronto_pago_dias = descuento_pronto_pago_dias
    db.commit()
    onboarding_services.marcar_completado(db, condominio_id, PasoOnboarding.CUOTAS)
    return RedirectResponse(f"/finanzas/cuotas?condominio_id={condominio_id}", status_code=303)


# ── Finanzas: cargos (solo administradores) ─────────────────────────────────

@router.get("/finanzas/cargos", response_class=HTMLResponse)
def finanzas_cargos(
    request: Request, condominio_id: int | None = None,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not can_read_finance_module(user):
        return _forbidden(request, user)
    condominios, condominio = _resolve_condominio(db, condominio_id)
    cargos = []
    unidades_by_id = {}
    if condominio:
        cargos = (
            db.query(Cargo).join(Unidad, Cargo.unidad_id == Unidad.id)
            .filter(Unidad.condominio_id == condominio.id)
            .order_by(Cargo.fecha_vencimiento.desc()).all()
        )
        unidades_by_id = {u.id: u.identificador for u in db.query(Unidad).filter(Unidad.condominio_id == condominio.id).all()}
    return templates.TemplateResponse(
        request, "finanzas_cargos.html",
        {"user": user, "active": "finanzas", "condominios": condominios, "condominio": condominio,
         "condominio_id": condominio.id if condominio else None, "cargos": cargos, "unidades_by_id": unidades_by_id},
    )


@router.post("/finanzas/cargos/generar")
def finanzas_cargos_generar(
    request: Request,
    condominio_id: int = Form(...), periodo: str = Form(...),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not can_write_finance_module(user):
        return _forbidden(request, user)
    finanzas_services.generar_cargos_periodo(db, condominio_id, periodo)
    return RedirectResponse(f"/finanzas/cargos?condominio_id={condominio_id}", status_code=303)


@router.post("/finanzas/cargos/aplicar-recargos")
def finanzas_cargos_aplicar_recargos(
    request: Request,
    condominio_id: int = Form(...),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not can_write_finance_module(user):
        return _forbidden(request, user)
    finanzas_services.aplicar_recargos_vencidos(db, condominio_id)
    return RedirectResponse(f"/finanzas/cargos?condominio_id={condominio_id}", status_code=303)


@router.get("/finanzas/cargos/{cargo_id}", response_class=HTMLResponse)
def finanzas_cargo_detail(
    cargo_id: int, request: Request,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not can_read_finance_module(user):
        return _forbidden(request, user)
    cargo = db.query(Cargo).get(cargo_id)
    if not cargo:
        return RedirectResponse("/finanzas", status_code=303)
    unidad = db.query(Unidad).get(cargo.unidad_id)
    return templates.TemplateResponse(
        request, "finanzas_cargo_detail.html",
        {"user": user, "active": "finanzas", "cargo": cargo, "unidad": unidad, "factura": cargo.factura},
    )


@router.post("/finanzas/cargos/{cargo_id}/pagos")
def finanzas_cargo_pago(
    cargo_id: int, request: Request,
    monto: Decimal = Form(...), metodo: str = Form("EFECTIVO"), referencia: str = Form(""),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not can_write_finance_module(user):
        return _forbidden(request, user)
    cargo = db.query(Cargo).get(cargo_id)
    if cargo:
        finanzas_services.registrar_pago(db, cargo, monto, MetodoPago(metodo), referencia or None, None, user.id)
    return RedirectResponse(f"/finanzas/cargos/{cargo_id}", status_code=303)


@router.post("/finanzas/cargos/{cargo_id}/factura")
def finanzas_cargo_factura(
    cargo_id: int, request: Request,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not can_write_finance_module(user):
        return _forbidden(request, user)
    cargo = db.query(Cargo).get(cargo_id)
    if cargo and not cargo.factura:
        db.add(Factura(cargo_id=cargo_id, notas="Pendiente de timbrado: no hay PAC conectado."))
        db.commit()
    return RedirectResponse(f"/finanzas/cargos/{cargo_id}", status_code=303)


@router.get("/finanzas/unidades/{unidad_id}", response_class=HTMLResponse)
def finanzas_unidad_estado_cuenta(
    unidad_id: int, request: Request, desde: str | None = None, hasta: str | None = None,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    """Accesible para administradores y para el propietario/residente dueño de la unidad."""
    if not user:
        return RedirectResponse("/login", status_code=303)
    unidad = db.query(Unidad).get(unidad_id)
    if not unidad:
        return RedirectResponse("/finanzas", status_code=303)

    if not can_read_finance_module(user):
        propietario = _mi_propietario(db, user)
        es_dueno = propietario is not None and unidad.propietario_id == propietario.id
        if not (is_resident(user) and es_dueno):
            return _forbidden(request, user)

    fecha_desde = date.fromisoformat(desde) if desde else None
    fecha_hasta = date.fromisoformat(hasta) if hasta else None
    detalle = finanzas_services.estado_cuenta_completo(db, unidad, fecha_desde, fecha_hasta)
    propietario = unidad.propietario

    return templates.TemplateResponse(
        request, "finanzas_estado_cuenta.html",
        {
            "user": user, "active": "finanzas", "unidad": unidad,
            "propietario": propietario, "movimientos": detalle["movimientos"], "totales": detalle["totales"],
            "desde": desde or "", "hasta": hasta or "",
            "puede_administrar": can_write_finance_module(user), "es_admin": is_admin(user),
        },
    )


@router.get("/finanzas/unidades/{unidad_id}/excel")
def finanzas_unidad_excel(
    unidad_id: int, request: Request,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    unidad = db.query(Unidad).get(unidad_id)
    if not unidad:
        return RedirectResponse("/finanzas", status_code=303)
    if not can_read_finance_module(user):
        propietario = _mi_propietario(db, user)
        es_dueno = propietario is not None and unidad.propietario_id == propietario.id
        if not (is_resident(user) and es_dueno):
            return _forbidden(request, user)

    detalle = finanzas_services.estado_cuenta_completo(db, unidad)
    path = finanzas_services.exportar_estado_cuenta_excel(unidad, detalle)
    return FileResponse(path, filename=f"estado_cuenta_{unidad.identificador}.xlsx",
                         media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.get("/finanzas/unidades/{unidad_id}/imprimir", response_class=HTMLResponse)
def finanzas_unidad_imprimir(
    unidad_id: int, request: Request,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    unidad = db.query(Unidad).get(unidad_id)
    if not unidad:
        return RedirectResponse("/finanzas", status_code=303)
    if not can_read_finance_module(user):
        return _forbidden(request, user)
    detalle = finanzas_services.estado_cuenta_completo(db, unidad)
    return templates.TemplateResponse(
        request, "finanzas_estado_cuenta_imprimir.html",
        {"unidad": unidad, "propietario": unidad.propietario, "movimientos": detalle["movimientos"],
         "totales": detalle["totales"], "hoy": date.today()},
    )


@router.post("/finanzas/unidades/{unidad_id}/enviar-aviso")
def finanzas_unidad_enviar_aviso(
    unidad_id: int, request: Request,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not can_write_finance_module(user):
        return _forbidden(request, user)
    # El envío real requiere conectar un proveedor de correo (ver app/utils/mailer.py).
    return RedirectResponse(f"/finanzas/unidades/{unidad_id}?aviso=preparado", status_code=303)


# ── Finanzas: registrar y aplicar pagos ─────────────────────────────────────

@router.get("/finanzas/unidades/{unidad_id}/pagos/nuevo", response_class=HTMLResponse)
def finanzas_pago_nuevo(
    unidad_id: int, request: Request,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not can_write_finance_module(user):
        return _forbidden(request, user)
    unidad = db.query(Unidad).get(unidad_id)
    if not unidad:
        return RedirectResponse("/finanzas", status_code=303)
    cuentas = db.query(CuentaBancaria).filter(CuentaBancaria.condominio_id == unidad.condominio_id).all()
    fondos = db.query(Fondo).filter(Fondo.condominio_id == unidad.condominio_id).all()
    return templates.TemplateResponse(
        request, "finanzas_pago_form.html",
        {"user": user, "active": "finanzas", "unidad": unidad, "cuentas": cuentas, "fondos": fondos},
    )


@router.post("/finanzas/unidades/{unidad_id}/pagos/nuevo")
async def finanzas_pago_crear(
    unidad_id: int, request: Request,
    monto: str = Form(...), metodo: str = Form("EFECTIVO"), referencia: str = Form(""),
    fecha_pago: str = Form(...), cuenta_bancaria_id: str = Form(""), fondo_id: str = Form(""),
    auto_aplicar: bool = Form(False), comprobante: UploadFile | None = File(None),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not can_write_finance_module(user):
        return _forbidden(request, user)
    unidad = db.query(Unidad).get(unidad_id)
    if not unidad:
        return RedirectResponse("/finanzas", status_code=303)

    comprobante_path = None
    if comprobante and comprobante.filename:
        import secrets as _secrets
        comprobante_path = f"{_secrets.token_hex(8)}_{comprobante.filename}"
        (PAGO_COMPROBANTES_DIR / comprobante_path).write_bytes(await comprobante.read())

    pago = finanzas_services.registrar_pago_unidad(
        db, unidad, Decimal(monto), MetodoPago(metodo), referencia or None,
        date.fromisoformat(fecha_pago), _opt_int(cuenta_bancaria_id), _opt_int(fondo_id),
        user.id, auto_aplicar, comprobante_path,
    )
    return RedirectResponse(f"/finanzas/pagos/{pago.id}", status_code=303)


@router.get("/finanzas/pagos/{pago_id}", response_class=HTMLResponse)
def finanzas_pago_detail(
    pago_id: int, request: Request,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not can_read_finance_module(user):
        return _forbidden(request, user)
    pago = db.query(Pago).get(pago_id)
    if not pago:
        return RedirectResponse("/finanzas", status_code=303)
    pendientes = (
        db.query(Cargo)
        .filter(Cargo.unidad_id == pago.unidad_id, Cargo.estado.in_([EstadoCargo.PENDIENTE, EstadoCargo.PARCIAL, EstadoCargo.VENCIDO]))
        .order_by(Cargo.fecha_vencimiento).all()
    )
    return templates.TemplateResponse(
        request, "finanzas_pago_detail.html",
        {"user": user, "active": "finanzas", "pago": pago, "unidad": pago.unidad, "pendientes": pendientes},
    )


@router.post("/finanzas/pagos/{pago_id}/aplicar")
def finanzas_pago_aplicar(
    pago_id: int, request: Request, cargo_id: int = Form(...), monto: str = Form(...),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not can_write_finance_module(user):
        return _forbidden(request, user)
    pago = db.query(Pago).get(pago_id)
    cargo = db.query(Cargo).get(cargo_id)
    if pago and cargo:
        try:
            finanzas_services.aplicar_pago_manual(db, pago, cargo, Decimal(monto))
        except ValueError:
            pass
    return RedirectResponse(f"/finanzas/pagos/{pago_id}", status_code=303)


@router.post("/finanzas/pagos/{pago_id}/revertir")
def finanzas_pago_revertir(
    pago_id: int, request: Request,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not can_write_finance_module(user):
        return _forbidden(request, user)
    pago = db.query(Pago).get(pago_id)
    unidad_id = None
    if pago:
        unidad_id = pago.unidad_id
        finanzas_services.revertir_pago(db, pago)
    return RedirectResponse(f"/finanzas/unidades/{unidad_id}" if unidad_id else "/finanzas", status_code=303)


@router.get("/finanzas/pagos/{pago_id}/comprobante")
def finanzas_pago_comprobante(
    pago_id: int,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user or not can_read_finance_module(user):
        return RedirectResponse("/login", status_code=303)
    pago = db.query(Pago).get(pago_id)
    if not pago or not pago.comprobante_path:
        return RedirectResponse("/finanzas", status_code=303)
    return FileResponse(PAGO_COMPROBANTES_DIR / pago.comprobante_path, filename=pago.comprobante_path.split("_", 1)[-1])


# ── Finanzas: conciliación (solo administradores) ───────────────────────────

@router.get("/finanzas/conciliacion", response_class=HTMLResponse)
def finanzas_conciliacion(
    request: Request, condominio_id: int | None = None,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not can_read_finance_module(user):
        return _forbidden(request, user)
    condominios, condominio = _resolve_condominio(db, condominio_id)
    movimientos = []
    pagos_recientes = []
    if condominio:
        movimientos = (
            db.query(MovimientoBancario).filter(MovimientoBancario.condominio_id == condominio.id)
            .order_by(MovimientoBancario.fecha.desc()).all()
        )
        pagos_recientes = (
            db.query(Pago).join(Unidad, Pago.unidad_id == Unidad.id)
            .filter(Unidad.condominio_id == condominio.id, Pago.estado != EstadoPago.CANCELADO)
            .order_by(Pago.created_at.desc()).limit(30).all()
        )
    return templates.TemplateResponse(
        request, "finanzas_conciliacion.html",
        {"user": user, "active": "finanzas", "condominios": condominios, "condominio": condominio,
         "condominio_id": condominio.id if condominio else None, "movimientos": movimientos, "pagos_recientes": pagos_recientes},
    )


@router.post("/finanzas/conciliacion/movimientos")
def finanzas_movimiento_create(
    request: Request,
    condominio_id: int = Form(...), fecha: date = Form(...), descripcion: str = Form(""),
    monto: Decimal = Form(...), tipo: str = Form("ABONO"),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not can_write_finance_module(user):
        return _forbidden(request, user)
    db.add(MovimientoBancario(
        condominio_id=condominio_id, fecha=fecha, descripcion=descripcion or None,
        monto=monto, tipo=TipoMovimiento(tipo),
    ))
    db.commit()
    return RedirectResponse(f"/finanzas/conciliacion?condominio_id={condominio_id}", status_code=303)


@router.post("/finanzas/conciliacion/movimientos/{movimiento_id}/conciliar")
def finanzas_movimiento_conciliar(
    movimiento_id: int, request: Request, pago_id: int = Form(...),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not can_write_finance_module(user):
        return _forbidden(request, user)
    movimiento = db.query(MovimientoBancario).get(movimiento_id)
    pago = db.query(Pago).get(pago_id)
    condominio_id = movimiento.condominio_id if movimiento else None
    if movimiento and pago:
        finanzas_services.conciliar_movimiento(db, movimiento, pago)
    return RedirectResponse(f"/finanzas/conciliacion?condominio_id={condominio_id}", status_code=303)


# ── Emisión de cargos (individual y masiva) ─────────────────────────────────

@router.get("/finanzas/emisiones", response_class=HTMLResponse)
def emisiones_list(
    request: Request, condominio_id: int | None = None,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not can_read_finance_module(user):
        return _forbidden(request, user)
    condominios, condominio = _resolve_condominio(db, condominio_id)
    lotes = []
    if condominio:
        lotes = (
            db.query(EmisionLote).filter(EmisionLote.condominio_id == condominio.id)
            .order_by(EmisionLote.created_at.desc()).all()
        )
    return templates.TemplateResponse(
        request, "finanzas_emisiones.html",
        {"user": user, "active": "finanzas", "condominios": condominios, "condominio": condominio,
         "condominio_id": condominio.id if condominio else None, "lotes": lotes},
    )


@router.get("/finanzas/emisiones/nueva", response_class=HTMLResponse)
def emisiones_nueva(
    request: Request, condominio_id: int | None = None,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not can_write_finance_module(user):
        return _forbidden(request, user)
    condominios, condominio = _resolve_condominio(db, condominio_id)
    ctx = {"user": user, "active": "finanzas", "condominios": condominios, "condominio": condominio,
           "condominio_id": condominio.id if condominio else None, "errors": []}
    if condominio:
        from app.modules.finanzas.models import PartidaPresupuestal
        unidades = db.query(Unidad).filter(Unidad.condominio_id == condominio.id).order_by(Unidad.identificador).all()
        grupos = sorted({u.grupo for u in unidades if u.grupo})
        partidas = (
            db.query(PartidaPresupuestal)
            .filter(PartidaPresupuestal.condominio_id == condominio.id, PartidaPresupuestal.tipo == "INGRESO")
            .all()
        )
        fondos = db.query(Fondo).filter(Fondo.condominio_id == condominio.id).order_by(Fondo.nombre).all()
        ctx.update({"unidades": unidades, "grupos": grupos, "partidas": partidas, "fondos": fondos})
    return templates.TemplateResponse(request, "finanzas_emision_form.html", ctx)


@router.post("/finanzas/emisiones/nueva", response_class=HTMLResponse)
async def emisiones_crear(
    request: Request,
    condominio_id: int = Form(...),
    tipo_seleccion: str = Form(...), grupo: str = Form(""),
    tipo_cargo: str = Form("EXTRAORDINARIA"), concepto: str = Form(...), descripcion: str = Form(""),
    monto: str = Form(...), fecha_emision: str = Form(...), fecha_vencimiento: str = Form(...),
    partida_id: str = Form(""), fondo_id: str = Form(""),
    recurrencia: str = Form("NINGUNA"), dia_generacion: str = Form(""),
    descuento_activo: bool = Form(False), descuento_tipo: str = Form("PORCENTAJE"),
    descuento_valor: str = Form(""), descuento_dias_antes: str = Form(""),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not can_write_finance_module(user):
        return _forbidden(request, user)

    form = await request.form()
    unidad_ids = [int(v) for v in form.getlist("unidad_ids")] if form.getlist("unidad_ids") else None

    try:
        payload = EmisionCargosRequest(
            tipo_seleccion=TipoSeleccionUnidades(tipo_seleccion),
            unidad_ids=unidad_ids, grupo=grupo or None,
            tipo_cargo=TipoCargo(tipo_cargo), concepto=concepto, descripcion=descripcion or None,
            monto=Decimal(monto or "0"),
            partida_id=_opt_int(partida_id), fondo_id=_opt_int(fondo_id),
            fecha_emision=date.fromisoformat(fecha_emision), fecha_vencimiento=date.fromisoformat(fecha_vencimiento),
            recurrencia=TipoRecurrencia(recurrencia), dia_generacion=_opt_int(dia_generacion),
            descuento_activo=descuento_activo, descuento_tipo=TipoRecargo(descuento_tipo) if descuento_activo else None,
            descuento_valor=Decimal(descuento_valor) if descuento_activo and descuento_valor else None,
            descuento_dias_antes=_opt_int(descuento_dias_antes) if descuento_activo else None,
        )
    except (ValidationError, ValueError) as e:
        errors = [str(err.get("msg", err)) for err in e.errors()] if isinstance(e, ValidationError) else [str(e)]
        condominios, condominio = _resolve_condominio(db, condominio_id)
        from app.modules.finanzas.models import PartidaPresupuestal
        unidades = db.query(Unidad).filter(Unidad.condominio_id == condominio_id).order_by(Unidad.identificador).all()
        return templates.TemplateResponse(
            request, "finanzas_emision_form.html",
            {"user": user, "active": "finanzas", "condominios": condominios, "condominio": condominio,
             "condominio_id": condominio_id, "errors": errors, "unidades": unidades,
             "grupos": sorted({u.grupo for u in unidades if u.grupo}),
             "partidas": db.query(PartidaPresupuestal).filter(PartidaPresupuestal.condominio_id == condominio_id, PartidaPresupuestal.tipo == "INGRESO").all(),
             "fondos": db.query(Fondo).filter(Fondo.condominio_id == condominio_id).all()},
            status_code=400,
        )

    try:
        lote = finanzas_services.emitir_cargos(db, condominio_id, payload, user.id)
    except finanzas_services.EmisionError as e:
        condominios, condominio = _resolve_condominio(db, condominio_id)
        from app.modules.finanzas.models import PartidaPresupuestal
        unidades = db.query(Unidad).filter(Unidad.condominio_id == condominio_id).order_by(Unidad.identificador).all()
        return templates.TemplateResponse(
            request, "finanzas_emision_form.html",
            {"user": user, "active": "finanzas", "condominios": condominios, "condominio": condominio,
             "condominio_id": condominio_id, "errors": [str(e)], "unidades": unidades,
             "grupos": sorted({u.grupo for u in unidades if u.grupo}),
             "partidas": db.query(PartidaPresupuestal).filter(PartidaPresupuestal.condominio_id == condominio_id, PartidaPresupuestal.tipo == "INGRESO").all(),
             "fondos": db.query(Fondo).filter(Fondo.condominio_id == condominio_id).all()},
            status_code=400,
        )

    return RedirectResponse(f"/finanzas/emisiones/{lote.id}", status_code=303)


@router.get("/finanzas/emisiones/{lote_id}", response_class=HTMLResponse)
def emision_detail(
    lote_id: int, request: Request,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not can_read_finance_module(user):
        return _forbidden(request, user)
    lote = db.query(EmisionLote).get(lote_id)
    if not lote:
        return RedirectResponse("/finanzas/emisiones", status_code=303)
    cargos = db.query(Cargo).filter(Cargo.lote_id == lote_id).order_by(Cargo.periodo.desc(), Cargo.unidad_id).all()
    unidades_by_id = {u.id: u.identificador for u in db.query(Unidad).filter(Unidad.condominio_id == lote.condominio_id).all()}
    return templates.TemplateResponse(
        request, "finanzas_emision_detail.html",
        {"user": user, "active": "finanzas", "lote": lote, "cargos": cargos, "unidades_by_id": unidades_by_id},
    )


@router.post("/finanzas/emisiones/{lote_id}/pausar")
def emision_pausar(lote_id: int, user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db)):
    if not user or not can_write_finance_module(user):
        return RedirectResponse("/login", status_code=303)
    lote = db.query(EmisionLote).get(lote_id)
    if lote:
        lote.activo = False
        db.commit()
    return RedirectResponse(f"/finanzas/emisiones/{lote_id}", status_code=303)


@router.post("/finanzas/emisiones/{lote_id}/reanudar")
def emision_reanudar(lote_id: int, user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db)):
    if not user or not can_write_finance_module(user):
        return RedirectResponse("/login", status_code=303)
    lote = db.query(EmisionLote).get(lote_id)
    if lote:
        lote.activo = True
        db.commit()
    return RedirectResponse(f"/finanzas/emisiones/{lote_id}", status_code=303)


@router.post("/finanzas/emisiones/procesar-recurrentes")
def emisiones_procesar_recurrentes(
    condominio_id: int = Form(...),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user or not can_write_finance_module(user):
        return RedirectResponse("/login", status_code=303)
    finanzas_services.procesar_recurrencias_pendientes(db)
    return RedirectResponse(f"/finanzas/emisiones?condominio_id={condominio_id}", status_code=303)


# ── Reservaciones (administradores y residentes; no guardias) ──────────────

@router.get("/reservaciones", response_class=HTMLResponse)
def reservaciones_page(
    request: Request, condominio_id: int | None = None,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not (is_admin(user) or is_resident(user)):
        return _forbidden(request, user)
    condominios, condominio = _resolve_condominio(db, condominio_id)
    ctx = {"user": user, "active": "reservaciones", "condominios": condominios, "condominio": condominio,
           "condominio_id": condominio.id if condominio else None}
    if condominio:
        unidades = db.query(Unidad).filter(Unidad.condominio_id == condominio.id).all()
        amenidades = db.query(Amenidad).filter(Amenidad.condominio_id == condominio.id).all()
        amenidad_ids = [a.id for a in amenidades]
        reservaciones = (
            db.query(Reservacion).filter(Reservacion.amenidad_id.in_(amenidad_ids))
            .order_by(Reservacion.fecha.desc()).all() if amenidad_ids else []
        )
        ctx.update({
            "unidades": unidades, "amenidades": amenidades, "reservaciones": reservaciones,
            "amenidades_by_id": {a.id: a.nombre for a in amenidades},
            "unidades_by_id": {u.id: u.identificador for u in unidades},
        })
    return templates.TemplateResponse(request, "reservaciones.html", ctx)


@router.post("/reservaciones/amenidades")
def reservaciones_amenidad_create(
    request: Request,
    condominio_id: int = Form(...), nombre: str = Form(...), capacidad: str = Form(""),
    requiere_deposito: bool = Form(False), monto_deposito: Decimal = Form(Decimal("0")),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not is_admin(user):
        return _forbidden(request, user)
    db.add(Amenidad(
        condominio_id=condominio_id, nombre=nombre, capacidad=_opt_int(capacidad),
        requiere_deposito=requiere_deposito, monto_deposito=monto_deposito if requiere_deposito else Decimal("0"),
    ))
    db.commit()
    return RedirectResponse(f"/reservaciones?condominio_id={condominio_id}", status_code=303)


@router.post("/reservaciones")
def reservaciones_create(
    request: Request,
    condominio_id: int = Form(...), amenidad_id: int = Form(...), unidad_id: int = Form(...),
    fecha: date = Form(...), hora_inicio: time = Form(...), hora_fin: time = Form(...),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not (is_admin(user) or is_resident(user)):
        return _forbidden(request, user)
    if hora_inicio < hora_fin and not reservaciones_services.hay_traslape(db, amenidad_id, fecha, hora_inicio, hora_fin):
        db.add(Reservacion(amenidad_id=amenidad_id, unidad_id=unidad_id, fecha=fecha, hora_inicio=hora_inicio, hora_fin=hora_fin))
        db.commit()
    return RedirectResponse(f"/reservaciones?condominio_id={condominio_id}", status_code=303)


@router.post("/reservaciones/{reservacion_id}/cancelar")
def reservaciones_cancelar(
    reservacion_id: int, request: Request,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not (is_admin(user) or is_resident(user)):
        return _forbidden(request, user)
    reservacion = db.query(Reservacion).get(reservacion_id)
    condominio_id = None
    if reservacion:
        reservacion.estado = EstadoReservacion.CANCELADA
        condominio_id = reservacion.amenidad.condominio_id
        db.commit()
    return RedirectResponse(f"/reservaciones?condominio_id={condominio_id}", status_code=303)


# ── Seguridad (administradores y guardias) ──────────────────────────────────

@router.get("/seguridad", response_class=HTMLResponse)
def seguridad_page(
    request: Request, condominio_id: int | None = None,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not (is_admin(user) or is_guardia(user)):
        return _forbidden(request, user)
    condominios, condominio = _resolve_condominio(db, condominio_id)
    ctx = {"user": user, "active": "seguridad", "condominios": condominios, "condominio": condominio,
           "condominio_id": condominio.id if condominio else None}
    if condominio:
        unidades = db.query(Unidad).filter(Unidad.condominio_id == condominio.id).all()
        unidad_ids = [u.id for u in unidades]
        visitas = db.query(Visita).filter(Visita.unidad_id.in_(unidad_ids)).order_by(Visita.entrada.desc()).limit(30).all() if unidad_ids else []
        paquetes = db.query(Paquete).filter(Paquete.unidad_id.in_(unidad_ids)).order_by(Paquete.fecha_recepcion.desc()).limit(30).all() if unidad_ids else []
        accesos_qr = db.query(AccesoQR).filter(AccesoQR.unidad_id.in_(unidad_ids)).order_by(AccesoQR.created_at.desc()).limit(30).all() if unidad_ids else []
        ctx.update({
            "unidades": unidades, "visitas": visitas, "paquetes": paquetes, "accesos_qr": accesos_qr,
            "unidades_by_id": {u.id: u.identificador for u in unidades},
        })
    return templates.TemplateResponse(request, "seguridad.html", ctx)


@router.post("/seguridad/visitas")
def seguridad_visita_create(
    request: Request,
    unidad_id: int = Form(...), nombre_visitante: str = Form(...), motivo: str = Form(""),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not (is_admin(user) or is_guardia(user)):
        return _forbidden(request, user)
    db.add(Visita(unidad_id=unidad_id, nombre_visitante=nombre_visitante, motivo=motivo or None))
    db.commit()
    unidad = db.query(Unidad).get(unidad_id)
    return RedirectResponse(f"/seguridad?condominio_id={unidad.condominio_id}", status_code=303)


@router.post("/seguridad/visitas/{visita_id}/salida")
def seguridad_visita_salida(
    visita_id: int, request: Request,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    from datetime import datetime, timezone
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not (is_admin(user) or is_guardia(user)):
        return _forbidden(request, user)
    visita = db.query(Visita).get(visita_id)
    condominio_id = None
    if visita:
        visita.salida = datetime.now(timezone.utc)
        condominio_id = visita.unidad.condominio_id
        db.commit()
    return RedirectResponse(f"/seguridad?condominio_id={condominio_id}", status_code=303)


@router.post("/seguridad/paquetes")
def seguridad_paquete_create(
    request: Request,
    unidad_id: int = Form(...), descripcion: str = Form(""), recibido_por: str = Form(""),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not (is_admin(user) or is_guardia(user)):
        return _forbidden(request, user)
    db.add(Paquete(unidad_id=unidad_id, descripcion=descripcion or None, recibido_por=recibido_por or None))
    db.commit()
    unidad = db.query(Unidad).get(unidad_id)
    return RedirectResponse(f"/seguridad?condominio_id={unidad.condominio_id}", status_code=303)


@router.post("/seguridad/paquetes/{paquete_id}/entregar")
def seguridad_paquete_entregar(
    paquete_id: int, request: Request,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    from datetime import datetime, timezone
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not (is_admin(user) or is_guardia(user)):
        return _forbidden(request, user)
    paquete = db.query(Paquete).get(paquete_id)
    condominio_id = None
    if paquete:
        paquete.entregado = True
        paquete.fecha_entrega = datetime.now(timezone.utc)
        condominio_id = paquete.unidad.condominio_id
        db.commit()
    return RedirectResponse(f"/seguridad?condominio_id={condominio_id}", status_code=303)


@router.post("/seguridad/accesos-qr")
def seguridad_qr_create(
    request: Request,
    unidad_id: int = Form(...), invitado: str = Form(""),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not (is_admin(user) or is_guardia(user)):
        return _forbidden(request, user)
    db.add(AccesoQR(unidad_id=unidad_id, invitado=invitado or None, codigo=seguridad_services.generar_codigo()))
    db.commit()
    unidad = db.query(Unidad).get(unidad_id)
    return RedirectResponse(f"/seguridad?condominio_id={unidad.condominio_id}", status_code=303)


# ── Comunicación (administradores y residentes; no guardias) ───────────────

@router.get("/comunicacion", response_class=HTMLResponse)
def comunicacion_page(
    request: Request, condominio_id: int | None = None,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not (is_admin(user) or is_resident(user)):
        return _forbidden(request, user)
    condominios, condominio = _resolve_condominio(db, condominio_id)
    ctx = {"user": user, "active": "comunicacion", "condominios": condominios, "condominio": condominio,
           "condominio_id": condominio.id if condominio else None}
    if condominio:
        unidades = db.query(Unidad).filter(Unidad.condominio_id == condominio.id).all()
        unidad_ids = [u.id for u in unidades]
        avisos = db.query(Aviso).filter(Aviso.condominio_id == condominio.id).order_by(Aviso.created_at.desc()).all()
        tickets = (
            db.query(Ticket).filter(Ticket.unidad_id.in_(unidad_ids)).order_by(Ticket.created_at.desc()).all()
            if unidad_ids else []
        )
        ctx.update({
            "unidades": unidades, "avisos": avisos, "tickets": tickets,
            "unidades_by_id": {u.id: u.identificador for u in unidades},
        })
    return templates.TemplateResponse(request, "comunicacion.html", ctx)


@router.post("/comunicacion/avisos")
def comunicacion_aviso_create(
    request: Request,
    condominio_id: int = Form(...), titulo: str = Form(...), contenido: str = Form(...),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not is_admin(user):
        return _forbidden(request, user)
    db.add(Aviso(condominio_id=condominio_id, titulo=titulo, contenido=contenido, autor_id=user.id))
    db.commit()
    return RedirectResponse(f"/comunicacion?condominio_id={condominio_id}", status_code=303)


@router.post("/comunicacion/tickets")
def comunicacion_ticket_create(
    request: Request,
    titulo: str = Form(...), descripcion: str = Form(""), unidad_id: str | None = Form(None),
    prioridad: str = Form("MEDIA"),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not (is_admin(user) or is_resident(user)):
        return _forbidden(request, user)
    uid = _opt_int(unidad_id)
    db.add(Ticket(
        titulo=titulo, descripcion=descripcion or None, unidad_id=uid,
        prioridad=PrioridadTicket(prioridad), autor_id=user.id,
    ))
    db.commit()
    condominio_id = db.query(Unidad).get(uid).condominio_id if uid else None
    return RedirectResponse(f"/comunicacion?condominio_id={condominio_id}" if condominio_id else "/comunicacion", status_code=303)


@router.post("/comunicacion/tickets/{ticket_id}")
def comunicacion_ticket_update(
    ticket_id: int, request: Request, estado: str = Form(...),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not is_admin(user):
        return _forbidden(request, user)
    ticket = db.query(Ticket).get(ticket_id)
    condominio_id = None
    if ticket:
        ticket.estado = EstadoTicket(estado)
        if ticket.unidad_id:
            condominio_id = ticket.unidad.condominio_id
        db.commit()
    return RedirectResponse(f"/comunicacion?condominio_id={condominio_id}" if condominio_id else "/comunicacion", status_code=303)


# ── Mantenimiento (solo administradores) ────────────────────────────────────

@router.get("/mantenimiento", response_class=HTMLResponse)
def mantenimiento_page(
    request: Request, condominio_id: int | None = None,
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not is_admin(user):
        return _forbidden(request, user)
    condominios, condominio = _resolve_condominio(db, condominio_id)
    ctx = {"user": user, "active": "mantenimiento", "condominios": condominios, "condominio": condominio,
           "condominio_id": condominio.id if condominio else None}
    proveedores = db.query(Proveedor).order_by(Proveedor.nombre).all()
    ctx["proveedores"] = proveedores
    ctx["proveedores_by_id"] = {p.id: p.nombre for p in proveedores}
    if condominio:
        ordenes = db.query(OrdenTrabajo).filter(OrdenTrabajo.condominio_id == condominio.id).order_by(OrdenTrabajo.created_at.desc()).all()
        ctx["ordenes"] = ordenes
    return templates.TemplateResponse(request, "mantenimiento.html", ctx)


@router.post("/mantenimiento/proveedores")
def mantenimiento_proveedor_create(
    request: Request,
    nombre: str = Form(...), servicio: str = Form(""), telefono: str = Form(""), email: str = Form(""),
    condominio_id: str | None = Form(None),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not is_admin(user):
        return _forbidden(request, user)
    db.add(Proveedor(nombre=nombre, servicio=servicio or None, telefono=telefono or None, email=email or None))
    db.commit()
    return RedirectResponse(f"/mantenimiento?condominio_id={condominio_id}" if condominio_id else "/mantenimiento", status_code=303)


@router.post("/mantenimiento/ordenes")
def mantenimiento_orden_create(
    request: Request,
    condominio_id: int = Form(...), titulo: str = Form(...), descripcion: str = Form(""),
    proveedor_id: str | None = Form(None), prioridad: str = Form("MEDIA"),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not is_admin(user):
        return _forbidden(request, user)
    db.add(OrdenTrabajo(
        condominio_id=condominio_id, titulo=titulo, descripcion=descripcion or None,
        proveedor_id=_opt_int(proveedor_id), prioridad=PrioridadOrden(prioridad),
    ))
    db.commit()
    return RedirectResponse(f"/mantenimiento?condominio_id={condominio_id}", status_code=303)


@router.post("/mantenimiento/ordenes/{orden_id}")
def mantenimiento_orden_update(
    orden_id: int, request: Request, estado: str = Form(...),
    user: User | None = Depends(get_current_user_optional), db: Session = Depends(get_db),
):
    from datetime import datetime, timezone
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not is_admin(user):
        return _forbidden(request, user)
    orden = db.query(OrdenTrabajo).get(orden_id)
    condominio_id = None
    if orden:
        orden.estado = EstadoOrden(estado)
        if orden.estado == EstadoOrden.RESUELTA:
            orden.resuelta_at = datetime.now(timezone.utc)
        condominio_id = orden.condominio_id
        db.commit()
    return RedirectResponse(f"/mantenimiento?condominio_id={condominio_id}", status_code=303)


# ── Reportes: páginas (solo administradores) ────────────────────────────────

@router.get("/reportes", response_class=HTMLResponse)
def reportes_list(request: Request, user: User | None = Depends(get_current_user_optional)):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not is_admin(user):
        return _forbidden(request, user)
    projects = reportes_services.list_projects()
    return templates.TemplateResponse(
        request, "reportes_list.html",
        {"user": user, "active": "reportes", "projects": projects},
    )


@router.post("/reportes")
def reportes_create(
    request: Request,
    name: str = Form(...),
    user: User | None = Depends(get_current_user_optional),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not is_admin(user):
        return _forbidden(request, user)
    name = name.strip()
    if name:
        try:
            reportes_services.create_project(name)
        except FileExistsError:
            pass
    return RedirectResponse("/reportes", status_code=303)


@router.post("/reportes/{name}/delete")
def reportes_delete(name: str, request: Request, user: User | None = Depends(get_current_user_optional)):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not is_admin(user):
        return _forbidden(request, user)
    try:
        reportes_services.delete_project(name)
    except FileNotFoundError:
        pass
    return RedirectResponse("/reportes", status_code=303)


@router.get("/reportes/{name}", response_class=HTMLResponse)
def reportes_editor(
    name: str,
    request: Request,
    file: str | None = None,
    user: User | None = Depends(get_current_user_optional),
):
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not is_admin(user):
        return _forbidden(request, user)
    try:
        files = reportes_services.list_project_files(name)
    except FileNotFoundError:
        return RedirectResponse("/reportes", status_code=303)

    current_file = file or (files[0]["path"] if files else None)
    content = ""
    if current_file:
        try:
            content = reportes_services.read_file(name, current_file)
        except FileNotFoundError:
            current_file = None

    return templates.TemplateResponse(
        request, "reportes_editor.html",
        {
            "user": user, "active": "reportes",
            "project": name, "files": files,
            "current_file": current_file, "content": content,
        },
    )
