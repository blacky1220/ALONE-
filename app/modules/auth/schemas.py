from typing import Optional
from datetime import datetime
from pydantic import BaseModel, EmailStr, ConfigDict


# Esquemas de Tokens
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    sub: Optional[str] = None


# Esquemas de Usuario
class UserBase(BaseModel):
    email: EmailStr
    full_name: str
    phone: Optional[str] = None
    is_active: bool = True


class UserCreate(UserBase):
    password: str
    role_id: Optional[int] = None


class UserResponse(UserBase):
    id: int
    is_superuser: bool
    role_id: Optional[int] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# Solicitud de inicio de sesión JSON
class LoginRequest(BaseModel):
    email: EmailStr
    password: str