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

# Nombres reales de variable de entorno (`RENT_*`) que alimentan las
# constantes de arriba. `config.requerido()` (usado por
# `CostoVigenteProvider`/`IvaProvider`/`ingesta_tactica.py` para conectar
# SQL en vivo) lee `os.environ` directo, no el atributo ya resuelto del
# módulo — así que pisar solo `config.TACTICA_SQL_SERVER` etc. (abajo) no
# alcanza para bloquear una conexión real si `backend/.env` tiene
# credenciales reales cargadas (como pasó 2026-08-14, al conectar Táctica
# por primera vez). Hay que limpiar las dos cosas.
_ENV_VARS_RENT = [
    "RENT_SHEET_GLOBAL_ID", "RENT_SHEET_CATEGORIAS_ID", "RENT_SHEET_BASE_GENERAL_ID",
    "RENT_SHEET_MARGEN_VERONICA_ID", "RENT_SHEET_MARGEN_MATIAS_ID", "RENT_SHEET_MARGEN_CRISTIAN_ID",
    "RENT_SHEET_MASTER_COMPRAS_ML_ID", "RENT_SHEET_VINCULACION_ID",
    "RENT_TACTICA_SQL_SERVER", "RENT_TACTICA_SQL_DATABASE", "RENT_TACTICA_SQL_USER", "RENT_TACTICA_SQL_PASSWORD",
]


@pytest.fixture(autouse=True)
def _sin_variables_de_entorno_rent(monkeypatch):
    """`config.py` resuelve estas constantes una sola vez, al importarse
    (incluye `load_dotenv()`) — limpiar `os.environ` en un fixture por-test
    no alcanza para ESE caso, porque para entonces el módulo ya quedó con
    el valor real de un `backend/.env` local. Hay que pisar el atributo del
    módulo directamente para que la suite no dependa de la máquina donde
    corre.

    Pero `config.requerido()` (a diferencia de las constantes ya resueltas)
    lee `os.environ` en el momento, no un atributo cacheado — lo usan
    `CostoVigenteProvider`/`IvaProvider`/`ingesta_tactica.py` para la
    conexión SQL real. Si `backend/.env` tiene credenciales reales (caso
    real desde que se conectó Táctica, 2026-08-14), pisar solo el atributo
    del módulo NO alcanza: `requerido()` seguiría encontrando la variable
    real en `os.environ` y un test podría disparar una conexión real sin
    querer. Por eso también se limpian las variables de entorno mismas."""
    for nombre in _CONFIG_DE_ENTORNO:
        monkeypatch.setattr(config, nombre, None)
    for nombre in _ENV_VARS_RENT:
        monkeypatch.delenv(nombre, raising=False)


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
