"""Arquitectura de navegación del panel lateral (Sidebar) del módulo contable/operativo.

Este archivo es la fuente única de verdad para dos entregables:

1. FINANCE_PERMISSIONS — matriz de permisos por rol para cada opción del menú
   (equivalente a lo pedido: "Matriz de permisos por rol para cada opción del
   menú"). Se consume tanto para ocultar entradas del menú como para proteger
   las rutas reales (ver app/core/dependencies.py: require_finance_read /
   require_finance_write).

2. NAV_CONFIG — árbol de datos para renderizar el menú lateral colapsable de
   forma dinámica (equivalente al "navigationConfig" pedido). Cada hoja trae
   su ruta, ícono, badge opcional y los roles que la ven — el sidebar
   (app/templates/_sidebar_finanzas.html) solo itera esta estructura, no
   tiene lógica de negocio propia.

Roles: SUPER_ADMIN (SUPERADMIN, ADMIN_CONDOMINIO en este proyecto), ACCOUNTANT
(CONTADOR) y AUDITOR — ver app/core/rbac.py para la definición y para los
roles operativos no financieros (Guardia, Propietario, Residente, Inquilino).
"""

from app.core.rbac import FINANCE_READ_ROLES, FINANCE_WRITE_ROLES

# ── 1. Matriz de permisos por ruta ──────────────────────────────────────────
# clave -> conjunto de roles autorizados. FINANCE_WRITE_ROLES = SUPER_ADMIN +
# ACCOUNTANT (capturar/editar/generar/aplicar). FINANCE_READ_ROLES = los
# anteriores + AUDITOR (solo consulta: reportes, bitácoras, comprobantes).
FINANCE_PERMISSIONS: dict[str, set[str]] = {
    # 1. Ingresos y Descuentos
    "ingresos.capturar": FINANCE_WRITE_ROLES,
    "ingresos.estados_cuenta": FINANCE_WRITE_ROLES,
    "ingresos.control": FINANCE_READ_ROLES,
    "ingresos.conciliacion": FINANCE_READ_ROLES,
    "ingresos.reporte": FINANCE_READ_ROLES,
    "ingresos.comprobantes": FINANCE_READ_ROLES,
    "ingresos.aplicar_descuento": FINANCE_WRITE_ROLES,
    "ingresos.control_descuentos": FINANCE_READ_ROLES,
    # 2. Cuotas y Adeudos
    "cuotas.generar": FINANCE_WRITE_ROLES,
    "cuotas.recurrentes": FINANCE_READ_ROLES,  # pausar/reanudar dentro de la página exige write
    "cuotas.editar": FINANCE_WRITE_ROLES,
    "cuotas.cobranza": FINANCE_READ_ROLES,
    "cuotas.recargos": FINANCE_WRITE_ROLES,
    "cuotas.estado_cuenta_lote": FINANCE_WRITE_ROLES,
    "cuotas.config": FINANCE_WRITE_ROLES,
    # 3. Egresos
    "egresos.capturar": FINANCE_WRITE_ROLES,
    "egresos.control": FINANCE_READ_ROLES,
    "egresos.reporte": FINANCE_READ_ROLES,
    # 4. Cuentas por Pagar (Proveedores)
    "cxp.capturar": FINANCE_WRITE_ROLES,
    "cxp.control": FINANCE_READ_ROLES,  # programar/pagar dentro de la página exige write
    "cxp.reporte": FINANCE_READ_ROLES,
    "cxp.antiguedad": FINANCE_READ_ROLES,
}


def roles_for(item_key: str) -> set[str]:
    return FINANCE_PERMISSIONS.get(item_key, FINANCE_WRITE_ROLES)


# ── 2. Árbol de navegación (navigationConfig) ───────────────────────────────
# type: "group" (colapsable, sin ruta propia) | "item" (hoja con ruta).
# badge: nombre de una métrica dinámica resuelta en tiempo de request
# (ver app/web/router.py:_sidebar_badges) — None si no aplica.
NAV_CONFIG: list[dict] = [
    {
        "key": "ingresos", "type": "group", "label": "Ingresos y Descuentos", "icon": "",
        "children": [
            {"key": "ingresos.capturar", "type": "item", "label": "Capturar Pagos", "icon": "",
             "route": "/app/ingresos/capturar", "badge": None},
            {"key": "ingresos.estados_cuenta", "type": "item", "label": "Escanear Estado de Cuenta", "icon": "",
             "route": "/app/estados-cuenta", "badge": None},
            {"key": "ingresos.control", "type": "item", "label": "Control de Ingresos", "icon": "",
             "route": "/app/ingresos/control", "badge": None},
            {"key": "ingresos.conciliacion", "type": "item", "label": "Conciliación Bancaria", "icon": "",
             "route": "/finanzas/conciliacion", "badge": None},
            {"key": "ingresos.reporte", "type": "item", "label": "Reporte Detallado", "icon": "",
             "route": "/app/ingresos/reporte", "badge": None},
            {"key": "ingresos.comprobantes", "type": "item", "label": "Comprobantes de Pago", "icon": "",
             "route": "/app/ingresos/comprobantes", "badge": None},
            {"key": "ingresos.aplicar_descuento", "type": "item", "label": "Aplicar Descuento", "icon": "",
             "route": "/app/ingresos/aplicar-descuento", "badge": None},
            {"key": "ingresos.control_descuentos", "type": "item", "label": "Control de Descuentos", "icon": "",
             "route": "/app/ingresos/control-descuentos", "badge": None},
        ],
    },
    {
        "key": "cuotas", "type": "group", "label": "Cuotas y Adeudos", "icon": "",
        "children": [
            {"key": "cuotas.generar", "type": "item", "label": "Generar Cuotas y Adeudos", "icon": "",
             "route": "/finanzas/emisiones/nueva", "badge": None},
            {"key": "cuotas.recurrentes", "type": "item", "label": "Adeudos Recurrentes", "icon": "",
             "route": "/app/cuotas/recurrentes", "badge": None},
            {"key": "cuotas.editar", "type": "item", "label": "Editar Adeudos", "icon": "",
             "route": "/app/cuotas/editar", "badge": None},
            {"key": "cuotas.cobranza", "type": "item", "label": "Control de Cobranza", "icon": "",
             "route": "/app/cuotas/cobranza", "badge": "cartera_vencida"},
            {"key": "cuotas.recargos", "type": "item", "label": "Generar Recargos", "icon": "",
             "route": "/app/cuotas/recargos", "badge": None},
            {"key": "cuotas.estado_cuenta_lote", "type": "item", "label": "Enviar/Imprimir Estado de Cuenta", "icon": "",
             "route": "/app/cuotas/estado-cuenta-lote", "badge": None},
            {"key": "cuotas.config", "type": "item", "label": "Configurar Cuotas", "icon": "",
             "route": "/finanzas/cuotas", "badge": None},
        ],
    },
    {
        "key": "egresos", "type": "group", "label": "Egresos", "icon": "",
        "children": [
            {"key": "egresos.capturar", "type": "item", "label": "Captura de Egresos", "icon": "",
             "route": "/onboarding/egresos", "badge": None},
            {"key": "egresos.control", "type": "item", "label": "Control de Egresos", "icon": "",
             "route": "/onboarding/egresos", "badge": None},
            {"key": "egresos.reporte", "type": "item", "label": "Reporte Detallado", "icon": "",
             "route": "/app/egresos/reporte", "badge": None},
        ],
    },
    {
        "key": "cxp", "type": "group", "label": "Cuentas por Pagar", "icon": "",
        "children": [
            {"key": "cxp.capturar", "type": "item", "label": "Capturar Cuentas por Pagar", "icon": "",
             "route": "/app/cuentas-por-pagar/capturar", "badge": None},
            {"key": "cxp.control", "type": "item", "label": "Control de Cuentas por Pagar", "icon": "",
             "route": "/app/cuentas-por-pagar/control", "badge": None},
            {"key": "cxp.reporte", "type": "item", "label": "Reporte Detallado", "icon": "",
             "route": "/app/cuentas-por-pagar/reporte", "badge": None},
            {"key": "cxp.antiguedad", "type": "item", "label": "Antigüedad de Compras", "icon": "",
             "route": "/app/cuentas-por-pagar/antiguedad", "badge": "cxp_vencidas"},
        ],
    },
]


def visible_nav(role: str | None) -> list[dict]:
    """Filtra NAV_CONFIG a lo que el rol dado puede ver. Un grupo se omite por
    completo si ningún hijo le queda visible."""
    resultado = []
    for group in NAV_CONFIG:
        children = [c for c in group["children"] if role in roles_for(c["key"])]
        if children:
            resultado.append({**group, "children": children})
    return resultado
