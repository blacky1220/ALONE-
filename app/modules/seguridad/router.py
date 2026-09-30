from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_admin_or_guardia
from app.modules.seguridad import services
from app.modules.seguridad.models import AccesoQR, Paquete, Visita
from app.modules.seguridad.schemas import (
    AccesoQRCreate, AccesoQRResponse, PaqueteCreate, PaqueteResponse, VisitaCreate, VisitaResponse,
)

router = APIRouter(
    prefix="/seguridad",
    tags=["Seguridad"],
    dependencies=[Depends(require_admin_or_guardia)],
)


# ── Visitas ──────────────────────────────────────────────────────────────────

@router.get("/visitas", response_model=list[VisitaResponse])
def list_visitas(unidad_id: int | None = None, db: Session = Depends(get_db)):
    query = db.query(Visita)
    if unidad_id:
        query = query.filter(Visita.unidad_id == unidad_id)
    return query.order_by(Visita.entrada.desc()).all()


@router.post("/visitas", response_model=VisitaResponse, status_code=201)
def create_visita(data: VisitaCreate, db: Session = Depends(get_db)):
    visita = Visita(**data.model_dump())
    db.add(visita)
    db.commit()
    db.refresh(visita)
    return visita


@router.post("/visitas/{visita_id}/salida", response_model=VisitaResponse)
def registrar_salida(visita_id: int, db: Session = Depends(get_db)):
    visita = db.query(Visita).get(visita_id)
    if not visita:
        raise HTTPException(404, "Visita no encontrada")
    visita.salida = datetime.now(timezone.utc)
    db.commit()
    db.refresh(visita)
    return visita


# ── Paquetería ───────────────────────────────────────────────────────────────

@router.get("/paquetes", response_model=list[PaqueteResponse])
def list_paquetes(unidad_id: int | None = None, db: Session = Depends(get_db)):
    query = db.query(Paquete)
    if unidad_id:
        query = query.filter(Paquete.unidad_id == unidad_id)
    return query.order_by(Paquete.fecha_recepcion.desc()).all()


@router.post("/paquetes", response_model=PaqueteResponse, status_code=201)
def create_paquete(data: PaqueteCreate, db: Session = Depends(get_db)):
    paquete = Paquete(**data.model_dump())
    db.add(paquete)
    db.commit()
    db.refresh(paquete)
    return paquete


@router.post("/paquetes/{paquete_id}/entregar", response_model=PaqueteResponse)
def entregar_paquete(paquete_id: int, db: Session = Depends(get_db)):
    paquete = db.query(Paquete).get(paquete_id)
    if not paquete:
        raise HTTPException(404, "Paquete no encontrado")
    paquete.entregado = True
    paquete.fecha_entrega = datetime.now(timezone.utc)
    db.commit()
    db.refresh(paquete)
    return paquete


# ── Accesos QR ───────────────────────────────────────────────────────────────

@router.get("/accesos-qr", response_model=list[AccesoQRResponse])
def list_accesos_qr(unidad_id: int | None = None, db: Session = Depends(get_db)):
    query = db.query(AccesoQR)
    if unidad_id:
        query = query.filter(AccesoQR.unidad_id == unidad_id)
    return query.order_by(AccesoQR.created_at.desc()).all()


@router.post("/accesos-qr", response_model=AccesoQRResponse, status_code=201)
def create_acceso_qr(data: AccesoQRCreate, db: Session = Depends(get_db)):
    acceso = AccesoQR(unidad_id=data.unidad_id, invitado=data.invitado, codigo=services.generar_codigo())
    db.add(acceso)
    db.commit()
    db.refresh(acceso)
    return acceso


@router.get("/accesos-qr/{acceso_id}/imagen")
def get_acceso_qr_imagen(acceso_id: int, db: Session = Depends(get_db)):
    acceso = db.query(AccesoQR).get(acceso_id)
    if not acceso:
        raise HTTPException(404, "Acceso no encontrado")
    return {"png_base64": services.generar_qr_png_base64(acceso.codigo)}


@router.post("/accesos-qr/validar/{codigo}", response_model=AccesoQRResponse)
def validar_acceso_qr(codigo: str, db: Session = Depends(get_db)):
    acceso = db.query(AccesoQR).filter(AccesoQR.codigo == codigo).first()
    if not acceso:
        raise HTTPException(404, "Código no encontrado")
    if acceso.usado:
        raise HTTPException(409, "Este código ya fue utilizado")
    acceso.usado = True
    acceso.fecha_uso = datetime.now(timezone.utc)
    db.commit()
    db.refresh(acceso)
    return acceso
