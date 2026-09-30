"""Matriz de roles y accesos (RBAC).

Super Administrador (SUPERADMIN, ADMIN_CONDOMINIO): acceso total.
Contador (CONTADOR / ACCOUNTANT): opera el módulo contable/financiero completo
(capturar, editar, generar, aplicar) pero no administra condominios, usuarios ni RBAC.
Auditor (AUDITOR): solo lectura del módulo contable/financiero — ve reportes,
bitácoras y comprobantes, no puede capturar ni modificar nada.
Guardia (GUARDIA): solo seguridad, sin acceso financiero.
Propietario / Residente (PROPIETARIO, RESIDENTE): autoservicio — su estado de
cuenta, reservas, avisos y tickets.
Inquilino (INQUILINO): igual que residente pero sin visibilidad financiera.
"""

from sqlalchemy.orm import Session

from app.modules.auth.models import Role, User, UserRoleEnum

ADMIN_ROLES = {UserRoleEnum.SUPERADMIN.value, UserRoleEnum.ADMIN_CONDOMINIO.value}
CONTADOR_ROLES = {UserRoleEnum.CONTADOR.value}
AUDITOR_ROLES = {UserRoleEnum.AUDITOR.value}
GUARDIA_ROLES = {UserRoleEnum.GUARDIA.value}
RESIDENT_ROLES = {UserRoleEnum.PROPIETARIO.value, UserRoleEnum.RESIDENTE.value, UserRoleEnum.INQUILINO.value}
FINANCE_VISIBLE_ROLES = ADMIN_ROLES | {UserRoleEnum.PROPIETARIO.value, UserRoleEnum.RESIDENTE.value}

# Módulo contable/financiero (Ingresos, Cuotas, Egresos, Cuentas por pagar):
# quién puede CAPTURAR/EDITAR/GENERAR/APLICAR vs. quién solo puede CONSULTAR.
FINANCE_WRITE_ROLES = ADMIN_ROLES | CONTADOR_ROLES
FINANCE_READ_ROLES = FINANCE_WRITE_ROLES | AUDITOR_ROLES

ROLE_LABELS = {
    UserRoleEnum.SUPERADMIN.value: "Super administrador",
    UserRoleEnum.ADMIN_CONDOMINIO.value: "Administrador del condominio",
    UserRoleEnum.CONTADOR.value: "Contador",
    UserRoleEnum.AUDITOR.value: "Auditor",
    UserRoleEnum.PROPIETARIO.value: "Propietario",
    UserRoleEnum.RESIDENTE.value: "Residente",
    UserRoleEnum.INQUILINO.value: "Inquilino",
    UserRoleEnum.GUARDIA.value: "Guardia",
}


def role_name(user: User | None) -> str | None:
    if user is None or user.role is None:
        return None
    return user.role.name


def is_admin(user: User | None) -> bool:
    return role_name(user) in ADMIN_ROLES


def is_contador(user: User | None) -> bool:
    return role_name(user) in CONTADOR_ROLES


def is_auditor(user: User | None) -> bool:
    return role_name(user) in AUDITOR_ROLES


def is_guardia(user: User | None) -> bool:
    return role_name(user) in GUARDIA_ROLES


def is_resident(user: User | None) -> bool:
    return role_name(user) in RESIDENT_ROLES


def can_see_finance(user: User | None) -> bool:
    return role_name(user) in FINANCE_VISIBLE_ROLES


def can_read_finance_module(user: User | None) -> bool:
    """Puede ver el módulo contable (Ingresos/Cuotas/Egresos/Cuentas por pagar): admin, contador o auditor."""
    return role_name(user) in FINANCE_READ_ROLES


def can_write_finance_module(user: User | None) -> bool:
    """Puede capturar/editar/generar/aplicar en el módulo contable: admin o contador (no auditor)."""
    return role_name(user) in FINANCE_WRITE_ROLES


def seed_roles(db: Session) -> None:
    """Crea las filas de Role si no existen todavía."""
    existing = {r.name for r in db.query(Role).all()}
    for role_enum in UserRoleEnum:
        if role_enum.value not in existing:
            db.add(Role(name=role_enum.value))
    db.commit()


def backfill_missing_roles(db: Session) -> None:
    """Asigna SUPERADMIN a cuentas creadas antes de que existiera RBAC (role_id nulo)."""
    superadmin = db.query(Role).filter(Role.name == UserRoleEnum.SUPERADMIN.value).first()
    if not superadmin:
        return
    db.query(User).filter(User.role_id.is_(None)).update({User.role_id: superadmin.id})
    db.commit()


def default_role_id_for_new_user(db: Session) -> int:
    """Primer usuario del sistema -> SUPERADMIN. Los siguientes -> PROPIETARIO por defecto
    (un administrador puede reasignarles el rol correcto después desde /usuarios)."""
    is_first_user = db.query(User).count() == 0
    role_name_ = UserRoleEnum.SUPERADMIN.value if is_first_user else UserRoleEnum.PROPIETARIO.value
    role = db.query(Role).filter(Role.name == role_name_).first()
    return role.id if role else None
