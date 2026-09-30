from typing import Generator, Optional
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.modules.auth.models import User

# Indica a FastAPI de dónde extraer el token Bearer
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")

COOKIE_NAME = "access_token"


def _decode_user(token: str, db: Session) -> Optional[User]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            return None
    except JWTError:
        return None

    try:
        user = db.query(User).filter(User.id == int(user_id)).first()
        if user is None or not user.is_active:
            return None
        return user
    except Exception:
        return None


def get_current_user_optional(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    """
    Igual que get_current_user pero devuelve None en lugar de lanzar 401.
    Usado por las páginas HTML para decidir si mostrar sesión iniciada o no.
    Acepta el token tanto por header Authorization como por cookie (para el frontend).
    """
    token = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1]
    if not token:
        token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    return _decode_user(token, db)


def get_current_user_flexible(request: Request, db: Session = Depends(get_db)) -> User:
    """
    Como get_current_user, pero también acepta el JWT desde la cookie de sesión
    del frontend además del header Authorization. Usado por endpoints de la API
    que también son consumidos por las páginas HTML (ej. módulo de reportes).
    """
    user = get_current_user_optional(request, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No se pudieron validar las credenciales",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_current_user(
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme)
) -> User:
    """
    Decodifica el JWT, valida la firma y recupera el usuario actual de la BD.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudieron validar las credenciales",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None:
        raise credentials_exception
        
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Usuario inactivo"
        )
        
    return user


def get_current_active_superuser(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Verifica si el usuario autenticado tiene rol de Superadmin del SaaS.
    """
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El usuario no tiene permisos de superadministrador"
        )
    return current_user


def require_admin(current_user: User = Depends(get_current_user_flexible)) -> User:
    from app.core.rbac import is_admin
    if not is_admin(current_user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Requiere rol de administrador")
    return current_user


def require_admin_or_guardia(current_user: User = Depends(get_current_user_flexible)) -> User:
    from app.core.rbac import is_admin, is_guardia
    if not (is_admin(current_user) or is_guardia(current_user)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Requiere rol de administrador o guardia")
    return current_user


def require_admin_or_resident(current_user: User = Depends(get_current_user_flexible)) -> User:
    from app.core.rbac import is_admin, is_resident
    if not (is_admin(current_user) or is_resident(current_user)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No tienes permisos para acceder a este recurso")
    return current_user


def require_finance_read(current_user: User = Depends(get_current_user_flexible)) -> User:
    """Módulo contable (Ingresos/Cuotas/Egresos/Cuentas por pagar) en modo lectura:
    SUPER_ADMIN, CONTADOR (ACCOUNTANT) o AUDITOR."""
    from app.core.rbac import can_read_finance_module
    if not can_read_finance_module(current_user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No tienes permisos de lectura sobre el módulo contable")
    return current_user


def require_finance_write(current_user: User = Depends(get_current_user_flexible)) -> User:
    """Módulo contable en modo escritura (capturar/editar/generar/aplicar):
    SUPER_ADMIN o CONTADOR (ACCOUNTANT). AUDITOR queda excluido a propósito."""
    from app.core.rbac import can_write_finance_module
    if not can_write_finance_module(current_user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tu rol solo tiene acceso de lectura al módulo contable")
    return current_user