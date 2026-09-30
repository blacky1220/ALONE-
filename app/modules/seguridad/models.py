from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Boolean, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class Visita(Base):
    __tablename__ = "visitas"

    id = Column(Integer, primary_key=True, index=True)
    unidad_id = Column(Integer, ForeignKey("unidades.id", ondelete="CASCADE"), nullable=False)
    nombre_visitante = Column(String(150), nullable=False)
    motivo = Column(String(255), nullable=True)
    entrada = Column(DateTime(timezone=True), server_default=func.now())
    salida = Column(DateTime(timezone=True), nullable=True)

    unidad = relationship("Unidad")


class Paquete(Base):
    __tablename__ = "paquetes"

    id = Column(Integer, primary_key=True, index=True)
    unidad_id = Column(Integer, ForeignKey("unidades.id", ondelete="CASCADE"), nullable=False)
    descripcion = Column(String(255), nullable=True)
    recibido_por = Column(String(150), nullable=True)
    fecha_recepcion = Column(DateTime(timezone=True), server_default=func.now())
    entregado = Column(Boolean, default=False)
    fecha_entrega = Column(DateTime(timezone=True), nullable=True)

    unidad = relationship("Unidad")


class AccesoQR(Base):
    """Invitación de acceso por código QR de un solo uso para visitantes."""
    __tablename__ = "accesos_qr"

    id = Column(Integer, primary_key=True, index=True)
    unidad_id = Column(Integer, ForeignKey("unidades.id", ondelete="CASCADE"), nullable=False)
    codigo = Column(String(64), unique=True, nullable=False)
    invitado = Column(String(150), nullable=True)
    usado = Column(Boolean, default=False)
    fecha_uso = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    unidad = relationship("Unidad")
