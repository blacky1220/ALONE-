from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_admin_or_resident
from app.modules.auth.models import User
from app.modules.comunicacion.models import Aviso, Ticket
from app.modules.comunicacion.schemas import (
    AvisoCreate, AvisoResponse, TicketCreate, TicketResponse, TicketUpdate,
)

router = APIRouter(
    prefix="/comunicacion",
    tags=["Comunicación"],
    dependencies=[Depends(require_admin_or_resident)],
)


# ── Avisos ───────────────────────────────────────────────────────────────────

@router.get("/avisos", response_model=list[AvisoResponse])
def list_avisos(condominio_id: int, db: Session = Depends(get_db)):
    return (
        db.query(Aviso)
        .filter(Aviso.condominio_id == condominio_id)
        .order_by(Aviso.created_at.desc())
        .all()
    )


@router.post("/avisos", response_model=AvisoResponse, status_code=201)
def create_aviso(
    data: AvisoCreate, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_resident)
):
    aviso = Aviso(**data.model_dump(), autor_id=current_user.id)
    db.add(aviso)
    db.commit()
    db.refresh(aviso)
    return aviso


# ── Tickets ──────────────────────────────────────────────────────────────────

@router.get("/tickets", response_model=list[TicketResponse])
def list_tickets(unidad_id: int | None = None, db: Session = Depends(get_db)):
    query = db.query(Ticket)
    if unidad_id:
        query = query.filter(Ticket.unidad_id == unidad_id)
    return query.order_by(Ticket.created_at.desc()).all()


@router.post("/tickets", response_model=TicketResponse, status_code=201)
def create_ticket(
    data: TicketCreate, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_resident)
):
    ticket = Ticket(**data.model_dump(), autor_id=current_user.id)
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


@router.patch("/tickets/{ticket_id}", response_model=TicketResponse)
def update_ticket(ticket_id: int, data: TicketUpdate, db: Session = Depends(get_db)):
    ticket = db.query(Ticket).get(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket no encontrado")
    ticket.estado = data.estado
    db.commit()
    db.refresh(ticket)
    return ticket
