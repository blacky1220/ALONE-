"""Puntos de integración para pagos en línea y facturación CFDI.

Hoy no hay ninguna pasarela de pago ni PAC (proveedor autorizado de
certificación) conectados: los pagos se registran manualmente y las
facturas quedan en estado PENDIENTE. Para conectar un proveedor real
(Stripe, Conekta, Mercado Pago, un PAC del SAT, etc.) implementa una
subclase de estas interfaces y reemplaza `gateway`/`cfdi_provider` abajo.
"""

from abc import ABC, abstractmethod


class PaymentGatewayAdapter(ABC):
    @abstractmethod
    def crear_intento_pago(self, cargo, monto: float) -> dict:
        ...


class ManualGatewayAdapter(PaymentGatewayAdapter):
    """No hay pasarela conectada: el pago debe registrarse manualmente por un administrador."""

    def crear_intento_pago(self, cargo, monto: float) -> dict:
        raise NotImplementedError(
            "No hay una pasarela de pago en línea configurada. "
            "Registra el pago manualmente desde el estado de cuenta de la unidad."
        )


class CFDIProvider(ABC):
    @abstractmethod
    def timbrar(self, factura) -> dict:
        ...


class NullCFDIProvider(CFDIProvider):
    """No hay PAC configurado: la factura queda pendiente de timbrado."""

    def timbrar(self, factura) -> dict:
        raise NotImplementedError(
            "No hay un proveedor de timbrado CFDI (PAC) configurado todavía."
        )


gateway: PaymentGatewayAdapter = ManualGatewayAdapter()
cfdi_provider: CFDIProvider = NullCFDIProvider()
