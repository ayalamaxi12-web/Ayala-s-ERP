"""Configuración centralizada del motor de Rentabilidad.

Ninguna credencial ni identificador de fuente externa se hardcodea aquí ni en
ningún otro módulo de `rentabilidad/` — todo se resuelve por variable de
entorno. Ver RENTABILIDAD_IMPLEMENTACION.md para la lista de fuentes.
"""
import os


class ConfiguracionFaltante(RuntimeError):
    """Se pidió un valor de configuración que no fue provisto por variable de entorno."""


def _env(nombre: str, default: str | None = None) -> str | None:
    return os.environ.get(nombre, default)


def requerido(nombre: str) -> str:
    """Como `_env`, pero falla explícitamente si falta — para usar en adaptadores
    que no pueden operar sin la fuente configurada (§2.2 RENTABILIDAD_IMPLEMENTACION.md).
    """
    valor = _env(nombre)
    if not valor:
        raise ConfiguracionFaltante(
            f"Falta la variable de entorno '{nombre}'. Configurala para habilitar esta fuente."
        )
    return valor


# ── Persistencia ──
# Producción: Postgres en Railway (RENT_DATABASE_URL apuntando al addon).
# Sin configurar: SQLite local, solo para desarrollo y para correr la suite de tests.
DATABASE_URL = _env("RENT_DATABASE_URL", "sqlite:///" + os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "_dev.sqlite3"
))

# ── Fuentes externas de solo lectura (§2.1 RENTABILIDAD_IMPLEMENTACION.md) ──
# Ningún ID hardcodeado: se completan por variable de entorno. Mientras falten,
# los adaptadores correspondientes levantan ConfiguracionFaltante al usarse —
# no bloquea el resto del desarrollo (implementados igual, sin datos reales).

# `Global` + `Importacion Tactica` viven en el mismo libro (§2.1).
SHEET_GLOBAL_ID = _env("RENT_SHEET_GLOBAL_ID")
TAB_GLOBAL = "Global"
TAB_IMPORTACION_TACTICA = "Importacion Tactica"

# GRAL CATEGORIAS — mismo concepto que CATS_ID en docs/index.html, pero este
# módulo no reutiliza esa constante del frontend: se configura de forma
# independiente para el backend.
SHEET_CATEGORIAS_ID = _env("RENT_SHEET_CATEGORIAS_ID")
TAB_CATEGORIAS = "GRAL CATEGORIAS"

SHEET_BASE_GENERAL_ID = _env("RENT_SHEET_BASE_GENERAL_ID")

# Márgenes objetivo L3/L4/L5 por PM — cascada Verónica → Matías → Cristian (§9, §8.1)
SHEET_MARGEN_VERONICA_ID = _env("RENT_SHEET_MARGEN_VERONICA_ID")
SHEET_MARGEN_MATIAS_ID = _env("RENT_SHEET_MARGEN_MATIAS_ID")
SHEET_MARGEN_CRISTIAN_ID = _env("RENT_SHEET_MARGEN_CRISTIAN_ID")

# Rentabilidad esperada por el PM (ECOM AU)
SHEET_MASTER_COMPRAS_ML_ID = _env("RENT_SHEET_MASTER_COMPRAS_ML_ID")

# Vinculación de órdenes ECOM (AN), hoja "hOJA 1"
SHEET_VINCULACION_ID = _env("RENT_SHEET_VINCULACION_ID")
TAB_VINCULACION = "hOJA 1"
