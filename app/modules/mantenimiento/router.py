from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_admin
from app.modules.mantenimiento.models import EstadoOrden, OrdenTrabajo, Proveedor
from app.modules.mantenimiento.schemas import (
    OrdenTrabajoCreate, OrdenTrabajoResponse, OrdenTrabajoUpdate, ProveedorCreate, ProveedorResponse,
)

router = APIRouter(
    prefix="/mantenimiento",
    tags=["Mantenimiento"],
    dependencies=[Depends(require_admin)],
)


# ── Proveedores ──────────────────────────────────────────────────────────────

@router.get("/proveedores", response_model=list[ProveedorResponse])
def list_proveedores(db: Session = Depends(get_db)):
    return db.query(Proveedor).order_by(Proveedor.nombre).all()


@router.post("/proveedores", response_model=ProveedorResponse, status_code=201)
def create_proveedor(data: ProveedorCreate, db: Session = Depends(get_db)):
    proveedor = Proveedor(**data.model_dump())
    db.add(proveedor)
    db.commit()
    db.refresh(proveedor)
    return proveedor


# ── Órdenes de trabajo ───────────────────────────────────────────────────────

@router.get("/ordenes", response_model=list[OrdenTrabajoResponse])
def list_ordenes(condominio_id: int, db: Session = Depends(get_db)):
    return (
        db.query(OrdenTrabajo)
        .filter(OrdenTrabajo.condominio_id == condominio_id)
        .order_by(OrdenTrabajo.created_at.desc())
        .all()
    )


@router.post("/ordenes", response_model=OrdenTrabajoResponse, status_code=201)
def create_orden(data: OrdenTrabajoCreate, db: Session = Depends(get_db)):
    orden = OrdenTrabajo(**data.model_dump())
    db.add(orden)
    db.commit()
    db.refresh(orden)
    return orden


@router.patch("/ordenes/{orden_id}", response_model=OrdenTrabajoResponse)
def update_orden(orden_id: int, data: OrdenTrabajoUpdate, db: Session = Depends(get_db)):
    orden = db.query(OrdenTrabajo).get(orden_id)
    if not orden:
        raise HTTPException(404, "Orden no encontrada")
    orden.estado = data.estado
    if data.estado == EstadoOrden.RESUELTA:
        orden.resuelta_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(orden)
    return orden
