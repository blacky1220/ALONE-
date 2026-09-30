from typing import Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict

from app.modules.comunicacion.models import EstadoTicket, PrioridadTicket


class AvisoCreate(BaseModel):
    condominio_id: int
    titulo: str
    contenido: str


class AvisoResponse(AvisoCreate):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class TicketCreate(BaseModel):
    unidad_id: Optional[int] = None
    titulo: str
    descripcion: Optional[str] = None
    prioridad: PrioridadTicket = PrioridadTicket.MEDIA


class TicketUpdate(BaseModel):
    estado: EstadoTicket


class TicketResponse(BaseModel):
    id: int
    unidad_id: Optional[int] = None
    titulo: str
    descripcion: Optional[str] = None
    estado: EstadoTicket
    prioridad: PrioridadTicket
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
