"""Ayala Core -- motor de precios propio (reverse-markup) para los SKU
piloto que dejan de depender del sistema de precios de Ecom, escribiendo
directo a MercadoLibre. Ver la constitución del módulo:
docs/business/COMERCIAL/canales/mercadolibre/AYALA_CORE.md -- toda regla
de negocio de acá sale de ese documento y del motor real de la planilla
de Maxx ("VENTAS POR CANALES MATIAS", pestañas Calculadora/Motor/Tasas),
NO se inventa nada acá.

La fórmula de `calcular_precio_condicion` es una transcripción exacta de
`Motor!B32:G32` de esa planilla (leída en modo solo-lectura vía la API
pública de Sheets, 2026-09-02) -- reproduce el ejemplo congelado de
AYALA_CORE.md A.3.1 al peso exacto (ver test_ayala_core.py).
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Callable

from ml_auth import SELLERS
from ml_full import _sku_de_item
from ml_ofertas import CUOTAS_PCT_DEFAULT, _cuotas_sin_interes, costo_envio_real_item

# Los 5 SKU piloto (AYALA_CORE.md A.1) -- lista extensible, NO un límite
# estructural: no hardcodear "5" en ningún lado que dependa de esto.
SKUS_PILOTO: list[str] = [
    "PLANCHA-SUB-26X26-PORT",
    "PLANCHA-SUB-30X38-10EN1",
    "PLANCHA-SUB-30X38-5EN1",
    "PLANCHA-SUB-GORRA",
    "PLANCHA-SUB-TERMO",
]

# Tasas del motor -- Tasas!B6:D7 de la planilla real (misma para las dos
# alícuotas hoy, 10,5% y 21%). Se mantienen a mano por Maxx (no vienen de
# la API de ML por dominio, a diferencia de Ofertas ML -- ver AYALA_CORE.md
# A.2/A.3, decisión explícita de Maxx de replicar la planilla tal cual).
COMISION_ML_DEFAULT = Decimal("15.32")
IIBB_PCT_DEFAULT = Decimal("6.50")
ENVIO_FULL_PCT_DEFAULT = Decimal("0.50")  # solo si envío a Bodega (Full), Tasas!D6:D7

# Financiero por condición -- Tasas!C13:C18. Reducida es un 5% FIJO (no
# escala con la cantidad de cuotas -- distinto de cuotas sin interés,
# donde el % sube con la cantidad). Cuotas sin interés reutiliza
# `CUOTAS_PCT_DEFAULT` de `ml_ofertas` -- MISMA tabla, un solo lugar para
# corregir si ML cambia la tasa (ver AYALA_CORE.md, Decisiones tomadas
# 2026-09-02).
REDUCIDA_PCT_DEFAULT = Decimal("5.00")

# Renta objetivo -- Calculadora!B11 (Contado) + B12 ("Diferencial en
# cuotas"). Motor!D31:G31 confirma la cascada real: cada escalón de
# cuotas resta EXACTAMENTE el mismo diferencial sobre el escalón
# anterior (Contado -> Reducida: sin cambio; Reducida -> 3c -> 6c -> 9c
# -> 12c: -2 puntos cada paso). Default 32%/2 puntos reproduce el
# ejemplo de AYALA_CORE.md A.3.1 (32/32/30/28/26/24) -- ambos valores son
# editables por SKU (A.3 punto 7).
RENTA_CONTADO_DEFAULT = Decimal("32.00")
RENTA_DIFERENCIAL_CUOTAS_DEFAULT = Decimal("2.00")

# Cuántos "escalones" de -diferencial% aplican por condición, contados
# desde Contado/Reducida (escalón 0) hasta 12 cuotas (escalón 4).
_ESCALON_POR_CONDICION: dict[str | int, int] = {
    "contado": 0, "reducida": 0, 3: 1, 6: 2, 9: 3, 12: 4,
}

CONDICIONES: tuple[str | int, ...] = ("contado", "reducida", 3, 6, 9, 12)

_IVA_SERVICIOS_ML = Decimal("1.21")  # IVA del servicio/comisión de ML -- SIEMPRE 21%,
# sin importar la alícuota del producto (confirmado en la fórmula real).


def _financiero_pct(condicion: str | int) -> Decimal:
    if condicion == "contado":
        return Decimal("0")
    if condicion == "reducida":
        return REDUCIDA_PCT_DEFAULT
    pct = CUOTAS_PCT_DEFAULT.get(condicion)
    if pct is None:
        raise ValueError(f"condición de pago no soportada: {condicion!r}")
    return pct


def calcular_precio_condicion(
    *,
    costo_sin_iva: Decimal,
    iva_factor: Decimal,
    envio_real: Decimal,
    financiero_pct: Decimal,
    renta_pct: Decimal,
    comision_pct: Decimal = COMISION_ML_DEFAULT,
    iibb_pct: Decimal = IIBB_PCT_DEFAULT,
    envio_full: bool = False,
    envio_full_pct: Decimal = ENVIO_FULL_PCT_DEFAULT,
) -> Decimal:
    """Reverse-markup: resuelve el precio de venta (con IVA) tal que,
    descontando comisión ML, IIBB, el costo financiero de la condición
    de pago, el envío y la renta objetivo, cubre EXACTAMENTE el costo
    del producto. `iva_factor` es 1+alícuota (1,105 o 1,21), igual que
    devuelve `IvaProvider.factor()` en `rentabilidad/adapters.py` --
    pensado para no tener que reconvertir nada al llamar desde ahí.

    Nota real de la planilla: la comisión de ML y el % de Envío Full se
    descuentan siempre sobre 1,21 (el servicio de ML factura IVA 21%
    sin importar la alícuota del producto vendido); el IIBB se descuenta
    sobre la alícuota propia del producto (`iva_factor`)."""
    numerador = costo_sin_iva + envio_real / _IVA_SERVICIOS_ML
    full = (envio_full_pct / 100) if envio_full else Decimal("0")
    denominador = (
        (1 / iva_factor)
        - (comision_pct / 100) / _IVA_SERVICIOS_ML
        - (iibb_pct / 100) / iva_factor
        - (financiero_pct / 100)
        - (renta_pct / 100)
        - full
    )
    return (numerador / denominador).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def calcular_precios_todas_condiciones(
    *,
    costo_sin_iva: Decimal,
    iva_factor: Decimal,
    envio_real: Decimal,
    renta_contado_pct: Decimal = RENTA_CONTADO_DEFAULT,
    diferencial_cuotas_pct: Decimal = RENTA_DIFERENCIAL_CUOTAS_DEFAULT,
    envio_full: bool = False,
    comision_pct: Decimal = COMISION_ML_DEFAULT,
    iibb_pct: Decimal = IIBB_PCT_DEFAULT,
) -> dict[str, Decimal]:
    """El motor completo, las 6 condiciones de una (A.8 punto 2 de
    AYALA_CORE.md: "tabla ... precio calculado por el motor para cada
    condición"). Devuelve un dict con claves 'contado'/'reducida'/'3'/
    '6'/'9'/'12' -- strings, para que sea JSON-friendly tal cual en el
    endpoint."""
    return {
        str(condicion): calcular_precio_condicion(
            costo_sin_iva=costo_sin_iva,
            iva_factor=iva_factor,
            envio_real=envio_real,
            financiero_pct=_financiero_pct(condicion),
            renta_pct=renta_contado_pct - diferencial_cuotas_pct * _ESCALON_POR_CONDICION[condicion],
            comision_pct=comision_pct,
            iibb_pct=iibb_pct,
            envio_full=envio_full,
        )
        for condicion in CONDICIONES
    }


def detectar_condicion_pago(detalle: dict) -> str | int:
    """A.4 de AYALA_CORE.md: la condición de pago se lee en vivo de los
    `tags` reales de la publicación, nunca se carga a mano. `pcj-co-
    funded` = Reducida (ML "3 a 12 cuotas con interés bajo", 5% fijo sin
    importar cuántas cuotas elija el comprador dentro del rango) --
    confirmado en vivo 2026-09-02 (MLA3655836976, cuenta IT) que este tag
    reemplaza a los de cuotas sin interés, son mutuamente excluyentes.
    Si no hay ninguno de los dos, cae a Contado por default."""
    tags = detalle.get("tags") or []
    if "pcj-co-funded" in tags:
        return "reducida"
    cuotas = _cuotas_sin_interes(detalle)
    return cuotas if cuotas else "contado"


def _condicion_por_eliminacion(item_id: str | None, hermanos: list[dict]) -> str | int | None:
    """Dentro de una familia completa (6 hermanas, una por condición --
    A.4/A.5), si exactamente UNA condición no aparece en ninguna tag y
    exactamente UNA condición quedó "duplicada" (dos hermanas con el mismo
    tag, o dos sin tag que caen juntas al default `contado`), la hermana
    de sobra de ese balde duplicado solo puede ser la condición faltante
    -- no hay otra lectura posible con 6 casilleros y 6 hermanas. Cubre
    dos casos reales pedidos por Maxx 2026-09-04:
    1. Tag ausente (MLA3193414376, SKU PLANCHA-SUB-30X38-5EN1, cuenta IT):
       la publicación tiene 6 cuotas reales pero ML no exponía ningún tag
       de cuotas en `/items/{id}` -- su único tag no genérico era
       `standard_price_by_channel` (precio-por-canal Marketplace/Mercado
       Shops, confirmado vía `/items/{id}/prices`, sin relación con
       cuotas) -- cae al default 'contado', duplicando ese balde.
    2. "Pasaje de cuotas": el tag de una hermana quedó mal asignado a OTRA
       condición ya ocupada (ej. dos hermanas con `9x_campaign` cuando una
       en realidad es de 6) -- el balde duplicado puede ser cualquiera,
       no solo 'contado'.
    Para desambiguar cuál de las dos hermanas del balde es la "real" y
    cuál la "huérfana" (la que hay que reasignar) se compara el precio
    contra el orden canónico de costo financiero (`CONDICIONES`, ya
    ordenado de más barato a más caro): si la condición faltante es más
    barata que la del balde duplicado, la huérfana es la de precio más
    bajo del par; si es más cara, la de precio más alto. Deliberadamente
    conservador: ante cualquier ambigüedad (familia incompleta, más de un
    hueco, más de un balde duplicado, balde con más de 2) devuelve `None`
    y quien llama se queda con la detección naive -- nunca inventa una
    condición con más de una lectura posible."""
    if not item_id or len(hermanos) != len(CONDICIONES):
        return None
    por_condicion: dict[str | int, list[dict]] = {}
    for h in hermanos:
        por_condicion.setdefault(detectar_condicion_pago(h), []).append(h)
    faltantes = [c for c in CONDICIONES if c not in por_condicion]
    sobrantes = [c for c, items in por_condicion.items() if len(items) > 1]
    if len(faltantes) != 1 or len(sobrantes) != 1:
        return None
    condicion_faltante = faltantes[0]
    condicion_balde = sobrantes[0]
    balde = por_condicion[condicion_balde]
    if len(balde) != 2:
        return None
    ordenados = sorted(balde, key=lambda h: Decimal(str(h.get("price") or 0)))
    idx_faltante, idx_balde = CONDICIONES.index(condicion_faltante), CONDICIONES.index(condicion_balde)
    huerfano, _real = (ordenados[0], ordenados[1]) if idx_faltante < idx_balde else (ordenados[1], ordenados[0])
    if huerfano.get("item_id") != item_id:
        return None
    return condicion_faltante


def resolver_condicion_pago(
    ml, detalle: dict, cuenta: str, cache_familias: dict[str, list[dict]] | None = None,
) -> str | int:
    """Envoltorio de `detectar_condicion_pago` que siempre cruza contra la
    familia completa (`ml.items_de_producto(user_product_id, cuenta)`,
    A.4/A.5: un MLA por condición) antes de confiar en el tag propio --
    ver `_condicion_por_eliminacion` para los dos casos reales que motivan
    esto (tag ausente y "pasaje de cuotas"/tag duplicado en otra
    condición). Si no hay `user_product_id` (o la familia no tiene
    exactamente 6 o no hay ambigüedad clara) se resigna a la detección
    naive por tag. `cache_familias` opcional evita pedir la misma familia
    dos veces en un mismo escaneo (la comparten hasta 6 hermanas)."""
    condicion = detectar_condicion_pago(detalle)
    user_product_id = detalle.get("user_product_id")
    item_id = detalle.get("id")
    if not user_product_id or not item_id:
        return condicion
    if cache_familias is not None and user_product_id in cache_familias:
        hermanos = cache_familias[user_product_id]
    else:
        try:
            hermanos = ml.items_de_producto(user_product_id, cuenta)
        except Exception:
            hermanos = []
        if cache_familias is not None:
            cache_familias[user_product_id] = hermanos
    override = _condicion_por_eliminacion(item_id, hermanos)
    return override if override is not None else condicion


def descubrir_publicaciones(
    ml, costo_provider, iva_provider, cuentas: list[str], tc: Decimal,
    renta_contado_pct: Decimal = RENTA_CONTADO_DEFAULT,
    diferencial_cuotas_pct: Decimal = RENTA_DIFERENCIAL_CUOTAS_DEFAULT,
    progreso_cb: Callable[[int, int, str], None] | None = None,
    skus_filtro: list[str] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Pedido de Maxx 2026-09-02: "que detecte los SKU solos de las dos
    cuentas" -- escanea TODAS las publicaciones activas de las cuentas
    pedidas (`ml.items_activos`) y se queda solo con las que tienen
    exactamente uno de `skus_filtro` (default `SKUS_PILOTO`, pero
    seleccionable -- pedido 2026-09-03: "que selecciono 1 o varios SKU")
    como SKU (via `_sku_de_item`, `seller_custom_field` o el atributo
    `SELLER_SKU`). Un combo (SKU + otros SKU) nunca matchea exacto a uno
    solo de la lista, así que esto ya cumple la exclusión de combos de
    A.5 -- no hace falta consultar Ecom para esto en particular (Ecom sí
    sigue haciendo falta para casos donde el combo reutiliza el mismo SKU
    sin concatenar, no confirmado todavía que pase acá).

    Cada fila trae también `costo_sin_iva_ars`/`iva_factor` -- pedido
    2026-09-03: el frontend los necesita para recalcular el precio de una
    condición sin referencia de competencia con un margen manual, sin
    tener que pegarle de nuevo al backend por cada tecla que Maxx toca.

    Caro: recorre TODO el catálogo activo (~6.200 publicaciones hoy entre
    las dos cuentas) -- pensado para correr como job de background, no en
    cada carga de pantalla (mismo criterio que `ofertas_propias_activas`).
    `progreso_cb(procesados, total, fase)` opcional, mismo patrón que el
    resto de los escaneos largos de este módulo."""
    skus_validos = skus_filtro or SKUS_PILOTO
    filas: list[dict] = []
    incidencias: list[dict] = []
    cache_familias: dict[str, list[dict]] = {}
    for cuenta in cuentas:
        ids = ml.items_activos(cuenta)

        def _progreso(actual, total, fase, cuenta=cuenta):
            if progreso_cb:
                progreso_cb(actual, total, f"Trayendo catálogo ({cuenta})")

        detalles = ml.detalle_items_ofertas(ids, cuenta, _progreso if progreso_cb else None)
        for d in detalles:
            sku = _sku_de_item(d)
            if sku not in skus_validos:
                continue
            costo_usd = costo_provider.obtener(sku)
            iva_factor = iva_provider.factor(sku)
            if costo_usd is None or iva_factor is None:
                incidencias.append({
                    "item_id": d.get("id"), "cuenta": cuenta, "sku": sku,
                    "motivo": "SIN_COSTO_TACTICA" if costo_usd is None else "SIN_IVA_TACTICA",
                })
                continue
            costo_ars = costo_usd * tc
            condicion = resolver_condicion_pago(ml, d, cuenta, cache_familias)
            try:
                envio_info = costo_envio_real_item(ml, d["id"], cuenta)
            except Exception:
                envio_info = None
            # Corregido 2026-09-03 (bug real, encontrado corriendo el job en
            # vivo: "Error: 'list_cost'"): `costo_envio_real_item` devuelve
            # `costo_envio_real` (ya resuelto a 0 si no es "free"), NUNCA
            # `list_cost` -- esa clave no existe en este dict, ver su
            # docstring/`costo_envio_real` en ml_ofertas.py.
            envio_real = Decimal(str(envio_info["costo_envio_real"])) if envio_info else Decimal(0)
            precios = calcular_precios_todas_condiciones(
                costo_sin_iva=costo_ars, iva_factor=iva_factor, envio_real=envio_real,
                renta_contado_pct=renta_contado_pct, diferencial_cuotas_pct=diferencial_cuotas_pct,
            )
            precio_calculado = precios[str(condicion)]
            precio_actual = Decimal(str(d.get("price") or 0))
            # Pedido de Maxx 2026-09-04: mostrar en la tabla si la
            # publicación YA tiene un precio tachado puesto en ML
            # (`original_price`, ya venía pedido en el batch desde
            # 2026-09-02, solo faltaba exponerlo acá).
            tachado_actual = d.get("original_price")
            filas.append({
                "cuenta": cuenta, "item_id": d.get("id"), "sku": sku, "titulo": d.get("title", ""),
                "permalink": d.get("permalink"), "condicion_detectada": condicion,
                "precio_actual": precio_actual, "precio_calculado": precio_calculado,
                "diferencia": precio_actual - precio_calculado, "envio_real": envio_real,
                "costo_sin_iva_ars": costo_ars, "iva_factor": iva_factor,
                "precio_tachado_actual": Decimal(str(tachado_actual)) if tachado_actual else None,
            })
    return filas, incidencias


def resolver_competencia_por_producto(ml, product_id: str, cuenta: str = "IT") -> list[dict]:
    """Pedido de Maxx 2026-09-03: encontró un competidor vendiendo casi al
    mismo precio que él pero en 9 cuotas -- eso lo deja afuera de las
    ventas en cuotas para tickets altos. Trae precio/condición de CADA
    vendedor real que compite en una ficha de producto, para comparar "en
    las mismas condiciones" en vez de a ciegas contra el costo.

    `product_id` es el ID de la ficha de catálogo (el `MLA...` que
    aparece en la URL después de `/p/` en la página de "Opciones de
    compra" de ML) -- NO el `item_id` de una publicación puntual.

    **Corregido 2026-09-03** (encontrado al responder "¿de dónde lo va a
    detectar?"): la primera versión pedía `GET /items/{item_id}` de la
    publicación del competidor -- confirmado en vivo que ESE endpoint
    está gateado por ownership para publicaciones ajenas (403
    `access_denied`, con y sin auth, hasta pidiendo solo campos
    públicos). Scrapear la página pública tampoco es opción: ML sirve una
    interstitial de "tráfico sospechoso" ante un `requests.get` con
    User-Agent de navegador -- es bot-detection real, no se intenta
    evadir (política del proyecto). La salida real es
    `ml.items_de_producto()` (`GET /products/{id}/items`), que SÍ trae
    todos los vendedores -- se descartan los que son cuentas propias
    (`SELLERS`) para quedarse solo con competencia real."""
    propios = set(SELLERS.values())
    ofertas = ml.items_de_producto(product_id, cuenta)
    return [
        {
            "item_id": o.get("item_id"), "seller_id": o.get("seller_id"),
            "precio": o.get("price"), "precio_tachado": o.get("original_price"),
            "condicion_detectada": detectar_condicion_pago(o),
        }
        for o in ofertas
        if str(o.get("seller_id")) not in propios
    ]


# ── Job en background -- mismo patrón que ml_ofertas.py/ml_full.py ──

_jobs: dict = {}


_CAMPOS_DECIMAL = ("precio_actual", "precio_calculado", "diferencia", "envio_real", "costo_sin_iva_ars", "iva_factor")


def iniciar_job_publicaciones(
    job_id: str, cuentas: list[str] | None = None, tc: float = 0,
    renta_contado: float = float(RENTA_CONTADO_DEFAULT),
    diferencial_cuotas: float = float(RENTA_DIFERENCIAL_CUOTAS_DEFAULT),
    skus: list[str] | None = None,
) -> None:
    _jobs[job_id] = {"status": "running", "log": ["Escaneando publicaciones activas..."], "result": None, "progress": None}
    try:
        from ml_ofertas import MLOfertasClient
        from rentabilidad.adapters import CostoVigenteProvider, IvaProvider

        ml = MLOfertasClient()
        costo_provider = CostoVigenteProvider()
        iva_provider = IvaProvider()
        tc_decimal = Decimal(str(tc)) if tc else Decimal(1)

        def _progreso(actual, total, label):
            _jobs[job_id]["progress"] = {"current": actual, "total": total, "label": label}

        filas, incidencias = descubrir_publicaciones(
            ml, costo_provider, iva_provider, cuentas or list(SELLERS.keys()), tc_decimal,
            renta_contado_pct=Decimal(str(renta_contado)), diferencial_cuotas_pct=Decimal(str(diferencial_cuotas)),
            progreso_cb=_progreso, skus_filtro=skus,
        )
        _jobs[job_id]["progress"] = None
        _jobs[job_id]["result"] = {
            "filas": [{
                **{k: v for k, v in f.items() if k not in _CAMPOS_DECIMAL},
                **{k: float(f[k]) for k in _CAMPOS_DECIMAL},
            } for f in filas],
            "incidencias": incidencias,
        }
        _jobs[job_id]["status"] = "done"
        _jobs[job_id]["log"].append(f"Listo: {len(filas)} publicaciones de los SKU piloto encontradas.")
    except Exception as e:
        _jobs[job_id]["status"] = "error"
        _jobs[job_id]["log"].append(f"Error: {e}")


def estado_job(job_id: str):
    return _jobs.get(job_id)
