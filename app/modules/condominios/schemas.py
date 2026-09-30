from typing import Optional
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict


class CondominioCreate(BaseModel):
    nombre: str
    direccion: Optional[str] = None
    ciudad: Optional[str] = None


class CondominioResponse(CondominioCreate):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class UnidadCreate(BaseModel):
    condominio_id: int
    identificador: str
    grupo: Optional[str] = None
    tipo: str = "departamento"
    cuota_mantenimiento: Decimal = Decimal("0")
    indiviso_pct: Optional[Decimal] = None
    propietario_id: Optional[int] = None


class UnidadUpdate(BaseModel):
    identificador: Optional[str] = None
    grupo: Optional[str] = None
    tipo: Optional[str] = None
    cuota_mantenimiento: Optional[Decimal] = None
    indiviso_pct: Optional[Decimal] = None
    propietario_id: Optional[int] = None


class UnidadResponse(BaseModel):
    id: int
    condominio_id: int
    identificador: str
    grupo: Optional[str] = None
    tipo: str
    cuota_mantenimiento: Decimal
    indiviso_pct: Optional[Decimal] = None
    saldo_favor: Decimal
    propietario_id: Optional[int] = None
    model_config = ConfigDict(from_attributes=True)
