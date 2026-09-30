from typing import Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict

from app.modules.mantenimiento.models import EstadoOrden, PrioridadOrden


class ProveedorCreate(BaseModel):
    nombre: str
    servicio: Optional[str] = None
    telefono: Optional[str] = None
    email: Optional[str] = None


class ProveedorResponse(ProveedorCreate):
    id: int
    model_config = ConfigDict(from_attributes=True)


class OrdenTrabajoCreate(BaseModel):
    condominio_id: int
    proveedor_id: Optional[int] = None
    titulo: str
    descripcion: Optional[str] = None
    prioridad: PrioridadOrden = PrioridadOrden.MEDIA


class OrdenTrabajoUpdate(BaseModel):
    estado: EstadoOrden


class OrdenTrabajoResponse(BaseModel):
    id: int
    condominio_id: int
    proveedor_id: Optional[int] = None
    titulo: str
    descripcion: Optional[str] = None
    estado: EstadoOrden
    prioridad: PrioridadOrden
    created_at: datetime
    resuelta_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)
