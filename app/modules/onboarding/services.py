import csv
import io
import secrets
from datetime import datetime, timedelta, timezone

import openpyxl
from sqlalchemy.orm import Session

from app.modules.onboarding.models import EstadoPaso, OnboardingProgreso, PasoOnboarding

PASO_LABELS = {
    PasoOnboarding.PRESUPUESTO: ("Crea tu presupuesto", "Partidas de ingresos y egresos proyectados."),
    PasoOnboarding.BANCOS: ("Configura cuentas de banco", "Catálogo de cuentas bancarias y cajas chicas."),
    PasoOnboarding.ADEUDOS_INICIALES: ("Captura los adeudos iniciales", "Cartera vencida previa a la migración."),
    PasoOnboarding.SALDOS_FAVOR: ("Captura los saldos a favor", "Pagos anticipados y billetera virtual por unidad."),
    PasoOnboarding.CUOTAS: ("Captura las cuotas condominales", "Reglas de cobro, descuentos y recargos."),
    PasoOnboarding.INGRESOS: ("Captura tus ingresos del mes", "Cobros, multas, amenidades y tags vehiculares."),
    PasoOnboarding.EGRESOS: ("Captura los egresos", "Salidas de dinero con proveedor y comprobante."),
    PasoOnboarding.INVITACIONES: ("Invita a residentes", "Enrolamiento con enlace mágico de activación."),
}


# ── Progreso del checklist ───────────────────────────────────────────────────

def get_progreso(db: Session, condominio_id: int) -> dict[PasoOnboarding, OnboardingProgreso]:
    rows = db.query(OnboardingProgreso).filter(OnboardingProgreso.condominio_id == condominio_id).all()
    return {r.paso: r for r in rows}


def checklist(db: Session, condominio_id: int) -> list[dict]:
    progreso = get_progreso(db, condominio_id)
    items = []
    for paso in PasoOnboarding:
        row = progreso.get(paso)
        estado = row.estado if row else EstadoPaso.PENDIENTE
        titulo, descripcion = PASO_LABELS[paso]
        items.append({"paso": paso.value, "titulo": titulo, "descripcion": descripcion, "estado": estado.value})
    return items


def _get_or_create(db: Session, condominio_id: int, paso: PasoOnboarding) -> OnboardingProgreso:
    row = (
        db.query(OnboardingProgreso)
        .filter(OnboardingProgreso.condominio_id == condominio_id, OnboardingProgreso.paso == paso)
        .first()
    )
    if not row:
        row = OnboardingProgreso(condominio_id=condominio_id, paso=paso, estado=EstadoPaso.PENDIENTE)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def marcar_visitado(db: Session, condominio_id: int, paso: PasoOnboarding) -> None:
    """Sube de PENDIENTE a EN_PROGRESO la primera vez que el admin abre el paso."""
    row = _get_or_create(db, condominio_id, paso)
    if row.estado == EstadoPaso.PENDIENTE:
        row.estado = EstadoPaso.EN_PROGRESO
        db.commit()


def marcar_completado(db: Session, condominio_id: int, paso: PasoOnboarding) -> None:
    row = _get_or_create(db, condominio_id, paso)
    if row.estado != EstadoPaso.COMPLETADO:
        row.estado = EstadoPaso.COMPLETADO
        db.commit()


def establecer_estado(db: Session, condominio_id: int, paso: PasoOnboarding, estado: EstadoPaso) -> None:
    row = _get_or_create(db, condominio_id, paso)
    row.estado = estado
    db.commit()


# ── Enlaces mágicos de invitación ────────────────────────────────────────────

def generar_token() -> str:
    return secrets.token_urlsafe(24)


def token_expira_en(dias: int = 7) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=dias)


# ── Importación CSV / Excel ──────────────────────────────────────────────────

def parse_tabular_upload(filename: str, content: bytes) -> list[dict]:
    """Lee un archivo .csv o .xlsx y devuelve una lista de dicts (encabezado -> valor)."""
    if filename.lower().endswith(".xlsx"):
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        headers = [str(h).strip() if h is not None else "" for h in rows[0]]
        return [
            {headers[i]: row[i] for i in range(len(headers)) if i < len(row)}
            for row in rows[1:]
            if any(v is not None for v in row)
        ]

    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]
