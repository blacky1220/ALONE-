from typing import Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class PropietarioCreate(BaseModel):
    full_name: str
    email: Optional[str] = None
    phone: Optional[str] = None


class PropietarioResponse(PropietarioCreate):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
