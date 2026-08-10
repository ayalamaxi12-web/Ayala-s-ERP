"""Wiring HTTP del motor de Rentabilidad hacia el ERP — expone
`RentabilidadTacticaCalculator` (RENTABILIDAD_FUNCIONAL.md §6) para que la
pantalla "Rentabilidad Táctica" de `docs/index.html` deje de calcular en
JavaScript y use el motor ya probado.

No agrega reglas de negocio: traduce filas del CSV que hoy sube el operador
a `LineaTacticaInput` y devuelve `ResultadoTactica` tal cual lo calcula el
motor. No persiste nada en `venta_tactica` — esa es una etapa separada
(persistencia, Etapa 9/10 de RENTABILIDAD_IMPLEMENTACION.md §9), no
construida todavía a propósito.
"""
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import gsheets, seed
from .adapters import CostoVigenteProvider, IvaProvider
from .calculators import LineaTacticaInput, RentabilidadTacticaCalculator
from .config import ConfiguracionFaltante
from .db import sesion
from .models import Regimen

router = APIRouter(prefix="/rentabilidad", tags=["rentabilidad"])

RENTABILIDAD_DIR = Path(__file__).resolve().parent

# §6.1 del funcional: la tabla que empareja la descripción textual del
# comprobante (lo que trae la columna "Tipo de Factura" del export de
# Táctica) con el código corto que espera `resolver_regimen` — ambos nombran
# la misma columna I, el código ya viene embebido como palabra suelta dentro
# del texto descriptivo. No es una regla nueva, es la tabla §6.1 usada para
# traducir formato, igual que `_tipo_factura()` en ingesta_tactica.py hace
# desde CAE en vez de desde texto.
_CODIGOS_COMPROBANTE = ("FEA", "FEB", "FEE", "FAE", "CEA", "CEB", "CEE", "CVE", "CVA", "CVB", "MLA")
_RE_COMPROBANTE = re.compile(r"\b(" + "|".join(_CODIGOS_COMPROBANTE) + r")\b")


def extraer_comprobante(texto_tipo_factura: str) -> str:
    m = _RE_COMPROBANTE.search((texto_tipo_factura or "").upper())
    return m.group(1) if m else (texto_tipo_factura or "").strip()


def migrar_y_sembrar() -> None:
    """Crea el esquema (Alembic, fuente de verdad — no `create_all`) y siembra
    las tablas paramétricas. Idempotente: seguro de llamar en cada arranque."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(RENTABILIDAD_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(RENTABILIDAD_DIR / "migrations"))
    command.upgrade(cfg, "head")
    with sesion() as db:
        seed.seed(db)


def _fetch_fn_con_cache():
    """Una sola lectura de red por (sheet_id, tab) para todo el request — sin
    esto, `CostoVigenteProvider`/`IvaProvider` releerían la hoja completa por
    cada línea del CSV (una línea de rentabilidad por SKU, no por request)."""
    cache: dict[tuple[str, str], list[list[str]]] = {}

    def fetch(spreadsheet_id: str, tab: str) -> list[list[str]]:
        clave = (spreadsheet_id, tab)
        if clave not in cache:
            cache[clave] = gsheets.leer_valores(spreadsheet_id, tab)
        return cache[clave]

    return fetch


class LineaTacticaIn(BaseModel):
    codigo: str
    tipo_factura: str  # texto crudo de la columna "Tipo de Factura" del CSV
    nro_factura: str
    cantidad: str
    precio_venta: str
    tc: str


class ResultadoTacticaOut(BaseModel):
    codigo: str
    nro_factura: str
    regimen: str
    costo_lista: Decimal | None = None
    iva_producto: Decimal | None = None
    iva: Decimal | None = None
    imp_cheque: Decimal | None = None
    iibb: Decimal | None = None
    costo_total_pesos: Decimal | None = None
    costo_financiero_1: Decimal | None = None
    costo_financiero_2: Decimal | None = None
    margen_real: Decimal | None = None
    margen_pct: Decimal | None = None
    precio_venta_iva: Decimal | None = None
    incidencia: str | None = None


class CalcularTacticaIn(BaseModel):
    lineas: list[LineaTacticaIn]


class CalcularTacticaOut(BaseModel):
    resultados: list[ResultadoTacticaOut]


def _decimal(v: str, campo: str, codigo: str) -> Decimal:
    try:
        return Decimal(v)
    except InvalidOperation:
        raise HTTPException(422, f"Valor no numérico en '{campo}' (SKU {codigo!r}): {v!r}")


def calcular_lineas(
    lineas: list[LineaTacticaIn],
    db: Session,
    costo_provider: CostoVigenteProvider,
    iva_provider: IvaProvider,
) -> list[ResultadoTacticaOut]:
    """Lógica pura del endpoint, sin FastAPI/HTTP de por medio — así se
    testea igual que el resto de `rentabilidad/` (proveedores inyectados,
    sin red ni credenciales reales, ver test_adapters.py)."""
    calculador = RentabilidadTacticaCalculator(db, costo_provider, iva_provider)
    resultados: list[ResultadoTacticaOut] = []
    for linea in lineas:
        comprobante = extraer_comprobante(linea.tipo_factura)
        try:
            r = calculador.calcular(LineaTacticaInput(
                codigo=linea.codigo,
                tipo_factura=comprobante,
                nro_factura=linea.nro_factura,
                cantidad=_decimal(linea.cantidad, "cantidad", linea.codigo),
                precio_venta=_decimal(linea.precio_venta, "precio_venta", linea.codigo),
                tc=_decimal(linea.tc, "tc", linea.codigo),
            ))
            resultados.append(ResultadoTacticaOut(
                codigo=linea.codigo, nro_factura=linea.nro_factura,
                regimen=r.regimen.value, costo_lista=r.costo_lista,
                iva_producto=r.iva_producto, iva=r.iva, imp_cheque=r.imp_cheque,
                iibb=r.iibb, costo_total_pesos=r.costo_total_pesos,
                costo_financiero_1=r.costo_financiero_1, costo_financiero_2=r.costo_financiero_2,
                margen_real=r.margen_real, margen_pct=r.margen_pct,
                precio_venta_iva=r.precio_venta_iva, incidencia=r.incidencia,
            ))
        except ConfiguracionFaltante as e:
            resultados.append(ResultadoTacticaOut(
                codigo=linea.codigo, nro_factura=linea.nro_factura,
                regimen=Regimen.NO_RECONOCIDO.value, incidencia=f"CONFIG_FALTANTE: {e}",
            ))
    return resultados


@router.post("/tactica/calcular", response_model=CalcularTacticaOut)
def calcular_tactica(payload: CalcularTacticaIn) -> CalcularTacticaOut:
    fetch = _fetch_fn_con_cache()
    costo_provider = CostoVigenteProvider(fetch_fn=fetch)
    iva_provider = IvaProvider(fetch_fn=fetch)
    with sesion() as db:
        resultados = calcular_lineas(payload.lineas, db, costo_provider, iva_provider)
    return CalcularTacticaOut(resultados=resultados)
