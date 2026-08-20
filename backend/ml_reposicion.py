"""
Simulador de reposición Full — cuánto conviene enviar, por SKU.

Continuación de `ml_full.py` (misma doc, `03_MODULO_FULL.md` §5 y §10
puntos 5 y 12). Sigue siendo de **solo lectura y de simulación**: calcula
y muestra cuánto convendría enviar a Full, pero no crea el envío real en
Mercado Libre. Confirmado con Maxx (2026-08-20): "eso lo llevamos al ERP
después de verificar que el cálculo da bien" — la creación real del envío
queda para después, y de cualquier forma sigue detrás de la puerta de
escritura de `docs/business/COMERCIAL/00_LEEME.md` §5.

Fuente de ventas, confirmada contra el portal real de Mercado Libre
(`developers.mercadolibre.com.ar/es_ar/gestiona-ventas`, 2026-08-20 — no
había MCP disponible en la sesión, así que se escaló al siguiente paso de
la escalera doc → MCP → web real): `MLFullClient.ventas_por_item`, que usa
`/orders/search?seller=...&order.status=paid&order.date_closed.from=...&order.date_closed.to=...`.

Fuente de "disponible para enviar", confirmada con Maxx (2026-08-20): el
depósito **Pitec** de Ecom (`EcomFullAdapter.stock_disponible_por_sku`) —
no la suma de todos los depósitos que no son Full.

**Táctica no tiene una fuente de stock consultable hoy** (ni Sheet, ni
API, ni tabla en `rentabilidad/` — se revisó y no existe). Confirmado con
Maxx: cuando Pitec llega a 0, la reposición es un traspaso MANUAL de
mercadería de Táctica a Ecom, no un número que este módulo pueda sumar
solo. Por eso el simulador NO agrega un "stock Táctica" al disponible:
cuando falta stock en Pitec, marca `alerta_revisar_tactica` para que una
persona lo revise, en vez de inventar un número.

GAPS documentados, no resueltos todavía (no son reglas inventadas, son
huecos reales sin dato para llenarlos):
- La "ventana con stock" (para detectar venta censurada) se estima por
  primera/última venta del período, igual que ya hace la planilla
  (`03_MODULO_FULL.md` §5) — el log de movimientos exacto (§4.1) sigue
  sin confirmar si existe por API.
- La segunda condición de censura del doc ("rotación ≥ 3 y unidades ≥
  10") **no está implementada**: necesita stock PROMEDIO del período, que
  requiere fotos diarias de stock (§4.2) que todavía no existen. Solo se
  implementa la primera condición (stock actual en 0 + ventas ≥ 5 + días
  sin vender ≥ 3).
- "Envíos pendientes" no se resta de `falta_enviar` — no hay tracking de
  envíos en tránsito en este sistema todavía (punto 11 del orden de
  construcción del doc, depende de que el envío real exista para poder
  guardar el pronóstico al momento de crearlo).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from ml_auth import SELLERS
from ml_full import EcomFullAdapter, MLFullClient, conciliar


@dataclass
class FilaReposicion:
    sku: str
    stock_full: int
    ventas_periodo: int
    dias_periodo: int
    primera_venta: str | None
    ultima_venta: str | None
    censurado: bool
    ventas_diarias: float
    stock_objetivo: float
    falta_enviar: int
    disponible_pitec: int | None
    enviar_posible: int
    alerta_revisar_tactica: bool
    cobertura_dias: float | None
    quiebre_estimado: str | None


@dataclass
class ResultadoReposicion:
    filas: list[FilaReposicion]
    incidencias_sku: list[dict]
    incidencias_sin_vincular: list[dict]
    skus_no_en_ecom: list[str]


def _factores_por_item(resultado) -> dict[str, list[tuple[str, int]]]:
    """`item_id` -> [(sku, factor), ...], leído de las `publicaciones` que
    ya resolvió `conciliar()` -- no se vuelve a golpear la vinculación de
    Ecom."""
    mapa: dict[str, list[tuple[str, int]]] = {}
    for fila in resultado.filas:
        for pub in fila.publicaciones:
            mapa.setdefault(pub["item_id"], []).append((fila.sku, pub["factor"]))
    return mapa


def calcular_reposicion(
    ml: MLFullClient, ecom: EcomFullAdapter, cuentas: list[str] | None = None,
    dias_ventas: int = 30, semanas_objetivo: float = 3, hoy: date | None = None,
) -> ResultadoReposicion:
    """Orquesta el simulador completo (§5 y §10 puntos 5/12 de
    `03_MODULO_FULL.md`): reutiliza `conciliar()` para el stock Full por
    SKU y la vinculación/factor de pack ya resuelta, le suma las ventas
    confirmadas del período (mismas dos cuentas, en unidades reales
    aplicando el mismo factor) y el stock disponible en Pitec, y aplica
    las fórmulas de la planilla:

        Ventas diarias corregida = unidades / ventana con stock (si
                                    censurado) o / días del período (si no)
        Stock objetivo           = ventas diarias × semanas objetivo × 7
        Falta enviar             = máx(0, stock objetivo − stock en Full)
        Enviar posible           = mín(falta enviar, disponible en Pitec)
        Cobertura en días        = stock en Full / ventas diarias
        Quiebre estimado         = hoy + cobertura
    """
    cuentas = cuentas or list(SELLERS.keys())
    hoy = hoy or date.today()
    desde_iso = f"{(hoy - timedelta(days=dias_ventas)).isoformat()}T00:00:00.000-00:00"
    hasta_iso = f"{hoy.isoformat()}T23:00:00.000-00:00"

    resultado_conciliacion = conciliar(ml, ecom, cuentas)
    factores_por_item = _factores_por_item(resultado_conciliacion)

    ventas_por_item: dict[str, dict] = {}
    for cuenta in cuentas:
        # Los item_id de ML son únicos por cuenta -- no hay colisión entre
        # las dos cuentas al combinar los diccionarios.
        ventas_por_item.update(ml.ventas_por_item(cuenta, desde_iso, hasta_iso))

    filas: list[FilaReposicion] = []
    for fila_stock in resultado_conciliacion.filas:
        ventas_total = 0
        primera = None
        ultima = None
        for pub in fila_stock.publicaciones:
            venta_item = ventas_por_item.get(pub["item_id"])
            if not venta_item:
                continue
            ventas_total += venta_item["unidades"] * pub["factor"]
            if venta_item["primera"] and (primera is None or venta_item["primera"] < primera):
                primera = venta_item["primera"]
            if venta_item["ultima"] and (ultima is None or venta_item["ultima"] > ultima):
                ultima = venta_item["ultima"]

        dias_sin_vender = (hoy - date.fromisoformat(ultima)).days if ultima else dias_ventas
        censurado = fila_stock.stock_ml == 0 and ventas_total >= 5 and dias_sin_vender >= 3
        if censurado and primera and ultima:
            ventana = max((date.fromisoformat(ultima) - date.fromisoformat(primera)).days, 1)
            ventas_diarias = ventas_total / ventana
        else:
            ventas_diarias = ventas_total / dias_ventas

        stock_objetivo = ventas_diarias * semanas_objetivo * 7
        falta_enviar = max(0, round(stock_objetivo - fila_stock.stock_ml))
        disponible = ecom.stock_disponible_por_sku(fila_stock.sku)
        enviar_posible = min(falta_enviar, disponible) if disponible is not None else 0
        alerta_tactica = disponible is not None and falta_enviar > disponible

        if ventas_diarias > 0:
            cobertura = fila_stock.stock_ml / ventas_diarias
            quiebre = (hoy + timedelta(days=cobertura)).isoformat()
        else:
            cobertura = None
            quiebre = None

        filas.append(FilaReposicion(
            sku=fila_stock.sku, stock_full=fila_stock.stock_ml, ventas_periodo=ventas_total,
            dias_periodo=dias_ventas, primera_venta=primera, ultima_venta=ultima,
            censurado=censurado, ventas_diarias=round(ventas_diarias, 2),
            stock_objetivo=round(stock_objetivo, 1), falta_enviar=falta_enviar,
            disponible_pitec=disponible, enviar_posible=enviar_posible,
            alerta_revisar_tactica=alerta_tactica,
            cobertura_dias=round(cobertura, 1) if cobertura is not None else None,
            quiebre_estimado=quiebre,
        ))

    return ResultadoReposicion(
        filas=filas, incidencias_sku=resultado_conciliacion.incidencias_sku,
        incidencias_sin_vincular=resultado_conciliacion.incidencias_sin_vincular,
        skus_no_en_ecom=resultado_conciliacion.skus_no_en_ecom,
    )


# ── Job en background — mismo patrón que ml_full.py (jobs propios, no
# compartidos con main.py ni con ml_full.py). ──

_jobs: dict[str, dict] = {}


def iniciar_job(
    job_id: str, ecom_email: str | None = None, ecom_password: str | None = None,
    dias_ventas: int = 30, semanas_objetivo: float = 3,
) -> None:
    from rentabilidad.ingesta_ecom_api import EcomApiClient

    _jobs[job_id] = {"status": "running", "log": ["Iniciando simulación de reposición..."], "result": None}
    try:
        ml = MLFullClient()
        ecom = EcomFullAdapter(EcomApiClient(email=ecom_email, password=ecom_password))
        resultado = calcular_reposicion(ml, ecom, dias_ventas=dias_ventas, semanas_objetivo=semanas_objetivo)
        _jobs[job_id]["result"] = {
            "filas": [f.__dict__ for f in resultado.filas],
            "incidencias_sku": resultado.incidencias_sku,
            "incidencias_sin_vincular": resultado.incidencias_sin_vincular,
            "skus_no_en_ecom": resultado.skus_no_en_ecom,
        }
        _jobs[job_id]["status"] = "done"
        _jobs[job_id]["log"].append(f"Listo: {len(resultado.filas)} SKUs calculados.")
    except Exception as e:
        _jobs[job_id]["status"] = "error"
        _jobs[job_id]["log"].append(f"Error: {e}")


def estado_job(job_id: str) -> dict | None:
    return _jobs.get(job_id)
