import sys
from pathlib import Path

# Asegurar que la raíz del proyecto esté en sys.path al ejecutar directamente `python app/main.py`
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.rbac import backfill_missing_roles, seed_roles
from app.core.scheduler import start_scheduler, stop_scheduler
from app.modules.auth.router import router as auth_router
from app.modules.auth.models import User # Asegúrate de importar tus modelos para que SQLAlchemy los detecte
from app.modules.comunicacion.router import router as comunicacion_router
from app.modules.condominios.router import router as condominios_router
from app.modules.finanzas.router import router as finanzas_router
from app.modules.mantenimiento.router import router as mantenimiento_router
from app.modules.onboarding.router import router as onboarding_router
from app.modules.propietarios.router import router as propietarios_router
from app.modules.reportes.router import router as reportes_router
from app.modules.reservaciones.router import router as reservaciones_router
from app.modules.seguridad.router import router as seguridad_router
from app.web.app_router import router as app_web_router
from app.web.importador_router import router as importador_web_router
from app.web.onboarding_router import router as onboarding_web_router
from app.web.router import router as web_router

# El esquema de la base de datos ahora se gestiona con Alembic (ver ALEMBIC/),
# no con create_all(): corre `alembic upgrade head` para aplicar migraciones.

# Sembrar roles y migrar cuentas creadas antes de que existiera RBAC
try:
    with SessionLocal() as _db:
        seed_roles(_db)
        backfill_missing_roles(_db)
except Exception as _e:
    print(f"[Startup Warning] No se pudo conectar a la base de datos: {_e}")

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Los navegadores piden /favicon.ico aunque el HTML declare <link rel="icon">.
# Servirlo aquí evita un 404 por cada carga de página en los logs.
_FAVICON_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    b'<rect width="32" height="32" rx="7" fill="#2f6f4f"/>'
    b'<path fill="#fff" d="M8 24V11l8-4 8 4v13h-5v-6h-6v6z"/></svg>'
)


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(
        content=_FAVICON_SVG,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


app.include_router(auth_router, prefix=settings.API_V1_STR)
app.include_router(condominios_router, prefix=settings.API_V1_STR)
app.include_router(propietarios_router, prefix=settings.API_V1_STR)
app.include_router(finanzas_router, prefix=settings.API_V1_STR)
app.include_router(reservaciones_router, prefix=settings.API_V1_STR)
app.include_router(seguridad_router, prefix=settings.API_V1_STR)
app.include_router(comunicacion_router, prefix=settings.API_V1_STR)
app.include_router(mantenimiento_router, prefix=settings.API_V1_STR)
app.include_router(onboarding_router, prefix=settings.API_V1_STR)
app.include_router(reportes_router, prefix=settings.API_V1_STR)
app.include_router(onboarding_web_router)
app.include_router(importador_web_router)
app.include_router(app_web_router)
app.include_router(web_router)


@app.on_event("startup")
def _startup_scheduler():
    start_scheduler()


@app.on_event("shutdown")
def _shutdown_scheduler():
    stop_scheduler()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)