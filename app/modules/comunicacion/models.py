import enum
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Enum, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class EstadoTicket(str, enum.Enum):
    ABIERTO = "ABIERTO"
    EN_PROCESO = "EN_PROCESO"
    CERRADO = "CERRADO"


class PrioridadTicket(str, enum.Enum):
    BAJA = "BAJA"
    MEDIA = "MEDIA"
    ALTA = "ALTA"


class Aviso(Base):
    __tablename__ = "avisos"

    id = Column(Integer, primary_key=True, index=True)
    condominio_id = Column(Integer, ForeignKey("condominios.id", ondelete="CASCADE"), nullable=False)
    titulo = Column(String(150), nullable=False)
    contenido = Column(Text, nullable=False)
    autor_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    autor = relationship("User")


class Ticket(Base):
    """Ticket de incidencia / queja / sugerencia reportado por un residente."""
    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True, index=True)
    unidad_id = Column(Integer, ForeignKey("unidades.id", ondelete="CASCADE"), nullable=True)
    titulo = Column(String(150), nullable=False)
    descripcion = Column(Text, nullable=True)
    estado = Column(Enum(EstadoTicket), default=EstadoTicket.ABIERTO)
    prioridad = Column(Enum(PrioridadTicket), default=PrioridadTicket.MEDIA)
    autor_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    unidad = relationship("Unidad")
    autor = relationship("User")
