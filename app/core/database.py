from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.core.config import settings

# 1. Crear el motor de conexión usando directamente DATABASE_URL
#    pool_pre_ping: Supabase cierra las conexiones ociosas del pool. Sin esto, la
#    primera petición después de un rato inactivo revienta con
#    "server closed the connection unexpectedly" y devuelve un 500 al usuario.
#    Con pre_ping SQLAlchemy valida la conexión y la reabre de forma transparente.
#    pool_recycle: recicla conexiones antes de que el pooler las corte por su cuenta.
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=1800,
)

# 2. Configurar la fábrica de sesiones
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 3. Base para nuestros modelos de base de datos
Base = declarative_base()

# 4. Dependencia para inyectar la sesión en las rutas
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()