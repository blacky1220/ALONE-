from typing import Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class VisitaCreate(BaseModel):
    unidad_id: int
    nombre_visitante: str
    motivo: Optional[str] = None


class VisitaResponse(VisitaCreate):
    id: int
    entrada: datetime
    salida: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class PaqueteCreate(BaseModel):
    unidad_id: int
    descripcion: Optional[str] = None
    recibido_por: Optional[str] = None


class PaqueteResponse(PaqueteCreate):
    id: int
    fecha_recepcion: datetime
    entregado: bool
    fecha_entrega: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class AccesoQRCreate(BaseModel):
    unidad_id: int
    invitado: Optional[str] = None


class AccesoQRResponse(BaseModel):
    id: int
    unidad_id: int
    codigo: str
    invitado: Optional[str] = None
    usado: bool
    fecha_uso: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)
