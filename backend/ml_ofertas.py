"""
Ofertas ML — margen real de cada promoción/campaña activa, en las dos cuentas.

Fases 1 y 2 de `docs/business/COMERCIAL/canales/mercadolibre/REQ_MODULO_OFERTAS_ML.md`
(lectura + alertas). **Solo lectura** — no crea, edita ni da de baja ninguna
oferta en ML (Fase 3, gateada por `docs/business/COMERCIAL/00_LEEME.md` §5,
no implementada acá).

**Fórmula canónica (REQ §2.0), corregida 2026-08-27 por Maxx en vivo:**

    base_sin_iva   = precio_oferta / (1 + iva_pct)
    comision       = precio_oferta × comisión_por_dominio_ML  (o general si no está en la tabla)
    costo_fijo     = tramo_por_precio(precio_oferta)          # 1255/2500/3030/0, solo <33k
    cuotas         = precio_oferta × cuotas_pct                # 0 si no ofrece cuotas
    envio          = tramo_por_precio(precio_oferta)           # 0 si <33k, con descuento MercadoLíder Platinum si aplica
    imp_cheque     = precio_oferta × 1,2%                      # sobre el precio CON IVA (bruto)
    iibb           = base_sin_iva × 5%                         # sobre el precio SIN IVA (neto) -- NO sobre precio_oferta
    costo_producto = costo_sin_iva_desde_TACTICA × TC          # nunca del PM Sheet

    margen_$  = base_sin_iva − comision − costo_fijo − cuotas − envio − imp_cheque − iibb − costo_producto
    margen_%  = margen_$ / base_sin_iva

Nota histórica: la primera versión de este módulo ponía IIBB también sobre
`precio_oferta` (bruto), documentado en ese momento como una divergencia
deliberada del panel viejo de Competidores ML (`compMargenAt` en
`docs/index.html`, que sí restaba IIBB sobre el neto) por una lectura
literal del REQ §1.2.c/§2.0. Maxx corrigió esto en vivo el 2026-08-27:
Imp. Cheque va sobre el bruto, IIBB va sobre el neto -- no son la misma
base, y el panel viejo tenía razón en eso. El REQ y este módulo quedan
actualizados a este criterio; no es una reinterpretación propia, es la
corrección que dio la dirección.

**Categoría → comisión, por `domain_id`, no por nombre de categoría.**
`category_id` de una publicación no es estable como clave de negocio (dos
categorías con nombres parecidos pueden tener ids distintos, y el nombre
público de `/categories/{id}` no siempre coincide con el nombre de dominio
"de negocio"). El campo correcto es `domain_id` -- ya viene directo en
`/items/{id}` sin pedir nada aparte, y singular contra la cuenta real
(2026-08-27) coincide EXACTO con las 15 categorías del REQ §6 vía
`GET /sites/MLA/domain_discovery/search?q=<nombre>` (`domain_name` en la
respuesta es literalmente el mismo texto que usó Maxx para relevar la
tabla). Mapeo verificado uno por uno, no adivinado:

| Categoría (REQ §6)                  | domain_id                              |
|--------------------------------------|-----------------------------------------|
| Tóners                               | MLA-TONERS                              |
| Cartuchos de tinta                   | MLA-INK_CARTRIDGES                      |
| Rollos y planchas de vinilo          | MLA-VINYL_ROLLS_AND_SHEETS              |
| Tintas para impresoras               | MLA-PRINTER_INKS                        |
| Papeles de librería y oficina        | MLA-SCHOOL_AND_OFFICE_PAPERS            |
| Filamentos para impresora 3D         | MLA-3D_PRINTER_FILAMENTS                |
| Fundas para notebooks y netbooks     | MLA-LAPTOP_CASES                        |
| Auriculares                          | MLA-HEADPHONES                          |
| Estampadoras                         | MLA-SCREEN_PRINTERS                     |
| Sistemas de tinta continuos          | MLA-CONTINUOUS_INK_SYSTEMS              |
| Cintas para impresora                | MLA-PRINTER_RIBBONS                     |
| Calculadoras                         | MLA-CALCULATORS                         |
| Gorros y sombreros                   | MLA-HATS_AND_CAPS                       |
| Tapas para encuadernación            | MLA-BINDING_COVERS                      |
| Anilladoras                          | MLA-COIL_BINDING_MACHINES               |

Cualquier `domain_id` fuera de esta tabla usa `comision_general` (default
15,5%, editable) -- nunca se asume una de las 15 tasas específicas para un
dominio no confirmado.

**Ofertas activas — dos mecanismos de ML, cubren "campañas mías" y
"campañas de ML" de forma barata; "ofertas propias" (`PRICE_DISCOUNT`)
queda para un pase aparte, ver `ofertas_propias_activas`.**

Confirmado contra la cuenta real (2026-08-27), no de memoria ni del mapa
(el mapa no tenía el endpoint):
1. `GET /seller-promotions/users/{seller_id}?app_version=v2` -- lista TODAS
   las promociones/campañas del vendedor (propias tipo `SELLER_CAMPAIGN`/
   `SELLER_COUPON_CAMPAIGN`, y de ML tipo `DEAL`/`SMART`/`PRICE_MATCHING`/
   `PRE_NEGOTIATED`/`UNHEALTHY_STOCK`/`LIGHTNING`/`MARKETPLACE_CAMPAIGN`),
   con `status` (`started` = activa ahora, `pending` = todavía no arrancó,
   etc.). ~20 promociones reales por cuenta -- barato, una sola llamada.
2. `GET /seller-promotions/promotions/{id}/items?promotion_type=<tipo>&app_version=v2`
   -- lista los ítems efectivamente enrolados en ESA promoción puntual, con
   su precio activo. Se llama solo para las promociones con `status=started`
   del paso 1 -- nunca para todo el catálogo.

`PRICE_DISCOUNT` (descuento individual cargado por el vendedor) **no
aparece en el listado del vendedor** -- no es una "campaña" con id propia,
es un estado por publicación. La única forma confirmada de saberlo es
`GET /seller-promotions/items/{item_id}?app_version=v2` por ítem (mismo
endpoint que ya usaba `docs/index.html` para el DELETE al salir de una
oferta) -- cubrir esto para las ~6.200 publicaciones activas de las dos
cuentas es un escaneo caro (una llamada por ítem), separado a propósito de
la lectura de campañas para no bloquearla ni compartir su presupuesto de
llamadas.

**Escritura de precio (`activar_oferta_propia`) -- hallazgo crítico
confirmado navegando developers.mercadolibre.com.ar en vivo (2026-08-28):**
el `PUT /items/{id}` con `price`/`original_price` puede devolver 200 OK
e IGNORAR el cambio en silencio -- documentado como comportamiento oficial
desde el 18/03/2026 (`api-de-precios`, act. 2026-02-26): "las solicitudes
que incluyan `price` junto con otros atributos serán procesadas con un
200 OK, sin embargo, el valor enviado en `price` será ignorado y la
respuesta devolverá un warning". Esos campos están en proceso de
deprecación, y una publicación puede tener automatización de precios
activa que también ignore el PUT. Por eso `activar_oferta_propia` hace un
GET aparte después de escribir para confirmar el estado real -- nunca
confía en el eco de la respuesta del PUT. Ítems con precio mayorista/B2B
tienen su propio endpoint (`POST /items/{id}/prices/standard/quantity`,
`developers.mercadolibre.com.ar/es_ar/precio-por-cantidad`), no
implementado acá -- si un ítem lo tiene, este módulo no es el camino
correcto para tocarle el precio.

Reglas reales de elegibilidad del tachado (`descuento-individual`, act.
2026-06-09): reputación verde, ítem activo, condición nuevo, exposición
no gratuita (no aplica a libros en MLA), descuento entre 5% y <80%,
precio "creíble" (si no, `error_credibility_price`), y si el ítem está en
un DEAL activo el descuento individual no se aplica hasta que ese DEAL
termine.

`has_bids`: buscado explícitamente en la documentación pública
(2026-08-28) -- NO está documentado en ninguna página de Precios,
Promociones ni Validaciones. Se mantiene el manejo empírico sin asumir
que sea exclusivo de pujas de subasta.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable

import requests

from ml_auth import SELLERS
from ml_full import GetFn, MLFullClient

# ── Parámetros de margen -- valores por defecto del REQ §1.2.b/§2.0/§6,
# todos editables en runtime vía ParametrosMargen (nunca hardcodeados en la
# fórmula misma). ──

COMISION_POR_DOMINIO_DEFAULT: dict[str, Decimal] = {
    "MLA-TONERS": Decimal("15.5"),
    "MLA-INK_CARTRIDGES": Decimal("15.5"),
    "MLA-VINYL_ROLLS_AND_SHEETS": Decimal("14.3"),
    "MLA-PRINTER_INKS": Decimal("15.5"),
    "MLA-SCHOOL_AND_OFFICE_PAPERS": Decimal("15.0"),
    "MLA-3D_PRINTER_FILAMENTS": Decimal("15.5"),
    "MLA-LAPTOP_CASES": Decimal("15.5"),
    "MLA-HEADPHONES": Decimal("15.5"),
    "MLA-SCREEN_PRINTERS": Decimal("14.5"),
    "MLA-CONTINUOUS_INK_SYSTEMS": Decimal("15.5"),
    "MLA-PRINTER_RIBBONS": Decimal("15.5"),
    "MLA-CALCULATORS": Decimal("15.0"),
    "MLA-HATS_AND_CAPS": Decimal("15.5"),
    "MLA-BINDING_COVERS": Decimal("15.0"),
    "MLA-COIL_BINDING_MACHINES": Decimal("15.0"),
}
COMISION_GENERAL_DEFAULT = Decimal("15.5")

# Costo fijo por unidad vendida (logística Flex/acuerdo/retiro), solo <33k.
# (techo_precio, monto) ascendente + catch-all final (techo=None).
COSTO_FIJO_TRAMOS_DEFAULT: list[tuple[Decimal | None, Decimal]] = [
    (Decimal(16000), Decimal(1255)),
    (Decimal(24000), Decimal(2500)),
    (Decimal(33000), Decimal(3030)),
    (None, Decimal(0)),
]

# % que se SUMA al cargo por vender cuando la oferta ofrece cuotas sin
# interés. 18 cuotas no existe en ML Argentina hoy (REQ §1.2.b) -- no está.
CUOTAS_PCT_DEFAULT: dict[int, Decimal] = {
    3: Decimal("8.40"), 6: Decimal("12.30"), 9: Decimal("15.70"), 12: Decimal("19.20"),
}

# Envío con descuento por reputación (MercadoLíder Platinum). (techo, monto).
# Corregido 2026-08-27 (Maxx, en vivo -- "si no sale más de 33000 no tiene
# envío, eso es fijo"): por debajo de $33.000 no hay envío gratis obligado,
# así que el costo es 0 -- el vendedor "absorbe el envío" recién a partir
# de ese umbral (REQ_MODULO_OFERTAS_ML.md §1.2, línea de contexto sobre el
# umbral, y §2.0 "envio = regla_envio(precio_oferta) # 0 si <33k"). El
# mismo REQ §1.2 tenía una tabla con "<$33.000 → $9.800" que se contradice
# con esas dos líneas -- se trata como error de transcripción, no como
# regla real: valores de $33.000-$49.999 y $50.000+ se mantienen tal cual
# estaban (7000/7470), el techo de <33.000 pasa a valer 0.
ENVIO_TRAMOS_DEFAULT: list[tuple[Decimal | None, Decimal]] = [
    (Decimal(33000), Decimal(0)),
    (Decimal(50000), Decimal(7000)),
    (None, Decimal(7470)),
]

IMP_CHEQUE_PCT_DEFAULT = Decimal("1.2")
IIBB_PCT_DEFAULT = Decimal("5")


def _por_tramo(precio: Decimal, tramos: list[tuple[Decimal | None, Decimal]]) -> Decimal:
    """Primer tramo cuyo techo el precio no alcanza; `None` = catch-all."""
    for techo, monto in tramos:
        if techo is None or precio < techo:
            return monto
    return Decimal(0)


@dataclass
class ParametrosMargen:
    """Todo lo que el REQ pide editable con on/off (§2.0), con los valores
    confirmados como default. TC y el costo del producto NO viven acá --
    se resuelven antes de llamar a `calcular_margen_oferta` (TC porque es
    un valor, no un descuento; costo porque sale de Táctica por SKU)."""
    comision_por_dominio: dict[str, Decimal] = field(default_factory=lambda: dict(COMISION_POR_DOMINIO_DEFAULT))
    comision_general: Decimal = COMISION_GENERAL_DEFAULT
    costo_fijo_tramos: list[tuple[Decimal | None, Decimal]] = field(default_factory=lambda: list(COSTO_FIJO_TRAMOS_DEFAULT))
    cuotas_pct: dict[int, Decimal] = field(default_factory=lambda: dict(CUOTAS_PCT_DEFAULT))
    envio_tramos: list[tuple[Decimal | None, Decimal]] = field(default_factory=lambda: list(ENVIO_TRAMOS_DEFAULT))
    imp_cheque_pct: Decimal = IMP_CHEQUE_PCT_DEFAULT
    iibb_pct: Decimal = IIBB_PCT_DEFAULT
    usar_comision: bool = True
    usar_costo_fijo: bool = True
    usar_cuotas: bool = True
    usar_envio: bool = True
    usar_imp_cheque: bool = True
    usar_iibb: bool = True


@dataclass
class ResultadoMargenOferta:
    base_sin_iva: Decimal
    comision: Decimal
    costo_fijo: Decimal
    cuotas: Decimal
    envio: Decimal
    imp_cheque: Decimal
    iibb: Decimal
    costo_producto: Decimal
    margen: Decimal
    margen_pct: Decimal | None  # None si base_sin_iva es 0 -- no hay sobre qué medir


def calcular_margen_oferta(
    precio_oferta: Decimal, iva_factor: Decimal, costo_producto_ars: Decimal,
    domain_id: str | None, cuotas_ofrecidas: int | None, params: ParametrosMargen,
) -> ResultadoMargenOferta:
    """Fórmula canónica REQ §2.0, literal -- ver docstring del módulo para
    el porqué de cada base imponible. `iva_factor` y `costo_producto_ars`
    vienen resueltos por el llamador (Táctica, nunca el PM Sheet)."""
    base_sin_iva = precio_oferta / iva_factor

    comision_pct = params.comision_por_dominio.get(domain_id, params.comision_general) if domain_id else params.comision_general
    comision = (precio_oferta * comision_pct / 100) if params.usar_comision else Decimal(0)

    costo_fijo = _por_tramo(precio_oferta, params.costo_fijo_tramos) if params.usar_costo_fijo else Decimal(0)

    cuotas_pct = params.cuotas_pct.get(cuotas_ofrecidas, Decimal(0)) if cuotas_ofrecidas else Decimal(0)
    cuotas = (precio_oferta * cuotas_pct / 100) if params.usar_cuotas else Decimal(0)

    envio = _por_tramo(precio_oferta, params.envio_tramos) if params.usar_envio else Decimal(0)

    # Corregido 2026-08-27 (Maxx, en vivo): Imp. Cheque va sobre el precio
    # CON IVA (precio_oferta, bruto) -- IIBB va sobre el precio SIN IVA
    # (base_sin_iva). No son la misma base. Esto corrige lo que decía el
    # docstring del módulo (que asumía las dos sobre precio bruto).
    imp_cheque = (precio_oferta * params.imp_cheque_pct / 100) if params.usar_imp_cheque else Decimal(0)
    iibb = (base_sin_iva * params.iibb_pct / 100) if params.usar_iibb else Decimal(0)

    margen = base_sin_iva - comision - costo_fijo - cuotas - envio - imp_cheque - iibb - costo_producto_ars
    margen_pct = (margen / base_sin_iva) if base_sin_iva else None

    return ResultadoMargenOferta(
        base_sin_iva=base_sin_iva, comision=comision, costo_fijo=costo_fijo, cuotas=cuotas,
        envio=envio, imp_cheque=imp_cheque, iibb=iibb, costo_producto=costo_producto_ars,
        margen=margen, margen_pct=margen_pct,
    )


# ── Cliente ML — extiende MLFullClient (mismo transporte con retry/backoff
# ante 429/503, mismo items_activos) con lo específico de Ofertas. ──

class MLOfertasClient(MLFullClient):
    def promociones_seller(self, cuenta: str) -> list[dict]:
        """Campañas del vendedor (propias y de ML) -- barato, una sola
        llamada, ~20 resultados reales por cuenta (confirmado 2026-08-27).
        NO incluye `PRICE_DISCOUNT` (ver docstring del módulo)."""
        seller_id = SELLERS[cuenta]
        headers = {"Authorization": f"Bearer {self._token(cuenta)}"}
        d = self._get(
            f"https://api.mercadolibre.com/seller-promotions/users/{seller_id}",
            {"app_version": "v2"}, headers,
        )
        # `.get("results", [])` no alcanza: el default de `.get` solo
        # aplica si la clave FALTA, no si está presente con valor `None`.
        # La primera corrida real (2026-08-27) tiró "'NoneType' object is
        # not iterable" acá -- indica que para al menos una cuenta ML
        # devolvió `"results": null` explícito en vez de `[]` u omitir la
        # clave. No se pudo confirmar el caso exacto sin logs de esa
        # corrida, pero el fix cubre cualquiera de las dos formas.
        return (d or {}).get("results") or []

    def items_de_promocion(self, promotion_id: str, promotion_type: str, cuenta: str) -> list[dict]:
        """Ítems efectivamente enrolados (no candidatos) en una campaña
        puntual, con su precio activo -- `status=started` server-side es
        lo que evita traer los candidatos (pueden ser miles, confirmado:
        una sola campaña real tenía 2283 candidatos contra 343
        efectivamente activos). Pagina con el cursor `searchAfter` de la
        respuesta -- confirmado que el parámetro para pedir la página
        siguiente es `search_after` (snake_case), distinto del nombre de
        campo de la respuesta."""
        headers = {"Authorization": f"Bearer {self._token(cuenta)}"}
        params = {"promotion_type": promotion_type, "app_version": "v2", "status": "started", "limit": 50}
        salida: list[dict] = []
        while True:
            d = self._get(
                f"https://api.mercadolibre.com/seller-promotions/promotions/{promotion_id}/items", params, headers,
            )
            resultados = (d or {}).get("results") or []
            salida.extend(resultados)
            cursor = (d.get("paging") or {}).get("searchAfter")
            if not cursor or not resultados:
                break
            params = {**params, "search_after": cursor}
        return salida

    def promociones_item(self, item_id: str, cuenta: str) -> list[dict]:
        """Todas las promociones (candidatas y activas, de cualquier tipo)
        de UNA publicación puntual -- mismo endpoint que ya usaba
        `docs/index.html` para el DELETE al salir de una oferta. Devuelve
        una lista plana, no envuelta en `results` (confirmado 2026-08-27,
        distinto de los otros dos endpoints de este cliente)."""
        headers = {"Authorization": f"Bearer {self._token(cuenta)}"}
        return self._get(
            f"https://api.mercadolibre.com/seller-promotions/items/{item_id}", {"app_version": "v2"}, headers,
        ) or []

    def detalle_items_ofertas(self, item_ids: list[str], cuenta: str,
                               progreso_cb: Callable[[int, int, str], None] | None = None) -> list[dict]:
        """SKU/categoría/título/cuotas por lote de 20 -- `domain_id` viene
        directo acá, sin pedir nada aparte (ver docstring del módulo).
        `progreso_cb(procesados, total, "catalogo")` opcional -- este lote
        de llamadas (hasta ~310 para un escaneo completo de ofertas
        propias) es buena parte del tiempo "muerto" que veía Maxx antes de
        que arrancara a reportar progreso el loop de promociones."""
        headers = {"Authorization": f"Bearer {self._token(cuenta)}"}
        salida: list[dict] = []
        total = len(item_ids)
        for i in range(0, total, 20):
            if progreso_cb:
                progreso_cb(i, total, "catalogo")
            lote = item_ids[i:i + 20]
            d = self._get(
                "https://api.mercadolibre.com/items",
                {"ids": ",".join(lote), "attributes": "id,title,permalink,seller_custom_field,domain_id,installments"},
                headers,
            )
            for entrada in (d or []):
                cuerpo = entrada.get("body") if isinstance(entrada, dict) and "body" in entrada else entrada
                if cuerpo:
                    salida.append(cuerpo)
        if progreso_cb:
            progreso_cb(total, total, "catalogo")
        return salida

    def detalle_item_completo(self, item_id: str, cuenta: str) -> dict:
        """UN ítem, con `price` -- distinto de `detalle_items_ofertas`
        (que es para lotes de hasta 20 y no pide `price`, porque cada
        promoción ya trae el suyo). Para "buscar un MLA puntual, tenga o
        no oferta activa, y armar la fila a mano" (pedido 2026-08-27:
        activar una oferta nueva en una publicación que hoy no tiene
        ninguna, no solo gestionar las que ya aparecen en el escaneo de
        campañas)."""
        headers = {"Authorization": f"Bearer {self._token(cuenta)}"}
        return self._get(
            f"https://api.mercadolibre.com/items/{item_id}",
            {"attributes": "id,title,price,permalink,seller_custom_field,domain_id,installments"}, headers,
        )


# ── Fase 3 — escritura (activar / sacar de UNA promoción puntual) ──
# Habilitada 2026-08-27 por decisión explícita de Maxx: el criterio
# original del gate de `docs/business/COMERCIAL/00_LEEME.md` §5 (motor de
# rentabilidad en vivo + suite de regresión al centavo) quedó obsoleto -- el
# cierre real de Rentabilidad pasó por otro camino (rentabilidad histórica
# vía snapshots de período, ver §5 actualizado del LEEME). La escritura
# queda habilitada SOLO para este módulo, no para el resto de Comercial.
#
# El "sacar" tiene que ser selectivo por promoción (pedido explícito, no
# el baja-todo que ya usa `docs/index.html`/`ofertasDeletePromo`). Contrato
# verificado 2026-08-27 contra la documentación oficial de ML
# (developers.mercadolibre.com.ar: Manage Promotions / Seller Campaigns /
# Price Discount) -- MISMO endpoint que ya usa el código viejo
# (`DELETE seller-promotions/items/{id}`), acotado con querystring:
#   - Descuento propio:  ?promotion_type=PRICE_DISCOUNT&app_version=v2
#   - Campaña puntual:   ?promotion_type=SELLER_CAMPAIGN&promotion_id={id}&app_version=v2
# TODAVÍA NO verificado contra una llamada real (sin credenciales de ML en
# el entorno local que armó este módulo) -- la primera ejecución real es,
# a propósito, sobre una sola publicación de baja rotación elegida por
# Maxx, antes de usarlo en volumen.

def _put_real(url: str, headers: dict, body: dict):
    """Mismo retry/backoff que `_get_real` de `ml_full.py` ante 429/503."""
    ultimo_error = None
    for intento in range(4):
        r = requests.put(url, json=body, headers=headers, timeout=20)
        if r.status_code in (429, 503):
            ultimo_error = r
            if intento < 3:
                time.sleep(float(r.headers.get("Retry-After", 2 ** (intento + 1))))
                continue
        try:
            return r.json()
        except ValueError:
            r.raise_for_status()
            raise
    ultimo_error.raise_for_status()


def _delete_real(url: str, params: dict, headers: dict):
    ultimo_error = None
    for intento in range(4):
        r = requests.delete(url, params=params, headers=headers, timeout=20)
        if r.status_code in (429, 503):
            ultimo_error = r
            if intento < 3:
                time.sleep(float(r.headers.get("Retry-After", 2 ** (intento + 1))))
                continue
        try:
            return r.json()
        except ValueError:
            r.raise_for_status()
            raise
    ultimo_error.raise_for_status()


def _post_real(url: str, headers: dict, body: dict):
    ultimo_error = None
    for intento in range(4):
        r = requests.post(url, json=body, headers=headers, timeout=20)
        if r.status_code in (429, 503):
            ultimo_error = r
            if intento < 3:
                time.sleep(float(r.headers.get("Retry-After", 2 ** (intento + 1))))
                continue
        try:
            return r.json()
        except ValueError:
            r.raise_for_status()
            raise
    ultimo_error.raise_for_status()


def _explicar_has_bids(mensaje_ml: str, estado_item: dict | None = None) -> str:
    """`has_bids` no está documentado en developers.mercadolibre.com.ar
    (buscado explícitamente 2026-08-28, ver docstring del módulo).

    Caso 1 confirmado con datos reales (MLA852181648, 2026-08-28): precio
    mayorista/B2B (`standard_price_by_quantity` en `tags`) -- esos ítems
    tienen su PROPIO endpoint de precio (`POST /items/{id}/prices/
    standard/quantity`, developers.mercadolibre.com.ar/es_ar/
    precio-por-cantidad, no implementado acá), `has_bids` ahí es
    probablemente un código reusado por ML para "el precio no se maneja
    por acá".

    Caso 2 (MLA627267951, 2026-08-28): mismo error, SIN ese tag -- la
    hipótesis de "ofertas de compradores pendientes" quedó descartada por
    Maxx en vivo (si fuera por eso, ML tampoco debería dejar editar el
    precio a mano DENTRO de ML, y no hay evidencia de que pase). Causa
    real todavía sin confirmar para este caso. En vez de seguir
    adivinando, se manda `buying_mode`/`sub_status`/`status` crudos en el
    mensaje -- son los campos más directos para diagnosticarlo (si
    `buying_mode` fuera literal `auction`, confirmaría pujas reales; si
    es `buy_it_now` como es lo normal en MLA hoy, descarta esa lectura
    literal del nombre del campo)."""
    estado_item = estado_item or {}
    tags = estado_item.get("tags") or []
    if "standard_price_by_quantity" in tags:
        return (f"ML rechaza el cambio de precio (mensaje real: \"{mensaje_ml}\"). Esta publicación tiene precio "
                "mayorista/por cantidad (tag `standard_price_by_quantity`) -- ese tipo de publicación tiene su propio "
                "endpoint de precio en la API de ML, distinto del que usa este módulo, y no está implementado acá. "
                "No se puede activar una oferta con precio simple sobre esta publicación desde el ERP por ahora.")
    diagnostico = (f"buying_mode={estado_item.get('buying_mode')!r}, sub_status={estado_item.get('sub_status')!r}, "
                   f"status={estado_item.get('status')!r}, tags={tags!r}")
    return (f"ML no permite cambiar el precio de esta publicación ahora mismo (mensaje real: \"{mensaje_ml}\"). "
            "No tiene precio mayorista ni tachado previo, así que ninguna de las dos hipótesis que ya probamos "
            f"explica esto. Causa real no confirmada -- estado crudo del ítem para diagnosticar: {diagnostico}. "
            "Revisá la publicación directo en ML antes de reintentar.")


class MLOfertasEscritura(MLOfertasClient):
    """Único punto de escritura del módulo. Separado de `MLOfertasClient`
    (que hereda `_get` de `MLFullClient`, documentado ahí como "solo
    lectura del lado Mercado Libre") para no volver ambiguo ese contrato --
    los jobs de lectura de Fase 1/2 siguen instanciando `MLOfertasClient`
    a secas, nunca esta clase. `put_fn`/`delete_fn`/`post_fn` inyectables,
    mismo patrón `get_fn`/`token_fn` que el resto del módulo."""

    def __init__(self, get_fn: GetFn | None = None, token_fn: Callable[[str], str] | None = None,
                 put_fn: Callable[[str, dict, dict], object] | None = None,
                 delete_fn: Callable[[str, dict, dict], object] | None = None,
                 post_fn: Callable[[str, dict, dict], object] | None = None):
        super().__init__(get_fn=get_fn, token_fn=token_fn)
        self._put = put_fn or _put_real
        self._delete = delete_fn or _delete_real
        self._post = post_fn or _post_real

    def activar_oferta_propia(self, item_id: str, cuenta: str, precio: Decimal, precio_tachado: Decimal) -> dict:
        """`PUT items/{id}` con `price`+`original_price`.

        **No confiar en lo que devuelve el PUT -- verificado contra la
        documentación oficial 2026-08-28
        (developers.mercadolibre.com.ar/es_ar/api-de-precios, act.
        2026-02-26): "A partir del 18 de marzo de 2026, las solicitudes
        que actualicen únicamente el campo `price` serán rechazadas con
        un 400 Bad Request. Las solicitudes que incluyan `price` junto
        con otros atributos serán procesadas con un 200 OK, sin embargo,
        el valor enviado en `price` será ignorado y la respuesta
        devolverá un warning informando que el precio no fue
        actualizado." Además `price`/`base_price`/`original_price` de
        `/items` están en proceso de deprecación, y una publicación puede
        tener automatización de precios activa que ignore este PUT por
        completo. Esto explica los dos casos reales de esta sesión
        (MLA875537547: tachado no aplicado con 200 OK; MLA852181648,
        precio mayorista: ni el precio se aplicó) -- el PUT puede devolver
        éxito y hacer eco del valor que vos mandaste SIN haberlo aplicado,
        así que la respuesta del PUT no sirve para confirmar nada. Por
        eso acá se hace un GET aparte después de escribir, para chequear
        el estado real.

        Reglas reales de elegibilidad para que el tachado (`PRICE_DISCOUNT`)
        se aplique, confirmadas en developers.mercadolibre.com.ar/es_ar/
        descuento-individual (act. 2026-06-09): reputación verde, ítem
        activo, condición nuevo, exposición no gratuita (no aplica a
        libros en MLA), descuento entre 5% y <80%, precio "creíble" (si
        no, `error_credibility_price`), y si el ítem está en un DEAL
        activo el descuento individual no se aplica hasta que termine ese
        DEAL. Subir el precio del ítem saca los descuentos solo. Hay
        estados asíncronos (`sync_requested`/`restore_requested`) -- el
        GET de verificación puede no reflejar el cambio al instante.

        Precio mayorista/B2B tiene su PROPIO endpoint, no este:
        `POST /items/{id}/prices/standard/quantity` (o la variante % B2B,
        developers.mercadolibre.com.ar/es_ar/precio-por-cantidad) -- no
        implementado acá, si un ítem tiene precio mayorista este método
        no es el camino correcto para tocarle el precio.

        `has_bids`: buscado en la documentación pública 2026-08-28 (API
        de Precios, Referencias de precios, Validaciones, Sincroniza y
        modifica publicaciones) -- NO está documentado. No se sabe si es
        exclusivo de pujas de subasta o cubre otras restricciones; se
        mantiene el fallback empírico de abajo sin asumir la causa."""
        headers = {"Authorization": f"Bearer {self._token(cuenta)}", "Content-Type": "application/json"}
        url = f"https://api.mercadolibre.com/items/{item_id}"
        aviso_ml = None

        d = self._put(url, headers, {"price": float(precio), "original_price": float(precio_tachado)}) or {}
        if not d.get("id"):
            if d.get("error") == "validation_error" and "has_bids" in (d.get("message") or ""):
                mensaje_ml = d.get("message") or "has_bids"
                # Reintento con price=original_price=precio_tachado (dos
                # atributos, no la regla de "solo price" -> 400) -- sin
                # descuento real, solo para ver si al menos el precio base
                # se puede tocar. Corregido 2026-08-28: antes mandaba SOLO
                # `price`, que ahora siempre da 400 de por sí (ver
                # docstring del módulo) -- ese reintento estaba condenado
                # a fallar en un paso distinto, sin relación con has_bids.
                self._put(url, headers, {"price": float(precio_tachado), "original_price": float(precio_tachado)})
                # `tags` va en el mismo GET de verificación de abajo (no
                # una llamada aparte) -- para distinguir "es precio
                # mayorista" de "causa desconocida" en el aviso, ver
                # `_explicar_has_bids`.
                mensaje_bids = mensaje_ml
            else:
                return {"ok": False, "error": d.get("message") or str(d)}
        else:
            mensaje_bids = None

        estado = self._get(url, {"attributes": "id,price,original_price,tags,buying_mode,sub_status,status"}, headers) or {}
        if mensaje_bids:
            aviso_ml = _explicar_has_bids(mensaje_bids, estado) + " Se reintentó fijar el precio base sin descuento."
        precio_real, tachado_real = estado.get("price"), estado.get("original_price")
        precio_pedido = precio_tachado if aviso_ml else precio  # en el fallback se pidió el precio base = tachado
        precio_ok = precio_real is not None and abs(float(precio_real) - float(precio_pedido)) < 1

        if aviso_ml:
            # Vino del fallback has_bids: nunca se pidió tachado, así que
            # "éxito" acá es solo que el precio base haya quedado en el
            # valor pedido -- no hay un modo "con_tachado" posible.
            if precio_ok:
                return {"ok": True, "modo": "sin_tachado_bids", "aviso": aviso_ml}
            return {"ok": False,
                    "error": f"{aviso_ml} Y el GET de verificación tampoco confirma el precio base "
                             f"(real: {precio_real!r}, pedido: {float(precio_pedido)}) -- verificá la publicación real, "
                             "puede ser precio mayorista con endpoint propio u otra restricción no confirmada."}

        tachado_ok = tachado_real is not None and abs(float(tachado_real) - float(precio_tachado)) < 1
        if precio_ok and tachado_ok:
            return {"ok": True, "modo": "con_tachado"}
        if precio_ok:
            return {"ok": True, "modo": "sin_tachado_ml",
                     "aviso": f"Precio real confirmado ${precio_real}, tachado real: {tachado_real!r} (pedido: {float(precio_tachado)}). "
                              "Puede ser reputación no verde, ítem no nuevo, descuento fuera de 5%-80%, precio no creíble, o la publicación está en un DEAL activo -- ver docstring."}
        return {"ok": False,
                "error": f"ML respondió éxito pero el GET de verificación NO confirma el cambio "
                         f"(precio real: {precio_real!r}, pedido: {float(precio)}) -- ML puede estar ignorando el PUT silenciosamente "
                         "(deprecación de price/original_price, automatización de precios activa en la publicación, o precio mayorista con endpoint propio). Verificá la publicación real en ML."}

    def sacar_de_promocion(self, item_id: str, cuenta: str, promotion_type: str, promotion_id: str | None = None) -> dict:
        """Saca la publicación de UNA promoción puntual -- deja las demás
        intactas. `promotion_id` obligatorio para campañas (`SELLER_
        CAMPAIGN` y variantes de ML), no aplica para `PRICE_DISCOUNT`.

        Contrato confirmado navegando la documentación oficial en vivo
        2026-08-28 (antes solo por búsqueda, sin poder abrir la página
        completa): `?promotion_type=PRICE_DISCOUNT&app_version=v2` está en
        developers.mercadolibre.com.ar/es_ar/descuento-individual (act.
        2026-06-09, sección "Eliminar descuento individual a un ítem");
        `?promotion_type=SELLER_CAMPAIGN&promotion_id={id}` es la variante
        homóloga para campañas, documentada en
        developers.mercadolibre.com.ar/es_ar/central-de-promociones (act.
        2026-06-09) -- esa misma página documenta el DELETE SIN parámetros
        (baja-todo) que ya usaba `docs/index.html`. Errores documentados:
        `423_ENTITY_LOCKED` (ítem bloqueado temporalmente, reintentable) y
        `400_BAD_REQUEST` (formato inválido)."""
        headers = {"Authorization": f"Bearer {self._token(cuenta)}"}
        params = {"app_version": "v2", "promotion_type": promotion_type}
        if promotion_id:
            params["promotion_id"] = promotion_id
        d = self._delete(f"https://api.mercadolibre.com/seller-promotions/items/{item_id}", params, headers) or {}
        exitosas = d.get("successful_ids") or []
        if exitosas:
            return {"ok": True, "successful_ids": exitosas}
        errores = d.get("errors") or []
        return {"ok": False, "error": errores[0].get("error") if errores else str(d)}

    def fijar_precio_base(self, item_id: str, cuenta: str, precio_base: Decimal) -> dict:
        """Fija el precio de lista del ítem, SIN descuento -- paso previo
        obligatorio para `meter_en_campana`, que toma el tachado del
        `price` vigente del ítem en el momento de enrolar, no de un campo
        que se pueda mandar (confirmado developers.mercadolibre.com.ar/
        es_ar/campanas-del-vendedor, 2026-08-28: "el original_price…te lo
        devuelve la respuesta, no lo definís vos"). Mismo riesgo de "200
        OK pero lo ignora" que `activar_oferta_propia` (ver su docstring)
        -- se verifica con un GET aparte, nunca se confía en el PUT.
        Manda `price` y `original_price` iguales (sin descuento real)
        porque un PUT con SOLO `price` da 400 desde el 18/03/2026 -- hace
        falta otro atributo en el body para que no lo rechace de una."""
        headers = {"Authorization": f"Bearer {self._token(cuenta)}", "Content-Type": "application/json"}
        url = f"https://api.mercadolibre.com/items/{item_id}"
        d = self._put(url, headers, {"price": float(precio_base), "original_price": float(precio_base)}) or {}
        if not d.get("id"):
            mensaje_ml = d.get("message") or str(d)
            if "has_bids" in mensaje_ml:
                # Caso real 2026-08-28 (MLA627267951 y MLA852181648): mismo
                # `has_bids` que en activar_oferta_propia, acá SIN fallback
                # posible -- ya se mandaron price+original_price juntos
                # (dos atributos, no la regla de "solo price"), así que no
                # hay una combinación distinta que probar. Se pide `tags`
                # para poder distinguir "es precio mayorista" de "causa
                # desconocida" en el mensaje -- ver `_explicar_has_bids`.
                estado_tags = self._get(url, {"attributes": "id,tags,buying_mode,sub_status,status"}, headers) or {}
                return {"ok": False, "error": _explicar_has_bids(mensaje_ml, estado_tags)}
            return {"ok": False, "error": mensaje_ml}
        estado = self._get(url, {"attributes": "id,price"}, headers) or {}
        precio_real = estado.get("price")
        if precio_real is not None and abs(float(precio_real) - float(precio_base)) < 1:
            return {"ok": True}
        return {"ok": False,
                "error": f"ML respondió éxito pero el GET de verificación no confirma el precio base "
                         f"(real: {precio_real!r}, pedido: {float(precio_base)})."}

    def meter_en_campana(self, item_id: str, cuenta: str, promotion_id: str, deal_price: Decimal) -> dict:
        """Enrola la publicación en una campaña `SELLER_CAMPAIGN` que ya
        existe -- este método NO crea campañas, Maxx las crea a mano en
        ML ("Promociones" → "Crear nueva"), esto solo mete publicaciones
        adentro. Endpoint distinto de `/items/{id}` (no tiene el riesgo
        del PUT deprecado), confirmado developers.mercadolibre.com.ar/
        es_ar/campanas-del-vendedor (act. 2026-03-13):
        `POST /seller-promotions/items/{item_id}?app_version=v2` con
        `{promotion_id, promotion_type: SELLER_CAMPAIGN, deal_price}`.

        El tachado sale del `price` vigente del ítem en ese momento --
        llamar `fijar_precio_base` antes para un tachado específico.
        Descuento debe quedar entre 10% y 80% (distinto del 5%-80% de
        `PRICE_DISCOUNT`) -- no documentado si hay chequeo de "precio
        creíble" para este tipo. Una vez `started`, el precio solo puede
        MEJORAR (bajar) en un reintento, ML rechaza subirlo."""
        headers = {"Authorization": f"Bearer {self._token(cuenta)}", "Content-Type": "application/json"}
        body = {"promotion_id": promotion_id, "promotion_type": "SELLER_CAMPAIGN", "deal_price": float(deal_price)}
        d = self._post(f"https://api.mercadolibre.com/seller-promotions/items/{item_id}", headers, body) or {}
        if d.get("price") is not None:
            return {"ok": True, "price": d.get("price"), "original_price": d.get("original_price")}
        return {"ok": False, "error": d.get("message") or str(d)}


def activar_en_campana_tradicional(
    ml: MLOfertasEscritura, cuenta: str, item_id: str, precio_pm: Decimal,
    inflacion_pct: Decimal = Decimal(25), promotion_id: str | None = None,
) -> dict:
    """Automatiza el flujo real de Maxx (confirmado 2026-08-28, 80% de su
    uso): infla `precio_pm` (el precio que definió el PM) un
    `inflacion_pct` -- eso queda como tachado -- y mete la publicación en
    su campaña mensual propia ("Oferta Tradicional <mes>") con
    `precio_pm` sin cambios como precio final. Dos pasos reales de ML, no
    uno: `fijar_precio_base` (tachado) y `meter_en_campana` (precio
    final) -- si el primero falla no se intenta el segundo.

    `promotion_id` opcional: si no se pasa, se resuelve solo con la
    primera `SELLER_CAMPAIGN` con `status` `started` o `pending` de
    `promociones_seller` -- asume que Maxx tiene una sola campaña propia
    viva a la vez (su descripción: crea una nueva cada mes). Si hay más
    de una, se toma la primera que aparezca; pasar `promotion_id`
    explícito para no depender de ese orden."""
    if promotion_id is None:
        campanas = [c for c in ml.promociones_seller(cuenta)
                    if c.get("type") == "SELLER_CAMPAIGN" and c.get("status") in ("started", "pending")]
        if not campanas:
            return {"ok": False, "error": "No se encontró ninguna campaña propia (SELLER_CAMPAIGN) activa o pendiente en esta cuenta."}
        promotion_id = campanas[0]["id"]
        nombre_campana = campanas[0].get("name")
    else:
        nombre_campana = None

    precio_tachado = (precio_pm * (Decimal(100) + inflacion_pct) / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)

    r1 = ml.fijar_precio_base(item_id, cuenta, precio_tachado)
    if not r1.get("ok"):
        return {"ok": False, "error": f"No se pudo fijar el precio base (tachado ${precio_tachado}): {r1.get('error')}"}

    r2 = ml.meter_en_campana(item_id, cuenta, promotion_id, precio_pm)
    if not r2.get("ok"):
        return {"ok": False, "error": f"Precio base fijado en ${precio_tachado}, pero no se pudo enrolar en la campaña: {r2.get('error')}"}

    return {"ok": True, "promotion_id": promotion_id, "nombre_campana": nombre_campana,
            "precio": r2.get("price"), "original_price": r2.get("original_price"),
            "precio_tachado_pedido": float(precio_tachado)}


def listar_promociones_item(ml: MLOfertasClient, cuenta: str, item_id: str) -> list[dict]:
    """Promociones activas/candidatas de UNA publicación, con nombre y
    vigencia cuando se puede resolver -- pedido explícito: "ver qué tiene
    activo antes de sacar algo". `promociones_item` (por-ítem) no trae el
    nombre de campaña -- se cruza con `promociones_seller` (por-cuenta),
    que sí lo tiene. Los nombres exactos de los campos de fecha
    (`date_from`/`start_date`/etc.) y del id de promoción dentro de
    `promociones_item` son la parte de este módulo TODAVÍA no confirmada
    contra una llamada real -- se leen con fallbacks defensivos a
    propósito, para no romper si el nombre real es otro."""
    campanas = {c.get("id"): c for c in ml.promociones_seller(cuenta) if c.get("id")}
    salida = []
    for p in ml.promociones_item(item_id, cuenta):
        tipo = p.get("type")
        promo_id = p.get("promotion_id") or p.get("id")
        campana = campanas.get(promo_id) or {}
        salida.append({
            "promotion_type": tipo,
            "promotion_id": promo_id,
            "status": p.get("status"),
            "nombre": campana.get("name") or ("Descuento propio" if tipo == "PRICE_DISCOUNT" else tipo),
            "fecha_desde": campana.get("date_from") or campana.get("start_date") or p.get("date_from"),
            "fecha_hasta": campana.get("date_to") or campana.get("finish_date") or campana.get("end_date") or p.get("date_to"),
            "precio": p.get("price"),
            "precio_tachado": p.get("original_price"),
        })
    return salida


# ── Orquestación — Fase 1 (lectura + margen) ──

@dataclass
class FilaOferta:
    item_id: str
    cuenta: str
    sku: str | None
    sku_ml: str | None
    titulo: str
    permalink: str | None
    domain_id: str | None
    tipo_oferta: str  # SELLER_CAMPAIGN / DEAL / SMART / PRICE_MATCHING / ... / PRICE_DISCOUNT
    nombre_campana: str | None
    precio_normal: Decimal
    precio_oferta: Decimal
    descuento_pct: Decimal
    cuotas_ofrecidas: int | None
    margen: ResultadoMargenOferta | None  # None si hay incidencia (sin poder calcular)
    incidencia: str | None


def _cuotas_sin_interes(detalle: dict) -> int | None:
    inst = detalle.get("installments") or {}
    return inst.get("quantity") if inst.get("quantity", 0) > 1 and inst.get("rate") == 0 else None


def _armar_fila(
    item_id: str, cuenta: str, detalle: dict, tipo: str, nombre_campana: str | None,
    precio_normal: Decimal, precio_oferta: Decimal,
    costo_provider, iva_provider, params: ParametrosMargen, tc: Decimal,
) -> tuple[FilaOferta, dict | None]:
    """Resuelve costo/IVA desde Táctica (nunca del PM Sheet, REQ §2.0) y
    arma la fila -- compartido entre `ofertas_activas` (campañas) y
    `ofertas_propias_activas` (PRICE_DISCOUNT) para no repetir la
    resolución de margen dos veces."""
    sku_ml = detalle.get("seller_custom_field")
    domain_id = detalle.get("domain_id")
    titulo = detalle.get("title", "")
    cuotas_ofrecidas = _cuotas_sin_interes(detalle)

    sku, margen, incidencia = sku_ml, None, None
    if not sku_ml:
        incidencia = "SIN_SKU"
    else:
        costo_usd = costo_provider.obtener(sku_ml)
        iva_factor = iva_provider.factor(sku_ml)
        if costo_usd is None:
            incidencia = "SIN_COSTO_TACTICA"
        elif iva_factor is None:
            incidencia = "SIN_IVA_TACTICA"
        else:
            costo_ars = costo_usd * tc
            margen = calcular_margen_oferta(precio_oferta, iva_factor, costo_ars, domain_id, cuotas_ofrecidas, params)

    descuento_pct = ((precio_normal - precio_oferta) / precio_normal * 100) if precio_normal else Decimal(0)
    fila = FilaOferta(
        item_id=item_id, cuenta=cuenta, sku=sku, sku_ml=sku_ml, titulo=titulo, permalink=detalle.get("permalink"),
        domain_id=domain_id, tipo_oferta=tipo, nombre_campana=nombre_campana, precio_normal=precio_normal,
        precio_oferta=precio_oferta, descuento_pct=descuento_pct, cuotas_ofrecidas=cuotas_ofrecidas,
        margen=margen, incidencia=incidencia,
    )
    incidencia_dict = {"item_id": item_id, "cuenta": cuenta, "sku": sku_ml, "motivo": incidencia} if incidencia else None
    return fila, incidencia_dict


def resolver_item_para_gestion(ml: MLOfertasClient, costo_provider, iva_provider, item_id: str, cuenta: str, tc: Decimal) -> dict:
    """Trae UN ítem puntual y resuelve costo/IVA de Táctica -- para el
    buscador de "MLA sin oferta activa" (armar la fila a mano en vez de
    sacarla del escaneo de campañas). Misma resolución de incidencia que
    `_armar_fila` (`SIN_SKU`/`SIN_COSTO_TACTICA`/`SIN_IVA_TACTICA`), sin
    tocar esa función porque ahí `precio_oferta` es obligatorio y acá
    todavía no existe ninguno."""
    d = ml.detalle_item_completo(item_id, cuenta) or {}
    if not d.get("id"):
        return {"encontrado": False}
    sku_ml = d.get("seller_custom_field")
    incidencia = None
    costo_usd = iva_factor = None
    if not sku_ml:
        incidencia = "SIN_SKU"
    else:
        costo_usd = costo_provider.obtener(sku_ml)
        iva_factor = iva_provider.factor(sku_ml)
        if costo_usd is None:
            incidencia = "SIN_COSTO_TACTICA"
        elif iva_factor is None:
            incidencia = "SIN_IVA_TACTICA"
    return {
        "encontrado": True, "item_id": d["id"], "cuenta": cuenta, "sku": sku_ml, "titulo": d.get("title", ""),
        "permalink": d.get("permalink"), "domain_id": d.get("domain_id"), "precio_actual": d.get("price"),
        "costo_sin_iva": costo_usd, "iva_factor": iva_factor, "tc": tc, "incidencia": incidencia,
    }


def ofertas_activas(
    ml: MLOfertasClient, costo_provider, iva_provider,
    cuentas: list[str] | None = None, params: ParametrosMargen | None = None, tc: Decimal = Decimal(1),
) -> tuple[list[FilaOferta], list[dict]]:
    """Campañas propias (`SELLER_CAMPAIGN`/`SELLER_COUPON_CAMPAIGN`) y de ML
    (`DEAL`/`SMART`/`PRICE_MATCHING`/`PRE_NEGOTIATED`/`UNHEALTHY_STOCK`/
    `LIGHTNING`/`MARKETPLACE_CAMPAIGN`) activas ahora mismo, de las cuentas
    pedidas, con margen real. NO cubre `PRICE_DISCOUNT` ("ofertas propias")
    -- ver `ofertas_propias_activas`, es un escaneo con costo distinto."""
    cuentas = cuentas or list(SELLERS.keys())
    params = params or ParametrosMargen()
    filas: list[FilaOferta] = []
    incidencias: list[dict] = []

    for cuenta in cuentas:
        promos = [p for p in ml.promociones_seller(cuenta) if p.get("status") == "started"]

        # item_id -> mejor oferta encontrada (menor precio) si aparece en
        # más de una campaña activa a la vez -- la que realmente rige.
        por_item: dict[str, dict] = {}
        for promo in promos:
            tipo = promo.get("type")
            for it in ml.items_de_promocion(promo["id"], tipo, cuenta):
                if it.get("status") != "started":
                    continue
                item_id = it["id"]
                precio = Decimal(str(it.get("price") or 0))
                existente = por_item.get(item_id)
                if existente is None or precio < existente["precio_oferta"]:
                    por_item[item_id] = {
                        "precio_oferta": precio,
                        "precio_normal": Decimal(str(it.get("original_price") or 0)),
                        "tipo": tipo, "nombre_campana": promo.get("name"),
                    }

        if not por_item:
            continue
        detalles = {d["id"]: d for d in ml.detalle_items_ofertas(list(por_item.keys()), cuenta)}

        for item_id, info in por_item.items():
            fila, incidencia = _armar_fila(
                item_id, cuenta, detalles.get(item_id, {}), info["tipo"], info["nombre_campana"],
                info["precio_normal"], info["precio_oferta"], costo_provider, iva_provider, params, tc,
            )
            filas.append(fila)
            if incidencia:
                incidencias.append(incidencia)

    return filas, incidencias


def ofertas_propias_activas(
    ml: MLOfertasClient, costo_provider, iva_provider, cuenta: str,
    params: ParametrosMargen | None = None, tc: Decimal = Decimal(1), item_ids: list[str] | None = None,
    progreso_cb: Callable[[int, int, str], None] | None = None,
) -> tuple[list[FilaOferta], list[dict]]:
    """"Ofertas propias" (`PRICE_DISCOUNT`) -- no tiene un listado barato
    como las campañas (ver docstring del módulo): hay que consultar
    `seller-promotions/items/{id}` publicación por publicación. Con
    `item_ids=None` escanea TODAS las publicaciones activas de la cuenta
    (`ml.items_activos`) -- caro (una llamada por publicación, ~6.200
    activas en las dos cuentas hoy), pensado para correr aparte de
    `ofertas_activas`, no en cada carga del dashboard. Pasar una lista
    acotada para un escaneo más barato. `progreso_cb(procesados, total, fase)`
    opcional -- pedido de Maxx 2026-08-27: reemplazar el "corriendo..."
    indeterminado por una barra de % real en escaneos largos. Dos fases,
    NO una: `detalle_items_ofertas` (fase "catalogo", ~310 llamadas en
    lotes de 20 para 6.200 ítems) corría entera SIN reportar nada antes de
    que arrancara la fase "promociones" -- era la mayor parte del tiempo
    "muerto" que se veía como `corriendo... (0 líneas)`."""
    params = params or ParametrosMargen()
    ids = item_ids if item_ids is not None else ml.items_activos(cuenta)
    filas: list[FilaOferta] = []
    incidencias: list[dict] = []

    detalle_cb = (lambda a, t, f: progreso_cb(a, t, f)) if progreso_cb else None
    detalles = {d["id"]: d for d in ml.detalle_items_ofertas(ids, cuenta, progreso_cb=detalle_cb)}

    total = len(ids)
    for i, item_id in enumerate(ids):
        if progreso_cb:
            progreso_cb(i, total, "promociones")
        try:
            promos_item = ml.promociones_item(item_id, cuenta)
        except requests.exceptions.RequestException as e:
            # Real 2026-08-27: `seller-promotions/items/{id}` devuelve 400
            # para al menos un ítem real (MLA637963331) -- causa exacta no
            # confirmada (¿publicación pausada/sin stock/no elegible para
            # promos?), pero antes este `raise_for_status()` de `_get_real`
            # tumbaba TODO el escaneo (~6.200 ítems) por un solo ítem
            # problemático. Un ítem que no se puede consultar se salta y se
            # deja registrado -- no se estima en silencio (00_LEEME §6),
            # pero tampoco bloquea a los demás.
            incidencias.append({"item_id": item_id, "cuenta": cuenta,
                                 "sku": detalles.get(item_id, {}).get("seller_custom_field"),
                                 "motivo": f"ERROR_ML_ITEM: {e}"})
            continue
        propia = next(
            (p for p in promos_item
             if p.get("type") == "PRICE_DISCOUNT" and p.get("status") == "started"),
            None,
        )
        if not propia:
            continue
        fila, incidencia = _armar_fila(
            item_id, cuenta, detalles.get(item_id, {}), "PRICE_DISCOUNT", propia.get("name") or None,
            Decimal(str(propia.get("original_price") or 0)), Decimal(str(propia.get("price") or 0)),
            costo_provider, iva_provider, params, tc,
        )
        filas.append(fila)
        if incidencia:
            incidencias.append(incidencia)

    if progreso_cb:
        progreso_cb(total, total, "promociones")
    return filas, incidencias


# ── Fase 2 — detección de SKUs candidatos a oferta que no la tienen ──
# Ventas generales (no Full-específicas: acá interesa la venta real de la
# publicación completa, salga de donde salga) vía /orders/search, mismo
# endpoint y mismo criterio (`order.status=paid`, `order.date_closed`) que
# ya usaba `ml_full.py` antes de migrar a `ventas_full_por_inventory` --
# ese cambio fue para no confundir venta self-service con venta de Full en
# el reabastecimiento de Full; acá no aplica esa distinción, así que
# `/orders/search` es la fuente correcta, no un paso atrás.

def ventas_por_item(ml: MLFullClient, cuenta: str, desde_iso: str, hasta_iso: str) -> dict[str, int]:
    seller_id = SELLERS[cuenta]
    headers = {"Authorization": f"Bearer {ml._token(cuenta)}"}
    acumulado: dict[str, int] = {}
    offset = 0
    while True:
        d = ml._get(
            "https://api.mercadolibre.com/orders/search",
            {"seller": seller_id, "order.status": "paid",
             "order.date_closed.from": desde_iso, "order.date_closed.to": hasta_iso,
             "offset": offset, "limit": 50},
            headers,
        )
        resultados = (d or {}).get("results") or []
        for orden in resultados:
            for oi in orden.get("order_items") or []:
                item_id = (oi.get("item") or {}).get("id")
                if not item_id:
                    continue
                acumulado[item_id] = acumulado.get(item_id, 0) + (oi.get("quantity") or 0)
        paging = (d or {}).get("paging") or {}
        total = paging.get("total", 0)
        offset += len(resultados)
        if offset >= total or not resultados:
            break
    return acumulado


@dataclass
class CandidatoOferta:
    item_id: str
    cuenta: str
    sku: str | None
    titulo: str
    permalink: str | None
    ventas_periodo: int
    stock: int


def detectar_skus_sin_oferta(
    ml: MLOfertasClient, cuenta: str, item_ids_con_oferta: set,
    dias_ventas: int = 30, min_ventas: int = 5, hoy=None,
    progreso_cb: Callable[[int, int, str], None] | None = None,
) -> list:
    """Alta rotación (>= `min_ventas` en `dias_ventas`) + stock > 0 + sin
    ninguna oferta activa ahora mismo (`item_ids_con_oferta`, la unión de
    lo que ya devolvieron `ofertas_activas`/`ofertas_propias_activas`).
    Escanea TODAS las publicaciones activas de la cuenta -- mismo costo que
    `ofertas_propias_activas`, pensado para correr aparte del dashboard
    principal, no en cada carga. `progreso_cb(procesados, total, fase)`
    opcional, ver `ofertas_propias_activas`."""
    from datetime import date, timedelta
    hoy = hoy or date.today()
    desde_iso = f"{(hoy - timedelta(days=dias_ventas)).isoformat()}T00:00:00.000-00:00"
    hasta_iso = f"{hoy.isoformat()}T23:00:00.000-00:00"

    ids = ml.items_activos(cuenta)
    if progreso_cb:
        progreso_cb(0, max(len(ids), 1), "ventas")
    ventas = ventas_por_item(ml, cuenta, desde_iso, hasta_iso)
    candidatos_ids = [i for i in ids if i not in item_ids_con_oferta and ventas.get(i, 0) >= min_ventas]
    if not candidatos_ids:
        if progreso_cb:
            progreso_cb(1, 1, "candidatos")
        return []

    headers = {"Authorization": f"Bearer {ml._token(cuenta)}"}
    resultado = []
    total = len(candidatos_ids)
    for i in range(0, total, 20):
        if progreso_cb:
            progreso_cb(i, total, "candidatos")
        lote = candidatos_ids[i:i + 20]
        d = ml._get(
            "https://api.mercadolibre.com/items",
            {"ids": ",".join(lote), "attributes": "id,title,permalink,seller_custom_field,available_quantity"},
            headers,
        )
        for entrada in (d or []):
            cuerpo = entrada.get("body") if isinstance(entrada, dict) and "body" in entrada else entrada
            if not cuerpo:
                continue
            stock = cuerpo.get("available_quantity") or 0
            if stock <= 0:
                continue
            resultado.append(CandidatoOferta(
                item_id=cuerpo["id"], cuenta=cuenta, sku=cuerpo.get("seller_custom_field"),
                titulo=cuerpo.get("title", ""), permalink=cuerpo.get("permalink"),
                ventas_periodo=ventas.get(cuerpo["id"], 0), stock=stock,
            ))
    if progreso_cb:
        progreso_cb(total, total, "candidatos")
    return resultado


# ── Job en background — mismo patrón que ml_full.py/ml_reposicion.py ──

_jobs: dict = {}


def _num(v):
    return float(v) if v is not None else None


def _fila_a_dict(f: FilaOferta) -> dict:
    m = f.margen
    return {
        "item_id": f.item_id, "cuenta": f.cuenta, "sku": f.sku, "sku_ml": f.sku_ml, "titulo": f.titulo,
        "permalink": f.permalink, "domain_id": f.domain_id, "tipo_oferta": f.tipo_oferta, "nombre_campana": f.nombre_campana,
        "precio_normal": _num(f.precio_normal), "precio_oferta": _num(f.precio_oferta),
        "descuento_pct": _num(f.descuento_pct), "cuotas_ofrecidas": f.cuotas_ofrecidas,
        "incidencia": f.incidencia,
        "margen": None if m is None else {
            "base_sin_iva": _num(m.base_sin_iva), "comision": _num(m.comision),
            "costo_fijo": _num(m.costo_fijo), "cuotas": _num(m.cuotas),
            "envio": _num(m.envio), "imp_cheque": _num(m.imp_cheque),
            "iibb": _num(m.iibb), "costo_producto": _num(m.costo_producto),
            "margen": _num(m.margen), "margen_pct": _num(m.margen_pct),
        },
    }


def iniciar_job(job_id: str, cuentas: list = None, incluir_propias: bool = False, tc: float = 0) -> None:
    """`tc` lo resuelve el llamador (`main.py`, vía `obtener_tc_bna()`) --
    este módulo no scrapea BNA para no duplicar esa lógica ni crear un
    import circular con `main.py`. `incluir_propias=True` suma el escaneo
    caro de `PRICE_DISCOUNT` (ver su docstring) -- por eso es opt-in, no
    el comportamiento por defecto. Reporta `progress` (current/total/label)
    en `_jobs[job_id]` durante el escaneo caro -- pedido de Maxx 2026-08-27,
    para que el frontend muestre una barra de % real en vez de
    "corriendo..." indeterminado."""
    _jobs[job_id] = {"status": "running", "log": ["Iniciando lectura de ofertas activas..."], "result": None, "progress": None}
    try:
        from rentabilidad.adapters import CostoVigenteProvider, IvaProvider

        ml = MLOfertasClient()
        costo_provider = CostoVigenteProvider()
        iva_provider = IvaProvider()
        params = ParametrosMargen()
        tc_decimal = Decimal(str(tc)) if tc else Decimal(1)

        cuentas = cuentas or list(SELLERS.keys())
        filas, incidencias = ofertas_activas(ml, costo_provider, iva_provider, cuentas=cuentas, params=params, tc=tc_decimal)
        _jobs[job_id]["log"].append(f"{len(filas)} ofertas de campaña encontradas.")

        if incluir_propias:
            for cuenta in cuentas:
                _jobs[job_id]["log"].append(f"Escaneando ofertas propias ({cuenta})... puede tardar.")

                def _progreso(actual, total, fase, cuenta=cuenta):
                    etiqueta = "Trayendo catálogo" if fase == "catalogo" else "Consultando promociones"
                    _jobs[job_id]["progress"] = {"current": actual, "total": total, "label": f"{etiqueta} — ofertas propias ({cuenta})"}

                f, i = ofertas_propias_activas(ml, costo_provider, iva_provider, cuenta, params=params, tc=tc_decimal, progreso_cb=_progreso)
                filas.extend(f)
                incidencias.extend(i)
        _jobs[job_id]["progress"] = None

        _jobs[job_id]["result"] = {
            "filas": [_fila_a_dict(f) for f in filas],
            "incidencias": incidencias,
            "tc": float(tc_decimal),
            "parametros": {
                "comision_por_dominio": {k: float(v) for k, v in params.comision_por_dominio.items()},
                "comision_general": float(params.comision_general),
                "costo_fijo_tramos": [[float(t) if t is not None else None, float(m)] for t, m in params.costo_fijo_tramos],
                "cuotas_pct": {str(k): float(v) for k, v in params.cuotas_pct.items()},
                "envio_tramos": [[float(t) if t is not None else None, float(m)] for t, m in params.envio_tramos],
                "imp_cheque_pct": float(params.imp_cheque_pct),
                "iibb_pct": float(params.iibb_pct),
            },
        }
        _jobs[job_id]["status"] = "done"
        _jobs[job_id]["log"].append(f"Listo: {len(filas)} ofertas activas en total.")
    except Exception as e:
        _jobs[job_id]["status"] = "error"
        _jobs[job_id]["log"].append(f"Error: {e}")


def estado_job(job_id: str):
    return _jobs.get(job_id)


def iniciar_job_alertas(job_id: str, cuenta: str, item_ids_con_oferta: list, dias_ventas: int = 30, min_ventas: int = 5) -> None:
    _jobs[job_id] = {"status": "running", "log": [f"Buscando SKUs candidatos a oferta ({cuenta})..."], "result": None, "progress": None}
    try:
        ml = MLOfertasClient()

        def _progreso(actual, total, fase):
            etiqueta = "Trayendo ventas" if fase == "ventas" else "Buscando candidatos"
            _jobs[job_id]["progress"] = {"current": actual, "total": total, "label": f"{etiqueta} ({cuenta})"}

        candidatos = detectar_skus_sin_oferta(ml, cuenta, set(item_ids_con_oferta), dias_ventas=dias_ventas, min_ventas=min_ventas, progreso_cb=_progreso)
        _jobs[job_id]["progress"] = None
        _jobs[job_id]["result"] = {
            "candidatos": [
                {"item_id": c.item_id, "cuenta": c.cuenta, "sku": c.sku, "titulo": c.titulo, "permalink": c.permalink,
                 "ventas_periodo": c.ventas_periodo, "stock": c.stock}
                for c in candidatos
            ],
        }
        _jobs[job_id]["status"] = "done"
        _jobs[job_id]["log"].append(f"Listo: {len(candidatos)} candidatos encontrados.")
    except Exception as e:
        _jobs[job_id]["status"] = "error"
        _jobs[job_id]["log"].append(f"Error: {e}")
