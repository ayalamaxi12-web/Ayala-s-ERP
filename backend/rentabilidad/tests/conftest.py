from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from rentabilidad import config, seed
from rentabilidad.db import Base

# Todas las constantes de `config.py` derivadas de una variable de entorno
# `RENT_*` (salvo DATABASE_URL, que sí debe seguir resolviendo a un sqlite
# de test si algo la usa). Lista explícita en vez de iterar el módulo: más
# fácil de mantener en sync con config.py a la vista.
_CONFIG_DE_ENTORNO = [
    "SHEET_GLOBAL_ID", "SHEET_CATEGORIAS_ID", "SHEET_BASE_GENERAL_ID",
    "SHEET_MARGEN_VERONICA_ID", "SHEET_MARGEN_MATIAS_ID", "SHEET_MARGEN_CRISTIAN_ID",
    "SHEET_MASTER_COMPRAS_ML_ID", "SHEET_VINCULACION_ID",
    "TACTICA_SQL_SERVER", "TACTICA_SQL_DATABASE", "TACTICA_SQL_USER", "TACTICA_SQL_PASSWORD",
]


@pytest.fixture(autouse=True)
def _sin_variables_de_entorno_rent(monkeypatch):
    """`config.py` resuelve estas constantes una sola vez, al importarse
    (incluye `load_dotenv()`) — limpiar `os.environ` en un fixture por-test
    no alcanza, porque para entonces el módulo ya quedó con el valor real
    de un `backend/.env` local. Hay que pisar el atributo del módulo
    directamente para que la suite no dependa de la máquina donde corre."""
    for nombre in _CONFIG_DE_ENTORNO:
        monkeypatch.setattr(config, nombre, None)


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
