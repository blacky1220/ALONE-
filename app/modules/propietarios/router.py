from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_admin
from app.modules.propietarios.models import Propietario
from app.modules.propietarios.schemas import PropietarioCreate, PropietarioResponse

router = APIRouter(
    prefix="/propietarios",
    tags=["Propietarios"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[PropietarioResponse])
def list_propietarios(db: Session = Depends(get_db)):
    return db.query(Propietario).order_by(Propietario.full_name).all()


@router.post("", response_model=PropietarioResponse, status_code=201)
def create_propietario(data: PropietarioCreate, db: Session = Depends(get_db)):
    propietario = Propietario(**data.model_dump())
    db.add(propietario)
    db.commit()
    db.refresh(propietario)
    return propietario


@router.get("/{propietario_id}", response_model=PropietarioResponse)
def get_propietario(propietario_id: int, db: Session = Depends(get_db)):
    propietario = db.query(Propietario).get(propietario_id)
    if not propietario:
        raise HTTPException(404, "Propietario no encontrado")
    return propietario


@router.delete("/{propietario_id}")
def delete_propietario(propietario_id: int, db: Session = Depends(get_db)):
    propietario = db.query(Propietario).get(propietario_id)
    if not propietario:
        raise HTTPException(404, "Propietario no encontrado")
    db.delete(propietario)
    db.commit()
    return {"deleted": True}
