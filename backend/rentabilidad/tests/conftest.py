from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from rentabilidad import seed
from rentabilidad.db import Base


@pytest.fixture()
def db_session():
    """Sesión aislada en SQLite en memoria, con el esquema completo creado
    directamente desde los modelos (no vía Alembic — la paridad de la
    migración se verifica aparte en test_migrations.py) y las tablas
    paramétricas ya seedeadas.
    """
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    session = Session()
    seed.seed(session)
    session.commit()
    try:
        yield session
    finally:
        session.close()


def d(valor: str) -> Decimal:
    """Atajo para literales Decimal exactos en los tests (nunca float)."""
    return Decimal(valor)
