from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_admin
from app.modules.onboarding import services
from app.modules.onboarding.models import InvitacionResidente, PasoOnboarding
from app.modules.onboarding.schemas import (
    ChecklistItem,
    EstadoPasoUpdate,
    InvitacionCreate,
    InvitacionResponse,
)
from app.modules.propietarios.models import Propietario

router = APIRouter(
    prefix="/onboarding",
    tags=["Onboarding"],
    dependencies=[Depends(require_admin)],
)


@router.get("/checklist", response_model=list[ChecklistItem])
def get_checklist(condominio_id: int, db: Session = Depends(get_db)):
    return services.checklist(db, condominio_id)


@router.post("/checklist/{paso}/estado")
def set_estado_paso(paso: PasoOnboarding, condominio_id: int, data: EstadoPasoUpdate, db: Session = Depends(get_db)):
    services.establecer_estado(db, condominio_id, paso, data.estado)
    return {"ok": True}


@router.get("/invitaciones", response_model=list[InvitacionResponse])
def list_invitaciones(propietario_id: int | None = None, db: Session = Depends(get_db)):
    query = db.query(InvitacionResidente)
    if propietario_id:
        query = query.filter(InvitacionResidente.propietario_id == propietario_id)
    return query.order_by(InvitacionResidente.created_at.desc()).all()


@router.post("/invitaciones", response_model=InvitacionResponse, status_code=201)
def create_invitacion(data: InvitacionCreate, db: Session = Depends(get_db)):
    propietario = db.query(Propietario).get(data.propietario_id)
    if not propietario:
        raise HTTPException(404, "Propietario no encontrado")
    invitacion = InvitacionResidente(
        propietario_id=propietario.id,
        email=data.email or propietario.email,
        token=services.generar_token(),
        expires_at=services.token_expira_en(),
    )
    db.add(invitacion)
    db.commit()
    db.refresh(invitacion)
    return invitacion
