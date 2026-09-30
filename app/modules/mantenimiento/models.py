import enum
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Enum, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class EstadoOrden(str, enum.Enum):
    ABIERTA = "ABIERTA"
    EN_PROCESO = "EN_PROCESO"
    RESUELTA = "RESUELTA"


class PrioridadOrden(str, enum.Enum):
    BAJA = "BAJA"
    MEDIA = "MEDIA"
    ALTA = "ALTA"


class Proveedor(Base):
    __tablename__ = "proveedores"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(150), nullable=False)
    servicio = Column(String(150), nullable=True)
    telefono = Column(String(20), nullable=True)
    email = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    ordenes = relationship("OrdenTrabajo", back_populates="proveedor")


class OrdenTrabajo(Base):
    __tablename__ = "ordenes_trabajo"

    id = Column(Integer, primary_key=True, index=True)
    condominio_id = Column(Integer, ForeignKey("condominios.id", ondelete="CASCADE"), nullable=False)
    proveedor_id = Column(Integer, ForeignKey("proveedores.id", ondelete="SET NULL"), nullable=True)
    titulo = Column(String(150), nullable=False)
    descripcion = Column(Text, nullable=True)
    estado = Column(Enum(EstadoOrden), default=EstadoOrden.ABIERTA)
    prioridad = Column(Enum(PrioridadOrden), default=PrioridadOrden.MEDIA)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    resuelta_at = Column(DateTime(timezone=True), nullable=True)

    proveedor = relationship("Proveedor", back_populates="ordenes")
