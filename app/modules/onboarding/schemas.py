from typing import Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict

from app.modules.onboarding.models import EstadoPaso, PasoOnboarding


class ChecklistItem(BaseModel):
    paso: str
    titulo: str
    descripcion: str
    estado: str


class EstadoPasoUpdate(BaseModel):
    estado: EstadoPaso


class InvitacionCreate(BaseModel):
    propietario_id: int
    email: Optional[str] = None


class InvitacionResponse(BaseModel):
    id: int
    propietario_id: int
    email: str
    token: str
    usado: bool
    created_at: datetime
    expires_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class ActivacionRequest(BaseModel):
    full_name: str
    password: str
