"""Engine y sesión de SQLAlchemy para el motor de Rentabilidad.

Persistencia: PostgreSQL en Railway (ver config.DATABASE_URL). Todo importe
monetario se modela con Numeric — nunca float (prohibición técnica #2 de
RENTABILIDAD_IMPLEMENTACION.md).
"""
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from . import config


class Base(DeclarativeBase):
    pass


def crear_engine(database_url: str | None = None):
    url = database_url or config.DATABASE_URL
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args, future=True)


engine = crear_engine()
SessionLocal = sessionmaker(bind=engine, future=True, expire_on_commit=False)


@contextmanager
def sesion():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
