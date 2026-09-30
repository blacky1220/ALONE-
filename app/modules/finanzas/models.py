import enum
from decimal import Decimal
from sqlalchemy import Column, Integer, String, Numeric, ForeignKey, DateTime, Date, Enum, Boolean, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class EstadoCargo(str, enum.Enum):
    PENDIENTE = "PENDIENTE"
    PARCIAL = "PARCIAL"
    PAGADO = "PAGADO"
    VENCIDO = "VENCIDO"


class TipoRecargo(str, enum.Enum):
    FIJO = "FIJO"
    PORCENTAJE = "PORCENTAJE"


class MetodoPago(str, enum.Enum):
    EFECTIVO = "EFECTIVO"
    TRANSFERENCIA = "TRANSFERENCIA"
    TARJETA = "TARJETA"
    SPEI = "SPEI"
    OTRO = "OTRO"


class TipoMovimiento(str, enum.Enum):
    ABONO = "ABONO"
    CARGO = "CARGO"


class EstadoFactura(str, enum.Enum):
    PENDIENTE = "PENDIENTE"
    TIMBRADA = "TIMBRADA"
    CANCELADA = "CANCELADA"


class TipoFondo(str, enum.Enum):
    OPERATIVO = "OPERATIVO"
    RESERVA = "RESERVA"
    MANTENIMIENTO_MAYOR = "MANTENIMIENTO_MAYOR"
    CAJA_CHICA = "CAJA_CHICA"


class TipoCalculoCuota(str, enum.Enum):
    FIJA = "FIJA"
    INDIVISO = "INDIVISO"  # prorrateado por Unidad.indiviso_pct


class TipoCargo(str, enum.Enum):
    CUOTA = "CUOTA"
    EXTRAORDINARIA = "EXTRAORDINARIA"
    MULTA = "MULTA"
    AMENIDAD = "AMENIDAD"
    TAG_VEHICULAR = "TAG_VEHICULAR"
    SALDO_INICIAL = "SALDO_INICIAL"
    OTRO = "OTRO"


class TipoPartida(str, enum.Enum):
    INGRESO = "INGRESO"
    EGRESO = "EGRESO"


class TipoSeleccionUnidades(str, enum.Enum):
    TODAS = "TODAS"
    MANUAL = "MANUAL"
    GRUPO = "GRUPO"


class TipoRecurrencia(str, enum.Enum):
    NINGUNA = "NINGUNA"
    MENSUAL = "MENSUAL"
    BIMESTRAL = "BIMESTRAL"
    ANUAL = "ANUAL"


class EstadoPago(str, enum.Enum):
    """Equivalentes a UNAPPLIED / PARTIAL / APPLIED de la especificación."""
    NO_APLICADO = "NO_APLICADO"
    PARCIAL = "PARCIAL"
    APLICADO = "APLICADO"
    CANCELADO = "CANCELADO"


class Fondo(Base):
    """Bolsa contable a la que se destina el dinero recaudado (Operativo, Reserva, Mantenimiento Mayor...).
    Distinto de CuentaBancaria: el fondo es la clasificación contable, la cuenta es dónde vive el dinero físicamente."""
    __tablename__ = "fondos"

    id = Column(Integer, primary_key=True, index=True)
    condominio_id = Column(Integer, ForeignKey("condominios.id", ondelete="CASCADE"), nullable=False)
    nombre = Column(String(100), nullable=False)
    tipo_fondo = Column(Enum(TipoFondo), default=TipoFondo.OPERATIVO, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class EmisionLote(Base):
    """Registro de una emisión de cargos (individual o masiva), única o recurrente.
    Cuando es recurrente, este mismo registro actúa como plantilla: el worker en
    segundo plano vuelve a generar cargos a partir de él en cada periodo."""
    __tablename__ = "emisiones_lotes"

    id = Column(Integer, primary_key=True, index=True)
    condominio_id = Column(Integer, ForeignKey("condominios.id", ondelete="CASCADE"), nullable=False)

    tipo_seleccion = Column(Enum(TipoSeleccionUnidades), nullable=False, default=TipoSeleccionUnidades.MANUAL)
    grupo = Column(String(80), nullable=True)  # solo si tipo_seleccion == GRUPO

    tipo_cargo = Column(Enum(TipoCargo), default=TipoCargo.EXTRAORDINARIA, nullable=False)
    concepto = Column(String(150), nullable=False)
    descripcion = Column(Text, nullable=True)
    moneda = Column(String(3), default="MXN", nullable=False)
    monto = Column(Numeric(12, 2), nullable=False)

    partida_id = Column(Integer, ForeignKey("partidas_presupuestales.id", ondelete="SET NULL"), nullable=True)
    fondo_id = Column(Integer, ForeignKey("fondos.id", ondelete="SET NULL"), nullable=True)

    fecha_emision = Column(Date, nullable=False)
    fecha_vencimiento = Column(Date, nullable=False)

    recurrencia = Column(Enum(TipoRecurrencia), default=TipoRecurrencia.NINGUNA, nullable=False)
    dia_generacion = Column(Integer, nullable=True)  # día del mes en que se auto-genera el siguiente periodo
    activo = Column(Boolean, default=True)  # permite pausar una plantilla recurrente
    ultimo_periodo_generado = Column(String(7), nullable=True)  # "YYYY-MM"

    descuento_activo = Column(Boolean, default=False)
    descuento_tipo = Column(Enum(TipoRecargo), nullable=True)
    descuento_valor = Column(Numeric(12, 2), nullable=True)
    descuento_dias_antes = Column(Integer, nullable=True)  # días antes del vencimiento para calificar

    total_unidades = Column(Integer, default=0)
    total_facturado = Column(Numeric(14, 2), default=0)
    creado_por_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    partida = relationship("PartidaPresupuestal")
    fondo = relationship("Fondo")
    cargos = relationship("Cargo", back_populates="lote")


class CuentaBancaria(Base):
    __tablename__ = "cuentas_bancarias"

    id = Column(Integer, primary_key=True, index=True)
    condominio_id = Column(Integer, ForeignKey("condominios.id", ondelete="CASCADE"), nullable=False)
    banco = Column(String(100), nullable=False)
    clabe = Column(String(18), nullable=True)
    numero_cuenta = Column(String(30), nullable=True)
    titular = Column(String(150), nullable=True)
    tipo_fondo = Column(Enum(TipoFondo), default=TipoFondo.OPERATIVO, nullable=False)
    saldo_inicial = Column(Numeric(12, 2), default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PartidaPresupuestal(Base):
    """Presupuesto anual por partida, comparable contra el gasto/ingreso real devengado."""
    __tablename__ = "partidas_presupuestales"

    id = Column(Integer, primary_key=True, index=True)
    condominio_id = Column(Integer, ForeignKey("condominios.id", ondelete="CASCADE"), nullable=False)
    nombre = Column(String(150), nullable=False)
    tipo = Column(Enum(TipoPartida), nullable=False)
    anio = Column(Integer, nullable=False)
    monto_proyectado_anual = Column(Numeric(14, 2), nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    egresos = relationship("Egreso", back_populates="partida")


class Egreso(Base):
    __tablename__ = "egresos"

    id = Column(Integer, primary_key=True, index=True)
    condominio_id = Column(Integer, ForeignKey("condominios.id", ondelete="CASCADE"), nullable=False)
    proveedor_id = Column(Integer, ForeignKey("proveedores.id", ondelete="SET NULL"), nullable=True)
    cuenta_bancaria_id = Column(Integer, ForeignKey("cuentas_bancarias.id", ondelete="SET NULL"), nullable=True)
    partida_id = Column(Integer, ForeignKey("partidas_presupuestales.id", ondelete="SET NULL"), nullable=True)
    descripcion = Column(String(255), nullable=False)
    monto = Column(Numeric(12, 2), nullable=False)
    fecha = Column(Date, server_default=func.current_date())
    comprobante_pdf_path = Column(String(500), nullable=True)
    comprobante_xml_path = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    proveedor = relationship("Proveedor")
    cuenta_bancaria = relationship("CuentaBancaria")
    partida = relationship("PartidaPresupuestal", back_populates="egresos")


class SaldoFavorMovimiento(Base):
    """Bitácora de la billetera virtual (saldo a favor) de cada unidad."""
    __tablename__ = "saldo_favor_movimientos"

    id = Column(Integer, primary_key=True, index=True)
    unidad_id = Column(Integer, ForeignKey("unidades.id", ondelete="CASCADE"), nullable=False)
    monto = Column(Numeric(12, 2), nullable=False)  # positivo = abono, negativo = uso/amortización
    motivo = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    unidad = relationship("Unidad")


class CuotaConfig(Base):
    """Reglas de cobro y mora por condominio."""
    __tablename__ = "cuota_config"

    id = Column(Integer, primary_key=True, index=True)
    condominio_id = Column(Integer, ForeignKey("condominios.id", ondelete="CASCADE"), unique=True, nullable=False)
    tipo_calculo = Column(Enum(TipoCalculoCuota), default=TipoCalculoCuota.FIJA, nullable=False)
    monto_total_prorrateo = Column(Numeric(14, 2), nullable=True)  # solo si tipo_calculo == INDIVISO
    dia_limite_pago = Column(Integer, default=10)  # día del mes límite sin recargo
    dias_gracia = Column(Integer, default=0)
    recargo_tipo = Column(Enum(TipoRecargo), default=TipoRecargo.PORCENTAJE)
    recargo_valor = Column(Numeric(12, 2), default=0)  # % o monto fijo según recargo_tipo
    descuento_pronto_pago_pct = Column(Numeric(5, 2), default=0)
    descuento_pronto_pago_dias = Column(Integer, default=0)  # pagar dentro de N días desde la emisión
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Cargo(Base):
    """Recibo de cobro emitido a una unidad por un periodo determinado."""
    __tablename__ = "cargos"

    id = Column(Integer, primary_key=True, index=True)
    unidad_id = Column(Integer, ForeignKey("unidades.id", ondelete="CASCADE"), nullable=False)
    lote_id = Column(Integer, ForeignKey("emisiones_lotes.id", ondelete="SET NULL"), nullable=True)
    partida_id = Column(Integer, ForeignKey("partidas_presupuestales.id", ondelete="SET NULL"), nullable=True)
    fondo_id = Column(Integer, ForeignKey("fondos.id", ondelete="SET NULL"), nullable=True)
    tipo = Column(Enum(TipoCargo), default=TipoCargo.CUOTA, nullable=False)
    periodo = Column(String(7), nullable=False)  # "YYYY-MM"
    concepto = Column(String(150), default="Cuota de mantenimiento")
    descripcion = Column(Text, nullable=True)
    moneda = Column(String(3), default="MXN", nullable=False)
    monto_base = Column(Numeric(12, 2), nullable=False)
    recargo = Column(Numeric(12, 2), default=0)
    descuento = Column(Numeric(12, 2), default=0)
    # Regla de descuento por pronto pago propia del cargo (si vino de una emisión con descuento activo).
    descuento_tipo = Column(Enum(TipoRecargo), nullable=True)
    descuento_valor = Column(Numeric(12, 2), nullable=True)
    descuento_dias_antes = Column(Integer, nullable=True)
    fecha_emision = Column(Date, server_default=func.current_date())
    fecha_vencimiento = Column(Date, nullable=False)
    estado = Column(Enum(EstadoCargo), default=EstadoCargo.PENDIENTE, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    unidad = relationship("Unidad")
    lote = relationship("EmisionLote", back_populates="cargos")
    partida = relationship("PartidaPresupuestal")
    fondo = relationship("Fondo")
    aplicaciones = relationship("PagoAplicacion", back_populates="cargo", cascade="all, delete-orphan")
    factura = relationship("Factura", back_populates="cargo", uselist=False)

    @property
    def monto_total(self):
        return (self.monto_base or 0) + (self.recargo or 0) - (self.descuento or 0)

    @property
    def monto_pagado(self):
        return sum((a.monto_aplicado for a in self.aplicaciones), start=0)

    @property
    def saldo(self):
        return self.monto_total - self.monto_pagado


class Pago(Base):
    """Abono/ingreso recibido de una unidad. No está atado a un solo cargo: su monto se
    reparte entre cero o más cargos a través de PagoAplicacion. La parte no aplicada es,
    por definición, el saldo a favor disponible de la unidad."""
    __tablename__ = "pagos"

    id = Column(Integer, primary_key=True, index=True)
    unidad_id = Column(Integer, ForeignKey("unidades.id", ondelete="CASCADE"), nullable=False)
    monto = Column(Numeric(12, 2), nullable=False)
    fecha_pago = Column(Date, server_default=func.current_date())
    metodo = Column(Enum(MetodoPago), default=MetodoPago.EFECTIVO)
    referencia = Column(String(120), nullable=True)
    cuenta_bancaria_id = Column(Integer, ForeignKey("cuentas_bancarias.id", ondelete="SET NULL"), nullable=True)
    fondo_id = Column(Integer, ForeignKey("fondos.id", ondelete="SET NULL"), nullable=True)
    estado = Column(Enum(EstadoPago), default=EstadoPago.NO_APLICADO, nullable=False)
    comprobante_path = Column(String(500), nullable=True)
    procesador = Column(String(50), default="manual")  # punto de integración: "manual" | "stripe" | "conekta" | ...
    registrado_por_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    unidad = relationship("Unidad")
    cuenta_bancaria = relationship("CuentaBancaria")
    fondo = relationship("Fondo")
    aplicaciones = relationship("PagoAplicacion", back_populates="pago", cascade="all, delete-orphan")

    @property
    def monto_aplicado(self):
        return sum((a.monto_aplicado for a in self.aplicaciones), start=0)

    @property
    def monto_disponible(self):
        return self.monto - self.monto_aplicado


class PagoAplicacion(Base):
    """Aplicación (total o parcial, auditable) de un Pago contra un Cargo específico."""
    __tablename__ = "pago_aplicaciones"

    id = Column(Integer, primary_key=True, index=True)
    pago_id = Column(Integer, ForeignKey("pagos.id", ondelete="CASCADE"), nullable=False)
    cargo_id = Column(Integer, ForeignKey("cargos.id", ondelete="CASCADE"), nullable=False)
    monto_aplicado = Column(Numeric(12, 2), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    pago = relationship("Pago", back_populates="aplicaciones")
    cargo = relationship("Cargo", back_populates="aplicaciones")


class MovimientoBancario(Base):
    """Movimiento importado del estado de cuenta bancario, para conciliación manual."""
    __tablename__ = "movimientos_bancarios"

    id = Column(Integer, primary_key=True, index=True)
    condominio_id = Column(Integer, ForeignKey("condominios.id", ondelete="CASCADE"), nullable=False)
    cuenta_bancaria_id = Column(Integer, ForeignKey("cuentas_bancarias.id", ondelete="SET NULL"), nullable=True)
    fecha = Column(Date, nullable=False)
    descripcion = Column(String(255), nullable=True)
    monto = Column(Numeric(12, 2), nullable=False)
    tipo = Column(Enum(TipoMovimiento), default=TipoMovimiento.ABONO)
    conciliado = Column(Boolean, default=False)
    pago_id = Column(Integer, ForeignKey("pagos.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    pago = relationship("Pago")
    cuenta_bancaria = relationship("CuentaBancaria")


class Factura(Base):
    """Registro de facturación CFDI. El timbrado real requiere conectar un PAC (ver adapters.py)."""
    __tablename__ = "facturas"

    id = Column(Integer, primary_key=True, index=True)
    cargo_id = Column(Integer, ForeignKey("cargos.id", ondelete="CASCADE"), unique=True, nullable=False)
    estado = Column(Enum(EstadoFactura), default=EstadoFactura.PENDIENTE)
    uuid_fiscal = Column(String(50), nullable=True)
    notas = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    cargo = relationship("Cargo", back_populates="factura")


class DescuentoAplicado(Base):
    """Bitácora de descuentos aplicados manualmente a un cargo (Ingresos y Descuentos
    → Aplicar Descuento / Control de Descuentos). Independiente del descuento por
    pronto pago, que se calcula solo al momento del pago."""
    __tablename__ = "descuentos_aplicados"

    id = Column(Integer, primary_key=True, index=True)
    cargo_id = Column(Integer, ForeignKey("cargos.id", ondelete="CASCADE"), nullable=False)
    tipo = Column(Enum(TipoRecargo), nullable=False)  # reutiliza FIJO/PORCENTAJE
    valor = Column(Numeric(12, 2), nullable=False)
    monto_descontado = Column(Numeric(12, 2), nullable=False)
    motivo = Column(String(255), nullable=False)
    aplicado_por_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    cargo = relationship("Cargo")
    aplicado_por = relationship("User")


# ── Cuentas por Pagar (proveedores) ─────────────────────────────────────────

class EstadoCuentaPorPagar(str, enum.Enum):
    PENDIENTE = "PENDIENTE"
    PROGRAMADA = "PROGRAMADA"  # tiene al menos un pago futuro agendado
    PARCIAL = "PARCIAL"
    PAGADA = "PAGADA"
    VENCIDA = "VENCIDA"


class EstadoPagoProveedor(str, enum.Enum):
    PROGRAMADO = "PROGRAMADO"
    PAGADO = "PAGADO"
    CANCELADO = "CANCELADO"


class CuentaPorPagar(Base):
    """Factura o pasivo pendiente con un proveedor a crédito (Cuentas por Pagar →
    Capturar / Control / Reporte / Antigüedad de Compras). Distinta de Egreso: un
    Egreso es una salida de dinero inmediata; una CuentaPorPagar es un compromiso
    que se liquida (total o parcialmente) más adelante con uno o varios PagoProveedor."""
    __tablename__ = "cuentas_por_pagar"

    id = Column(Integer, primary_key=True, index=True)
    condominio_id = Column(Integer, ForeignKey("condominios.id", ondelete="CASCADE"), nullable=False)
    proveedor_id = Column(Integer, ForeignKey("proveedores.id", ondelete="CASCADE"), nullable=False)
    partida_id = Column(Integer, ForeignKey("partidas_presupuestales.id", ondelete="SET NULL"), nullable=True)
    folio_factura = Column(String(80), nullable=True)
    concepto = Column(String(255), nullable=False)
    monto = Column(Numeric(12, 2), nullable=False)
    fecha_factura = Column(Date, nullable=False)
    fecha_vencimiento = Column(Date, nullable=False)  # plazo de crédito del proveedor
    estado = Column(Enum(EstadoCuentaPorPagar), default=EstadoCuentaPorPagar.PENDIENTE, nullable=False)
    comprobante_path = Column(String(500), nullable=True)
    notas = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    proveedor = relationship("Proveedor")
    partida = relationship("PartidaPresupuestal")
    pagos = relationship("PagoProveedor", back_populates="cuenta", cascade="all, delete-orphan")

    @property
    def monto_pagado(self):
        return sum((p.monto for p in self.pagos if p.estado == EstadoPagoProveedor.PAGADO), start=Decimal("0"))

    @property
    def saldo(self):
        return self.monto - self.monto_pagado


class PagoProveedor(Base):
    """Pago (o programación de pago futuro) contra una CuentaPorPagar."""
    __tablename__ = "pagos_proveedores"

    id = Column(Integer, primary_key=True, index=True)
    cuenta_id = Column(Integer, ForeignKey("cuentas_por_pagar.id", ondelete="CASCADE"), nullable=False)
    monto = Column(Numeric(12, 2), nullable=False)
    fecha_programada = Column(Date, nullable=False)
    fecha_pagada = Column(Date, nullable=True)
    cuenta_bancaria_id = Column(Integer, ForeignKey("cuentas_bancarias.id", ondelete="SET NULL"), nullable=True)
    estado = Column(Enum(EstadoPagoProveedor), default=EstadoPagoProveedor.PROGRAMADO, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    cuenta = relationship("CuentaPorPagar", back_populates="pagos")
    cuenta_bancaria = relationship("CuentaBancaria")


# ── Importación / escaneo de estados de cuenta bancarios ────────────────────

class EstadoImportacion(str, enum.Enum):
    BORRADOR = "BORRADOR"    # subida y leída, en revisión manual
    APLICADA = "APLICADA"    # ya se generaron los pagos a las unidades


class ImportacionBancaria(Base):
    """Un estado de cuenta bancario subido en PDF y leído por el sistema. Sus
    renglones (MovimientoImportado) se revisan/corrigen y luego se convierten en
    pagos aplicados a cada unidad."""
    __tablename__ = "importaciones_bancarias"

    id = Column(Integer, primary_key=True, index=True)
    condominio_id = Column(Integer, ForeignKey("condominios.id", ondelete="CASCADE"), nullable=False)
    cuenta_bancaria_id = Column(Integer, ForeignKey("cuentas_bancarias.id", ondelete="SET NULL"), nullable=True)
    nombre_archivo = Column(String(255), nullable=False)
    estado = Column(Enum(EstadoImportacion), default=EstadoImportacion.BORRADOR, nullable=False)
    total_movimientos = Column(Integer, default=0)
    texto_crudo = Column(Text, nullable=True)  # para verificar que se leyó bien
    aviso = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    creado_por_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    condominio = relationship("Condominio")
    cuenta_bancaria = relationship("CuentaBancaria")
    movimientos = relationship(
        "MovimientoImportado", back_populates="importacion",
        cascade="all, delete-orphan", order_by="MovimientoImportado.orden",
    )

    @property
    def total_abonos(self):
        return sum((m.monto for m in self.movimientos if m.tipo == TipoMovimiento.ABONO), start=Decimal("0"))

    @property
    def total_aplicados(self):
        return sum(1 for m in self.movimientos if m.pago_id)


class MovimientoImportado(Base):
    """Un renglón leído del estado de cuenta. Para los ABONOS, `unidad_id` indica
    a qué departamento se abonará (sugerido por el sistema, confirmado por el
    usuario) y `pago_id` queda ligado cuando la importación se aplica."""
    __tablename__ = "movimientos_importados"

    id = Column(Integer, primary_key=True, index=True)
    importacion_id = Column(Integer, ForeignKey("importaciones_bancarias.id", ondelete="CASCADE"), nullable=False)
    orden = Column(Integer, default=0)
    fecha = Column(Date, nullable=False)
    descripcion = Column(String(255), nullable=True)
    monto = Column(Numeric(12, 2), nullable=False)
    tipo = Column(Enum(TipoMovimiento), default=TipoMovimiento.ABONO, nullable=False)
    saldo = Column(Numeric(12, 2), nullable=True)
    unidad_id = Column(Integer, ForeignKey("unidades.id", ondelete="SET NULL"), nullable=True)
    confianza = Column(String(20), default="ninguno")  # referencia | monto | manual | ninguno
    aplicar = Column(Boolean, default=True)  # incluir este renglón al aplicar pagos
    pago_id = Column(Integer, ForeignKey("pagos.id", ondelete="SET NULL"), nullable=True)

    importacion = relationship("ImportacionBancaria", back_populates="movimientos")
    unidad = relationship("Unidad")
