import enum
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Table
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base

# Tabla de asociación Muchos a Muchos entre Roles y Permisos
role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", Integer, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)


class UserRoleEnum(str, enum.Enum):
    SUPERADMIN = "SUPERADMIN"
    ADMIN_CONDOMINIO = "ADMIN_CONDOMINIO"
    CONTADOR = "CONTADOR"  # ACCOUNTANT: opera el módulo contable/financiero completo
    AUDITOR = "AUDITOR"  # AUDITOR: solo lectura del módulo contable/financiero
    PROPIETARIO = "PROPIETARIO"
    RESIDENTE = "RESIDENTE"
    INQUILINO = "INQUILINO"
    GUARDIA = "GUARDIA"


class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False, index=True)
    description = Column(String(255), nullable=True)

    # Relaciones
    users = relationship("User", back_populates="role")
    permissions = relationship("Permission", secondary=role_permissions, back_populates="roles")


class Permission(Base):
    __tablename__ = "permissions"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(100), unique=True, nullable=False, index=True)  # ej: "finanzas:read"
    description = Column(String(255), nullable=True)

    # Relaciones
    roles = relationship("Role", secondary=role_permissions, back_populates="permissions")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(150), nullable=False)
    phone = Column(String(20), nullable=True)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)

    role_id = Column(Integer, ForeignKey("roles.id", ondelete="SET NULL"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relaciones
    role = relationship("Role", back_populates="users")