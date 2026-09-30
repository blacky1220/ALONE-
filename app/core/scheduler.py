"""Worker en segundo plano: genera automáticamente los cargos de las emisiones
recurrentes (mensual/bimestral/anual) cuando llega su día de generación.

Usa APScheduler en proceso (BackgroundScheduler) — suficiente para un despliegue de
un solo servidor como este. Si el sistema crece a varias instancias, este job debe
moverse a un worker dedicado (Celery beat, RQ scheduler, etc.) para no duplicar la
emisión al correr en cada réplica."""

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.database import SessionLocal

logger = logging.getLogger("scheduler")

_scheduler: BackgroundScheduler | None = None


def _job_generar_cargos_recurrentes() -> None:
    from app.modules.finanzas.services import procesar_recurrencias_pendientes

    db = SessionLocal()
    try:
        procesados = procesar_recurrencias_pendientes(db)
        if procesados:
            logger.info("Cargos recurrentes generados para %d emisión(es).", len(procesados))
    except Exception:
        logger.exception("Error generando cargos recurrentes")
    finally:
        db.close()


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    _scheduler = BackgroundScheduler(timezone="America/Mexico_City")
    _scheduler.add_job(
        _job_generar_cargos_recurrentes,
        trigger="cron", hour=1, minute=0,
        id="generar_cargos_recurrentes", replace_existing=True,
    )
    _scheduler.start()
    logger.info("Scheduler iniciado: cargos recurrentes se revisan diario a la 01:00.")
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
