from typing import Optional
from datetime import date, time
from decimal import Decimal
from pydantic import BaseModel, ConfigDict

from app.modules.reservaciones.models import EstadoReservacion


class AmenidadCreate(BaseModel):
    condominio_id: int
    nombre: str
    descripcion: Optional[str] = None
    capacidad: Optional[int] = None
    hora_apertura: Optional[time] = None
    hora_cierre: Optional[time] = None
    requiere_deposito: bool = False
    monto_deposito: Decimal = Decimal("0")


class AmenidadResponse(AmenidadCreate):
    id: int
    model_config = ConfigDict(from_attributes=True)


class ReservacionCreate(BaseModel):
    amenidad_id: int
    unidad_id: int
    fecha: date
    hora_inicio: time
    hora_fin: time


class ReservacionResponse(BaseModel):
    id: int
    amenidad_id: int
    unidad_id: int
    fecha: date
    hora_inicio: time
    hora_fin: time
    estado: EstadoReservacion
    deposito_pagado: bool
    model_config = ConfigDict(from_attributes=True)
