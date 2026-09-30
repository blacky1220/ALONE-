from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_admin
from app.modules.condominios.models import Condominio, Unidad
from app.modules.condominios.schemas import (
    CondominioCreate, CondominioResponse, UnidadCreate, UnidadResponse, UnidadUpdate,
)

router = APIRouter(
    prefix="/condominios",
    tags=["Condominios"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[CondominioResponse])
def list_condominios(db: Session = Depends(get_db)):
    return db.query(Condominio).order_by(Condominio.nombre).all()


@router.post("", response_model=CondominioResponse, status_code=201)
def create_condominio(data: CondominioCreate, db: Session = Depends(get_db)):
    condominio = Condominio(**data.model_dump())
    db.add(condominio)
    db.commit()
    db.refresh(condominio)
    return condominio


@router.get("/{condominio_id}", response_model=CondominioResponse)
def get_condominio(condominio_id: int, db: Session = Depends(get_db)):
    condominio = db.query(Condominio).get(condominio_id)
    if not condominio:
        raise HTTPException(404, "Condominio no encontrado")
    return condominio


@router.get("/{condominio_id}/unidades", response_model=list[UnidadResponse])
def list_unidades(condominio_id: int, db: Session = Depends(get_db)):
    return db.query(Unidad).filter(Unidad.condominio_id == condominio_id).order_by(Unidad.identificador).all()


@router.post("/unidades", response_model=UnidadResponse, status_code=201)
def create_unidad(data: UnidadCreate, db: Session = Depends(get_db)):
    if not db.query(Condominio).get(data.condominio_id):
        raise HTTPException(404, "Condominio no encontrado")
    unidad = Unidad(**data.model_dump())
    db.add(unidad)
    db.commit()
    db.refresh(unidad)
    return unidad


@router.patch("/unidades/{unidad_id}", response_model=UnidadResponse)
def update_unidad(unidad_id: int, data: UnidadUpdate, db: Session = Depends(get_db)):
    unidad = db.query(Unidad).get(unidad_id)
    if not unidad:
        raise HTTPException(404, "Unidad no encontrada")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(unidad, field, value)
    db.commit()
    db.refresh(unidad)
    return unidad


@router.delete("/unidades/{unidad_id}")
def delete_unidad(unidad_id: int, db: Session = Depends(get_db)):
    unidad = db.query(Unidad).get(unidad_id)
    if not unidad:
        raise HTTPException(404, "Unidad no encontrada")
    db.delete(unidad)
    db.commit()
    return {"deleted": True}
