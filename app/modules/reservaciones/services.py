from sqlalchemy.orm import Session

from app.modules.reservaciones.models import EstadoReservacion, Reservacion


def hay_traslape(db: Session, amenidad_id: int, fecha, hora_inicio, hora_fin, excluir_id: int | None = None) -> bool:
    query = db.query(Reservacion).filter(
        Reservacion.amenidad_id == amenidad_id,
        Reservacion.fecha == fecha,
        Reservacion.estado == EstadoReservacion.CONFIRMADA,
        Reservacion.hora_inicio < hora_fin,
        Reservacion.hora_fin > hora_inicio,
    )
    if excluir_id:
        query = query.filter(Reservacion.id != excluir_id)
    return db.query(query.exists()).scalar()
