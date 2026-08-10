"""Wiring HTTP del motor de Rentabilidad hacia el ERP — expone
`RentabilidadTacticaCalculator` (RENTABILIDAD_FUNCIONAL.md §6) para que la
pantalla "Rentabilidad Táctica" de `docs/index.html` deje de calcular en
JavaScript y use el motor ya probado.

No agrega reglas de negocio: traduce filas del CSV/SQL/Excel a los inputs
del motor y devuelve el resultado tal cual lo calcula.

**Dos familias de endpoints, deliberadamente separadas** (ajuste de
arquitectura pedido por Maxx, 2026-08-10):

- `/tactica/calcular`, `/tactica/periodo` — **consulta**. Calculan y
  devuelven, nunca escriben en `venta_tactica`/`venta_ecom`. Se puede
  llamar todas las veces que haga falta en un día sin dejar rastro en la
  base (`persistencia.construir_filas_*`).
- `/cierres/*` — **cierre**. La única forma de escribir en las tablas de
  hechos; queda registrado en `cierre_rentabilidad` con cuándo se guardó.
"""
import re
import tempfile
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import gsheets, seed
from .adapters import (
    ClasificacionProvider,
    CostoVigenteProvider,
    IvaProvider,
    MargenObjetivoProvider,
    ResponsableProvider,
    StockProvider,
    VinculacionProvider,
)
from .agregaciones import ECOM_DIMENSIONES, TACTICA_DIMENSIONES, agregar_ecom, agregar_tactica
from .calculators import LineaTacticaInput, RentabilidadTacticaCalculator
from .config import ConfiguracionFaltante
from .db import sesion
from .ingesta_ecom import EcomExcelAdapter
from .ingesta_tactica import FilaTactica, TacticaSqlAdapter
from .models import CierreRentabilidad, Regimen, VentaEcom, VentaTactica
from .persistencia import guardar_cierre_ecom, guardar_cierre_tactica, registrar_cierre
from .validador import ValidadorRentabilidad

router = APIRouter(prefix="/rentabilidad", tags=["rentabilidad"])


def _periodo_de_rango(desde: date, hasta: date) -> str:
    """Etiqueta de período para un rango de fechas — reemplaza el nombre de
    hoja mensual ("Junio-Julio") por algo derivable y sin ambigüedad. Es
    metadata de partición, no una regla de negocio (§1.2 IMPLEMENTACION)."""
    return f"{desde.isoformat()}_{hasta.isoformat()}"

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


# ── Período: SQL de Táctica -> adaptador -> motor ──
#
# A diferencia de `calcular_tactica` (arriba), acá no hay texto crudo de
# "Tipo de Factura" que traducir: `FilaTactica.a_linea_input()` (ver
# `ingesta_tactica.py`) ya entrega el código corto de comprobante resuelto
# desde `CAE`, así que no se llama a `extraer_comprobante`.


class CalcularTacticaPeriodoIn(BaseModel):
    desde: date
    hasta: date


class CalcularTacticaPeriodoOut(BaseModel):
    resultados: list[ResultadoTacticaOut]
    total_lineas: int


def calcular_periodo_tactica(
    filas: list[FilaTactica],
    db: Session,
    costo_provider: CostoVigenteProvider,
    iva_provider: IvaProvider,
) -> list[ResultadoTacticaOut]:
    """Misma orquestación que `calcular_lineas`, sobre filas ya traducidas
    por el adaptador SQL en vez de sobre el CSV que sube el operador."""
    calculador = RentabilidadTacticaCalculator(db, costo_provider, iva_provider)
    resultados: list[ResultadoTacticaOut] = []
    for fila in filas:
        try:
            r = calculador.calcular(fila.a_linea_input())
            resultados.append(ResultadoTacticaOut(
                codigo=fila.codigo, nro_factura=fila.nro_factura,
                regimen=r.regimen.value, costo_lista=r.costo_lista,
                iva_producto=r.iva_producto, iva=r.iva, imp_cheque=r.imp_cheque,
                iibb=r.iibb, costo_total_pesos=r.costo_total_pesos,
                costo_financiero_1=r.costo_financiero_1, costo_financiero_2=r.costo_financiero_2,
                margen_real=r.margen_real, margen_pct=r.margen_pct,
                precio_venta_iva=r.precio_venta_iva, incidencia=r.incidencia,
            ))
        except ConfiguracionFaltante as e:
            resultados.append(ResultadoTacticaOut(
                codigo=fila.codigo, nro_factura=fila.nro_factura,
                regimen=Regimen.NO_RECONOCIDO.value, incidencia=f"CONFIG_FALTANTE: {e}",
            ))
    return resultados


@router.post("/tactica/periodo", response_model=CalcularTacticaPeriodoOut)
def calcular_tactica_periodo(payload: CalcularTacticaPeriodoIn) -> CalcularTacticaPeriodoOut:
    """Lee Táctica directo del SQL Server (`TacticaSqlAdapter`, ya
    probado) para el rango dado y corre cada línea por el motor — sin subir
    ningún CSV a mano. No persiste nada, igual que `/tactica/calcular`."""
    if payload.hasta < payload.desde:
        raise HTTPException(422, "'hasta' no puede ser anterior a 'desde'.")
    filas = TacticaSqlAdapter().lineas(payload.desde, payload.hasta)
    fetch = _fetch_fn_con_cache()
    costo_provider = CostoVigenteProvider(fetch_fn=fetch)
    iva_provider = IvaProvider(fetch_fn=fetch)
    with sesion() as db:
        resultados = calcular_periodo_tactica(filas, db, costo_provider, iva_provider)
    return CalcularTacticaPeriodoOut(resultados=resultados, total_lineas=len(resultados))


# ══════════════════════════════════════════════════════════════════════════
# CIERRES — la única vía de escritura en venta_tactica/venta_ecom. Todo lo
# de arriba es consulta; nada de arriba persiste.
# ══════════════════════════════════════════════════════════════════════════

class GuardarCierreIn(BaseModel):
    desde: date
    hasta: date


class GuardarCierreOut(BaseModel):
    periodo: str
    total_lineas: int
    excluidas: int
    config_faltante: list[str]


@router.post("/cierres/tactica", response_model=GuardarCierreOut)
def cerrar_tactica(payload: GuardarCierreIn) -> GuardarCierreOut:
    """Guardar cierre de Táctica: SQL -> motor -> `venta_tactica`, y lo
    registra en `cierre_rentabilidad`. Reemplaza cualquier cierre previo del
    mismo rango (recarga completa del período, ver `persistencia.py`)."""
    if payload.hasta < payload.desde:
        raise HTTPException(422, "'hasta' no puede ser anterior a 'desde'.")
    periodo = _periodo_de_rango(payload.desde, payload.hasta)
    filas = TacticaSqlAdapter().lineas(payload.desde, payload.hasta)
    fetch = _fetch_fn_con_cache()
    with sesion() as db:
        resultado = guardar_cierre_tactica(
            db, periodo, filas,
            CostoVigenteProvider(fetch_fn=fetch), IvaProvider(fetch_fn=fetch),
            ClasificacionProvider(fetch_fn=fetch), ResponsableProvider(fetch_fn=fetch),
            MargenObjetivoProvider(fetch_fn=fetch),
        )
        registrar_cierre(db, periodo, payload.desde, payload.hasta, tactica_guardado=True)
    return GuardarCierreOut(
        periodo=periodo, total_lineas=len(resultado.filas),
        excluidas=sum(1 for f in resultado.filas if f.excluido),
        config_faltante=resultado.config_faltante,
    )


class GuardarCierreEcomOut(GuardarCierreOut):
    excluidas_por_estado_pago: int
    incidencias_costo: int


@router.post("/cierres/ecom/excel", response_model=GuardarCierreEcomOut)
async def cerrar_ecom_excel(
    desde: date = Form(...),
    hasta: date = Form(...),
    tc: str = Form(...),
    archivo: UploadFile = File(...),
) -> GuardarCierreEcomOut:
    """Guardar cierre de Ecom vía Excel (fuente disponible hoy — la API
    todavía tiene campos sin confirmar, ver ingesta_ecom_api.py). Mismo
    `EcomExcelAdapter` ya probado; el día que la API esté lista, cambia el
    adaptador de entrada, no esta capa ni el motor."""
    if hasta < desde:
        raise HTTPException(422, "'hasta' no puede ser anterior a 'desde'.")
    try:
        tc_decimal = Decimal(tc)
    except InvalidOperation:
        raise HTTPException(422, f"TC no numérico: {tc!r}")

    periodo = _periodo_de_rango(desde, hasta)
    contenido = await archivo.read()
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(contenido)
        tmp_path = tmp.name
    try:
        resultado_ingesta = EcomExcelAdapter().procesar(tmp_path, tc_decimal)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    fetch = _fetch_fn_con_cache()
    with sesion() as db:
        resultado = guardar_cierre_ecom(
            db, periodo, resultado_ingesta, IvaProvider(fetch_fn=fetch),
            ClasificacionProvider(fetch_fn=fetch), VinculacionProvider(fetch_fn=fetch),
            StockProvider(fetch_fn=fetch), MargenObjetivoProvider(fetch_fn=fetch),
        )
        registrar_cierre(db, periodo, desde, hasta, ecom_guardado=True, ecom_origen="excel")
    return GuardarCierreEcomOut(
        periodo=periodo, total_lineas=len(resultado.filas),
        excluidas=sum(1 for f in resultado.filas if f.excluido),
        config_faltante=resultado.config_faltante,
        excluidas_por_estado_pago=len(resultado_ingesta.excluidas_por_estado_pago),
        incidencias_costo=len(resultado_ingesta.incidencias_costo),
    )


class CierreOut(BaseModel):
    periodo: str
    desde: date
    hasta: date
    generado_en: str
    tactica_guardado: bool
    ecom_guardado: bool
    ecom_origen: str | None


@router.get("/cierres", response_model=list[CierreOut])
def listar_cierres() -> list[CierreOut]:
    """Históricos de Rentabilidad: qué períodos están guardados. No
    devuelve los datos del cierre — para eso, `/agregaciones/*` e
    `/incidencias` con el mismo `periodo`."""
    with sesion() as db:
        cierres = db.query(CierreRentabilidad).order_by(CierreRentabilidad.desde.desc()).all()
        return [
            CierreOut(
                periodo=c.periodo, desde=c.desde, hasta=c.hasta,
                generado_en=c.generado_en.isoformat(),
                tactica_guardado=c.tactica_guardado, ecom_guardado=c.ecom_guardado,
                ecom_origen=c.ecom_origen,
            )
            for c in cierres
        ]


# ══════════════════════════════════════════════════════════════════════════
# AGREGACIONES E INCIDENCIAS — leen `venta_tactica`/`venta_ecom`, así que
# solo tienen datos para un `periodo` que ya pasó por /cierres/*.
# ══════════════════════════════════════════════════════════════════════════

class FilaAgregadaOut(BaseModel):
    dimension_valor: str | None
    suma_1: Decimal
    suma_2: Decimal
    suma_costo: Decimal
    suma_resultado: Decimal
    pct: Decimal | None
    cantidad_lineas: int


@router.get("/agregaciones/tactica", response_model=list[FilaAgregadaOut])
def agregaciones_tactica(periodo: str, dimension: str, incluir_excluidos: bool = False) -> list[FilaAgregadaOut]:
    if dimension not in TACTICA_DIMENSIONES:
        raise HTTPException(422, f"'dimension' debe ser una de {sorted(TACTICA_DIMENSIONES)}.")
    with sesion() as db:
        filas = agregar_tactica(db, periodo, dimension, incluir_excluidos)
    return [
        FilaAgregadaOut(
            dimension_valor=f.dimension_valor, suma_1=f.suma_precio_venta_iva, suma_2=f.suma_precio_venta,
            suma_costo=f.suma_costo_total_pesos, suma_resultado=f.suma_margen_real,
            pct=f.pct, cantidad_lineas=f.cantidad_lineas,
        )
        for f in filas
    ]


@router.get("/agregaciones/ecom", response_model=list[FilaAgregadaOut])
def agregaciones_ecom(periodo: str, dimension: str, incluir_excluidos: bool = False) -> list[FilaAgregadaOut]:
    if dimension not in ECOM_DIMENSIONES:
        raise HTTPException(422, f"'dimension' debe ser una de {sorted(ECOM_DIMENSIONES)}.")
    with sesion() as db:
        filas = agregar_ecom(db, periodo, dimension, incluir_excluidos)
    return [
        FilaAgregadaOut(
            dimension_valor=f.dimension_valor, suma_1=f.suma_precio_final, suma_2=f.suma_precio_sin_iva,
            suma_costo=f.suma_costo_total, suma_resultado=f.suma_rentabilidad,
            pct=f.pct, cantidad_lineas=f.cantidad_lineas,
        )
        for f in filas
    ]


class IncidenciaOut(BaseModel):
    codigo: str
    severidad: str
    entidad: str
    referencia: str
    detalle: str


def incidencias_de_periodo(db: Session, periodo: str, entidad: str) -> list:
    """Lógica pura del endpoint — corre el validador (ya probado en
    test_validador.py) sobre lo que esté persistido para este `periodo`.
    Nunca calcula ni corrige nada, solo lee y reporta (§5 IMPLEMENTACION)."""
    validador = ValidadorRentabilidad(db)
    incidencias = []
    if entidad == "tactica":
        for fila in db.query(VentaTactica).filter(VentaTactica.periodo == periodo).all():
            incidencias.extend(validador.validar_linea_tactica(fila))
        incidencias.extend(validador.detectar_duplicados_tactica(periodo))
    else:
        for fila in db.query(VentaEcom).filter(VentaEcom.periodo == periodo).all():
            incidencias.extend(validador.validar_linea_ecom(fila))
        incidencias.extend(validador.detectar_duplicados_ecom(periodo))
    return incidencias


@router.get("/incidencias", response_model=list[IncidenciaOut])
def listar_incidencias(periodo: str, entidad: str) -> list[IncidenciaOut]:
    if entidad not in ("tactica", "ecom"):
        raise HTTPException(422, "'entidad' debe ser 'tactica' o 'ecom'.")
    with sesion() as db:
        incidencias = incidencias_de_periodo(db, periodo, entidad)
    return [
        IncidenciaOut(codigo=i.codigo, severidad=i.severidad, entidad=i.entidad, referencia=i.referencia, detalle=i.detalle)
        for i in incidencias
    ]
