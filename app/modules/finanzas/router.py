from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_finance_read, require_finance_write
from app.modules.auth.models import User
from app.modules.condominios.models import Unidad
from app.modules.finanzas import services
from app.modules.finanzas.adapters import cfdi_provider, gateway
from app.modules.finanzas.models import Cargo, CuentaBancaria, CuotaConfig, EmisionLote, Factura, Fondo, MovimientoBancario, Pago, PagoAplicacion, PartidaPresupuestal
from app.modules.finanzas.schemas import (
    AbonoSaldoFavorCreate,
    AplicacionResponse,
    AplicarPagoRequest,
    CargoDetailResponse,
    CargoManualCreate,
    CargoResponse,
    ConciliarRequest,
    CuentaBancariaCreate,
    CuentaBancariaResponse,
    CuotaConfigResponse,
    CuotaConfigUpsert,
    EmisionCargosRequest,
    EmisionLoteResponse,
    EmisionResumenResponse,
    EstadoCuentaCompletoResponse,
    FacturaResponse,
    FondoCreate,
    FondoResponse,
    GenerarCargosRequest,
    MovimientoBancarioCreate,
    MovimientoBancarioResponse,
    PagoCreate,
    PagoCreateUnidad,
    PagoResponse,
    PartidaComparativo,
    PartidaPresupuestalCreate,
    PartidaPresupuestalResponse,
)

router = APIRouter(
    prefix="/finanzas",
    tags=["Finanzas"],
    dependencies=[Depends(require_finance_read)],
)


# ── Configuración de cuota / mora ────────────────────────────────────────────

@router.put("/cuota-config", response_model=CuotaConfigResponse)
def upsert_cuota_config(data: CuotaConfigUpsert, db: Session = Depends(get_db), _: User = Depends(require_finance_write)):
    config = db.query(CuotaConfig).filter(CuotaConfig.condominio_id == data.condominio_id).first()
    if config:
        for field, value in data.model_dump().items():
            setattr(config, field, value)
    else:
        config = CuotaConfig(**data.model_dump())
        db.add(config)
    db.commit()
    db.refresh(config)
    return config


@router.get("/cuota-config/{condominio_id}", response_model=CuotaConfigResponse)
def get_cuota_config(condominio_id: int, db: Session = Depends(get_db)):
    config = db.query(CuotaConfig).filter(CuotaConfig.condominio_id == condominio_id).first()
    if not config:
        raise HTTPException(404, "No hay configuración de cuota para este condominio")
    return config


# ── Cargos (recibos) ─────────────────────────────────────────────────────────

@router.post("/cargos/generar", response_model=list[CargoResponse])
def generar_cargos(data: GenerarCargosRequest, db: Session = Depends(get_db), _: User = Depends(require_finance_write)):
    return services.generar_cargos_periodo(db, data.condominio_id, data.periodo)


@router.get("/cargos", response_model=list[CargoResponse])
def list_cargos(condominio_id: int | None = None, estado: str | None = None, db: Session = Depends(get_db)):
    query = db.query(Cargo)
    if condominio_id:
        query = query.join(Unidad, Cargo.unidad_id == Unidad.id).filter(Unidad.condominio_id == condominio_id)
    if estado:
        query = query.filter(Cargo.estado == estado)
    return query.order_by(Cargo.fecha_vencimiento.desc()).all()


@router.get("/cargos/{cargo_id}", response_model=CargoDetailResponse)
def get_cargo(cargo_id: int, db: Session = Depends(get_db)):
    cargo = db.query(Cargo).get(cargo_id)
    if not cargo:
        raise HTTPException(404, "Cargo no encontrado")
    return cargo


@router.post("/cargos/{cargo_id}/pagos", response_model=PagoResponse, status_code=201)
def registrar_pago(
    cargo_id: int,
    data: PagoCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_finance_write),
):
    cargo = db.query(Cargo).get(cargo_id)
    if not cargo:
        raise HTTPException(404, "Cargo no encontrado")
    return services.registrar_pago(
        db, cargo, data.monto, data.metodo, data.referencia, data.fecha_pago, current_user.id
    )


@router.post("/condominios/{condominio_id}/aplicar-recargos", response_model=list[CargoResponse])
def aplicar_recargos(condominio_id: int, db: Session = Depends(get_db), _: User = Depends(require_finance_write)):
    return services.aplicar_recargos_vencidos(db, condominio_id)


@router.get("/unidades/{unidad_id}/estado-cuenta", response_model=EstadoCuentaCompletoResponse)
def estado_cuenta(
    unidad_id: int, fecha_desde: str | None = None, fecha_hasta: str | None = None,
    db: Session = Depends(get_db),
):
    from datetime import date as _date

    unidad = db.query(Unidad).get(unidad_id)
    if not unidad:
        raise HTTPException(404, "Unidad no encontrada")
    desde = _date.fromisoformat(fecha_desde) if fecha_desde else None
    hasta = _date.fromisoformat(fecha_hasta) if fecha_hasta else None
    detalle = services.estado_cuenta_completo(db, unidad, desde, hasta)
    propietario = unidad.propietario
    return {
        "unidad_id": unidad.id,
        "identificador": unidad.identificador,
        "contacto_nombre": propietario.full_name if propietario else None,
        "contacto_email": propietario.email if propietario else None,
        "saldo_favor_actual": unidad.saldo_favor,
        "movimientos": detalle["movimientos"],
        "totales": detalle["totales"],
    }


# ── Facturación CFDI (sin PAC conectado todavía) ────────────────────────────

@router.post("/cargos/{cargo_id}/factura", response_model=FacturaResponse, status_code=201)
def crear_factura(cargo_id: int, db: Session = Depends(get_db), _: User = Depends(require_finance_write)):
    cargo = db.query(Cargo).get(cargo_id)
    if not cargo:
        raise HTTPException(404, "Cargo no encontrado")
    if cargo.factura:
        raise HTTPException(409, "Este cargo ya tiene una factura registrada")

    factura = Factura(cargo_id=cargo_id, notas="Pendiente de timbrado: no hay PAC conectado.")
    db.add(factura)
    db.commit()
    db.refresh(factura)

    try:
        cfdi_provider.timbrar(factura)
    except NotImplementedError:
        pass  # queda en estado PENDIENTE hasta que se conecte un PAC real

    return factura


# ── Pagos en línea (sin pasarela conectada todavía) ─────────────────────────

@router.post("/cargos/{cargo_id}/pago-en-linea")
def pago_en_linea(cargo_id: int, db: Session = Depends(get_db), _: User = Depends(require_finance_write)):
    cargo = db.query(Cargo).get(cargo_id)
    if not cargo:
        raise HTTPException(404, "Cargo no encontrado")
    try:
        return gateway.crear_intento_pago(cargo, float(cargo.saldo))
    except NotImplementedError as e:
        raise HTTPException(501, str(e))


# ── Conciliación bancaria ────────────────────────────────────────────────────

@router.get("/conciliacion/movimientos", response_model=list[MovimientoBancarioResponse])
def list_movimientos(condominio_id: int, db: Session = Depends(get_db)):
    return (
        db.query(MovimientoBancario)
        .filter(MovimientoBancario.condominio_id == condominio_id)
        .order_by(MovimientoBancario.fecha.desc())
        .all()
    )


@router.post("/conciliacion/movimientos", response_model=MovimientoBancarioResponse, status_code=201)
def create_movimiento(data: MovimientoBancarioCreate, db: Session = Depends(get_db), _: User = Depends(require_finance_write)):
    movimiento = MovimientoBancario(**data.model_dump())
    db.add(movimiento)
    db.commit()
    db.refresh(movimiento)
    return movimiento


@router.post("/conciliacion/movimientos/{movimiento_id}/conciliar", response_model=MovimientoBancarioResponse)
def conciliar(movimiento_id: int, data: ConciliarRequest, db: Session = Depends(get_db), _: User = Depends(require_finance_write)):
    from app.modules.finanzas.models import Pago

    movimiento = db.query(MovimientoBancario).get(movimiento_id)
    if not movimiento:
        raise HTTPException(404, "Movimiento no encontrado")
    pago = db.query(Pago).get(data.pago_id)
    if not pago:
        raise HTTPException(404, "Pago no encontrado")
    return services.conciliar_movimiento(db, movimiento, pago)


# ── Cuentas bancarias y cajas chicas ─────────────────────────────────────────

@router.get("/cuentas-bancarias", response_model=list[CuentaBancariaResponse])
def list_cuentas_bancarias(condominio_id: int, db: Session = Depends(get_db)):
    return db.query(CuentaBancaria).filter(CuentaBancaria.condominio_id == condominio_id).all()


@router.post("/cuentas-bancarias", response_model=CuentaBancariaResponse, status_code=201)
def create_cuenta_bancaria(data: CuentaBancariaCreate, db: Session = Depends(get_db), _: User = Depends(require_finance_write)):
    cuenta = CuentaBancaria(**data.model_dump())
    db.add(cuenta)
    db.commit()
    db.refresh(cuenta)
    return cuenta


# ── Presupuesto ──────────────────────────────────────────────────────────────

@router.get("/presupuesto/partidas", response_model=list[PartidaPresupuestalResponse])
def list_partidas(condominio_id: int, anio: int, db: Session = Depends(get_db)):
    return (
        db.query(PartidaPresupuestal)
        .filter(PartidaPresupuestal.condominio_id == condominio_id, PartidaPresupuestal.anio == anio)
        .all()
    )


@router.post("/presupuesto/partidas", response_model=PartidaPresupuestalResponse, status_code=201)
def create_partida(data: PartidaPresupuestalCreate, db: Session = Depends(get_db), _: User = Depends(require_finance_write)):
    partida = PartidaPresupuestal(**data.model_dump())
    db.add(partida)
    db.commit()
    db.refresh(partida)
    return partida


@router.get("/presupuesto/comparativo", response_model=list[PartidaComparativo])
def presupuesto_comparativo(condominio_id: int, anio: int, db: Session = Depends(get_db)):
    return services.presupuesto_comparativo(db, condominio_id, anio)


# ── Adeudos iniciales y saldos a favor ──────────────────────────────────────

@router.post("/unidades/{unidad_id}/adeudo-inicial", response_model=CargoResponse, status_code=201)
def crear_adeudo_inicial(unidad_id: int, monto: float, descripcion: str = "Saldo inicial deudor", db: Session = Depends(get_db), _: User = Depends(require_finance_write)):
    return services.crear_adeudo_inicial(db, unidad_id, monto, descripcion)


@router.post("/unidades/{unidad_id}/saldo-favor", response_model=PagoResponse, status_code=201)
def crear_saldo_favor(unidad_id: int, data: AbonoSaldoFavorCreate, db: Session = Depends(get_db), _: User = Depends(require_finance_write)):
    unidad = db.query(Unidad).get(unidad_id)
    if not unidad:
        raise HTTPException(404, "Unidad no encontrada")
    return services.registrar_abono_saldo_favor(db, unidad, data.monto, data.motivo)


@router.post("/cargos/manual", response_model=CargoResponse, status_code=201)
def crear_cargo_manual(data: CargoManualCreate, db: Session = Depends(get_db), current_user: User = Depends(require_finance_write)):
    return services.crear_cargo_manual(
        db, data.unidad_id, data.tipo, data.concepto, data.monto_base, data.periodo,
        data.fecha_vencimiento, data.cobrar_de_inmediato, data.metodo_pago, current_user.id,
    )


# ── Fondos contables ─────────────────────────────────────────────────────────

@router.get("/fondos", response_model=list[FondoResponse])
def list_fondos(condominio_id: int, db: Session = Depends(get_db)):
    return db.query(Fondo).filter(Fondo.condominio_id == condominio_id).order_by(Fondo.nombre).all()


@router.post("/fondos", response_model=FondoResponse, status_code=201)
def create_fondo(data: FondoCreate, db: Session = Depends(get_db), _: User = Depends(require_finance_write)):
    fondo = Fondo(**data.model_dump())
    db.add(fondo)
    db.commit()
    db.refresh(fondo)
    return fondo


# ── Emisión de cargos (individual y masiva) ─────────────────────────────────

@router.post("/condominios/{condominio_id}/emisiones", response_model=EmisionResumenResponse, status_code=201)
def emitir_cargos(
    condominio_id: int, data: EmisionCargosRequest,
    db: Session = Depends(get_db), current_user: User = Depends(require_finance_write),
):
    try:
        lote = services.emitir_cargos(db, condominio_id, data, current_user.id)
    except services.EmisionError as e:
        raise HTTPException(400, str(e))
    cargos = db.query(Cargo).filter(Cargo.lote_id == lote.id).all()
    return {"lote": lote, "cargos": cargos}


@router.get("/emisiones", response_model=list[EmisionLoteResponse])
def list_emisiones(condominio_id: int, db: Session = Depends(get_db)):
    return (
        db.query(EmisionLote).filter(EmisionLote.condominio_id == condominio_id)
        .order_by(EmisionLote.created_at.desc()).all()
    )


@router.get("/emisiones/{lote_id}", response_model=EmisionResumenResponse)
def get_emision(lote_id: int, db: Session = Depends(get_db)):
    lote = db.query(EmisionLote).get(lote_id)
    if not lote:
        raise HTTPException(404, "Emisión no encontrada")
    cargos = db.query(Cargo).filter(Cargo.lote_id == lote_id).order_by(Cargo.periodo.desc()).all()
    return {"lote": lote, "cargos": cargos}


@router.post("/emisiones/{lote_id}/pausar", response_model=EmisionLoteResponse)
def pausar_emision(lote_id: int, db: Session = Depends(get_db), _: User = Depends(require_finance_write)):
    lote = db.query(EmisionLote).get(lote_id)
    if not lote:
        raise HTTPException(404, "Emisión no encontrada")
    lote.activo = False
    db.commit()
    db.refresh(lote)
    return lote


@router.post("/emisiones/{lote_id}/reanudar", response_model=EmisionLoteResponse)
def reanudar_emision(lote_id: int, db: Session = Depends(get_db), _: User = Depends(require_finance_write)):
    lote = db.query(EmisionLote).get(lote_id)
    if not lote:
        raise HTTPException(404, "Emisión no encontrada")
    lote.activo = True
    db.commit()
    db.refresh(lote)
    return lote


@router.post("/emisiones/procesar-recurrentes", response_model=list[EmisionLoteResponse])
def procesar_recurrentes(db: Session = Depends(get_db), _: User = Depends(require_finance_write)):
    """Disparo manual del worker de recurrencias (el mismo que corre automáticamente
    una vez al día, ver app/core/scheduler.py). Útil para forzar la generación hoy."""
    return services.procesar_recurrencias_pendientes(db)


# ── Pagos (abonos desacoplados de los cargos) ───────────────────────────────

@router.post("/condominios/{condominio_id}/pagos", response_model=PagoResponse, status_code=201)
def registrar_pago_unidad(
    condominio_id: int, data: PagoCreateUnidad,
    db: Session = Depends(get_db), current_user: User = Depends(require_finance_write),
):
    unidad = db.query(Unidad).filter(Unidad.id == data.unidad_id, Unidad.condominio_id == condominio_id).first()
    if not unidad:
        raise HTTPException(404, "Unidad no encontrada en este condominio")
    return services.registrar_pago_unidad(
        db, unidad, data.monto, data.metodo, data.referencia, data.fecha_pago,
        data.cuenta_bancaria_id, data.fondo_id, current_user.id, data.auto_aplicar,
    )


@router.get("/pagos/{pago_id}", response_model=PagoResponse)
def get_pago(pago_id: int, db: Session = Depends(get_db)):
    pago = db.query(Pago).get(pago_id)
    if not pago:
        raise HTTPException(404, "Pago no encontrado")
    return pago


@router.get("/pagos/{pago_id}/aplicaciones", response_model=list[AplicacionResponse])
def list_aplicaciones_pago(pago_id: int, db: Session = Depends(get_db)):
    return db.query(PagoAplicacion).filter(PagoAplicacion.pago_id == pago_id).all()


@router.post("/pagos/{pago_id}/aplicar", response_model=AplicacionResponse, status_code=201)
def aplicar_pago(pago_id: int, data: AplicarPagoRequest, db: Session = Depends(get_db), _: User = Depends(require_finance_write)):
    pago = db.query(Pago).get(pago_id)
    if not pago:
        raise HTTPException(404, "Pago no encontrado")
    cargo = db.query(Cargo).get(data.cargo_id)
    if not cargo:
        raise HTTPException(404, "Cargo no encontrado")
    try:
        return services.aplicar_pago_manual(db, pago, cargo, data.monto)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/pagos/{pago_id}/revertir", response_model=PagoResponse)
def revertir_pago(pago_id: int, db: Session = Depends(get_db), _: User = Depends(require_finance_write)):
    pago = db.query(Pago).get(pago_id)
    if not pago:
        raise HTTPException(404, "Pago no encontrado")
    return services.revertir_pago(db, pago)
