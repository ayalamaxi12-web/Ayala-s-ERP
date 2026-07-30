"""Verifica que la migración Alembic (no `create_all`) deja el esquema
completo — la fuente de verdad del esquema en producción es Alembic."""
import os
import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

RENTABILIDAD_DIR = Path(__file__).resolve().parents[1]

TABLAS_ESPERADAS = {
    "venta_tactica",
    "venta_ecom",
    "parametro_tasa",
    "prefijo_perdida_definitiva",
    "regimen_comprobante",
    "sku_excluido",
    "sku_auxiliar",
}


def test_alembic_upgrade_head_crea_todas_las_tablas():
    # ignore_cleanup_errors: en Windows, SQLite puede mantener el archivo
    # tomado un instante después de cerrar la conexión; no es parte de lo que
    # este test verifica (que la migración corre y crea el esquema).
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = os.path.join(tmp, "migracion_test.sqlite3")
        db_url = f"sqlite:///{db_path}"

        cfg = Config(str(RENTABILIDAD_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(RENTABILIDAD_DIR / "migrations"))
        cfg.set_main_option("sqlalchemy.url", db_url)

        command.upgrade(cfg, "head")

        engine = create_engine(db_url, future=True)
        try:
            tablas = set(inspect(engine).get_table_names())
            assert TABLAS_ESPERADAS <= tablas
        finally:
            engine.dispose()
