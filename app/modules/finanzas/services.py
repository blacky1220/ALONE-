import calendar
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.modules.condominios.models import Unidad
from app.modules.finanzas.models import (
    Cargo,
    CuentaPorPagar,
    CuotaConfig,
    DescuentoAplicado,
    Egreso,
    EmisionLote,
    EstadoCargo,
    EstadoCuentaPorPagar,
    EstadoImportacion,
    EstadoPago,
    EstadoPagoProveedor,
    ImportacionBancaria,
    MetodoPago,
    MovimientoBancario,
    MovimientoImportado,
    Pago,
    PagoAplicacion,
    PagoProveedor,
    PartidaPresupuestal,
    TipoCalculoCuota,
    TipoCargo,
    TipoMovimiento,
    TipoPartida,
    TipoRecargo,
    TipoRecurrencia,
    TipoSeleccionUnidades,
)
from app.modules.finanzas import statement_parser


def _monto_base_unidad(unidad: Unidad, config: CuotaConfig | None) -> Decimal:
    if config and config.tipo_calculo == TipoCalculoCuota.INDIVISO and config.monto_total_prorrateo and unidad.indiviso_pct:
        return (config.monto_total_prorrateo * unidad.indiviso_pct / Decimal("100")).quantize(Decimal("0.01"))
    return unidad.cuota_mantenimiento or Decimal("0")


# ── Motor de aplicación de pagos (Cargos ↔ Abonos desacoplados) ─────────────
#
# Un Pago nunca pertenece a un solo Cargo: su monto se reparte entre cero o más
# cargos vía PagoAplicacion (auditable, permite aplicaciones parciales). Lo que
# no se aplica es, por definición, saldo a favor de la unidad — no existe un
# estado "guardado" de saldo a favor aparte: `Unidad.saldo_favor` es solo una
# caché sincronizada por `_sync_saldo_favor` para lecturas rápidas en UI.

def _aplicar_pago_a_cargo(db: Session, pago: Pago, cargo: Cargo, monto_maximo: Decimal) -> Decimal:
    """Aplica hasta `monto_maximo` del pago contra el cargo. Devuelve el monto realmente
    aplicado (puede ser menor si el cargo ya tenía poco saldo pendiente)."""
    _aplicar_descuento_pronto_pago(db, cargo, pago.fecha_pago or date.today())

    monto_a_aplicar = min(monto_maximo, cargo.saldo)
    if monto_a_aplicar <= 0:
        return Decimal("0")

    aplicacion = PagoAplicacion(pago_id=pago.id, cargo_id=cargo.id, monto_aplicado=monto_a_aplicar)
    cargo.aplicaciones.append(aplicacion)
    pago.aplicaciones.append(aplicacion)
    db.flush()

    if cargo.saldo <= 0:
        cargo.estado = EstadoCargo.PAGADO
    elif cargo.monto_pagado > 0:
        cargo.estado = EstadoCargo.PARCIAL

    return monto_a_aplicar


def _sync_saldo_favor(db: Session, unidad: Unidad) -> None:
    """Recalcula la caché Unidad.saldo_favor = Total Abonos - Total Aplicado a Cargos,
    excluyendo pagos cancelados. Es la fórmula de la especificación, cacheada para UI."""
    db.flush()  # la sesión usa autoflush=False: sin esto, un cambio de estado reciente
    # (p.ej. revertir_pago marcando CANCELADO) no se reflejaría todavía en esta consulta.
    pagos = db.query(Pago).filter(Pago.unidad_id == unidad.id, Pago.estado != EstadoPago.CANCELADO).all()
    total_abonos = sum((p.monto for p in pagos), start=Decimal("0"))
    total_aplicado = sum((p.monto_aplicado for p in pagos), start=Decimal("0"))
    unidad.saldo_favor = total_abonos - total_aplicado
    db.flush()


def registrar_pago_unidad(
    db: Session, unidad: Unidad, monto: Decimal, metodo, referencia: str | None, fecha_pago: date | None,
    cuenta_bancaria_id: int | None = None, fondo_id: int | None = None, user_id: int | None = None,
    auto_aplicar: bool = True, comprobante_path: str | None = None, procesador: str = "manual",
) -> Pago:
    """Registra un ingreso de la unidad. Si auto_aplicar, lo reparte FIFO (más antiguo
    primero) contra los cargos pendientes/vencidos; lo que sobra queda como saldo a
    favor. Si no hay ningún cargo pendiente, el pago completo queda NO_APLICADO."""
    pago = Pago(
        unidad_id=unidad.id, monto=monto, metodo=metodo, referencia=referencia,
        fecha_pago=fecha_pago or date.today(), cuenta_bancaria_id=cuenta_bancaria_id,
        fondo_id=fondo_id, registrado_por_id=user_id, comprobante_path=comprobante_path,
        procesador=procesador, estado=EstadoPago.NO_APLICADO,
    )
    db.add(pago)
    db.flush()

    if auto_aplicar:
        _aplicar_fifo(db, pago, unidad)

    _actualizar_estado_pago(pago)
    _sync_saldo_favor(db, unidad)
    db.commit()
    db.refresh(pago)
    return pago


def _aplicar_fifo(db: Session, pago: Pago, unidad: Unidad) -> None:
    """Reparte el monto disponible del pago contra los cargos pendientes de la unidad,
    del más antiguo (fecha_vencimiento) al más reciente, hasta agotar el pago o los adeudos."""
    pendientes = (
        db.query(Cargo)
        .filter(Cargo.unidad_id == unidad.id, Cargo.estado.in_([EstadoCargo.PENDIENTE, EstadoCargo.PARCIAL, EstadoCargo.VENCIDO]))
        .order_by(Cargo.fecha_vencimiento)
        .all()
    )
    for cargo in pendientes:
        if pago.monto_disponible <= 0:
            break
        _aplicar_pago_a_cargo(db, pago, cargo, pago.monto_disponible)


def _actualizar_estado_pago(pago: Pago) -> None:
    if pago.estado == EstadoPago.CANCELADO:
        return
    if pago.monto_aplicado <= 0:
        pago.estado = EstadoPago.NO_APLICADO
    elif pago.monto_aplicado < pago.monto:
        pago.estado = EstadoPago.PARCIAL
    else:
        pago.estado = EstadoPago.APLICADO


def aplicar_pago_manual(db: Session, pago: Pago, cargo: Cargo, monto: Decimal) -> PagoAplicacion:
    """Aplica manualmente parte (o todo) del saldo disponible de un pago contra un
    cargo específico — para cuando el saldo a favor se generó antes de que existiera
    el adeudo, o el FIFO automático no era lo que se quería."""
    if monto <= 0:
        raise ValueError("El monto a aplicar debe ser mayor a cero.")
    if monto > pago.monto_disponible:
        raise ValueError(f"El pago solo tiene ${pago.monto_disponible} disponibles para aplicar.")
    if monto > cargo.saldo:
        raise ValueError(f"El cargo solo tiene ${cargo.saldo} pendientes.")

    aplicado = _aplicar_pago_a_cargo(db, pago, cargo, monto)
    _actualizar_estado_pago(pago)
    _sync_saldo_favor(db, pago.unidad)
    db.commit()
    aplicacion = (
        db.query(PagoAplicacion)
        .filter(PagoAplicacion.pago_id == pago.id, PagoAplicacion.cargo_id == cargo.id)
        .order_by(PagoAplicacion.id.desc()).first()
    )
    return aplicacion


def revertir_pago(db: Session, pago: Pago) -> Pago:
    """Deshace un recibo: elimina todas sus aplicaciones (los cargos afectados vuelven
    al estado que les corresponda según lo que sigan teniendo aplicado de otros pagos)
    y marca el pago como CANCELADO. Transaccional: si algo falla no queda a medias."""
    try:
        cargos_afectados = {a.cargo for a in pago.aplicaciones}
        for aplicacion in list(pago.aplicaciones):
            db.delete(aplicacion)
        db.flush()

        for cargo in cargos_afectados:
            db.refresh(cargo)
            if cargo.saldo <= 0:
                cargo.estado = EstadoCargo.PAGADO
            elif cargo.monto_pagado > 0:
                cargo.estado = EstadoCargo.PARCIAL
            else:
                cargo.estado = EstadoCargo.VENCIDO if cargo.fecha_vencimiento < date.today() else EstadoCargo.PENDIENTE

        pago.estado = EstadoPago.CANCELADO
        _sync_saldo_favor(db, pago.unidad)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(pago)
    return pago


def generar_cargos_periodo(db: Session, condominio_id: int, periodo: str) -> list[Cargo]:
    """Emisión masiva: crea un cargo por cada unidad del condominio para el periodo dado
    (fijo o prorrateado por indiviso, según CuotaConfig), salvo que ya exista uno.
    Si la unidad tiene saldo a favor disponible (pagos no aplicados), lo usa de inmediato."""
    year, month = (int(p) for p in periodo.split("-"))
    config = db.query(CuotaConfig).filter(CuotaConfig.condominio_id == condominio_id).first()
    dia_limite = config.dia_limite_pago if config else 10
    ultimo_dia_mes = calendar.monthrange(year, month)[1]
    fecha_vencimiento = date(year, month, min(dia_limite, ultimo_dia_mes))

    unidades = db.query(Unidad).filter(Unidad.condominio_id == condominio_id).all()
    creados = []
    for unidad in unidades:
        existe = (
            db.query(Cargo)
            .filter(Cargo.unidad_id == unidad.id, Cargo.periodo == periodo, Cargo.tipo == TipoCargo.CUOTA)
            .first()
        )
        if existe:
            continue
        cargo = Cargo(
            unidad_id=unidad.id,
            tipo=TipoCargo.CUOTA,
            periodo=periodo,
            monto_base=_monto_base_unidad(unidad, config),
            fecha_vencimiento=fecha_vencimiento,
            estado=EstadoCargo.PENDIENTE,
        )
        db.add(cargo)
        db.flush()
        _aplicar_creditos_disponibles(db, cargo, unidad)
        creados.append(cargo)
    db.commit()
    for c in creados:
        db.refresh(c)
    return creados


def _aplicar_creditos_disponibles(db: Session, cargo: Cargo, unidad: Unidad) -> None:
    """Al emitir un cargo nuevo, usa cualquier pago con saldo no aplicado de la unidad
    (del más antiguo al más reciente) para amortizarlo de inmediato."""
    creditos = (
        db.query(Pago)
        .filter(Pago.unidad_id == unidad.id, Pago.estado.in_([EstadoPago.NO_APLICADO, EstadoPago.PARCIAL]))
        .order_by(Pago.fecha_pago)
        .all()
    )
    for pago in creditos:
        if cargo.saldo <= 0:
            break
        if pago.monto_disponible <= 0:
            continue
        _aplicar_pago_a_cargo(db, pago, cargo, pago.monto_disponible)
        _actualizar_estado_pago(pago)
    if creditos:
        _sync_saldo_favor(db, unidad)


def registrar_abono_saldo_favor(db: Session, unidad: Unidad, monto: Decimal, motivo: str | None) -> Pago:
    """Registra un pago anticipado: se aplica FIFO contra cualquier adeudo pendiente
    existente y el resto queda disponible como saldo a favor para cuotas futuras."""
    return registrar_pago_unidad(db, unidad, monto, MetodoPago.OTRO, motivo or "Saldo a favor", date.today())


def crear_adeudo_inicial(db: Session, unidad_id: int, monto: Decimal, descripcion: str) -> Cargo:
    """Saldo inicial deudor: cartera vencida previa a la migración al sistema."""
    cargo = Cargo(
        unidad_id=unidad_id,
        tipo=TipoCargo.SALDO_INICIAL,
        periodo="INICIAL",
        concepto=descripcion or "Saldo inicial deudor",
        monto_base=monto,
        fecha_vencimiento=date.today(),
        estado=EstadoCargo.PENDIENTE,
    )
    db.add(cargo)
    db.commit()
    db.refresh(cargo)
    return cargo


def crear_cargo_manual(
    db: Session, unidad_id: int, tipo: TipoCargo, concepto: str, monto_base: Decimal,
    periodo: str | None, fecha_vencimiento: date | None,
    cobrar_de_inmediato: bool, metodo_pago, user_id: int | None,
) -> Cargo:
    """Ingresos capturados manualmente: extraordinarias, multas, amenidades, tags vehiculares..."""
    cargo = Cargo(
        unidad_id=unidad_id,
        tipo=tipo,
        periodo=periodo or date.today().strftime("%Y-%m"),
        concepto=concepto,
        monto_base=monto_base,
        fecha_vencimiento=fecha_vencimiento or date.today(),
        estado=EstadoCargo.PENDIENTE,
    )
    db.add(cargo)
    db.commit()
    db.refresh(cargo)
    if cobrar_de_inmediato:
        registrar_pago(db, cargo, monto_base, metodo_pago, "Cobro inmediato", date.today(), user_id)
    return cargo


def registrar_pago(db: Session, cargo: Cargo, monto: Decimal, metodo, referencia, fecha_pago, user_id=None) -> Pago:
    """Paga directo un cargo específico (atajo usado desde la ficha del cargo): crea el
    Pago y lo aplica íntegro a ese cargo (o hasta donde alcance su saldo; el resto, si
    sobra, queda disponible como saldo a favor de la unidad)."""
    unidad = cargo.unidad or db.query(Unidad).get(cargo.unidad_id)
    pago = Pago(
        unidad_id=unidad.id, monto=monto, metodo=metodo, referencia=referencia,
        fecha_pago=fecha_pago or date.today(), registrado_por_id=user_id, estado=EstadoPago.NO_APLICADO,
    )
    db.add(pago)
    db.flush()

    _aplicar_pago_a_cargo(db, pago, cargo, monto)
    _actualizar_estado_pago(pago)
    _sync_saldo_favor(db, unidad)

    db.commit()
    db.refresh(pago)
    db.refresh(cargo)
    return pago


def _aplicar_descuento_pronto_pago(db: Session, cargo: Cargo, fecha_pago: date) -> None:
    if cargo.descuento:
        return

    # Regla propia del cargo (definida al emitirlo desde el módulo de emisión): N días
    # ANTES de la fecha de vencimiento.
    if cargo.descuento_tipo and cargo.descuento_valor and cargo.descuento_dias_antes:
        dias_antes_vencimiento = (cargo.fecha_vencimiento - fecha_pago).days
        if dias_antes_vencimiento >= cargo.descuento_dias_antes:
            if cargo.descuento_tipo == TipoRecargo.PORCENTAJE:
                cargo.descuento = (cargo.monto_base * cargo.descuento_valor / Decimal("100")).quantize(Decimal("0.01"))
            else:
                cargo.descuento = cargo.descuento_valor
        return

    # Regla global del condominio para cuotas ordinarias: N días desde la EMISIÓN.
    if cargo.tipo != TipoCargo.CUOTA or not cargo.fecha_emision:
        return
    config = db.query(CuotaConfig).join(Unidad, Unidad.condominio_id == CuotaConfig.condominio_id).filter(Unidad.id == cargo.unidad_id).first()
    if not config or not config.descuento_pronto_pago_dias or not config.descuento_pronto_pago_pct:
        return
    dias_transcurridos = (fecha_pago - cargo.fecha_emision).days
    if dias_transcurridos <= config.descuento_pronto_pago_dias:
        cargo.descuento = (cargo.monto_base * config.descuento_pronto_pago_pct / Decimal("100")).quantize(Decimal("0.01"))


def aplicar_recargos_vencidos(db: Session, condominio_id: int) -> list[Cargo]:
    """Recalcula el recargo por mora de los cargos vencidos y no pagados de un condominio."""
    config = db.query(CuotaConfig).filter(CuotaConfig.condominio_id == condominio_id).first()
    if not config:
        return []

    hoy = date.today()
    cargos = (
        db.query(Cargo)
        .join(Unidad, Cargo.unidad_id == Unidad.id)
        .filter(
            Unidad.condominio_id == condominio_id,
            Cargo.estado.in_([EstadoCargo.PENDIENTE, EstadoCargo.PARCIAL]),
            Cargo.fecha_vencimiento < hoy,
        )
        .all()
    )

    actualizados = []
    for cargo in cargos:
        dias_vencido = (hoy - cargo.fecha_vencimiento).days
        if dias_vencido <= (config.dias_gracia or 0):
            continue
        if config.recargo_tipo == TipoRecargo.PORCENTAJE:
            cargo.recargo = (cargo.monto_base * config.recargo_valor / Decimal("100")).quantize(Decimal("0.01"))
        else:
            cargo.recargo = config.recargo_valor
        cargo.estado = EstadoCargo.VENCIDO
        actualizados.append(cargo)

    db.commit()
    for c in actualizados:
        db.refresh(c)
    return actualizados


def estado_cuenta_unidad(db: Session, unidad_id: int) -> list[Cargo]:
    return (
        db.query(Cargo)
        .filter(Cargo.unidad_id == unidad_id)
        .order_by(Cargo.periodo.desc())
        .all()
    )


def estado_cuenta_completo(db: Session, unidad: Unidad, fecha_desde: date | None = None, fecha_hasta: date | None = None) -> dict:
    """Libro mayor de la unidad: mezcla Cargos (Debe) y Pagos (Haber) en una sola línea
    de tiempo, con los totales que pide la vista de estado de cuenta."""
    cargos_q = db.query(Cargo).filter(Cargo.unidad_id == unidad.id)
    pagos_q = db.query(Pago).filter(Pago.unidad_id == unidad.id, Pago.estado != EstadoPago.CANCELADO)
    if fecha_desde:
        cargos_q = cargos_q.filter(Cargo.fecha_emision >= fecha_desde)
        pagos_q = pagos_q.filter(Pago.fecha_pago >= fecha_desde)
    if fecha_hasta:
        cargos_q = cargos_q.filter(Cargo.fecha_emision <= fecha_hasta)
        pagos_q = pagos_q.filter(Pago.fecha_pago <= fecha_hasta)

    cargos = cargos_q.all()
    pagos = pagos_q.all()

    movimientos = []
    for c in cargos:
        movimientos.append({
            "fecha": c.fecha_emision, "tipo": "CARGO", "folio": f"CGO-{c.id}",
            "concepto": c.concepto, "debe": c.monto_total, "haber": Decimal("0"),
            "estatus": c.estado.value, "cargo_id": c.id, "pago_id": None,
        })
    for p in pagos:
        estatus = {"NO_APLICADO": "No aplicado", "PARCIAL": "Parcial", "APLICADO": "Aplicado"}.get(p.estado.value, p.estado.value)
        movimientos.append({
            "fecha": p.fecha_pago, "tipo": "PAGO", "folio": f"PAG-{p.id}",
            "concepto": f"Pago {p.metodo.value.lower()}" + (f" — {p.referencia}" if p.referencia else ""),
            "debe": Decimal("0"), "haber": p.monto,
            "estatus": estatus, "cargo_id": None, "pago_id": p.id,
        })
    movimientos.sort(key=lambda m: (m["fecha"], m["tipo"]))

    total_cuotas = sum((c.monto_base for c in cargos if c.tipo == TipoCargo.CUOTA), start=Decimal("0"))
    total_penalidades = sum((c.recargo for c in cargos), start=Decimal("0"))
    total_pagos = sum((p.monto for p in pagos), start=Decimal("0"))
    total_descuentos = sum((c.descuento for c in cargos), start=Decimal("0"))
    total_adeudado = sum((c.monto_total for c in cargos), start=Decimal("0"))
    balance_total = total_adeudado - total_pagos
    saldo_favor_remanente = sum((p.monto_disponible for p in pagos), start=Decimal("0"))

    return {
        "movimientos": movimientos,
        "totales": {
            "total_cuotas": total_cuotas,
            "total_penalidades": total_penalidades,
            "total_pagos": total_pagos,
            "total_descuentos": total_descuentos,
            "balance_total": balance_total,
            "saldo_favor_remanente": saldo_favor_remanente,
        },
    }


def exportar_estado_cuenta_excel(unidad: Unidad, detalle: dict):
    """Genera un .xlsx del estado de cuenta (libro mayor + totales) y devuelve su ruta."""
    import openpyxl
    from pathlib import Path as _Path

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Estado de cuenta"
    ws.append([f"Estado de cuenta — {unidad.identificador}"])
    ws.append([])
    ws.append(["Fecha", "Folio", "Concepto", "Cargo (Debe)", "Abono (Haber)", "Estatus"])
    for m in detalle["movimientos"]:
        ws.append([m["fecha"].isoformat(), m["folio"], m["concepto"], float(m["debe"]), float(m["haber"]), m["estatus"]])
    ws.append([])
    t = detalle["totales"]
    ws.append(["Total cuotas", float(t["total_cuotas"])])
    ws.append(["Total penalidades/intereses", float(t["total_penalidades"])])
    ws.append(["Total pagos recibidos", float(t["total_pagos"])])
    ws.append(["Total descuentos por pronto pago", float(t["total_descuentos"])])
    ws.append(["Balance total", float(t["balance_total"])])
    ws.append(["Saldo a favor remanente", float(t["saldo_favor_remanente"])])

    out_dir = _Path(__file__).resolve().parent / "data" / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"estado_cuenta_{unidad.id}.xlsx"
    wb.save(path)
    return path


def conciliar_movimiento(db: Session, movimiento: MovimientoBancario, pago: Pago) -> MovimientoBancario:
    movimiento.pago_id = pago.id
    movimiento.conciliado = True
    db.commit()
    db.refresh(movimiento)
    return movimiento


def presupuesto_comparativo(db: Session, condominio_id: int, anio: int) -> list[dict]:
    """Compara el presupuesto proyectado contra lo realmente devengado (ingresos cobrados / egresos pagados)."""
    partidas = (
        db.query(PartidaPresupuestal)
        .filter(PartidaPresupuestal.condominio_id == condominio_id, PartidaPresupuestal.anio == anio)
        .order_by(PartidaPresupuestal.tipo, PartidaPresupuestal.nombre)
        .all()
    )
    hoy = date.today()
    resultado = []
    for partida in partidas:
        if partida.tipo == TipoPartida.EGRESO:
            egresos_anio = (
                db.query(Egreso)
                .filter(Egreso.partida_id == partida.id, Egreso.fecha >= date(anio, 1, 1), Egreso.fecha <= date(anio, 12, 31))
                .all()
            )
            real_acumulado = sum((e.monto for e in egresos_anio), start=Decimal("0"))
            real_mes = sum((e.monto for e in egresos_anio if e.fecha.month == hoy.month and hoy.year == anio), start=Decimal("0"))
        else:
            pagos_anio = (
                db.query(Pago)
                .join(Unidad, Pago.unidad_id == Unidad.id)
                .filter(
                    Unidad.condominio_id == condominio_id, Pago.estado != EstadoPago.CANCELADO,
                    Pago.fecha_pago >= date(anio, 1, 1), Pago.fecha_pago <= date(anio, 12, 31),
                )
                .all()
            )
            real_acumulado = sum((p.monto for p in pagos_anio), start=Decimal("0"))
            real_mes = sum((p.monto for p in pagos_anio if p.fecha_pago.month == hoy.month and hoy.year == anio), start=Decimal("0"))

        resultado.append({
            "partida_id": partida.id,
            "nombre": partida.nombre,
            "tipo": partida.tipo,
            "proyectado_anual": partida.monto_proyectado_anual,
            "proyectado_mensual": (partida.monto_proyectado_anual / Decimal("12")).quantize(Decimal("0.01")),
            "real_mes_actual": real_mes,
            "real_acumulado_anio": real_acumulado,
        })
    return resultado


# ── Emisión de cargos (individual y masiva) ─────────────────────────────────

class EmisionError(ValueError):
    pass


def _resolver_unidades_destino(
    db: Session, condominio_id: int, tipo_seleccion: TipoSeleccionUnidades,
    unidad_ids: list[int] | None, grupo: str | None,
) -> list[Unidad]:
    query = db.query(Unidad).filter(Unidad.condominio_id == condominio_id)
    if tipo_seleccion == TipoSeleccionUnidades.MANUAL:
        if not unidad_ids:
            return []
        query = query.filter(Unidad.id.in_(unidad_ids))
    elif tipo_seleccion == TipoSeleccionUnidades.GRUPO:
        if not grupo:
            return []
        query = query.filter(Unidad.grupo == grupo)
    return query.all()


def _crear_cargo_desde_lote(db: Session, lote: EmisionLote, unidad: Unidad, periodo: str, fecha_emision: date, fecha_vencimiento: date) -> Cargo:
    cargo = Cargo(
        unidad_id=unidad.id, lote_id=lote.id, partida_id=lote.partida_id, fondo_id=lote.fondo_id,
        tipo=lote.tipo_cargo, periodo=periodo, concepto=lote.concepto, descripcion=lote.descripcion,
        moneda=lote.moneda, monto_base=lote.monto,
        descuento_tipo=lote.descuento_tipo if lote.descuento_activo else None,
        descuento_valor=lote.descuento_valor if lote.descuento_activo else None,
        descuento_dias_antes=lote.descuento_dias_antes if lote.descuento_activo else None,
        fecha_emision=fecha_emision, fecha_vencimiento=fecha_vencimiento,
        estado=EstadoCargo.PENDIENTE,
    )
    db.add(cargo)
    db.flush()
    _aplicar_creditos_disponibles(db, cargo, unidad)
    return cargo


def emitir_cargos(db: Session, condominio_id: int, data, user_id: int | None = None) -> EmisionLote:
    """Motor único de emisión de cargos, individual o masiva. Crea el lote y un Cargo
    atómico por cada unidad destino dentro de una sola transacción; si algo falla no
    se persiste nada. Aplica saldo a favor de inmediato cuando la unidad ya tiene."""
    if data.fecha_vencimiento < data.fecha_emision:
        raise EmisionError("La fecha de vencimiento no puede ser anterior a la fecha de emisión.")
    if data.monto <= 0:
        raise EmisionError("El monto debe ser mayor a cero.")
    if data.descuento_activo and (not data.descuento_valor or data.descuento_valor <= 0 or not data.descuento_dias_antes or data.descuento_dias_antes <= 0):
        raise EmisionError("La regla de descuento por pronto pago requiere un valor y días válidos.")
    if data.recurrencia != TipoRecurrencia.NINGUNA and not data.dia_generacion:
        raise EmisionError("Un cargo recurrente necesita el día de generación automática.")

    unidades = _resolver_unidades_destino(db, condominio_id, data.tipo_seleccion, data.unidad_ids, data.grupo)
    if not unidades:
        raise EmisionError("No se encontraron unidades para la selección indicada.")

    periodo = data.fecha_emision.strftime("%Y-%m")

    try:
        lote = EmisionLote(
            condominio_id=condominio_id, tipo_seleccion=data.tipo_seleccion, grupo=data.grupo,
            tipo_cargo=data.tipo_cargo, concepto=data.concepto, descripcion=data.descripcion,
            moneda=data.moneda, monto=data.monto, partida_id=data.partida_id, fondo_id=data.fondo_id,
            fecha_emision=data.fecha_emision, fecha_vencimiento=data.fecha_vencimiento,
            recurrencia=data.recurrencia, dia_generacion=data.dia_generacion,
            descuento_activo=data.descuento_activo,
            descuento_tipo=data.descuento_tipo if data.descuento_activo else None,
            descuento_valor=data.descuento_valor if data.descuento_activo else None,
            descuento_dias_antes=data.descuento_dias_antes if data.descuento_activo else None,
            ultimo_periodo_generado=periodo, creado_por_id=user_id,
        )
        db.add(lote)
        db.flush()

        for unidad in unidades:
            _crear_cargo_desde_lote(db, lote, unidad, periodo, data.fecha_emision, data.fecha_vencimiento)

        lote.total_unidades = len(unidades)
        lote.total_facturado = Decimal(len(unidades)) * data.monto
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(lote)
    return lote


def _corresponde_generar(lote: EmisionLote, hoy: date) -> bool:
    meses_desde_inicio = (hoy.year - lote.fecha_emision.year) * 12 + (hoy.month - lote.fecha_emision.month)
    if lote.recurrencia == TipoRecurrencia.MENSUAL:
        return True
    if lote.recurrencia == TipoRecurrencia.BIMESTRAL:
        return meses_desde_inicio % 2 == 0
    if lote.recurrencia == TipoRecurrencia.ANUAL:
        return hoy.month == lote.fecha_emision.month
    return False


def procesar_recurrencias_pendientes(db: Session) -> list[EmisionLote]:
    """Worker en segundo plano: revisa las plantillas de emisión recurrentes activas y
    genera los cargos del nuevo periodo cuando corresponde. Pensado para correr una vez
    al día (ver app/core/scheduler.py); también puede dispararse manualmente."""
    hoy = date.today()
    periodo_actual = hoy.strftime("%Y-%m")

    candidatos = (
        db.query(EmisionLote)
        .filter(
            EmisionLote.activo.is_(True),
            EmisionLote.recurrencia != TipoRecurrencia.NINGUNA,
            EmisionLote.dia_generacion.isnot(None),
            EmisionLote.dia_generacion <= hoy.day,
            EmisionLote.ultimo_periodo_generado != periodo_actual,
        )
        .all()
    )

    procesados = []
    for lote in candidatos:
        if not _corresponde_generar(lote, hoy):
            continue

        if lote.tipo_seleccion == TipoSeleccionUnidades.MANUAL:
            unidad_ids_originales = {
                c.unidad_id for c in db.query(Cargo.unidad_id).filter(Cargo.lote_id == lote.id).all()
            }
            unidades = db.query(Unidad).filter(Unidad.id.in_(unidad_ids_originales)).all()
        else:
            unidades = _resolver_unidades_destino(db, lote.condominio_id, lote.tipo_seleccion, None, lote.grupo)
        if not unidades:
            continue

        dias_vigencia = max((lote.fecha_vencimiento - lote.fecha_emision).days, 0)
        ultimo_dia_mes = calendar.monthrange(hoy.year, hoy.month)[1]
        nueva_fecha_emision = date(hoy.year, hoy.month, min(lote.dia_generacion, ultimo_dia_mes))
        nueva_fecha_vencimiento = nueva_fecha_emision + timedelta(days=dias_vigencia)

        for unidad in unidades:
            ya_generado = (
                db.query(Cargo)
                .filter(Cargo.lote_id == lote.id, Cargo.unidad_id == unidad.id, Cargo.periodo == periodo_actual)
                .first()
            )
            if ya_generado:
                continue
            _crear_cargo_desde_lote(db, lote, unidad, periodo_actual, nueva_fecha_emision, nueva_fecha_vencimiento)

        lote.ultimo_periodo_generado = periodo_actual
        lote.total_unidades = len(unidades)
        lote.total_facturado = Decimal(len(unidades)) * lote.monto
        procesados.append(lote)

    db.commit()
    for lote in procesados:
        db.refresh(lote)
    return procesados


# ── Descuentos manuales (Ingresos y Descuentos → Aplicar / Control) ────────

def aplicar_descuento_manual(
    db: Session, cargo: Cargo, tipo: TipoRecargo, valor: Decimal, motivo: str, user_id: int | None,
) -> DescuentoAplicado:
    """Aplica (o incrementa) un descuento manual sobre un cargo. Se suma al campo
    Cargo.descuento existente (p.ej. si ya traía descuento por pronto pago) y queda
    registrado en la bitácora de Control de Descuentos, auditable por motivo."""
    if valor <= 0:
        raise ValueError("El valor del descuento debe ser mayor a cero.")
    if tipo == TipoRecargo.PORCENTAJE:
        monto_descontado = (cargo.monto_base * valor / Decimal("100")).quantize(Decimal("0.01"))
    else:
        monto_descontado = valor
    monto_descontado = min(monto_descontado, cargo.saldo)
    if monto_descontado <= 0:
        raise ValueError("Este cargo ya no tiene saldo pendiente sobre el cual aplicar un descuento.")

    cargo.descuento = (cargo.descuento or Decimal("0")) + monto_descontado
    registro = DescuentoAplicado(
        cargo_id=cargo.id, tipo=tipo, valor=valor, monto_descontado=monto_descontado,
        motivo=motivo, aplicado_por_id=user_id,
    )
    db.add(registro)
    if cargo.saldo <= 0:
        cargo.estado = EstadoCargo.PAGADO
    db.commit()
    db.refresh(registro)
    return registro


# ── Control de Cobranza (cartera vencida) ───────────────────────────────────

def cartera_vencida(db: Session, condominio_id: int) -> list[dict]:
    """Matriz de cartera vencida: un renglón por unidad con adeudo vencido, con el
    desglose de cuánto debe y desde hace cuántos días."""
    hoy = date.today()
    cargos = (
        db.query(Cargo)
        .join(Unidad, Cargo.unidad_id == Unidad.id)
        .filter(Unidad.condominio_id == condominio_id, Cargo.estado == EstadoCargo.VENCIDO)
        .all()
    )
    por_unidad: dict[int, dict] = {}
    for c in cargos:
        dias = (hoy - c.fecha_vencimiento).days
        row = por_unidad.setdefault(c.unidad_id, {
            "unidad_id": c.unidad_id, "identificador": c.unidad.identificador,
            "propietario": c.unidad.propietario.full_name if c.unidad.propietario else None,
            "total_vencido": Decimal("0"), "cargos_vencidos": 0, "dias_max_vencido": 0,
        })
        row["total_vencido"] += c.saldo
        row["cargos_vencidos"] += 1
        row["dias_max_vencido"] = max(row["dias_max_vencido"], dias)
    return sorted(por_unidad.values(), key=lambda r: r["dias_max_vencido"], reverse=True)


# ── Cuentas por Pagar (proveedores) ─────────────────────────────────────────

def _actualizar_estado_cxp(cuenta: CuentaPorPagar) -> None:
    if cuenta.estado == EstadoCuentaPorPagar.PAGADA and cuenta.saldo > 0:
        pass  # no se revierte automáticamente un estado terminal manual
    if cuenta.saldo <= 0:
        cuenta.estado = EstadoCuentaPorPagar.PAGADA
    elif cuenta.monto_pagado > 0:
        cuenta.estado = EstadoCuentaPorPagar.PARCIAL
    elif any(p.estado == EstadoPagoProveedor.PROGRAMADO for p in cuenta.pagos):
        cuenta.estado = EstadoCuentaPorPagar.PROGRAMADA
    elif cuenta.fecha_vencimiento < date.today():
        cuenta.estado = EstadoCuentaPorPagar.VENCIDA
    else:
        cuenta.estado = EstadoCuentaPorPagar.PENDIENTE


def crear_cuenta_por_pagar(
    db: Session, condominio_id: int, proveedor_id: int, partida_id: int | None,
    folio_factura: str | None, concepto: str, monto: Decimal, fecha_factura: date,
    fecha_vencimiento: date, notas: str | None = None, comprobante_path: str | None = None,
) -> CuentaPorPagar:
    if monto <= 0:
        raise ValueError("El monto debe ser mayor a cero.")
    if fecha_vencimiento < fecha_factura:
        raise ValueError("La fecha de vencimiento no puede ser anterior a la fecha de la factura.")
    cuenta = CuentaPorPagar(
        condominio_id=condominio_id, proveedor_id=proveedor_id, partida_id=partida_id,
        folio_factura=folio_factura, concepto=concepto, monto=monto,
        fecha_factura=fecha_factura, fecha_vencimiento=fecha_vencimiento,
        notas=notas, comprobante_path=comprobante_path,
    )
    db.add(cuenta)
    db.commit()
    db.refresh(cuenta)
    return cuenta


def programar_pago_proveedor(db: Session, cuenta: CuentaPorPagar, monto: Decimal, fecha_programada: date, cuenta_bancaria_id: int | None) -> PagoProveedor:
    if monto <= 0:
        raise ValueError("El monto debe ser mayor a cero.")
    if monto > cuenta.saldo:
        raise ValueError(f"Esta cuenta por pagar solo tiene ${cuenta.saldo} pendientes.")
    pago = PagoProveedor(
        cuenta_id=cuenta.id, monto=monto, fecha_programada=fecha_programada,
        cuenta_bancaria_id=cuenta_bancaria_id, estado=EstadoPagoProveedor.PROGRAMADO,
    )
    cuenta.pagos.append(pago)
    _actualizar_estado_cxp(cuenta)
    db.commit()
    db.refresh(pago)
    return pago


def marcar_pago_proveedor_pagado(db: Session, pago: PagoProveedor, fecha_pagada: date | None = None) -> PagoProveedor:
    pago.estado = EstadoPagoProveedor.PAGADO
    pago.fecha_pagada = fecha_pagada or date.today()
    _actualizar_estado_cxp(pago.cuenta)
    db.commit()
    db.refresh(pago)
    return pago


def cancelar_pago_proveedor(db: Session, pago: PagoProveedor) -> PagoProveedor:
    pago.estado = EstadoPagoProveedor.CANCELADO
    _actualizar_estado_cxp(pago.cuenta)
    db.commit()
    db.refresh(pago)
    return pago


def marcar_cuentas_por_pagar_vencidas(db: Session, condominio_id: int) -> list[CuentaPorPagar]:
    """Job de mantenimiento: pasa a VENCIDA cualquier cuenta por pagar con saldo
    pendiente cuya fecha de vencimiento (plazo de crédito del proveedor) ya pasó."""
    hoy = date.today()
    cuentas = (
        db.query(CuentaPorPagar)
        .filter(
            CuentaPorPagar.condominio_id == condominio_id,
            CuentaPorPagar.estado.in_([EstadoCuentaPorPagar.PENDIENTE, EstadoCuentaPorPagar.PROGRAMADA, EstadoCuentaPorPagar.PARCIAL]),
            CuentaPorPagar.fecha_vencimiento < hoy,
        )
        .all()
    )
    for c in cuentas:
        c.estado = EstadoCuentaPorPagar.VENCIDA
    db.commit()
    for c in cuentas:
        db.refresh(c)
    return cuentas


def reporte_antiguedad_compras(db: Session, condominio_id: int) -> dict:
    """Antigüedad de Compras: agrupa el saldo pendiente por buckets de días vencidos
    (0-30, 31-60, 61-90, 90+) más lo que todavía no vence."""
    hoy = date.today()
    cuentas = (
        db.query(CuentaPorPagar)
        .filter(CuentaPorPagar.condominio_id == condominio_id, CuentaPorPagar.estado != EstadoCuentaPorPagar.PAGADA)
        .all()
    )
    buckets = {"vigente": Decimal("0"), "0_30": Decimal("0"), "31_60": Decimal("0"), "61_90": Decimal("0"), "90_mas": Decimal("0")}
    detalle = []
    for c in cuentas:
        if c.saldo <= 0:
            continue
        dias = (hoy - c.fecha_vencimiento).days
        if dias <= 0:
            bucket = "vigente"
        elif dias <= 30:
            bucket = "0_30"
        elif dias <= 60:
            bucket = "31_60"
        elif dias <= 90:
            bucket = "61_90"
        else:
            bucket = "90_mas"
        buckets[bucket] += c.saldo
        detalle.append({
            "cuenta_id": c.id, "proveedor": c.proveedor.nombre, "folio": c.folio_factura,
            "concepto": c.concepto, "saldo": c.saldo, "fecha_vencimiento": c.fecha_vencimiento,
            "dias_vencido": max(dias, 0), "bucket": bucket,
        })
    detalle.sort(key=lambda d: d["dias_vencido"], reverse=True)
    return {"buckets": buckets, "detalle": detalle, "total": sum(buckets.values(), start=Decimal("0"))}


# ── Importación / escaneo de estados de cuenta bancarios ────────────────────

def _saldos_pendientes_por_unidad(db: Session, condominio_id: int) -> dict[int, Decimal]:
    """{unidad_id: saldo pendiente total} para las unidades del condominio."""
    cargos = (
        db.query(Cargo).join(Unidad, Cargo.unidad_id == Unidad.id)
        .filter(Unidad.condominio_id == condominio_id,
                Cargo.estado.in_([EstadoCargo.PENDIENTE, EstadoCargo.PARCIAL, EstadoCargo.VENCIDO]))
        .all()
    )
    saldos: dict[int, Decimal] = {}
    for c in cargos:
        saldos[c.unidad_id] = saldos.get(c.unidad_id, Decimal("0")) + c.saldo
    return saldos


def _sugerir_por_monto(monto: Decimal, saldos: dict[int, Decimal]) -> int | None:
    """Si exactamente UNA unidad tiene un saldo pendiente igual al monto, la sugiere."""
    coincidencias = [uid for uid, saldo in saldos.items() if saldo == monto]
    return coincidencias[0] if len(coincidencias) == 1 else None


def crear_importacion(
    db: Session, condominio_id: int, nombre_archivo: str, contenido_bytes: bytes,
    cuenta_bancaria_id: int | None, user_id: int | None,
) -> ImportacionBancaria:
    """Lee el estado de cuenta (PDF, Excel o CSV), crea la importación en BORRADOR y sus
    renglones, sugiriendo a qué unidad pertenece cada ABONO (por referencia,
    nombre del propietario, adeudos pendientes o cuota fija)."""
    resultado = statement_parser.parse_bank_statement(contenido_bytes, nombre_archivo=nombre_archivo)
    unidades = db.query(Unidad).filter(Unidad.condominio_id == condominio_id).all()
    saldos = _saldos_pendientes_por_unidad(db, condominio_id)

    propietarios_map = {
        u.id: u.propietario.full_name
        for u in unidades
        if getattr(u, "propietario", None) and u.propietario.full_name
    }
    cuotas_map = {
        u.id: u.cuota_mantenimiento
        for u in unidades
        if u.cuota_mantenimiento and u.cuota_mantenimiento > 0
    }

    importacion = ImportacionBancaria(
        condominio_id=condominio_id, cuenta_bancaria_id=cuenta_bancaria_id,
        nombre_archivo=nombre_archivo, estado=EstadoImportacion.BORRADOR,
        total_movimientos=len(resultado["movimientos"]),
        texto_crudo=(resultado["texto_crudo"] or "")[:40000], aviso=resultado["aviso"],
        creado_por_id=user_id,
    )
    db.add(importacion)
    db.flush()

    for i, mov in enumerate(resultado["movimientos"]):
        es_abono = mov["tipo"] == "ABONO"
        unidad_id, confianza = None, "ninguno"
        if es_abono:
            unidad_id, confianza = statement_parser.sugerir_unidad(
                mov["descripcion"], mov["monto"], unidades,
                propietarios_por_unidad=propietarios_map,
                cuotas_por_unidad=cuotas_map,
            )
            if unidad_id is None:
                por_monto = _sugerir_por_monto(mov["monto"], saldos)
                if por_monto is not None:
                    unidad_id, confianza = por_monto, "monto"

        tipo_enum = TipoMovimiento.ABONO if mov["tipo"] == "ABONO" else TipoMovimiento.CARGO
        db.add(MovimientoImportado(
            importacion_id=importacion.id, orden=i, fecha=mov["fecha"],
            descripcion=mov["descripcion"], monto=mov["monto"],
            tipo=tipo_enum, saldo=mov.get("saldo"),
            unidad_id=unidad_id, confianza=confianza,
            aplicar=es_abono and unidad_id is not None,  # por defecto abonos emparejados
        ))
    db.commit()
    db.refresh(importacion)
    return importacion


def actualizar_movimiento_importado(
    db: Session,
    movimiento: MovimientoImportado,
    unidad_id: int | None = None,
    aplicar: bool = True,
    fecha: date | None = None,
    descripcion: str | None = None,
    monto: Decimal | None = None,
    tipo: TipoMovimiento | None = None,
) -> MovimientoImportado:
    """Guarda la edición de un renglón (unidad, fecha, descripción, monto, tipo y si aplica)."""
    if movimiento.pago_id:  # ya aplicado: no se modifica
        return movimiento

    if fecha is not None:
        movimiento.fecha = fecha
    if descripcion is not None:
        movimiento.descripcion = descripcion.strip()[:255]
    if monto is not None and monto > 0:
        movimiento.monto = monto
    if tipo is not None:
        movimiento.tipo = tipo

    if movimiento.unidad_id != unidad_id:
        movimiento.unidad_id = unidad_id
        movimiento.confianza = "manual" if unidad_id is not None else "ninguno"

    movimiento.aplicar = bool(aplicar and unidad_id is not None and movimiento.tipo == TipoMovimiento.ABONO)
    db.commit()
    db.refresh(movimiento)
    return movimiento


def agregar_movimiento_manual(
    db: Session,
    importacion: ImportacionBancaria,
    fecha: date,
    descripcion: str,
    monto: Decimal,
    tipo: TipoMovimiento,
    unidad_id: int | None = None,
    aplicar: bool = True,
) -> MovimientoImportado:
    """Agrega un movimiento manualmente a un estado de cuenta en borrador."""
    orden = len(importacion.movimientos)
    es_abono = (tipo == TipoMovimiento.ABONO)
    mov = MovimientoImportado(
        importacion_id=importacion.id,
        orden=orden,
        fecha=fecha,
        descripcion=descripcion.strip()[:255] or "(movimiento manual)",
        monto=abs(monto),
        tipo=tipo,
        unidad_id=unidad_id,
        confianza="manual" if unidad_id else "ninguno",
        aplicar=bool(es_abono and unidad_id is not None and aplicar),
    )
    db.add(mov)
    importacion.total_movimientos = (importacion.total_movimientos or 0) + 1
    db.commit()
    db.refresh(mov)
    return mov


def eliminar_movimiento_importado(db: Session, movimiento: MovimientoImportado) -> None:
    """Elimina un renglón de la importación si no ha sido aplicado."""
    if movimiento.pago_id:
        return
    importacion = movimiento.importacion
    db.delete(movimiento)
    if importacion and importacion.total_movimientos > 0:
        importacion.total_movimientos -= 1
    db.commit()


class ImportacionError(Exception):
    pass


def aplicar_importacion(db: Session, importacion: ImportacionBancaria, user_id: int | None) -> int:
    """Convierte en pagos aplicados todos los renglones ABONO marcados para
    aplicar y con unidad asignada, que aún no tengan pago. Devuelve cuántos
    pagos generó. Es idempotente: los renglones ya aplicados se saltan."""
    banco_ref = importacion.cuenta_bancaria.banco if importacion.cuenta_bancaria else "estado de cuenta"
    aplicados = 0

    pendientes = [
        m for m in importacion.movimientos
        if not m.pago_id and m.aplicar and m.tipo == TipoMovimiento.ABONO and m.unidad_id is not None
    ]

    if not pendientes and importacion.estado == EstadoImportacion.APLICADA:
        raise ImportacionError("Esta importación ya fue aplicada.")

    for mov in pendientes:
        unidad = db.query(Unidad).get(mov.unidad_id)
        if unidad is None:
            continue
        referencia = f"{banco_ref}: {mov.descripcion}"[:255]
        pago = registrar_pago_unidad(
            db, unidad, mov.monto, MetodoPago.TRANSFERENCIA, referencia, mov.fecha,
            cuenta_bancaria_id=importacion.cuenta_bancaria_id, user_id=user_id,
            auto_aplicar=True, procesador="importacion_bancaria",
        )
        mov.pago_id = pago.id
        aplicados += 1

    # Verificar si quedan abonos sin aplicar
    faltan = any(m for m in importacion.movimientos if not m.pago_id and m.tipo == TipoMovimiento.ABONO and m.unidad_id is not None)
    if not faltan:
        importacion.estado = EstadoImportacion.APLICADA

    db.commit()
    return aplicados


def exportar_importacion_excel(db_or_importacion, importacion_or_unidades=None):
    """Genera un reporte Excel (.xlsx) altamente detallado y profesional con 3 hojas:
    1. 'Resumen de Aplicación': Métricas clave, importes aplicados a cuotas y a saldo a favor.
    2. 'Pagos por Departamento': Desglose exacto de cada departamento, folio de pago, propietario,
       monto depositado, cuotas/adeudos saldados (CGO-XX) y remanente a saldo a favor.
    3. 'Conciliación Bancaria': Todos los movimientos del estado de cuenta (abonos y cargos).
    """
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    from pathlib import Path as _Path
    from sqlalchemy.orm import Session as _Session, object_session

    if isinstance(db_or_importacion, _Session):
        db = db_or_importacion
        importacion = importacion_or_unidades
    else:
        importacion = db_or_importacion
        db = object_session(importacion)

    wb = openpyxl.Workbook()

    # Estilos de diseño corporativo y contable
    font_main_title = Font(name="Calibri", size=14, bold=True, color="0F172A")
    font_subtitle = Font(name="Calibri", size=9, italic=True, color="64748B")
    font_section = Font(name="Calibri", size=11, bold=True, color="1E293B")
    font_th_dark = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
    font_th_emerald = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
    font_bold = Font(name="Calibri", size=10, bold=True, color="0F172A")
    font_regular = Font(name="Calibri", size=10, color="1E293B")
    font_faint = Font(name="Calibri", size=9, color="64748B")

    fill_th_dark = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
    fill_th_emerald = PatternFill(start_color="059669", end_color="059669", fill_type="solid")
    fill_row_alt = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    fill_total = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
    fill_card = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

    thin_border = Side(style="thin", color="CBD5E1")
    border_cell = Border(left=thin_border, right=thin_border, top=thin_border, bottom=thin_border)
    border_total = Border(top=Side(style="thin", color="0F172A"), bottom=Side(style="double", color="0F172A"))

    align_center = Alignment(horizontal="center", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center")
    align_right = Alignment(horizontal="right", vertical="center")

    CURRENCY_FORMAT = '"$"#,##0.00'
    DATE_FORMAT = 'yyyy-mm-dd'

    # Recopilar datos detallados de pagos y aplicaciones
    movs = importacion.movimientos
    condominio_nombre = importacion.condominio.nombre if importacion.condominio else "Condominio"
    cuenta_nombre = importacion.cuenta_bancaria.banco if importacion.cuenta_bancaria else "Cuenta no especificada"
    if importacion.cuenta_bancaria and importacion.cuenta_bancaria.clabe:
        cuenta_nombre += f" (CLABE: {importacion.cuenta_bancaria.clabe})"

    pagos_detalle = []
    total_aplicado_adeudos = Decimal("0")
    total_saldo_favor = Decimal("0")
    total_pagos_monto = Decimal("0")

    for m in movs:
        if not m.pago_id:
            continue
        pago = db.query(Pago).get(m.pago_id) if db else None
        if not pago:
            continue

        unidad = pago.unidad or (db.query(Unidad).get(pago.unidad_id) if db else None)
        unidad_ident = unidad.identificador if unidad else f"Unidad #{pago.unidad_id}"
        propietario_nom = (unidad.propietario.full_name if (unidad and getattr(unidad, "propietario", None)) else "—")

        monto_aplicado = pago.monto_aplicado
        saldo_favor = pago.monto_disponible

        total_pagos_monto += pago.monto
        total_aplicado_adeudos += monto_aplicado
        total_saldo_favor += saldo_favor

        # Desglose de qué adeudos saldó este pago
        cargos_saldados = []
        for app in pago.aplicaciones:
            cargo = app.cargo
            if cargo:
                cargos_saldados.append(f"CGO-{cargo.id} ({cargo.concepto} [{cargo.periodo}]): ${app.monto_aplicado:,.2f}")
            else:
                cargos_saldados.append(f"Cargo #{app.cargo_id}: ${app.monto_aplicado:,.2f}")

        detalle_adeudos_str = " | ".join(cargos_saldados) if cargos_saldados else "Sin adeudos pendientes (100% Saldo a favor)"

        pagos_detalle.append({
            "pago_id": pago.id,
            "folio": f"PAG-{pago.id}",
            "fecha": pago.fecha_pago,
            "unidad": unidad_ident,
            "propietario": propietario_nom,
            "monto": float(pago.monto),
            "monto_aplicado": float(monto_aplicado),
            "saldo_favor": float(saldo_favor),
            "detalle_adeudos": detalle_adeudos_str,
            "confianza": m.confianza,
            "descripcion_banco": m.descripcion,
            "estado": pago.estado.value if hasattr(pago.estado, "value") else str(pago.estado),
        })

    # =========================================================================
    # HOJA 1: Resumen Ejecutivo de la Aplicación
    # =========================================================================
    ws_resumen = wb.active
    ws_resumen.title = "Resumen de Aplicación"

    ws_resumen.append([f"CONDOMINIOS SAAS — REPORTE DETALLADO DE APLICACIÓN BANCARIA"])
    ws_resumen.cell(row=1, column=1).font = font_main_title
    ws_resumen.append([f"Condominio: {condominio_nombre} | Cuenta bancaria: {cuenta_nombre}"])
    ws_resumen.cell(row=2, column=1).font = font_subtitle
    ws_resumen.append([f"Archivo procesado: {importacion.nombre_archivo} | Estatus: {importacion.estado.value} | Fecha reporte: {date.today().isoformat()}"])
    ws_resumen.cell(row=3, column=1).font = font_subtitle
    ws_resumen.append([])

    # Tarjetas / Resumen de métricas
    ws_resumen.append(["MÉTRICAS CLAVE DE LA OPERACIÓN", "VALOR", "NOTAS DE AUDITORÍA"])
    for col_idx in range(1, 4):
        c = ws_resumen.cell(row=5, column=col_idx)
        c.font = font_th_dark
        c.fill = fill_th_dark
        c.alignment = align_center if col_idx == 2 else align_left

    kpis = [
        ("Total de movimientos en el estado de cuenta", len(movs), "Renglones leídos del archivo bancario", "int"),
        ("Total de abonos / depósitos bancarios", float(importacion.total_abonos), "Suma bruta de depósitos reconocidos", "currency"),
        ("Total de pagos aplicados a departamentos", float(total_pagos_monto), f"Correspondiente a {len(pagos_detalle)} pago(s) oficial(es)", "currency"),
        ("Monto aplicado a cuotas y adeudos vencidos", float(total_aplicado_adeudos), "Liquidación FIFO contra cargos pendientes", "currency"),
        ("Monto acreditado como Saldo a Favor", float(total_saldo_favor), "Excedentes disponibles en billetera virtual", "currency"),
        ("Departamentos beneficiados con pago", len({p['unidad'] for p in pagos_detalle}), "Unidades con saldo abonado", "int"),
        ("Comisiones y cargos bancarios (Egresos banco)", float(sum((m.monto for m in movs if m.tipo == TipoMovimiento.CARGO), start=Decimal("0"))), "Cargos bancarios informativos no aplicados", "currency"),
    ]

    r_idx = 6
    for titulo, val, nota, fmt in kpis:
        ws_resumen.append([titulo, val, nota])
        c1 = ws_resumen.cell(row=r_idx, column=1)
        c2 = ws_resumen.cell(row=r_idx, column=2)
        c3 = ws_resumen.cell(row=r_idx, column=3)
        c1.font = font_bold
        c1.border = border_cell
        c2.font = font_bold
        c2.border = border_cell
        c2.alignment = align_right
        if fmt == "currency":
            c2.number_format = CURRENCY_FORMAT
        else:
            c2.alignment = align_center
        c3.font = font_faint
        c3.border = border_cell
        if r_idx % 2 == 1:
            c1.fill = fill_row_alt
            c2.fill = fill_row_alt
            c3.fill = fill_row_alt
        r_idx += 1

    # =========================================================================
    # HOJA 2: Detalle de Pagos por Departamento
    # =========================================================================
    ws_pagos = wb.create_sheet(title="Pagos por Departamento")
    ws_pagos.append(["DETALLE DE PAGOS REGISTRADOS Y APLICADOS A DEPARTAMENTOS"])
    ws_pagos.cell(row=1, column=1).font = font_main_title
    ws_pagos.append(["Desglose de pagos oficiales generados, cargos liquidados y saldo a favor por unidad"])
    ws_pagos.cell(row=2, column=1).font = font_subtitle
    ws_pagos.append([])

    headers_pagos = [
        "Folio Pago", "Fecha Pago", "Departamento", "Propietario / Residente",
        "Monto Depositado", "Aplicado a Adeudos", "Saldo a Favor",
        "Cuotas / Cargos Liquidados", "Motivo Detección", "Concepto Banco", "Estatus"
    ]
    ws_pagos.append(headers_pagos)
    for col_idx in range(1, len(headers_pagos) + 1):
        c = ws_pagos.cell(row=4, column=col_idx)
        c.font = font_th_emerald
        c.fill = fill_th_emerald
        c.alignment = align_center

    start_pago_row = 5
    p_row = start_pago_row
    for p in pagos_detalle:
        ws_pagos.append([
            p["folio"],
            p["fecha"].isoformat() if hasattr(p["fecha"], "isoformat") else str(p["fecha"]),
            p["unidad"],
            p["propietario"],
            p["monto"],
            p["monto_aplicado"],
            p["saldo_favor"],
            p["detalle_adeudos"],
            p["confianza"].upper(),
            p["descripcion_banco"],
            p["estado"],
        ])
        for col_idx in range(1, len(headers_pagos) + 1):
            cell = ws_pagos.cell(row=p_row, column=col_idx)
            cell.font = font_regular
            cell.border = border_cell
            if col_idx in (1, 2, 3, 9, 11):
                cell.alignment = align_center
            elif col_idx in (5, 6, 7):
                cell.alignment = align_right
                cell.number_format = CURRENCY_FORMAT
                cell.font = font_bold
            else:
                cell.alignment = align_left
            if p_row % 2 == 1:
                cell.fill = fill_row_alt
        p_row += 1

    # Fila de totales en hoja de pagos
    if pagos_detalle:
        ws_pagos.append([
            "TOTALES", "", "", f"{len(pagos_detalle)} pago(s)",
            float(total_pagos_monto), float(total_aplicado_adeudos), float(total_saldo_favor),
            "", "", "", ""
        ])
        for col_idx in range(1, len(headers_pagos) + 1):
            cell = ws_pagos.cell(row=p_row, column=col_idx)
            cell.font = font_bold
            cell.fill = fill_total
            cell.border = border_total
            if col_idx in (5, 6, 7):
                cell.alignment = align_right
                cell.number_format = CURRENCY_FORMAT
            else:
                cell.alignment = align_center if col_idx <= 4 else align_left

    # =========================================================================
    # HOJA 3: Conciliación Completa (Todos los renglones)
    # =========================================================================
    ws_completo = wb.create_sheet(title="Movimientos Banco")
    ws_completo.append(["ESTADO DE CUENTA BANCARIO COMPLETO (AUDITORÍA)"])
    ws_completo.cell(row=1, column=1).font = font_main_title
    ws_completo.append(["Registro íntegro de abonos, cargos bancarios y su estatus de asignación"])
    ws_completo.cell(row=2, column=1).font = font_subtitle
    ws_completo.append([])

    headers_completo = [
        "# Renglón", "Fecha", "Concepto Bancario", "Tipo", "Monto", "Saldo Corrido",
        "Depto Asignado", "Detección", "¿Aplicar?", "Folio Pago Generado", "Estatus"
    ]
    ws_completo.append(headers_completo)
    for col_idx in range(1, len(headers_completo) + 1):
        c = ws_completo.cell(row=4, column=col_idx)
        c.font = font_th_dark
        c.fill = fill_th_dark
        c.alignment = align_center

    c_row = 5
    for idx, m in enumerate(movs, start=1):
        es_abono = (m.tipo == TipoMovimiento.ABONO)
        u_nom = ""
        if m.unidad_id and db:
            u_obj = db.query(Unidad).get(m.unidad_id)
            u_nom = u_obj.identificador if u_obj else f"Unidad #{m.unidad_id}"

        status_str = "No aplicado"
        if m.pago_id:
            status_str = f"APLICADO (PAG-{m.pago_id})"
        elif not es_abono:
            status_str = "Informativo (Cargo banco)"
        elif m.aplicar:
            status_str = "Pendiente de aplicar"

        ws_completo.append([
            idx,
            m.fecha.isoformat() if hasattr(m.fecha, "isoformat") else str(m.fecha),
            m.descripcion,
            m.tipo.value,
            float(m.monto),
            float(m.saldo) if m.saldo is not None else "",
            u_nom or "—",
            m.confianza.upper() if m.confianza else "—",
            "Sí" if m.aplicar else "No",
            f"PAG-{m.pago_id}" if m.pago_id else "—",
            status_str,
        ])
        for col_idx in range(1, len(headers_completo) + 1):
            cell = ws_completo.cell(row=c_row, column=col_idx)
            cell.font = font_regular
            cell.border = border_cell
            if col_idx in (1, 2, 4, 7, 8, 9, 10):
                cell.alignment = align_center
            elif col_idx in (5, 6):
                cell.alignment = align_right
                if cell.value != "":
                    cell.number_format = CURRENCY_FORMAT
            else:
                cell.alignment = align_left
            if c_row % 2 == 1:
                cell.fill = fill_row_alt
        c_row += 1

    # Autoajuste de anchos de columna para todas las hojas
    for sheet in wb.worksheets:
        sheet.views.sheetView[0].showGridLines = True
        for col in sheet.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                val = cell.value
                if val is not None:
                    s_val = str(val)
                    if len(s_val) < 60:
                        max_len = max(max_len, len(s_val))
            sheet.column_dimensions[col_letter].width = max(max_len + 3, 12)

    out_dir = _Path(__file__).resolve().parent / "data" / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"reporte_detallado_importacion_{importacion.id}.xlsx"
    wb.save(path)
    return path
