import enum
from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class PasoOnboarding(str, enum.Enum):
    PRESUPUESTO = "PRESUPUESTO"
    BANCOS = "BANCOS"
    ADEUDOS_INICIALES = "ADEUDOS_INICIALES"
    SALDOS_FAVOR = "SALDOS_FAVOR"
    CUOTAS = "CUOTAS"
    INGRESOS = "INGRESOS"
    EGRESOS = "EGRESOS"
    INVITACIONES = "INVITACIONES"


class EstadoPaso(str, enum.Enum):
    PENDIENTE = "PENDIENTE"
    EN_PROGRESO = "EN_PROGRESO"
    COMPLETADO = "COMPLETADO"


class OnboardingProgreso(Base):
    __tablename__ = "onboarding_progreso"
    __table_args__ = (UniqueConstraint("condominio_id", "paso", name="uq_onboarding_condominio_paso"),)

    id = Column(Integer, primary_key=True, index=True)
    condominio_id = Column(Integer, ForeignKey("condominios.id", ondelete="CASCADE"), nullable=False)
    paso = Column(Enum(PasoOnboarding), nullable=False)
    estado = Column(Enum(EstadoPaso), default=EstadoPaso.PENDIENTE, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class InvitacionResidente(Base):
    """Invitación de enrolamiento con enlace mágico. El envío real por correo/WhatsApp
    requiere conectar un proveedor (ver app/utils/mailer.py y whatsapp.py); por ahora
    el enlace se genera y se comparte manualmente desde la UI."""
    __tablename__ = "invitaciones_residentes"

    id = Column(Integer, primary_key=True, index=True)
    propietario_id = Column(Integer, ForeignKey("propietarios.id", ondelete="CASCADE"), nullable=False)
    email = Column(String(255), nullable=False)
    token = Column(String(64), unique=True, nullable=False)
    usado = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)

    propietario = relationship("Propietario")
