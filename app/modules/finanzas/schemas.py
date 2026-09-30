from typing import Optional
from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.finanzas.models import (
    EstadoCargo,
    EstadoFactura,
    EstadoPago,
    MetodoPago,
    TipoCalculoCuota,
    TipoCargo,
    TipoFondo,
    TipoMovimiento,
    TipoPartida,
    TipoRecargo,
    TipoRecurrencia,
    TipoSeleccionUnidades,
)


class CuotaConfigUpsert(BaseModel):
    condominio_id: int
    tipo_calculo: TipoCalculoCuota = TipoCalculoCuota.FIJA
    monto_total_prorrateo: Optional[Decimal] = None
    dia_limite_pago: int = 10
    dias_gracia: int = 0
    recargo_tipo: TipoRecargo = TipoRecargo.PORCENTAJE
    recargo_valor: Decimal = Decimal("0")
    descuento_pronto_pago_pct: Decimal = Decimal("0")
    descuento_pronto_pago_dias: int = 0


class CuotaConfigResponse(CuotaConfigUpsert):
    id: int
    model_config = ConfigDict(from_attributes=True)


class GenerarCargosRequest(BaseModel):
    condominio_id: int
    periodo: str  # "YYYY-MM"


class PagoCreate(BaseModel):
    monto: Decimal
    metodo: MetodoPago = MetodoPago.EFECTIVO
    referencia: Optional[str] = None
    fecha_pago: Optional[date] = None


class PagoCreateUnidad(BaseModel):
    """Payload de POST /finanzas/condominios/{id}/pagos — registro de un ingreso."""
    unidad_id: int
    monto: Decimal = Field(gt=0)
    metodo: MetodoPago = MetodoPago.EFECTIVO
    referencia: Optional[str] = None
    fecha_pago: Optional[date] = None
    cuenta_bancaria_id: Optional[int] = None
    fondo_id: Optional[int] = None
    auto_aplicar: bool = True


class AplicarPagoRequest(BaseModel):
    """Payload de POST /finanzas/pagos/{pago_id}/aplicar — aplicación manual contra un cargo."""
    cargo_id: int
    monto: Decimal = Field(gt=0)


class PagoResponse(BaseModel):
    id: int
    unidad_id: int
    monto: Decimal
    fecha_pago: date
    metodo: MetodoPago
    referencia: Optional[str] = None
    cuenta_bancaria_id: Optional[int] = None
    fondo_id: Optional[int] = None
    estado: EstadoPago
    monto_aplicado: Decimal
    monto_disponible: Decimal
    comprobante_path: Optional[str] = None
    procesador: str
    model_config = ConfigDict(from_attributes=True)


class AplicacionResponse(BaseModel):
    id: int
    pago_id: int
    cargo_id: int
    monto_aplicado: Decimal
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class CargoResponse(BaseModel):
    id: int
    unidad_id: int
    lote_id: Optional[int] = None
    tipo: TipoCargo
    periodo: str
    concepto: str
    descripcion: Optional[str] = None
    moneda: str
    monto_base: Decimal
    recargo: Decimal
    descuento: Decimal
    monto_total: Decimal
    monto_pagado: Decimal
    saldo: Decimal
    fecha_emision: date
    fecha_vencimiento: date
    estado: EstadoCargo
    model_config = ConfigDict(from_attributes=True)


class CargoDetailResponse(CargoResponse):
    aplicaciones: list[AplicacionResponse] = []


class CargoManualCreate(BaseModel):
    unidad_id: int
    tipo: TipoCargo = TipoCargo.OTRO
    concepto: str
    monto_base: Decimal
    periodo: Optional[str] = None
    fecha_vencimiento: Optional[date] = None
    cobrar_de_inmediato: bool = False
    metodo_pago: MetodoPago = MetodoPago.EFECTIVO


class MovimientoBancarioCreate(BaseModel):
    condominio_id: int
    cuenta_bancaria_id: Optional[int] = None
    fecha: date
    descripcion: Optional[str] = None
    monto: Decimal
    tipo: TipoMovimiento = TipoMovimiento.ABONO


class MovimientoBancarioResponse(MovimientoBancarioCreate):
    id: int
    conciliado: bool
    pago_id: Optional[int] = None
    model_config = ConfigDict(from_attributes=True)


class ConciliarRequest(BaseModel):
    pago_id: int


class FacturaResponse(BaseModel):
    id: int
    cargo_id: int
    estado: EstadoFactura
    uuid_fiscal: Optional[str] = None
    notas: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class EstadoCuentaResponse(BaseModel):
    unidad_id: int
    identificador: str
    saldo_total: Decimal
    cargos: list[CargoResponse]


class MovimientoResponse(BaseModel):
    fecha: date
    tipo: str  # "CARGO" | "PAGO"
    folio: str
    concepto: str
    debe: Decimal
    haber: Decimal
    estatus: str
    cargo_id: Optional[int] = None
    pago_id: Optional[int] = None


class TotalesEstadoCuenta(BaseModel):
    total_cuotas: Decimal
    total_penalidades: Decimal
    total_pagos: Decimal
    total_descuentos: Decimal
    balance_total: Decimal
    saldo_favor_remanente: Decimal


class EstadoCuentaCompletoResponse(BaseModel):
    unidad_id: int
    identificador: str
    contacto_nombre: Optional[str] = None
    contacto_email: Optional[str] = None
    saldo_favor_actual: Decimal
    movimientos: list[MovimientoResponse]
    totales: TotalesEstadoCuenta


class CuentaBancariaCreate(BaseModel):
    condominio_id: int
    banco: str
    clabe: Optional[str] = None
    numero_cuenta: Optional[str] = None
    titular: Optional[str] = None
    tipo_fondo: TipoFondo = TipoFondo.OPERATIVO
    saldo_inicial: Decimal = Decimal("0")


class CuentaBancariaResponse(CuentaBancariaCreate):
    id: int
    model_config = ConfigDict(from_attributes=True)


class PartidaPresupuestalCreate(BaseModel):
    condominio_id: int
    nombre: str
    tipo: TipoPartida
    anio: int
    monto_proyectado_anual: Decimal


class PartidaPresupuestalResponse(PartidaPresupuestalCreate):
    id: int
    model_config = ConfigDict(from_attributes=True)


class PartidaComparativo(BaseModel):
    partida_id: int
    nombre: str
    tipo: TipoPartida
    proyectado_anual: Decimal
    proyectado_mensual: Decimal
    real_mes_actual: Decimal
    real_acumulado_anio: Decimal


class EgresoResponse(BaseModel):
    id: int
    condominio_id: int
    proveedor_id: Optional[int] = None
    cuenta_bancaria_id: Optional[int] = None
    partida_id: Optional[int] = None
    descripcion: str
    monto: Decimal
    fecha: date
    comprobante_pdf_path: Optional[str] = None
    comprobante_xml_path: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class AbonoSaldoFavorCreate(BaseModel):
    """Registro rápido de un pago anticipado (se aplica FIFO y el resto queda como crédito)."""
    unidad_id: int
    monto: Decimal = Field(gt=0)
    motivo: Optional[str] = None


class ImportResumen(BaseModel):
    total_filas: int
    creados: int
    errores: list[str] = []


class FondoCreate(BaseModel):
    condominio_id: int
    nombre: str
    tipo_fondo: TipoFondo = TipoFondo.OPERATIVO


class FondoResponse(FondoCreate):
    id: int
    model_config = ConfigDict(from_attributes=True)


class EmisionCargosRequest(BaseModel):
    """Payload de POST /finanzas/emisiones — emisión individual o masiva de cargos."""

    tipo_seleccion: TipoSeleccionUnidades
    unidad_ids: Optional[list[int]] = None  # requerido si tipo_seleccion == MANUAL
    grupo: Optional[str] = None  # requerido si tipo_seleccion == GRUPO

    tipo_cargo: TipoCargo = TipoCargo.EXTRAORDINARIA
    concepto: str = Field(min_length=1, max_length=150)
    descripcion: Optional[str] = None
    moneda: str = "MXN"
    monto: Decimal = Field(gt=0)

    partida_id: Optional[int] = None
    fondo_id: Optional[int] = None

    fecha_emision: date
    fecha_vencimiento: date

    recurrencia: TipoRecurrencia = TipoRecurrencia.NINGUNA
    dia_generacion: Optional[int] = Field(default=None, ge=1, le=28)

    descuento_activo: bool = False
    descuento_tipo: Optional[TipoRecargo] = None
    descuento_valor: Optional[Decimal] = Field(default=None, gt=0)
    descuento_dias_antes: Optional[int] = Field(default=None, gt=0)

    @field_validator("monto")
    @classmethod
    def _monto_positivo(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("El monto debe ser mayor a cero.")
        return v

    @model_validator(mode="after")
    def _validar_reglas(self) -> "EmisionCargosRequest":
        if self.fecha_vencimiento < self.fecha_emision:
            raise ValueError("fecha_vencimiento no puede ser anterior a fecha_emision.")
        if self.tipo_seleccion == TipoSeleccionUnidades.MANUAL and not self.unidad_ids:
            raise ValueError("tipo_seleccion=MANUAL requiere unidad_ids.")
        if self.tipo_seleccion == TipoSeleccionUnidades.GRUPO and not self.grupo:
            raise ValueError("tipo_seleccion=GRUPO requiere grupo.")
        if self.recurrencia != TipoRecurrencia.NINGUNA and not self.dia_generacion:
            raise ValueError("Un cargo recurrente requiere dia_generacion (1-28).")
        if self.descuento_activo:
            if not self.descuento_tipo:
                raise ValueError("descuento_activo requiere descuento_tipo.")
            if not self.descuento_valor or self.descuento_valor <= 0:
                raise ValueError("descuento_activo requiere descuento_valor > 0.")
            if not self.descuento_dias_antes or self.descuento_dias_antes <= 0:
                raise ValueError("descuento_activo requiere descuento_dias_antes > 0.")
        return self


class EmisionLoteResponse(BaseModel):
    id: int
    condominio_id: int
    tipo_seleccion: TipoSeleccionUnidades
    grupo: Optional[str] = None
    tipo_cargo: TipoCargo
    concepto: str
    descripcion: Optional[str] = None
    moneda: str
    monto: Decimal
    partida_id: Optional[int] = None
    fondo_id: Optional[int] = None
    fecha_emision: date
    fecha_vencimiento: date
    recurrencia: TipoRecurrencia
    dia_generacion: Optional[int] = None
    activo: bool
    ultimo_periodo_generado: Optional[str] = None
    descuento_activo: bool
    descuento_tipo: Optional[TipoRecargo] = None
    descuento_valor: Optional[Decimal] = None
    descuento_dias_antes: Optional[int] = None
    total_unidades: int
    total_facturado: Decimal
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class EmisionResumenResponse(BaseModel):
    lote: EmisionLoteResponse
    cargos: list[CargoResponse]
