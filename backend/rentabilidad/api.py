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
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import costos_ecom, export_ventas_ecom, gsheets, pricing_pm, reportes_pricing, seed
from .cierre_ecom_diario import ayer_en_argentina, ciclo_de
from .adapters import (
    ClasificacionProvider,
    CostoVigenteProvider,
    IvaProvider,
    MargenObjetivoProvider,
    ResponsableProvider,
    StockProvider,
    VinculacionProvider,
    _consultar_catalogo_tactica_real,
)
from .agregaciones import ECOM_DIMENSIONES, TACTICA_DIMENSIONES, agregar_ecom, agregar_tactica
from .calculators import LineaTacticaInput, RentabilidadTacticaCalculator
from .config import ConfiguracionFaltante
from .db import sesion
from .ingesta_ecom import EcomExcelAdapter
from .ingesta_ecom_api import EcomApiAdapter
from .ingesta_tactica import TacticaSqlAdapter
from .liquidacion_fravega import LiquidacionFravegaAdapter, LiquidacionFravegaInvalida
from .models import CierreRentabilidad, Regimen, VentaEcom, VentaTactica
from .importar_historico import guardar_historico, importar
from .reporte_diario import reporte_diario
from .persistencia import (
    aplicar_liquidacion_fravega,
    construir_filas_ecom,
    construir_filas_tactica,
    guardar_cierre_ecom,
    guardar_cierre_tactica,
    registrar_cierre,
    ventas_fravega_estimadas,
)
from .tc_bna import TcBnaError, obtener_tc_bna
from .validador import Incidencia, ValidadorRentabilidad

router = APIRouter(prefix="/rentabilidad", tags=["rentabilidad"])


# `_periodo_de_rango`/`extraer_comprobante` viven en regimen.py (no acá) para
# que `importar_historico.py` los pueda usar sin import circular con la API
# -- se re-exportan con estos nombres para no romper nada que ya los importe
# de `rentabilidad.api`.
from .regimen import extraer_comprobante
from .regimen import periodo_de_rango as _periodo_de_rango

RENTABILIDAD_DIR = Path(__file__).resolve().parent


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


def _fetch_fn_con_cache(log=None):
    """Una sola lectura de red por (sheet_id, tab) para todo el request.

    Si una lectura falla, se recuerda el error y se vuelve a levantar al
    instante para esa misma pestaña: sin esto, cada orden del período
    reintentaba la lectura (cada lookup de clasificación la pide), y un
    Sheets caído o lento multiplicaba su demora por miles de órdenes."""
    cache: dict[tuple[str, str], list[list[str]]] = {}
    errores: dict[tuple[str, str], Exception] = {}

    def fetch(spreadsheet_id: str, tab: str) -> list[list[str]]:
        clave = (spreadsheet_id, tab)
        if clave in errores:
            raise errores[clave]
        if clave not in cache:
            inicio = time.monotonic()
            try:
                cache[clave] = gsheets.leer_valores(spreadsheet_id, tab)
            except Exception as e:
                errores[clave] = e
                if log:
                    log(f"Sheets '{tab}': falló en {time.monotonic() - inicio:.1f}s ({type(e).__name__}: {e}) — sigo sin ese dato")
                raise
            if log:
                log(f"Sheets '{tab}': {len(cache[clave])} filas en {time.monotonic() - inicio:.1f}s")
        return cache[clave]

    return fetch


def _consultar_catalogo_tactica_con_cache(log=None):
    """Una sola consulta SQL a Táctica para todo el request — sin esto,
    `CostoVigenteProvider`/`IvaProvider` (cada uno con su propia instancia)
    releerían el catálogo completo por separado. Mismo principio que
    `_fetch_fn_con_cache`, para la fuente SQL de costo/IVA (ver
    adapters.py, cambio de fuente 2026-08-14).

    El error también se recuerda (bug real, 2026-09-28: el Cron diario
    quedaba "colgado" sin túnel a Táctica — cada orden volvía a intentar la
    conexión con 5 reintentos y ~30s de espera, horas en total sin un solo
    error visible). Tras el primer fallo, las siguientes llamadas levantan
    el mismo error al instante."""
    cache: list[dict] | None = None
    error: Exception | None = None

    def consultar() -> list[dict]:
        nonlocal cache, error
        if error is not None:
            raise error
        if cache is None:
            inicio = time.monotonic()
            try:
                cache = _consultar_catalogo_tactica_real()
            except Exception as e:
                error = e
                if log:
                    log(f"Táctica SQL: falló en {time.monotonic() - inicio:.1f}s ({type(e).__name__}) — sigo sin ese dato")
                raise
            if log:
                log(f"Táctica SQL: {len(cache)} productos en {time.monotonic() - inicio:.1f}s")
        return cache

    return consultar


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


class IncidenciaOut(BaseModel):
    codigo: str
    severidad: str
    entidad: str
    referencia: str
    detalle: str


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
    consultar = _consultar_catalogo_tactica_con_cache()
    costo_provider = CostoVigenteProvider(consultar=consultar)
    iva_provider = IvaProvider(consultar=consultar)
    with sesion() as db:
        resultados = calcular_lineas(payload.lineas, db, costo_provider, iva_provider)
    return CalcularTacticaOut(resultados=resultados)


# ── Período: SQL de Táctica -> adaptador -> motor -> clasificación ──
#
# A diferencia de `calcular_tactica` (arriba, CSV manual), acá el PM no
# viene de ninguna columna de archivo: se resuelve con el mismo
# `ClasificacionProvider` que usa `/cierres/tactica` — por eso este camino
# usa `persistencia.construir_filas_tactica` (que ya hace esa clasificación)
# en vez del `calcular_lineas` liviano de arriba. No persiste nada: son los
# mismos objetos en memoria que usaría el cierre, solo que se descartan.

class CalcularTacticaPeriodoIn(BaseModel):
    desde: date
    hasta: date
    tc: str | None = None  # TC manual (pedido de Maxx 2026-08-18) -- reemplaza
    # la cotización de Táctica en TODAS las líneas del período; si se omite,
    # cada línea usa su propia cotización de Táctica sin cambios.


class VentaTacticaOut(BaseModel):
    # `periodo` es None en resultados de /tactica/periodo (consulta en vivo,
    # construir_filas_tactica no lo asigna -- no persiste) y viene poblado
    # solo en filas ya guardadas (histórico/cierre). "Ventas & Rentabilidad"
    # (docs/index.html) sintetiza su propia etiqueta de período para consulta
    # en vivo cuando esto es None -- ver [[project_rentabilidad-architecture]].
    periodo: str | None = None
    fecha: date
    empresa: str
    codigo: str
    tipo_factura: str
    nro_factura: str
    cantidad: Decimal
    precio_venta: Decimal
    regimen: str
    pm: str | None = None
    subcategoria: str | None = None
    responsable: str | None = None
    excluido: bool = False
    motivo_exclusion: str | None = None
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
    # TC de la factura (cotización de Táctica) — para el pie del informe.
    tc: Decimal | None = None


class ConsultarTacticaOut(BaseModel):
    resultados: list[VentaTacticaOut]
    total_lineas: int
    excluidas: int
    config_faltante: list[str]
    incidencias: list[IncidenciaOut]


def _venta_tactica_a_out(v: VentaTactica) -> VentaTacticaOut:
    return VentaTacticaOut(
        periodo=v.periodo, fecha=v.fecha, empresa=v.empresa, codigo=v.codigo, tipo_factura=v.tipo_factura,
        nro_factura=v.nro_factura, cantidad=v.cantidad, precio_venta=v.precio_venta,
        regimen=v.regimen.value if v.regimen else Regimen.NO_RECONOCIDO.value,
        pm=v.pm, subcategoria=v.subcategoria, responsable=v.responsable,
        excluido=v.excluido, motivo_exclusion=v.motivo_exclusion.value if v.motivo_exclusion else None,
        costo_lista=v.costo_lista, iva_producto=v.iva_producto, iva=v.iva,
        imp_cheque=v.imp_cheque, iibb=v.iibb, costo_total_pesos=v.costo_total_pesos,
        costo_financiero_1=v.costo_financiero_1, costo_financiero_2=v.costo_financiero_2,
        margen_real=v.margen_real, margen_pct=v.margen_pct, precio_venta_iva=v.precio_venta_iva,
        tc=v.tc,
    )


def incidencias_en_memoria_tactica(filas: list[VentaTactica]) -> list:
    """Mismo validador que usa `/incidencias`, pero sobre filas que todavía
    no se persistieron — `detectar_duplicados_tactica` consulta la tabla
    por período, así que V-16 se reimplementa acá en memoria (mismo
    criterio: comprobante+SKU repetido)."""
    validador = ValidadorRentabilidad(None)
    incidencias = [i for fila in filas for i in validador.validar_linea_tactica(fila)]
    conteos: dict[tuple[str, str], int] = {}
    for fila in filas:
        clave = (fila.nro_factura, fila.codigo)
        conteos[clave] = conteos.get(clave, 0) + 1
    for (nro, codigo), n in conteos.items():
        if n > 1:
            incidencias.append(Incidencia("V-16", "INFORMATIVO", "TACTICA", f"{nro}/{codigo}", f"Duplicado: {n} filas."))
    return incidencias


@router.post("/tactica/periodo", response_model=ConsultarTacticaOut)
def calcular_tactica_periodo(payload: CalcularTacticaPeriodoIn) -> ConsultarTacticaOut:
    """Lee Táctica directo del SQL Server (`TacticaSqlAdapter`, ya
    probado), corre motor + clasificación (mismo camino que `/cierres/
    tactica`) y devuelve el resultado — no persiste nada."""
    if payload.hasta < payload.desde:
        raise HTTPException(422, "'hasta' no puede ser anterior a 'desde'.")
    tc_override = None
    if payload.tc:
        try:
            tc_override = Decimal(payload.tc)
        except InvalidOperation:
            raise HTTPException(422, f"TC no numérico: {payload.tc!r}")
    filas = TacticaSqlAdapter().lineas(payload.desde, payload.hasta, tc_override)
    fetch = _fetch_fn_con_cache()
    consultar = _consultar_catalogo_tactica_con_cache()
    with sesion() as db:
        resultado = construir_filas_tactica(
            db, filas, CostoVigenteProvider(consultar=consultar), IvaProvider(consultar=consultar),
            ClasificacionProvider(fetch_fn=fetch), ResponsableProvider(fetch_fn=fetch),
            MargenObjetivoProvider(fetch_fn=fetch),
        )
        incidencias = incidencias_en_memoria_tactica(resultado.filas)
    return ConsultarTacticaOut(
        resultados=[_venta_tactica_a_out(f) for f in resultado.filas],
        total_lineas=len(resultado.filas),
        excluidas=sum(1 for f in resultado.filas if f.excluido),
        config_faltante=resultado.config_faltante,
        incidencias=[
            IncidenciaOut(codigo=i.codigo, severidad=i.severidad, entidad=i.entidad, referencia=i.referencia, detalle=i.detalle)
            for i in incidencias
        ],
    )


# ── Período: ECOM API -> adaptador -> motor — mismo criterio que
# `/tactica/periodo`. `EcomApiAdapter.periodo()` devuelve el mismo
# `ResultadoIngestaEcom` que `EcomExcelAdapter.procesar()`, así que
# `construir_filas_ecom` no distingue de dónde vino el dato.
#
# TC: pedido de Maxx (2026-08-10) — cuando corre por la API/el ERP, el TC no
# se tipea a mano, se toma el que informa el BNA al momento de ejecutar
# (sigue siendo UN solo TC para todo el período, la regla no cambia — ver
# tc_bna.py). `tc` queda como override opcional para reprocesar con un
# valor puntual; si se omite, se resuelve solo. El Excel (`/cierres/ecom/excel`)
# sigue pidiéndolo a mano a propósito: ahí se reproduce el proceso manual
# de Maxx para comparar contra el mismo TC que él usó ese día. ──

def origen_tc(tc_manual: str | None) -> str:
    """Texto que queda guardado junto al TC del cierre y sale en el informe."""
    if tc_manual:
        return "manual"
    from datetime import datetime, timedelta, timezone

    ahora = datetime.now(timezone(timedelta(hours=-3)))
    return f"BNA dólar billete venta, consultado {ahora:%Y-%m-%d %H:%M} ART"


def _resolver_tc(tc: str | None) -> Decimal:
    if tc:
        try:
            return Decimal(tc)
        except InvalidOperation:
            raise HTTPException(422, f"TC no numérico: {tc!r}")
    try:
        return obtener_tc_bna()
    except TcBnaError as e:
        raise HTTPException(502, f"No se pudo obtener el TC del BNA y no se pasó uno manual: {e}")


class ConsultarEcomIn(BaseModel):
    desde: date
    hasta: date
    tc: str | None = None  # si se omite, se toma el del BNA al momento de ejecutar


class ResultadoEcomOut(BaseModel):
    numero_orden: str
    canal_de_venta: str | None
    estado_pago: str | None
    excluido: bool
    precio_final: Decimal
    precio_sin_iva: Decimal
    costo_sin_iva: Decimal
    comision_venta: Decimal
    costo_envio: Decimal
    neto: Decimal | None = None
    costo_total: Decimal | None = None
    rentabilidad: Decimal | None = None
    # Agregado 2026-08-19 para que "Ventas & Rentabilidad" (docs/index.html)
    # pueda armar la misma fila unificada que ya arma `parseVentas()` del
    # Sheet -- estos campos ya existían en `VentaEcom`, solo faltaba
    # exponerlos acá (ver [[project_rentabilidad-architecture]]).
    fecha: date | None = None
    skus_vendidos: str | None = None
    pm: str | None = None
    subcategoria: str | None = None
    categoria: str | None = None
    responsable_de_ventas: str | None = None
    utilidad_venta: Decimal | None = None
    facturacion_usd: Decimal | None = None
    periodo: str | None = None
    # Agregado 2026-09-27 (integración Ecom por API): de dónde salió la
    # comisión (API | ESTIMADO_FRAVEGA | LIQUIDACION_FRAVEGA), número de
    # orden del canal externo y observación a revisar a mano.
    origen_comision: str | None = None
    orden_externa: str | None = None
    observacion: str | None = None
    tc: Decimal | None = None


class ConsultarEcomOut(BaseModel):
    resultados: list[ResultadoEcomOut]
    total_lineas: int
    excluidas_por_estado_pago: int
    incidencias_costo: int
    config_faltante: list[str]


def _providers_ecom(fetch):
    return dict(
        clasificacion_provider=ClasificacionProvider(fetch_fn=fetch),
        vinculacion_provider=VinculacionProvider(fetch_fn=fetch),
        stock_provider=StockProvider(fetch_fn=fetch),
        margen_provider=MargenObjetivoProvider(fetch_fn=fetch),
    )


def _venta_ecom_a_out(v: VentaEcom) -> ResultadoEcomOut:
    return ResultadoEcomOut(
        numero_orden=v.numero_orden, canal_de_venta=v.canal_de_venta, estado_pago=v.estado_pago,
        excluido=v.excluido, precio_final=v.precio_final, precio_sin_iva=v.precio_sin_iva,
        costo_sin_iva=v.costo_sin_iva, comision_venta=v.comision_venta, costo_envio=v.costo_envio,
        neto=v.neto, costo_total=v.costo_total, rentabilidad=v.rentabilidad,
        fecha=v.fecha_creacion_venta, skus_vendidos=v.skus_vendidos, pm=v.pm,
        subcategoria=v.subcategoria, categoria=v.categoria,
        responsable_de_ventas=v.responsable_de_ventas,
        utilidad_venta=v.utilidad_venta, facturacion_usd=v.facturacion_usd,
        periodo=v.periodo,
        origen_comision=v.origen_comision,
        orden_externa=v.orden_externa,
        observacion=v.observacion,
        tc=v.tc,
    )


@router.post("/ecom/periodo", response_model=ConsultarEcomOut)
def consultar_ecom_periodo(payload: ConsultarEcomIn) -> ConsultarEcomOut:
    """Lee Ecom directo de la API (`EcomApiAdapter`) para el rango dado y
    corre cada orden por el motor — sin descargar ningún Excel. No persiste
    nada, igual que `/tactica/periodo`."""
    if payload.hasta < payload.desde:
        raise HTTPException(422, "'hasta' no puede ser anterior a 'desde'.")
    tc = _resolver_tc(payload.tc)
    resultado_ingesta = EcomApiAdapter().periodo(payload.desde, payload.hasta, tc)
    fetch = _fetch_fn_con_cache()
    iva_provider = IvaProvider(consultar=_consultar_catalogo_tactica_con_cache())
    with sesion() as db:
        resultado = construir_filas_ecom(db, resultado_ingesta, iva_provider, **_providers_ecom(fetch))
    return ConsultarEcomOut(
        resultados=[_venta_ecom_a_out(f) for f in resultado.filas],
        total_lineas=len(resultado.filas),
        excluidas_por_estado_pago=len(resultado_ingesta.excluidas_por_estado_pago),
        incidencias_costo=len(resultado_ingesta.incidencias_costo),
        config_faltante=resultado.config_faltante,
    )


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
    consultar = _consultar_catalogo_tactica_con_cache()
    with sesion() as db:
        resultado = guardar_cierre_tactica(
            db, periodo, filas,
            CostoVigenteProvider(consultar=consultar), IvaProvider(consultar=consultar),
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
    """Guardar cierre de Ecom vía Excel — desde que `/cierres/ecom` (API)
    existe, este es el camino de **comparación/validación**, no la fuente
    operativa (pedido de Maxx, 2026-08-10). Se mantiene igual: mismo
    `EcomExcelAdapter` ya probado, sin cambios."""
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
            db, periodo, resultado_ingesta, IvaProvider(consultar=_consultar_catalogo_tactica_con_cache()),
            ClasificacionProvider(fetch_fn=fetch), VinculacionProvider(fetch_fn=fetch),
            StockProvider(fetch_fn=fetch), MargenObjetivoProvider(fetch_fn=fetch),
        )
        registrar_cierre(db, periodo, desde, hasta, ecom_guardado=True, ecom_origen="excel",
                         tc_ecom=tc_decimal, tc_ecom_origen="manual")
    return GuardarCierreEcomOut(
        periodo=periodo, total_lineas=len(resultado.filas),
        excluidas=sum(1 for f in resultado.filas if f.excluido),
        config_faltante=resultado.config_faltante,
        excluidas_por_estado_pago=len(resultado_ingesta.excluidas_por_estado_pago),
        incidencias_costo=len(resultado_ingesta.incidencias_costo),
    )


class GuardarCierreEcomIn(BaseModel):
    desde: date
    hasta: date
    tc: str | None = None  # si se omite, se toma el del BNA al momento de ejecutar


@router.post("/cierres/ecom", response_model=GuardarCierreEcomOut)
def cerrar_ecom_api(payload: GuardarCierreEcomIn) -> GuardarCierreEcomOut:
    """Guardar cierre de Ecom **desde la API real** — reemplaza a
    `/cierres/ecom/excel` como fuente operativa (pedido de Maxx,
    2026-08-10): el Excel queda solo como comparación/validación, ya no es
    necesario para que Rentabilidad funcione. `EcomApiAdapter.periodo()`
    devuelve el mismo `ResultadoIngestaEcom` que el Excel, así que
    `guardar_cierre_ecom` no cambia."""
    if payload.hasta < payload.desde:
        raise HTTPException(422, "'hasta' no puede ser anterior a 'desde'.")
    tc = _resolver_tc(payload.tc)

    periodo = _periodo_de_rango(payload.desde, payload.hasta)
    resultado_ingesta = EcomApiAdapter().periodo(payload.desde, payload.hasta, tc)
    fetch = _fetch_fn_con_cache()
    with sesion() as db:
        resultado = guardar_cierre_ecom(
            db, periodo, resultado_ingesta, IvaProvider(consultar=_consultar_catalogo_tactica_con_cache()), **_providers_ecom(fetch),
        )
        registrar_cierre(db, periodo, payload.desde, payload.hasta, ecom_guardado=True, ecom_origen="api",
                         tc_ecom=tc, tc_ecom_origen=origen_tc(payload.tc))
    return GuardarCierreEcomOut(
        periodo=periodo, total_lineas=len(resultado.filas),
        excluidas=sum(1 for f in resultado.filas if f.excluido),
        config_faltante=resultado.config_faltante,
        excluidas_por_estado_pago=len(resultado_ingesta.excluidas_por_estado_pago),
        incidencias_costo=len(resultado_ingesta.incidencias_costo),
    )


# ══════════════════════════════════════════════════════════════════════════
# FRÁVEGA — la API de Ecom no trae comisión ni fee logístico. Se estiman
# (comisión base) hasta que llega la liquidación quincenal; al cargarla, las
# ventas ya guardadas pasan a los valores reales (decisión de Maxx,
# 2026-09-27). Escribe en `liquidacion_fravega` y actualiza `venta_ecom`.
# ══════════════════════════════════════════════════════════════════════════

class LiquidacionFravegaOut(BaseModel):
    desde: date
    hasta: date
    ordenes_en_liquidacion: int
    ventas_actualizadas: int
    canceladas_observadas: list[str]  # número de orden Ecom
    sin_venta_en_ecom: int
    fravega_pendientes: int  # ventas de Frávega que siguen estimadas en toda la base


@router.post("/fravega/liquidacion", response_model=LiquidacionFravegaOut)
async def cargar_liquidacion_fravega(archivo: UploadFile = File(...)) -> LiquidacionFravegaOut:
    """Sube la liquidación de Frávega tal cual se descarga de Seller Center
    (.xlsx). Valida que el detalle reconstruya los totales de la propia
    liquidación antes de tocar nada; si no cuadra, 422 y no se aplica."""
    contenido = await archivo.read()
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(contenido)
        tmp_path = tmp.name
    try:
        liquidacion = LiquidacionFravegaAdapter().procesar(tmp_path)
    except LiquidacionFravegaInvalida as e:
        raise HTTPException(422, str(e))
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    if liquidacion.desde is None or liquidacion.hasta is None:
        raise HTTPException(422, "La liquidación no trae 'Liquidación desde/hasta' en la pestaña Totales.")

    with sesion() as db:
        resultado = aplicar_liquidacion_fravega(db, liquidacion, archivo=archivo.filename)
        db.flush()
        pendientes = len(ventas_fravega_estimadas(db))
    return LiquidacionFravegaOut(
        desde=liquidacion.desde, hasta=liquidacion.hasta,
        ordenes_en_liquidacion=resultado.ordenes_en_liquidacion,
        ventas_actualizadas=len(resultado.ventas_actualizadas),
        canceladas_observadas=resultado.canceladas_observadas,
        sin_venta_en_ecom=resultado.sin_venta_en_ecom,
        fravega_pendientes=pendientes,
    )


@router.get("/fravega/pendientes", response_model=list[ResultadoEcomOut])
def fravega_pendientes() -> list[ResultadoEcomOut]:
    """Ventas de Frávega guardadas que siguen con comisión estimada: las que
    esperan la liquidación de su quincena y las observadas (canceladas en
    Frávega pero cobradas en Ecom)."""
    with sesion() as db:
        return [_venta_ecom_a_out(v) for v in ventas_fravega_estimadas(db)]


# ══════════════════════════════════════════════════════════════════════════
# REPORTE DIARIO — solo lectura, para n8n (mail diario). Resume lo que la
# corrida diaria ya guardó; no recalcula nada.
# ══════════════════════════════════════════════════════════════════════════

def _verificar_token_reporte(token: str | None, x_reporte_token: str | None) -> None:
    """Si está configurada `RENT_REPORTE_TOKEN`, los reportes para n8n la
    exigen (header `X-Reporte-Token` o `?token=`)."""
    import os

    esperado = os.environ.get("RENT_REPORTE_TOKEN")
    if esperado and (x_reporte_token or token) != esperado:
        raise HTTPException(401, "Token de reporte inválido o ausente.")


@router.get("/reporte/ecom/diario")
def reporte_ecom_diario(
    fecha: date | None = None,
    top: int = 5,
    token: str | None = None,
    x_reporte_token: str | None = Header(default=None),
) -> dict:
    """Reporte del ciclo en curso (23 → 22) al día `fecha` (default: ayer,
    hora Argentina): ayer, acumulado del ciclo, por PM, top / pérdidas,
    alertas, Full y marketplaces (Frávega, OnCity, Megatone).

    Si está configurada `RENT_REPORTE_TOKEN`, exige ese token (header
    `X-Reporte-Token` o `?token=`)."""
    _verificar_token_reporte(token, x_reporte_token)
    if not 1 <= top <= 50:
        raise HTTPException(422, "'top' debe estar entre 1 y 50.")
    with sesion() as db:
        return reporte_diario(db, fecha, top)


class CierreOut(BaseModel):
    periodo: str
    desde: date
    hasta: date
    generado_en: str
    tactica_guardado: bool
    ecom_guardado: bool
    ecom_origen: str | None
    tc_ecom: Decimal | None = None
    tc_ecom_origen: str | None = None


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
                ecom_origen=c.ecom_origen, tc_ecom=c.tc_ecom, tc_ecom_origen=c.tc_ecom_origen,
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


# ══════════════════════════════════════════════════════════════════════════
# MIGRACIÓN HISTÓRICA — endpoint de un solo uso (2026-08-18, ver
# importar_historico.py). Corre del lado del servidor porque necesita
# RENT_DATABASE_URL/GOOGLE_CREDENTIALS_JSON de Railway, sin exponer esas
# credenciales fuera del backend. No pensado como feature permanente del
# frontend -- se llama una vez por curl para la migración inicial.
# ══════════════════════════════════════════════════════════════════════════

class ImportarHistoricoIn(BaseModel):
    sheet_id: str
    hasta_fecha_exclusive: date


class ImportarHistoricoOut(BaseModel):
    total_tactica: int
    total_ecom: int
    por_periodo_tactica: dict[str, int]
    por_periodo_ecom: dict[str, int]
    filas_ignoradas: dict[str, int]


@router.post("/importar-historico", response_model=ImportarHistoricoOut)
def importar_historico(payload: ImportarHistoricoIn) -> ImportarHistoricoOut:
    with sesion() as db:
        todas_las_pestanas = gsheets.listar_pestanas(payload.sheet_id)
        resultado = importar(
            db, payload.sheet_id, todas_las_pestanas, gsheets.leer_valores,
            payload.hasta_fecha_exclusive,
        )
        guardar_historico(db, resultado)

        por_periodo_tactica: dict[str, int] = {}
        for venta in resultado.tactica:
            por_periodo_tactica[venta.periodo] = por_periodo_tactica.get(venta.periodo, 0) + 1
        por_periodo_ecom: dict[str, int] = {}
        for venta in resultado.ecom:
            por_periodo_ecom[venta.periodo] = por_periodo_ecom.get(venta.periodo, 0) + 1

    return ImportarHistoricoOut(
        total_tactica=len(resultado.tactica),
        total_ecom=len(resultado.ecom),
        por_periodo_tactica=por_periodo_tactica,
        por_periodo_ecom=por_periodo_ecom,
        filas_ignoradas=resultado.filas_ignoradas,
    )


# ══════════════════════════════════════════════════════════════════════════
# HISTÓRICO — lectura fila por fila de TODO lo persistido (migrado del Sheet
# vía /importar-historico + lo que se vaya guardando por /cierres/*), sin
# filtrar por período. Pedido de Maxx (2026-08-19): unificar "Ventas &
# Rentabilidad" (docs/index.html, page-dashboard) con este motor -- esa
# página ya arma sus filtros/gráficos/comparaciones sobre una fila por
# línea, así que se devuelve el mismo shape que ya usan /tactica/periodo y
# /ecom/periodo (VentaTacticaOut/ResultadoEcomOut) para que el frontend use
# un solo mapeo tanto para histórico como para consulta en vivo.
# ══════════════════════════════════════════════════════════════════════════

def historico_tactica_de(db: Session, incluir_excluidos: bool = False) -> list[VentaTacticaOut]:
    q = db.query(VentaTactica)
    if not incluir_excluidos:
        q = q.filter(VentaTactica.excluido.is_(False))
    return [_venta_tactica_a_out(f) for f in q.order_by(VentaTactica.fecha).all()]


def historico_ecom_de(db: Session, incluir_excluidos: bool = False) -> list[ResultadoEcomOut]:
    q = db.query(VentaEcom)
    if not incluir_excluidos:
        q = q.filter(VentaEcom.excluido.is_(False))
    return [_venta_ecom_a_out(f) for f in q.order_by(VentaEcom.fecha_creacion_venta).all()]


@router.get("/historico/tactica", response_model=list[VentaTacticaOut])
def historico_tactica(incluir_excluidos: bool = False) -> list[VentaTacticaOut]:
    with sesion() as db:
        return historico_tactica_de(db, incluir_excluidos)


@router.get("/historico/ecom", response_model=list[ResultadoEcomOut])
def historico_ecom(incluir_excluidos: bool = False) -> list[ResultadoEcomOut]:
    with sesion() as db:
        return historico_ecom_de(db, incluir_excluidos)


# ══════════════════════════════════════════════════════════════════════════
# MOTOR DE PRECIOS — etapa 2: carga inicial de los precios de los PM y vista
# de todos los SKU con su margen proyectado por canal (pricing_pm.py).
# ══════════════════════════════════════════════════════════════════════════

class CargaPmOut(BaseModel):
    archivo: str | None
    leidos: int
    nuevos: int
    cambiados: int
    sin_cambios: int
    duplicados: list[str]
    sin_precio_web: list[str]


@router.post("/pricing/carga-pm", response_model=CargaPmOut)
async def pricing_carga_pm(
    archivo: UploadFile = File(...),
    cargado_por: str = Form(...),
    motivo: str | None = Form(default=None),
) -> CargaPmOut:
    """Sube la planilla de un PM ("VENTAS POR CANALES <PM>", .xlsx) y guarda
    en `pricing_sku` lo que decide el PM. Solo escribe lo que cambió;
    volver a subir el mismo archivo no duplica."""
    if not cargado_por.strip():
        raise HTTPException(422, "Falta 'cargado_por' (quién hace la carga).")
    contenido = await archivo.read()
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(contenido)
        tmp_path = tmp.name
    try:
        lectura = pricing_pm.leer_planilla_pm(pricing_pm.leer_xlsx_pm(tmp_path))
    except pricing_pm.PlanillaPmInvalida as e:
        raise HTTPException(422, str(e))
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    with sesion() as db:
        r = pricing_pm.cargar_precios_pm(
            db, lectura, cargado_por=cargado_por.strip(), hoy=ayer_en_argentina() + timedelta(days=1),
            motivo=motivo or f"Carga inicial desde planilla ({archivo.filename})",
        )
    return CargaPmOut(archivo=archivo.filename, leidos=r.leidos, nuevos=r.nuevos, cambiados=r.cambiados,
                      sin_cambios=r.sin_cambios, duplicados=r.duplicados, sin_precio_web=r.sin_precio_web)


class SyncPmOut(BaseModel):
    pm: str
    ok: bool
    detalle: str
    nuevos: int = 0
    cambiados: int = 0
    sin_cambios: int = 0


_ULTIMA_SYNC_PM: dict = {}


@router.post("/pricing/sync-pm", response_model=list[SyncPmOut])
def pricing_sync_pm() -> list[SyncPmOut]:
    """Fuente principal: lee el Sheet de cada PM por API y guarda solo lo que
    cambió. Un PM sin configurar o sin acceso sale con `ok=false` y el
    motivo; el resto se carga igual."""
    with sesion() as db:
        res = pricing_pm.sincronizar_desde_sheets(db, hoy=ayer_en_argentina() + timedelta(days=1))
    _ULTIMA_SYNC_PM.update(en=datetime.now(timezone.utc).isoformat(), ok=[r.pm for r in res if r.ok])
    return [
        SyncPmOut(pm=r.pm, ok=r.ok, detalle=r.detalle, nuevos=r.carga.nuevos if r.carga else 0,
                  cambiados=r.carga.cambiados if r.carga else 0, sin_cambios=r.carga.sin_cambios if r.carga else 0)
        for r in res
    ]


class FilasPmIn(BaseModel):
    pm: str
    filas: list[list]
    cargado_por: str | None = None


@router.post("/pricing/carga-pm-filas", response_model=SyncPmOut)
def pricing_carga_pm_filas(payload: FilasPmIn) -> SyncPmOut:
    """Respaldo: las filas del Sheet que ya lee el navegador con su propia
    conexión (Configuración → planillas PM), para un PM que el backend
    todavía no tiene configurado."""
    try:
        lectura = pricing_pm.leer_planilla_pm(payload.filas)
    except pricing_pm.PlanillaPmInvalida as e:
        raise HTTPException(422, str(e))
    with sesion() as db:
        r = pricing_pm.cargar_precios_pm(
            db, lectura, cargado_por=payload.cargado_por or f"Sheet {payload.pm} (navegador)",
            hoy=ayer_en_argentina() + timedelta(days=1), motivo="Sincronizado desde el Sheet del PM (navegador)",
        )
    return SyncPmOut(pm=payload.pm, ok=True, detalle=f"{r.leidos} SKU: {r.nuevos} nuevos, {r.cambiados} cambiados, {r.sin_cambios} sin cambios.",
                     nuevos=r.nuevos, cambiados=r.cambiados, sin_cambios=r.sin_cambios)


def _datos_sku_fn(avisos: list[str]):
    """Costo del catálogo de Ecom (fuente primaria, criterio de margen §7),
    IVA de Táctica con respaldo del IVA de Ecom, y PM/categoría de GRAL
    CATEGORIAS (una sola lectura). Si una fuente no responde, la vista sale
    igual con los precios y un aviso — no se inventa el dato."""
    consultar = _consultar_catalogo_tactica_con_cache()
    costo_p = costos_ecom.CostoEcomProvider()
    iva_p = costos_ecom.IvaConRespaldoEcom(tactica=IvaProvider(consultar=consultar))
    clasif = ClasificacionProvider(fetch_fn=_fetch_fn_con_cache())
    ecom_ok = clasif_ok = True
    try:
        costo_p.precargar()
        iva_p.precargar()
    except Exception as e:
        ecom_ok = False
        avisos.append(f"El catálogo de Ecom no respondió ({type(e).__name__}): sin costo ni IVA, no se calculan márgenes.")
    if ecom_ok and iva_p.tactica_caida:
        avisos.append("Táctica no respondió: el IVA sale del artículo en Ecom.")
    try:
        clasif._indices()
    except Exception as e:
        clasif_ok = False
        avisos.append(f"No se pudo leer GRAL CATEGORIAS ({type(e).__name__}): sin PM ni categoría (ML usa la comisión general).")

    def datos(sku: str) -> pricing_pm.DatosSku:
        costo = iva = None
        if ecom_ok:
            costo = costo_p.obtener(sku) or costo_p.obtener(sku.upper())
            iva = iva_p.factor(sku) or iva_p.factor(sku.upper())
        c = clasif.clasificacion_ecom(sku) if clasif_ok else {}
        categoria = c.get("categoria")
        return pricing_pm.DatosSku(
            costo_usd=costo, iva_factor=iva, pm=c.get("pm"),
            categoria=None if categoria == "SIN PM" else categoria, subcategoria=c.get("subcategoria"),
        )

    return datos


@router.get("/costos/ecom")
def costos_catalogo_ecom() -> dict:
    """Costo (USD, sin IVA) de todos los SKU del catálogo de Ecom — la fuente
    única de costo del ERP. Lo lee el front (Competidores) en vez de la
    planilla PM. La primera llamada tras un arranque baja el catálogo (~80 s)."""
    try:
        cat = costos_ecom.obtener_catalogo()
    except Exception as e:
        raise HTTPException(503, f"No se pudo leer el catálogo de costos de Ecom: {e}")
    return {
        "obtenido_en": cat.obtenido_en,
        "costos": {k: float(v) for k, v in cat.costos.items()},
        "iva": {k: float(v) for k, v in cat.iva.items()},
        "sin_costo": sorted(cat.sin_costo),
        "ambiguos": {k: [float(x) for x in v] for k, v in cat.ambiguos.items()},
    }


@router.get("/costos/cruce-tactica")
def costos_cruce_tactica(tolerancia_pct: Decimal = Decimal("1")) -> dict:
    """Alerta de diferencias de costo Ecom vs Táctica (por SKU en ambas).
    Táctica solo se usa para cruzar: si no responde, se informa y no se corta
    nada."""
    try:
        cat = costos_ecom.obtener_catalogo()
    except Exception as e:
        raise HTTPException(503, f"No se pudo leer el catálogo de costos de Ecom: {e}")
    try:
        tactica = CostoVigenteProvider(consultar=_consultar_catalogo_tactica_con_cache())
        tactica_costos = {sku: c for sku in cat.costos if (c := tactica.obtener(sku)) is not None}
    except Exception as e:
        raise HTTPException(503, f"Táctica no respondió ({type(e).__name__}): no se puede cruzar el costo.")
    difs = costos_ecom.cruzar_costos(cat.costos, tactica_costos, tolerancia_pct)
    return {"comparados": len(tactica_costos), "con_diferencia": len(difs), "tolerancia_pct": float(tolerancia_pct),
            "diferencias": [{**d, "ecom": float(d["ecom"]), "tactica": float(d["tactica"]), "dif_pct": float(d["dif_pct"])} for d in difs]}


def _periodo_en_curso() -> str:
    inicio, fin = ciclo_de(ayer_en_argentina())
    return _periodo_de_rango(inicio, fin)


@router.get("/pricing/skus")
def pricing_skus(
    fecha: date | None = None,
    pm: str | None = None,
    categoria: str | None = None,
    canal: str | None = None,
    solo_negativos: bool = False,
    margen_max: Decimal | None = None,  # en %, ej. 10 = margen menor a 10%
    buscar: str | None = None,
    cambiado_desde: date | None = None,
    tc: str | None = None,
) -> dict:
    """Todos los SKU cargados con su precio y margen proyectado por canal
    (Web, ML, Frávega, OnCity) y el margen real del ciclo en curso."""
    if canal and canal.upper() not in pricing_pm.motor.CANALES:
        raise HTTPException(422, f"Canal desconocido: {canal}")
    fecha = fecha or ayer_en_argentina() + timedelta(days=1)
    tc_valor, avisos = _resolver_tc(tc), []
    filtros = pricing_pm.FiltrosVista(
        pm=pm, categoria=categoria, canal=canal.upper() if canal else None, solo_negativos=solo_negativos,
        margen_max=margen_max / 100 if margen_max is not None else None, buscar=buscar, cambiado_desde=cambiado_desde,
    )
    periodo = _periodo_en_curso()
    with sesion() as db:
        filas = pricing_pm.vista_pricing(db, _datos_sku_fn(avisos), tc_valor, fecha, filtros, periodo_real=periodo)
    return {"fecha": fecha, "tc": tc_valor, "tc_origen": origen_tc(tc), "periodo_real": periodo,
            "ultima_sync_pm": _ULTIMA_SYNC_PM.get("en"), "avisos": avisos, "total": len(filas), "filas": filas}


@router.get("/pricing/skus/{sku}")
def pricing_sku_detalle(sku: str, fecha: date | None = None, tc: str | None = None) -> dict:
    """Ficha de un SKU: el desglose de cada cargo por canal y su historial
    de precios (quién y cuándo)."""
    fecha = fecha or ayer_en_argentina() + timedelta(days=1)
    tc_valor, avisos = _resolver_tc(tc), []
    with sesion() as db:
        vigente = pricing_pm.vigentes(db, fecha).get(pricing_pm.norm_sku(sku))
        if vigente is None:
            raise HTTPException(404, f"{sku} no tiene precios cargados en el motor.")
        datos = _datos_sku_fn(avisos)(vigente.sku)
        canales = pricing_pm.calcular_sku(
            vigente, datos, tc_valor, pricing_pm.motor.cargar_parametros(db, fecha), detalle=True,
            fee_hist=pricing_pm.fee_historico_fravega(db),
        )
        historial = [
            {c: getattr(h, c) for c in ("vigente_desde", "cargado_por", "motivo", *pricing_pm.CAMPOS_PM)}
            for h in pricing_pm.historial(db, sku)
        ]
    return {"sku": vigente.sku, "fecha": fecha, "tc": tc_valor, "avisos": avisos, "pm": datos.pm,
            "categoria": datos.categoria, "costo_usd": datos.costo_usd, "iva_factor": datos.iva_factor,
            "canales": canales, "historial": historial}


# ══════════════════════════════════════════════════════════════════════════
# REPORTES DEL MOTOR DE PRECIOS para n8n — solo lectura, mismo token que el
# reporte diario (reportes_pricing.py).
# ══════════════════════════════════════════════════════════════════════════

@router.get("/reporte/pricing/desvio-precios")
def reporte_desvio_precios(
    fecha: date | None = None,
    todo_el_ciclo: bool = False,
    umbral_pts: Decimal = Decimal(5),
    periodo: str | None = None,
    solo_revisar: bool = False,
    token: str | None = None,
    x_reporte_token: str | None = Header(default=None),
) -> dict:
    """Maca: margen real vs proyectado por SKU y canal (Web y ML sin envío).
    Por defecto, solo las ventas CREADAS AYER (hora Argentina), como el
    reporte diario de rentabilidad: lo de días anteriores capaz ya se
    corrigió (Maxx, 2026-10-03). `fecha` = otro día puntual;
    `todo_el_ciclo=true` = el acumulado del ciclo (o de `periodo`). Marca
    los que quedan más de `umbral_pts` puntos por debajo del proyectado,
    contemplando las cuotas."""
    _verificar_token_reporte(token, x_reporte_token)
    if umbral_pts < 0:
        raise HTTPException(422, "'umbral_pts' no puede ser negativo.")
    hoy = ayer_en_argentina() + timedelta(days=1)
    dia = None if todo_el_ciclo else (fecha or ayer_en_argentina())
    if periodo is None:
        periodo = _periodo_de_rango(*ciclo_de(dia)) if dia else _periodo_en_curso()
    with sesion() as db:
        res = reportes_pricing.desvio_precios(
            db, periodo, hoy, umbral_pts=umbral_pts, solo_revisar=solo_revisar, dia=dia,
        )
        cierre = db.get(CierreRentabilidad, periodo)
        if dia and (cierre is None or cierre.hasta < dia):
            res["avisos"].append(
                f"La corrida diaria todavía no guardó las ventas del {dia.isoformat()}"
                + (f" (datos hasta {cierre.hasta.isoformat()})." if cierre else ".")
            )
    return res


class _SinTactica:
    """Natalia compara precios, no margen: no hace falta el costo de Táctica
    (y así el reporte no depende del túnel)."""

    def obtener(self, sku):
        return None

    def factor(self, sku):
        return None


def _ofertas_ml_activas(incluir_propias: bool) -> list[dict]:
    """Ofertas activas de ML leídas en vivo con el módulo Ofertas ML (las dos
    cuentas). Import perezoso: `rentabilidad/` no depende de ML para el resto."""
    import ml_ofertas

    ml, sin = ml_ofertas.MLOfertasClient(), _SinTactica()
    filas, _ = ml_ofertas.ofertas_activas(ml, sin, sin)
    if incluir_propias:
        for cuenta in ml_ofertas.SELLERS:
            f, _ = ml_ofertas.ofertas_propias_activas(ml, sin, sin, cuenta)
            filas.extend(f)
    return [ml_ofertas._fila_a_dict(f) for f in filas]


@router.get("/reporte/pricing/ofertas")
def reporte_control_ofertas(
    tolerancia_pct: Decimal = Decimal(1),
    incluir_propias: bool = False,
    solo_revisar: bool = False,
    token: str | None = None,
    x_reporte_token: str | None = Header(default=None),
) -> dict:
    """Natalia: cada oferta activa de ML contra el precio ML del PM. Marca
    las que no cuadran (primero las que quedan por debajo). Con
    `incluir_propias=true` suma las ofertas propias (PRICE_DISCOUNT): el
    escaneo es publicación por publicación y tarda varios minutos."""
    _verificar_token_reporte(token, x_reporte_token)
    try:
        ofertas = _ofertas_ml_activas(incluir_propias)
    except Exception as e:
        raise HTTPException(502, f"No se pudieron leer las ofertas de Mercado Libre: {type(e).__name__}: {e}")
    with sesion() as db:
        res = reportes_pricing.control_ofertas(
            db, ofertas, ayer_en_argentina() + timedelta(days=1), tolerancia_pct=tolerancia_pct, solo_revisar=solo_revisar,
        )
    res["incluye_ofertas_propias"] = incluir_propias
    return res


@router.get("/reporte/ecom/ventas")
def reporte_ecom_ventas(
    fecha: date | None = None,
    todo_el_ciclo: bool = False,
    incluir_excluidas: bool = False,
    token: str | None = None,
    x_reporte_token: str | None = Header(default=None),
) -> dict:
    """Ventas Ecom guardadas por la corrida diaria, orden por orden, con las
    columnas del reporte de facturación (claves = títulos de columna) —
    para el Google Sheet de historial vía n8n. Por defecto las órdenes
    CREADAS AYER (hora Argentina); `fecha` = otro día; `todo_el_ciclo=true`
    = todo el ciclo de ese día (o del en curso)."""
    _verificar_token_reporte(token, x_reporte_token)
    dia = fecha or ayer_en_argentina()
    periodo = _periodo_de_rango(*ciclo_de(dia))
    with sesion() as db:
        res = export_ventas_ecom.exportar_ventas(
            db, periodo, dia=None if todo_el_ciclo else dia, incluir_excluidas=incluir_excluidas,
        )
        cierre = db.get(CierreRentabilidad, periodo)
    res["datos_guardados_hasta"] = cierre.hasta.isoformat() if cierre else None
    res["avisos"] = [] if cierre and cierre.hasta >= dia else [
        f"La corrida diaria todavía no guardó las ventas del {dia.isoformat()}"
        + (f" (datos hasta {cierre.hasta.isoformat()})." if cierre else ".")
    ]
    return res
