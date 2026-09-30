from sqlalchemy import Column, Integer, String, Numeric, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class Condominio(Base):
    __tablename__ = "condominios"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(150), nullable=False)
    direccion = Column(String(255), nullable=True)
    ciudad = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    unidades = relationship("Unidad", back_populates="condominio", cascade="all, delete-orphan")


class Unidad(Base):
    __tablename__ = "unidades"

    id = Column(Integer, primary_key=True, index=True)
    condominio_id = Column(Integer, ForeignKey("condominios.id", ondelete="CASCADE"), nullable=False)
    identificador = Column(String(50), nullable=False)  # ej. "A-101"
    grupo = Column(String(80), nullable=True)  # torre / clúster, para emisión masiva por grupo
    tipo = Column(String(50), default="departamento")
    cuota_mantenimiento = Column(Numeric(12, 2), nullable=False, default=0)
    indiviso_pct = Column(Numeric(6, 3), nullable=True)  # % de copropiedad, para cuotas prorrateadas por indiviso
    saldo_favor = Column(Numeric(12, 2), nullable=False, default=0)  # billetera virtual (pagos anticipados)
    propietario_id = Column(Integer, ForeignKey("propietarios.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    condominio = relationship("Condominio", back_populates="unidades")
    propietario = relationship("Propietario", back_populates="unidades")
