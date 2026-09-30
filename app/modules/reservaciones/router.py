from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_admin_or_resident
from app.modules.reservaciones import services
from app.modules.reservaciones.models import Amenidad, EstadoReservacion, Reservacion
from app.modules.reservaciones.schemas import (
    AmenidadCreate, AmenidadResponse, ReservacionCreate, ReservacionResponse,
)

router = APIRouter(
    prefix="/reservaciones",
    tags=["Reservaciones"],
    dependencies=[Depends(require_admin_or_resident)],
)


@router.get("/amenidades", response_model=list[AmenidadResponse])
def list_amenidades(condominio_id: int, db: Session = Depends(get_db)):
    return db.query(Amenidad).filter(Amenidad.condominio_id == condominio_id).all()


@router.post("/amenidades", response_model=AmenidadResponse, status_code=201)
def create_amenidad(data: AmenidadCreate, db: Session = Depends(get_db)):
    amenidad = Amenidad(**data.model_dump())
    db.add(amenidad)
    db.commit()
    db.refresh(amenidad)
    return amenidad


@router.get("", response_model=list[ReservacionResponse])
def list_reservaciones(amenidad_id: int | None = None, unidad_id: int | None = None, db: Session = Depends(get_db)):
    query = db.query(Reservacion)
    if amenidad_id:
        query = query.filter(Reservacion.amenidad_id == amenidad_id)
    if unidad_id:
        query = query.filter(Reservacion.unidad_id == unidad_id)
    return query.order_by(Reservacion.fecha.desc()).all()


@router.post("", response_model=ReservacionResponse, status_code=201)
def create_reservacion(data: ReservacionCreate, db: Session = Depends(get_db)):
    amenidad = db.query(Amenidad).get(data.amenidad_id)
    if not amenidad:
        raise HTTPException(404, "Amenidad no encontrada")
    if data.hora_inicio >= data.hora_fin:
        raise HTTPException(400, "La hora de inicio debe ser anterior a la hora de fin")
    if services.hay_traslape(db, data.amenidad_id, data.fecha, data.hora_inicio, data.hora_fin):
        raise HTTPException(409, "Ya existe una reservación en ese horario para esta amenidad")

    reservacion = Reservacion(**data.model_dump())
    db.add(reservacion)
    db.commit()
    db.refresh(reservacion)
    return reservacion


@router.post("/{reservacion_id}/cancelar", response_model=ReservacionResponse)
def cancelar_reservacion(reservacion_id: int, db: Session = Depends(get_db)):
    reservacion = db.query(Reservacion).get(reservacion_id)
    if not reservacion:
        raise HTTPException(404, "Reservación no encontrada")
    reservacion.estado = EstadoReservacion.CANCELADA
    db.commit()
    db.refresh(reservacion)
    return reservacion
