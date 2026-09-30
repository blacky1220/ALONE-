import enum
from sqlalchemy import Column, Integer, String, Numeric, ForeignKey, DateTime, Date, Time, Enum, Boolean, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class EstadoReservacion(str, enum.Enum):
    CONFIRMADA = "CONFIRMADA"
    CANCELADA = "CANCELADA"


class Amenidad(Base):
    __tablename__ = "amenidades"

    id = Column(Integer, primary_key=True, index=True)
    condominio_id = Column(Integer, ForeignKey("condominios.id", ondelete="CASCADE"), nullable=False)
    nombre = Column(String(100), nullable=False)
    descripcion = Column(Text, nullable=True)
    capacidad = Column(Integer, nullable=True)
    hora_apertura = Column(Time, nullable=True)
    hora_cierre = Column(Time, nullable=True)
    requiere_deposito = Column(Boolean, default=False)
    monto_deposito = Column(Numeric(12, 2), default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    reservaciones = relationship("Reservacion", back_populates="amenidad", cascade="all, delete-orphan")


class Reservacion(Base):
    __tablename__ = "reservaciones"

    id = Column(Integer, primary_key=True, index=True)
    amenidad_id = Column(Integer, ForeignKey("amenidades.id", ondelete="CASCADE"), nullable=False)
    unidad_id = Column(Integer, ForeignKey("unidades.id", ondelete="CASCADE"), nullable=False)
    fecha = Column(Date, nullable=False)
    hora_inicio = Column(Time, nullable=False)
    hora_fin = Column(Time, nullable=False)
    estado = Column(Enum(EstadoReservacion), default=EstadoReservacion.CONFIRMADA)
    deposito_pagado = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    amenidad = relationship("Amenidad", back_populates="reservaciones")
    unidad = relationship("Unidad")
