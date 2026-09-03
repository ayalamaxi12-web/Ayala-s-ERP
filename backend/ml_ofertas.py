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

import re
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable

import requests

from ml_auth import SELLERS
from ml_full import GetFn, MLFullClient, _sku_de_item

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
# Corregido 2026-09-02 (Maxx, en vivo -- simulador de costos real de una
# publicación en "Modificar publicación"): ML subió estas tasas desde los
# valores anteriores (8,40/12,30/15,70/19,20). La Reducida (5% fijo) NO
# cambió, se verificó en el mismo simulador. Mismo ajuste aplicado en
# docs/index.html (CUOTAS_PCT_ML y OFM.cuotasPct) y en AYALA_CORE.md.
CUOTAS_PCT_DEFAULT: dict[int, Decimal] = {
    3: Decimal("8.90"), 6: Decimal("13.40"), 9: Decimal("17.80"), 12: Decimal("21.60"),
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
        que arrancara a reportar progreso el loop de promociones.

        Pide `tags`, no `installments` -- ver `_cuotas_sin_interes`."""
        headers = {"Authorization": f"Bearer {self._token(cuenta)}"}
        salida: list[dict] = []
        total = len(item_ids)
        for i in range(0, total, 20):
            if progreso_cb:
                progreso_cb(i, total, "catalogo")
            lote = item_ids[i:i + 20]
            d = self._get(
                "https://api.mercadolibre.com/items",
                {"ids": ",".join(lote), "attributes": "id,title,permalink,seller_custom_field,domain_id,tags,attributes"},
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
            {"attributes": "id,title,price,original_price,permalink,seller_custom_field,domain_id,tags,attributes"}, headers,
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


def _explicar_has_bids(mensaje_ml: str, estado_item: dict | None = None, respuesta_completa: dict | None = None) -> str:
    """`has_bids` no está documentado en developers.mercadolibre.com.ar
    (buscado explícitamente 2026-08-28, ver docstring del módulo).

    **Causa real CONFIRMADA 2026-08-28 (MLA627267951, con la respuesta
    completa del PUT, no solo el `message` recortado)**:
    `has_bids:true` es ruido -- el `cause` real de la respuesta trae
    `{"code": "field_not_updatable", "references": ["original_price"],
    "message": "original_price is not modifiable."}`. Es decir: ML
    rechaza el PUT porque `original_price` **no se puede modificar por
    esta vía**, punto -- no tiene nada que ver con pujas ni con
    negociaciones pendientes, esas dos hipótesis (probadas antes, ver
    abajo) eran ruido también. `PUT /items/{id}` con `original_price`
    está roto para el tachado -- hace falta un mecanismo distinto
    (`/seller-promotions/` o la API de Precios nueva, en investigación).

    Caso 1 (MLA852181648, 2026-08-28): precio mayorista/B2B
    (`standard_price_by_quantity` en `tags`) -- esos ítems tienen su
    PROPIO endpoint de precio (`POST /items/{id}/prices/standard/
    quantity`, developers.mercadolibre.com.ar/es_ar/precio-por-cantidad,
    no implementado acá) -- causa distinta a la de `field_not_updatable`,
    se mantiene separada porque ahí el `cause` puede no traer esa
    referencia."""
    estado_item = estado_item or {}
    respuesta_completa = respuesta_completa or {}
    tags = estado_item.get("tags") or []

    causas = respuesta_completa.get("cause") or []
    original_price_bloqueado = any(
        c.get("code") == "field_not_updatable" and "original_price" in (c.get("references") or [])
        for c in causas
    )
    if original_price_bloqueado:
        return (f"ML rechaza el cambio (mensaje real: \"{mensaje_ml}\"). La causa REAL, confirmada con la "
                "respuesta completa: `original_price is not modifiable` -- el tachado no se puede fijar así en "
                "esta publicación, `has_bids` en el mensaje es ruido, no la causa. `PUT /items/{id}` no es el "
                "camino para el tachado acá -- hace falta otro mecanismo (en investigación, no implementado "
                "todavía). No hay una forma de fijarlo desde el ERP por ahora.")
    if "standard_price_by_quantity" in tags:
        return (f"ML rechaza el cambio de precio (mensaje real: \"{mensaje_ml}\"). Esta publicación tiene precio "
                "mayorista/por cantidad (tag `standard_price_by_quantity`) -- ese tipo de publicación tiene su propio "
                "endpoint de precio en la API de ML, distinto del que usa este módulo, y no está implementado acá. "
                "No se puede activar una oferta con precio simple sobre esta publicación desde el ERP por ahora.")
    diagnostico = (f"buying_mode={estado_item.get('buying_mode')!r}, sub_status={estado_item.get('sub_status')!r}, "
                   f"status={estado_item.get('status')!r}, tags={tags!r}")
    respuesta_txt = f" Respuesta completa del PUT: {respuesta_completa!r}." if respuesta_completa else ""
    return (f"ML no permite cambiar el precio de esta publicación ahora mismo (mensaje real: \"{mensaje_ml}\").{respuesta_txt} "
            "No tiene precio mayorista y no coincide con el patrón confirmado de `original_price is not "
            f"modifiable`, así que ninguna causa ya confirmada explica esto. Estado crudo del ítem: {diagnostico}. "
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
            aviso_ml = _explicar_has_bids(mensaje_bids, estado, d) + " Se reintentó fijar el precio base sin descuento."
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
        para `meter_en_campana`, que toma el tachado del `price` vigente
        del ítem en el momento de enrolar, no de un campo que se pueda
        mandar (confirmado developers.mercadolibre.com.ar/es_ar/campanas-
        del-vendedor, 2026-08-28: "el original_price…te lo devuelve la
        respuesta, no lo definís vos"). Mismo riesgo de "200 OK pero lo
        ignora" que `activar_oferta_propia` (ver su docstring) -- se
        verifica con un GET aparte, nunca se confía en el PUT.

        **Corregido 2026-08-31: manda SOLO `price`, sin `original_price`.**
        La versión anterior mandaba los dos campos iguales porque el
        docstring de `activar_oferta_propia` (basado en la documentación
        de `api-de-precios`) decía que un PUT con SOLO `price` daba 400
        desde el 18/03/2026 -- ese dato era incorrecto para este caso, o
        estaba desactualizado: probado en vivo contra la cuenta real
        (MLA852181648, `{"price": 15839}` sin ningún otro campo) y
        funcionó, verificado con un GET aparte. Mandar `original_price`
        junto con `price` era la causa real del rechazo sistémico
        `field_not_updatable`/`original_price` (confirmado en
        MLA1797165910 y otros) -- ese campo específicamente está roto por
        `PUT /items/{id}`, no `price`. Al no mandarlo más, esa causa de
        rechazo no debería volver a aparecer por esta vía."""
        headers = {"Authorization": f"Bearer {self._token(cuenta)}", "Content-Type": "application/json"}
        url = f"https://api.mercadolibre.com/items/{item_id}"
        d = self._put(url, headers, {"price": float(precio_base)}) or {}
        if not d.get("id"):
            mensaje_ml = d.get("message") or str(d)
            if "has_bids" in mensaje_ml:
                # Caso real 2026-08-28 (MLA627267951 y MLA852181648) --
                # ver `_explicar_has_bids`. Con el body de un solo campo
                # ya no debería salir por la causa `original_price`
                # (`field_not_updatable`), pero se deja el manejo genérico
                # por si `has_bids` aparece por otro motivo (mayorista,
                # etc.) sin asumir la causa de antemano.
                estado_tags = self._get(url, {"attributes": "id,tags,buying_mode,sub_status,status"}, headers) or {}
                return {"ok": False, "error": _explicar_has_bids(mensaje_ml, estado_tags, d)}
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
        MEJORAR (bajar) en un reintento, ML rechaza subirlo.

        **Bug corregido 2026-08-31**: la URL nunca llevaba `?app_version=v2`
        pese a que el docstring de arriba siempre dijo que iba -- no se
        había notado porque en todos los intentos reales anteriores
        `fijar_precio_base` fallaba antes (por el `original_price` roto,
        ver su docstring) y este método nunca llegaba a ejecutarse de
        verdad. Confirmado en vivo (MLA852181648) que sin el parámetro ML
        responde `"Invalid app_version"`."""
        headers = {"Authorization": f"Bearer {self._token(cuenta)}", "Content-Type": "application/json"}
        body = {"promotion_id": promotion_id, "promotion_type": "SELLER_CAMPAIGN", "deal_price": float(deal_price)}
        d = self._post(f"https://api.mercadolibre.com/seller-promotions/items/{item_id}?app_version=v2", headers, body) or {}
        if d.get("price") is not None:
            return {"ok": True, "price": d.get("price"), "original_price": d.get("original_price")}
        return {"ok": False, "error": d.get("message") or str(d)}


_PCT_EN_MENSAJE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%|allowed is (\d+(?:[.,]\d+)?)")


def _porcentaje_de_mensaje(mensaje: str) -> Decimal | None:
    """Best-effort: si el mensaje de error de ML menciona un número de
    porcentaje (ej. "the minimum percentage allowed is 26.000000" o
    similar), lo extrae para mostrarlo limpio en el aviso. Si no aparece
    ninguno, devuelve `None` y se muestra el mensaje crudo -- nunca se
    inventa un número que ML no dijo."""
    m = _PCT_EN_MENSAJE.search(mensaje or "")
    if not m:
        return None
    return Decimal((m.group(1) or m.group(2)).replace(",", "."))


_PALABRAS_CHALLENGE_SEGURIDAD = (
    "totp", "challenge", "liveness", "reauth", "verificacion_identidad",
    "verificación de identidad", "security_challenge", "two_factor", "mfa",
)


def _es_challenge_seguridad(mensaje: str) -> bool:
    """Heurística, NO confirmada contra una respuesta real de la API
    pública. El QR/verificación facial que le apareció a Maxx (2026-08-31,
    ver `project_ofertas-ml-margen-module.md`) salió siempre navegando
    `vendedores.mercadolibre.com.ar` a mano -- nunca se disparó en ninguno
    de los llamados a la API pública con Bearer OAuth de esa misma sesión
    de pruebas (mismo item, mismo enrolamiento). Se deja este chequeo como
    red de seguridad por si la API alguna vez lo expone de otra forma,
    pero el código/mensaje/status exacto que usaría no está confirmado --
    si aparece un caso real, actualizar esto con el dato real en vez de
    confiar en las palabras clave de acá."""
    m = (mensaje or "").lower()
    return any(p in m for p in _PALABRAS_CHALLENGE_SEGURIDAD)


def activar_en_campana_tradicional(
    ml: MLOfertasEscritura, cuenta: str, item_id: str, precio_pm: Decimal,
    descuento_pct: Decimal = Decimal(25), promotion_id: str | None = None,
) -> dict:
    """Automatiza el flujo real de Maxx (confirmado 2026-08-28, 80% de su
    uso): mete la publicación en su campaña mensual propia ("Oferta
    Tradicional <mes>") dejando `precio_final` (`precio_pm` ajustado por
    cuotas/envío real -- ver más abajo) como precio final -- SIEMPRE, pase
    lo que pase con el tachado. Esto es puro posicionamiento: no hay
    descuento real adicional al del ajuste, el cliente nunca paga menos de
    lo que ya pagaría; el tachado es teatro para que ML muestre la
    publicación como "en oferta". Por eso el precio final nunca se
    negocia MÁS ALLÁ del ajuste de cuotas/envío -- lo único que puede
    variar por campaña/ítem es cuánto hay que inflar el tachado para que
    ML acepte mostrarlo.

    **`precio_pm` ya NO es el precio final tal cual, desde 2026-09-02
    (pedido explícito de Maxx).** Ver el bloque de "Ajuste por cuotas +
    envío real" más abajo en el cuerpo de la función para la fórmula
    exacta y el porqué -- en resumen: `precio_final = precio_pm × (1 +
    %cuotas si aplica) + costo_envío_real (si tuvo envío gratis)`.

    **Fórmula del tachado estándar**, corregida 2026-08-28 (bug real
    encontrado por Maxx en vivo, MLA627267951: 25% de descuento sobre
    $16.865 en la sección de Promociones de ML dio $12.648,75, que es
    exactamente el precio del PM): `tachado × (1 − descuento_pct/100) =
    precio_pm`, así que `tachado = precio_pm / (1 − descuento_pct/100)`
    -- NO `precio_pm × (1 + descuento_pct/100)` (inflar X% y después
    descontar ese mismo X% no son operaciones inversas: para X=25%,
    ×1,25 después ×0,75 = ×0,9375, un 6,25% por debajo del original).

    **% mínimo/forzado por la campaña -- chequeo preventivo CUANDO SE
    PUEDE, escalada reactiva de respaldo SIEMPRE (corregido 2026-08-31,
    dos veces el mismo día -- ver abajo por qué el chequeo preventivo solo
    no alcanza).** `promociones_item` (`GET /seller-promotions/items/{id}`,
    el mismo endpoint que ya se usa para detectar `PRICE_DISCOUNT`) trae,
    para una promoción candidata (`status: candidate`) del ítem, `min_
    discounted_price`/`max_discounted_price`/`suggested_discounted_price`,
    relativos al `price` vigente del ítem EN EL MOMENTO de la lectura. Por
    eso el orden es: (1) fijar el tachado estándar (`descuento_pct`), (2)
    leer el rango con ese tachado ya puesto, (3) si `precio_pm` no entra
    en `max_discounted_price`, inflar el tachado (proporcional al techo
    observado) para que SÍ entre, sin tocar `precio_pm`. Si `precio_pm`
    cae por DEBAJO de `min_discounted_price`, no hay ajuste posible
    (inflar el tachado no mueve el piso) -- revierte todo y corta,
    bloqueante.

    **Por qué el chequeo preventivo NO es una garantía, y por qué NO se
    escala el tachado cuando falla (corregido 2026-09-01, ver docstring
    del paso 3 más abajo para el detalle completo):** el rango (`min/
    max/suggested_discounted_price`) solo aparece cuando la campaña sigue
    en `status: candidate` para ese ítem -- apenas el ítem fue enrolado
    una vez en ESA campaña puntual (aunque después se lo haya sacado),
    pasa a `status: started` y el rango desaparece de la respuesta. Pero
    incluso CUANDO aparece, confirmado en vivo con dos ítems reales el
    mismo día (MLA1625270713, MLA751588750) que puede dar luz verde y el
    enrolamiento real igual rechace por credibilidad -- el chequeo
    preventivo parece reaccionar al tachado momentáneo que se acaba de
    fijar, pero la validación real de ML usa un precio de referencia del
    ítem que no se mueve con eso. Por eso, si `meter_en_campana` rechaza
    por credibilidad (`ERROR_CREDIBILITY_DISCOUNTED_PRICE` / "not
    credible"), YA NO se escala el tachado (se probó hasta 70% en los dos
    casos reales y no cambió nada) -- se revierte de una y se avisa con
    el techo real que acredita ML en ese momento, sin insistir.

    **Verificación de seguridad (QR/reconocimiento facial) -- SIEMPRE
    bloqueante, nunca se reintenta solo.** Confirmado en vivo 2026-08-31
    que ML puede exigirla para participar en una campaña propia -- pasó
    en la UI real, nunca en la API pública con Bearer OAuth en esa misma
    sesión de pruebas, pero se detecta igual por las dudas
    (`_es_challenge_seguridad`, heurística no confirmada contra un caso
    real de la API -- ver su docstring). Si aparece, se revierte todo lo
    tocado hasta ese punto y se corta -- no hay forma de resolverla sin
    la presencia de Maxx.

    Reintentos ante 429/503 de la reversión los cubre el mismo backoff
    que ya tienen `fijar_precio_base`/`sacar_de_promocion` (vía
    `_put_real`/`_delete_real`) -- no hace falta duplicarlo acá.

    `promotion_id` opcional: si no se pasa, se resuelve solo filtrando
    `promociones_seller` por `type == SELLER_CAMPAIGN`, `status` `started`
    o `pending`, Y nombre que contenga "oferta tradicional" (case-
    insensitive) -- el patrón real con el que Maxx nombra la campaña que
    crea a mano cada mes ("Oferta Tradicional <mes>", confirmado en vivo
    contra la cuenta real: "Oferta tradicional Sep").

    **Corregido 2026-09-01 (bug real en vivo, MLA852181648, cuenta IT):**
    la versión anterior tomaba la PRIMERA `SELLER_CAMPAIGN` sin filtrar
    por nombre, asumiendo que Maxx tiene una sola campaña propia viva a
    la vez -- FALSO: `promociones_seller` devuelve "campañas del vendedor
    (propias y de ML)" (ver su docstring), y la cuenta real tenía TRES
    `SELLER_CAMPAIGN` con status activo/pendiente al mismo tiempo para
    este ítem ("Oferta tradicional Sep", "TVS-FIX-26-63 Agosto", "Toners
    Septiembre %%") -- probablemente campañas de categoría/marca armadas
    por ML en las que la cuenta quedó enrolada, no solo las que Maxx crea
    él mismo. Sin el filtro por nombre, tomó "TVS-FIX-26-63 Agosto" (la
    que apareció primera en la respuesta de ML) en vez de la campaña
    mensual real -- confirmado por Maxx contra la publicación real y
    contra la UI de ML. Si no aparece ninguna con ese nombre, corta con
    error explícito en vez de adivinar -- pasar `promotion_id` a mano
    para forzar otra campaña puntual."""
    if promotion_id is None:
        campanas = [c for c in ml.promociones_seller(cuenta)
                    if c.get("type") == "SELLER_CAMPAIGN" and c.get("status") in ("started", "pending")
                    and "oferta tradicional" in (c.get("name") or "").lower()]
        if not campanas:
            return {"ok": False, "error": "No se encontró ninguna campaña propia con nombre \"Oferta Tradicional <mes>\" activa o pendiente en esta cuenta -- si la creaste con otro nombre, pasá promotion_id a mano."}
        promotion_id = campanas[0]["id"]
        nombre_campana = campanas[0].get("name")
    else:
        nombre_campana = None

    if descuento_pct >= 100:
        return {"ok": False, "error": f"Descuento de {descuento_pct}% inválido -- tiene que ser menor a 100%."}

    # Precio previo del ítem -- para poder restaurarlo tal cual estaba si
    # algo se corta a mitad de camino (ver docstring). Se lee ANTES de
    # tocar nada; si esta lectura falla, se sigue igual (mismo criterio
    # que el resto del módulo: no bloquear por un GET que no es central),
    # pero una reversión posterior quedaría sin poder restaurar el precio
    # ni calcular el ajuste de cuotas de abajo (pide `tags` también, ver
    # `_cuotas_sin_interes`).
    headers = {"Authorization": f"Bearer {ml._token(cuenta)}"}
    previo = ml._get(f"https://api.mercadolibre.com/items/{item_id}", {"attributes": "id,price,tags"}, headers) or {}
    precio_previo = previo.get("price")

    # **Ajuste por cuotas + envío real -- pedido explícito de Maxx
    # 2026-09-02.** `precio_pm` (lo que recibe esta función) es el precio
    # SIN ajustar que define el PM para Ecom -- no necesariamente lo que
    # hay que cobrar de verdad en esta campaña. Motivo, palabras de Maxx:
    # "Ecom ya me sube automático el precio de envío (cuando tiene envío
    # gratis) al precio de base" -- cuando ML te descuenta un envío real,
    # el precio de lista tiene que subir esa misma plata para que el PM
    # siga netando lo que pidió (ejemplo suyo: PM $100.000 + envío real
    # $12.000 = $112.000). Mismo criterio con cuotas: si la publicación
    # está en una campaña de cuotas sin interés (`_cuotas_sin_interes`,
    # via `tags` -- ver su docstring, `installments` no existe), primero
    # se le suma el % que ESO cuesta (`CUOTAS_PCT_DEFAULT`, la tabla real
    # de lo que cobra ML por cuota -- NO la de `RULES`/frontend, que es
    # el margen propio de Maxx), y RECIÉN DESPUÉS se le suma el envío
    # real -- ese orden exacto, confirmado con Maxx. El tachado se calcula
    # sobre este precio ajustado (`precio_final`), no sobre `precio_pm`
    # crudo -- `precio_final` es el número que de verdad se cobra y el
    # único que se manda/verifica contra ML de acá en adelante.
    #
    # El costo real de envío puede fallar (shipping_id viejo/inválido en
    # la cache congelada, `/shipments/{id}` transitorio) -- nunca por eso
    # se corta la activación entera por un dato que es un ajuste, no el
    # corazón de la función. Se trata como "sin dato" (0), igual que
    # cuando la cache todavía no tiene nada para este ítem.
    cuotas_ofrecidas = _cuotas_sin_interes(previo)
    cuotas_pct = CUOTAS_PCT_DEFAULT.get(cuotas_ofrecidas) if cuotas_ofrecidas else None
    precio_con_cuotas = (
        (precio_pm * (1 + cuotas_pct / 100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        if cuotas_pct else precio_pm
    )
    try:
        envio_info = costo_envio_real_item(ml, item_id, cuenta)
    except Exception:
        envio_info = None
    costo_envio = (
        Decimal(str(envio_info["costo_envio_real"]))
        if envio_info and envio_info.get("cost_type") == "free" else Decimal(0)
    )
    precio_final = precio_con_cuotas + costo_envio

    _ajustes = []
    if cuotas_pct:
        _ajustes.append(f"+{cuotas_pct}% por estar en {cuotas_ofrecidas} cuotas sin interés")
    if costo_envio:
        _ajustes.append(f"+${costo_envio:.0f} de envío real (última venta)")
    ajuste_aviso = f"Precio del PM (${precio_pm}) ajustado a ${precio_final:.0f} -- {', '.join(_ajustes)}." if _ajustes else None

    precio_tachado = (precio_final / (1 - descuento_pct / 100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)

    def _revertir_precio(motivo: str) -> str:
        if precio_previo is None:
            return f"{motivo} No se pudo leer el precio anterior antes de empezar, así que no se lo puede restaurar solo -- revisá la publicación a mano."
        rv = ml.fijar_precio_base(item_id, cuenta, Decimal(str(precio_previo)))
        if rv.get("ok"):
            return f"{motivo} Precio restaurado a ${precio_previo} (el que tenía antes de esta operación)."
        return f"{motivo} Además, no se pudo restaurar el precio anterior (${precio_previo}): {rv.get('error')} -- revisá la publicación a mano."

    def _si_es_challenge(mensaje: str) -> dict | None:
        if not _es_challenge_seguridad(mensaje):
            return None
        aviso = _revertir_precio(
            f"ML pidió una verificación de seguridad (QR/reconocimiento facial) para esta operación -- "
            f"eso NO se puede resolver desde el ERP, requiere que lo hagas vos a mano. Mensaje real: \"{mensaje}\"."
        )
        return {"ok": False, "error": aviso, "requiere_verificacion_manual": True}

    # Paso 1: tachado estándar.
    r1 = ml.fijar_precio_base(item_id, cuenta, precio_tachado)
    if not r1.get("ok"):
        error = r1.get("error") or ""
        challenge = _si_es_challenge(error)
        if challenge:
            return challenge
        return {"ok": False, "error": f"No se pudo fijar el precio base (tachado ${precio_tachado}): {error}"}

    tachado_aplicado = precio_tachado
    aviso_pct: str | None = None

    # Paso 2: leer el rango real de ML para esta campaña+ítem, con el
    # tachado estándar ya puesto (ver docstring -- el rango es relativo al
    # `price` vigente en el momento de la lectura).
    promos = ml.promociones_item(item_id, cuenta)
    entrada = next((p for p in promos if p.get("id") == promotion_id), None)
    max_desc = entrada.get("max_discounted_price") if entrada else None
    min_desc = entrada.get("min_discounted_price") if entrada else None

    if min_desc is not None and float(precio_final) < float(min_desc):
        aviso = _revertir_precio(
            f"El precio final (${precio_final}, PM ${precio_pm} ajustado) queda por DEBAJO del piso que exige ML "
            f"para esta campaña (mínimo permitido: ${min_desc}) -- inflar el tachado no resuelve esto, el "
            "descuento resultante sería más agresivo de lo que ML permite para este ítem."
        )
        return {"ok": False, "error": aviso, "precio_pm": float(precio_pm), "precio_final": float(precio_final),
                "min_discounted_price": float(min_desc)}

    if max_desc is not None and float(precio_final) > float(max_desc):
        # El 25% (o el descuento_pct pedido) no alcanza para esta campaña
        # sobre este ítem puntual -- ML exige más "descuento visual". Se
        # recalcula el tachado mínimo necesario para que precio_final siga
        # siendo el precio final exacto, usando la proporción real
        # observada (max_desc / tachado_aplicado) como el % mínimo real
        # que ML fuerza a este precio de lista.
        frac_min_ml = 1 - (Decimal(str(max_desc)) / Decimal(str(tachado_aplicado)))
        tachado_ajustado = (precio_final / (1 - frac_min_ml)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        r1b = ml.fijar_precio_base(item_id, cuenta, tachado_ajustado)
        if not r1b.get("ok"):
            error = r1b.get("error") or ""
            challenge = _si_es_challenge(error)
            if challenge:
                return challenge
            aviso = _revertir_precio(
                f"ML exige más descuento visual que el {descuento_pct}% de siempre para esta campaña, pero no se "
                f"pudo inflar el tachado a ${tachado_ajustado} para compensarlo: {error}"
            )
            return {"ok": False, "error": aviso}
        tachado_aplicado = tachado_ajustado
        pct_real = float((1 - precio_final / tachado_aplicado) * 100)
        aviso_pct = (
            f"Quedó al {pct_real:.1f}% de descuento visual, no al {float(descuento_pct):.0f}% de siempre -- ML "
            f"exige más para esta campaña sobre este ítem. El precio final NO cambió, sigue siendo ${precio_final} "
            "(el tachado es solo para posicionar, no es una rebaja real)."
        )

    def _es_rechazo_por_credibilidad(mensaje: str) -> bool:
        return "credib" in (mensaje or "").lower()  # cubre ERROR_CREDIBILITY_DISCOUNTED_PRICE y "not credible"

    # Paso 3: enrolar con el precio final SIEMPRE clavado en precio_final
    # (precio_pm ya ajustado por cuotas/envío, ver más arriba). UN solo
    # intento -- NO se escala el tachado más allá de acá.
    #
    # **Sacada la escalada 2026-09-01** (había 2026-08-31, ver commit
    # df7f075): confirmado en vivo con DOS ítems reales el mismo día
    # (MLA1625270713 y MLA751588750) que escalar 30→35→40→45→50→60→70% no
    # cambia nada cuando el rechazo es por credibilidad. Causa real: el
    # chequeo preventivo del paso 2 (`promociones_item`) parece reaccionar
    # al `price` que se acaba de fijar momentáneamente (por eso a veces
    # deja pasar el intento), pero el enrolamiento real (`POST
    # /seller-promotions/items/...`) valida contra un precio de
    # referencia de ML propio del ítem que NO se mueve aunque se infle el
    # tachado -- confirmado leyendo el rango otra vez con el precio YA
    # restaurado a su valor real: `max_discounted_price` daba
    # exactamente el mismo techo que venía rechazando desde el principio.
    # Osea: cuando este rechazo aparece, significa que `precio_final`
    # (sin ningún descuento real) está por encima de lo que ML acredita
    # HOY para este ítem puntual -- ninguna cantidad de tachado "de
    # teatro" lo arregla, hace falta un descuento real (que esta función
    # nunca aplica sola, por diseño: el precio final es sagrado). La
    # única ganancia real de escalar era ninguna, y el costo SÍ era real:
    # hasta 7 PUTs de precio de más por intento sobre una publicación en
    # vivo.
    r2 = ml.meter_en_campana(item_id, cuenta, promotion_id, precio_final)

    if not r2.get("ok"):
        mensaje = r2.get("error") or ""
        challenge = _si_es_challenge(mensaje)
        if challenge:
            return challenge
        if _es_rechazo_por_credibilidad(mensaje):
            aviso = _revertir_precio(
                f"ML no acepta ${precio_final} como precio final para esta publicación en esta campaña -- "
                "rechazo de credibilidad. No es un problema del % de descuento visual (ningún tachado lo arregla): "
                "ML exige que el precio final tenga un descuento REAL respecto de lo que acredita para este ítem."
            )
            # Con el precio ya restaurado a su valor real, se vuelve a leer
            # el rango -- SOLO lectura, no se toca nada más -- para poder
            # avisar el techo genuino en vez de dejar a Maxx sin ningún
            # número para decidir.
            techo_msg = ""
            try:
                promos_post = ml.promociones_item(item_id, cuenta)
                entrada_post = next((p for p in promos_post if p.get("id") == promotion_id), None)
                techo = entrada_post.get("max_discounted_price") if entrada_post else None
            except Exception:
                techo = None
            if techo is not None and precio_previo is not None and float(precio_previo) > 0:
                techo_dec = Decimal(str(techo))
                desc_min_pct = float((1 - techo_dec / Decimal(str(precio_previo))) * 100)
                techo_msg = (
                    f" Ahora mismo ML acredita como máximo ${techo_dec:.0f} para este ítem "
                    f"(al menos {desc_min_pct:.1f}% de descuento real sobre su precio actual, ${precio_previo:.0f}) "
                    "-- para meterlo en esta campaña habría que bajar el precio final de verdad, no solo el tachado."
                )
            return {"ok": False, "error": aviso + techo_msg, "precio_pm": float(precio_pm),
                    "precio_final": float(precio_final),
                    "techo_acreditado_ml": float(techo) if techo is not None else None}
        aviso = _revertir_precio(f"ML rechazó el enrolamiento en la campaña: \"{mensaje}\".")
        return {"ok": False, "error": aviso}

    # Verificación del resultado real -- nunca se confía en que ML aplicó
    # exactamente lo pedido solo porque respondió sin error. Lo único
    # innegociable es que el precio final coincida con precio_final; el
    # tachado real puede ser el ajustado, no necesariamente el estándar.
    precio_real, tachado_real = r2.get("price"), r2.get("original_price")
    coincide = (
        precio_real is not None and tachado_real is not None
        and abs(float(precio_real) - float(precio_final)) < 1
        and abs(float(tachado_real) - float(tachado_aplicado)) < 1
    )
    if not coincide:
        r3 = ml.sacar_de_promocion(item_id, cuenta, "SELLER_CAMPAIGN", promotion_id)
        detalle_salida = "Se sacó de la campaña." if r3.get("ok") else f"Y no se pudo sacar de la campaña automáticamente: {r3.get('error')} -- revisá la publicación a mano."
        aviso = _revertir_precio(
            f"ML aplicó un resultado distinto al esperado pese al chequeo previo -- pedido: precio ${precio_final} con "
            f"tachado ${tachado_aplicado}, real: precio {precio_real!r}, tachado {tachado_real!r}. {detalle_salida}"
        )
        return {"ok": False, "error": aviso,
                "precio_pedido": float(precio_final), "precio_real": precio_real,
                "tachado_pedido": float(tachado_aplicado), "tachado_real": tachado_real}

    resultado = {"ok": True, "promotion_id": promotion_id, "nombre_campana": nombre_campana,
                 "precio": precio_real, "original_price": tachado_real,
                 "precio_tachado_pedido": float(tachado_aplicado),
                 "precio_pm": float(precio_pm), "precio_final": float(precio_final)}
    if ajuste_aviso:
        resultado["ajuste_cuotas_envio"] = ajuste_aviso
    if aviso_pct:
        resultado["aviso"] = aviso_pct
    return resultado


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


_CUOTAS_TAG_RE = re.compile(r"^cuota-simple-(\d+)$|^(\d+)x_campaign$")


def _cuotas_sin_interes(detalle: dict) -> int | None:
    """Corregido 2026-09-02 (bug real, encontrado por Maxx: "no me está
    trayendo en ninguna publicación el dato de si tiene cuotas o no").
    La versión anterior leía `detalle["installments"]["quantity"/"rate"]`
    -- confirmado en vivo que ese campo NO EXISTE en `/items/{id}`, ni
    filtrado por `attributes` ni en la respuesta completa sin filtrar
    (probado dos veces, items reales, ninguna trajo la clave). Nunca
    funcionó desde que se escribió.

    El mecanismo real (developers.mercadolibre.com.ar, campañas de
    cuotas): un ítem enrolado en una campaña de cuotas sin interés lo
    muestra en su array `tags`, con un valor tipo `cuota-simple-3`/
    `cuota-simple-6` (programa "Cuota Simple") o `3x_campaign` (u otro
    N -- programa de campañas con cuotas). Confirmado en vivo 2026-09-02
    contra un ítem real de Maxx (MLA3655836976, cuenta IT) que en ese
    momento mostraba cuotas en la publicación real: `tags` traía
    `"3x_campaign"`, sin ninguna clave `installments` en la respuesta.

    Si un ítem tuviera más de un tag de cuotas al mismo tiempo (no visto
    en un caso real, pero no confirmado que sea imposible), se queda con
    el N más alto -- asume que es el más favorable/reciente, no una
    regla documentada."""
    encontrados = []
    for tag in detalle.get("tags") or []:
        m = _CUOTAS_TAG_RE.match(tag)
        if m:
            encontrados.append(int(m.group(1) or m.group(2)))
    return max(encontrados) if encontrados else None


def _armar_fila(
    item_id: str, cuenta: str, detalle: dict, tipo: str, nombre_campana: str | None,
    precio_normal: Decimal, precio_oferta: Decimal,
    costo_provider, iva_provider, params: ParametrosMargen, tc: Decimal,
) -> tuple[FilaOferta, dict | None]:
    """Resuelve costo/IVA desde Táctica (nunca del PM Sheet, REQ §2.0) y
    arma la fila -- compartido entre `ofertas_activas` (campañas) y
    `ofertas_propias_activas` (PRICE_DISCOUNT) para no repetir la
    resolución de margen dos veces."""
    # Corregido 2026-09-02 (Maxx, en vivo: "hay muchísimos [SKU] que no
    # trae y ya vi varios de esos que en ML sí están cargados"). El SKU
    # puede vivir en `seller_custom_field` O en el atributo `SELLER_SKU`
    # -- mismo bug/fix ya confirmado en `ml_full.py` (`_sku_de_item`,
    # ver su docstring): acá solo se miraba `seller_custom_field`, y
    # encima el batch de `/items` nunca pedía el campo `attributes` (el
    # array de atributos del ítem), así que ese fallback ni siquiera
    # tenía datos para intentar. Se reutiliza la misma función, no se
    # duplica la lógica.
    sku_ml = _sku_de_item(detalle)
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
    sku_ml = _sku_de_item(d)  # ver el comentario en `_armar_fila` -- mismo fallback
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
        "cuotas_ofrecidas": _cuotas_sin_interes(d),
        "costo_envio_real": costo_envio_real_item(ml, item_id, cuenta),
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
                                 "sku": _sku_de_item(detalles.get(item_id, {})),
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


# ── Costo real de envío -- pedido de Maxx 2026-09-01, ver
# project_ofertas-ml-envio-gap en memoria. Reemplaza el aproximado fijo
# ($8.500 si el precio final supera $33.000, `S.shippingCost`/
# `S.shippingThreshold` en el frontend) por el costo REAL que ML le
# descontó en la última venta real de cada MLA. Congelado y actualizado
# "cada cierta cantidad de días" (decisión explícita de Maxx, no en
# vivo por panel) -- ver `iniciar_job_costos_envio` más abajo.

def ventas_recientes_por_item(ml: MLFullClient, cuenta: str, desde_iso: str, hasta_iso: str) -> dict[str, dict]:
    """Para cada publicación vendida en el rango, se queda con la orden
    PAGADA más reciente (fecha + `shipping.id`) -- no la suma de
    unidades como `ventas_por_item`, folgan la última venta real para
    poder resolver después su costo de envío puntual
    (`costo_envio_real`). Mismo endpoint/paginación que `ventas_por_item`
    (`/orders/search?seller=...&order.status=paid`) -- confirmado que
    ML NO tiene filtro por ítem en este endpoint (probado en vivo
    2026-09-01 con `item.id=`/`q=<sku>`, los dos ignorados en silencio),
    así que hay que barrer y filtrar del lado nuestro."""
    seller_id = SELLERS[cuenta]
    headers = {"Authorization": f"Bearer {ml._token(cuenta)}"}
    ultima: dict[str, dict] = {}
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
            fecha = orden.get("date_closed") or ""
            shipping_id = (orden.get("shipping") or {}).get("id")
            if not shipping_id:
                continue
            for oi in orden.get("order_items") or []:
                item_id = (oi.get("item") or {}).get("id")
                if not item_id:
                    continue
                previa = ultima.get(item_id)
                if previa is None or fecha > previa["fecha"]:
                    ultima[item_id] = {"fecha": fecha, "shipping_id": shipping_id, "orden_id": orden.get("id")}
        paging = (d or {}).get("paging") or {}
        total = paging.get("total", 0)
        offset += len(resultados)
        if offset >= total or not resultados:
            break
    return ultima


def costo_envio_real(ml: MLFullClient, cuenta: str, shipping_id) -> dict:
    """Costo real de envío que ML le descontó al vendedor en UNA venta
    puntual. Confirmado en vivo 2026-09-01 (MLA680197251, orden
    2000018227607384, cuenta IT): `GET /shipments/{id}` con el header
    `x-format-new: true` (obligatorio -- sin él ML devuelve el formato
    viejo) trae `lead_time.cost_type`/`lead_time.list_cost`.

    - `cost_type == "charged"`: el comprador pagó el envío -- no hay
      costo real que el vendedor absorba, se devuelve 0.
    - `cost_type == "free"` (envío gratis para el comprador -- el caso
      real que le interesa a Maxx, cuando ÉL absorbe el costo):
      `list_cost` es lo que ML le descuenta de verdad. Confirmado
      cruzando el detalle real de una venta puntual con Maxx: coincidió
      centavo a centavo ($8.890)."""
    headers = {"Authorization": f"Bearer {ml._token(cuenta)}", "x-format-new": "true"}
    d = ml._get(f"https://api.mercadolibre.com/shipments/{shipping_id}", {}, headers) or {}
    lead = d.get("lead_time") or {}
    cost_type = lead.get("cost_type")
    costo = Decimal(str(lead["list_cost"])) if cost_type == "free" and lead.get("list_cost") is not None else Decimal(0)
    return {"cost_type": cost_type, "costo_envio_real": float(costo)}


# Cache en memoria del último barrido -- item_id -> {"cuenta", "shipping_id",
# "orden_id", "fecha_venta"}. Se "congela" acá entre corridas del job
# (`iniciar_job_costos_envio`), y `resolver_item_para_gestion` lo consulta
# para resolver el costo real puntual SOLO del ítem que se está mirando
# (nunca pide /shipments para todo el catálogo de una -- eso sería miles
# de llamadas de más). Se pierde si el proceso reinicia, igual que
# `_jobs` -- mismo modelo de persistencia (o falta de) que el resto de
# este módulo.
_ultima_venta_cache: dict[str, dict] = {}


def costo_envio_real_item(ml: MLFullClient, item_id: str, cuenta: str) -> dict | None:
    """Resuelve el costo real de envío para UN ítem puntual, usando el
    `shipping_id` congelado por el último `iniciar_job_costos_envio` --
    `None` si ese ítem no vendió nada en la ventana del último barrido
    (todavía no corrido, o sin ventas recientes)."""
    entrada = _ultima_venta_cache.get(item_id)
    if not entrada:
        return None
    costo = costo_envio_real(ml, cuenta, entrada["shipping_id"])
    return {**costo, "orden_id": entrada["orden_id"], "fecha_venta": entrada["fecha"]}


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
            {"ids": ",".join(lote), "attributes": "id,title,permalink,seller_custom_field,available_quantity,attributes"},
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
                item_id=cuerpo["id"], cuenta=cuenta, sku=_sku_de_item(cuerpo),
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


def iniciar_job_costos_envio(job_id: str, cuentas: list = None, dias: int = 60) -> None:
    """Barre las ventas pagadas recientes (ambas cuentas por default) y
    "congela" en `_ultima_venta_cache` el `shipping_id` de la venta más
    reciente de cada publicación -- pedido explícito de Maxx 2026-09-01:
    correrlo cada tanto, no en vivo por ítem. NO llama a
    `/shipments/{id}` acá para todo el catálogo (sería carísimo) -- eso
    se resuelve recién por ítem puntual, al abrir su panel de gestión
    (`costo_envio_real_item`)."""
    _jobs[job_id] = {"status": "running", "log": ["Barriendo ventas recientes..."], "result": None, "progress": None}
    try:
        ml = MLFullClient()
        cuentas = cuentas or list(SELLERS.keys())
        hoy = date.today()
        # Mismo tope real de 60 días que ya vale para stock/fulfillment --
        # acá es /orders/search, sin ese límite documentado, pero no hay
        # necesidad real de ir más atrás: interesa la venta MÁS RECIENTE.
        desde = (hoy - timedelta(days=min(dias, 60))).isoformat() + "T00:00:00.000-00:00"
        hasta = hoy.isoformat() + "T23:00:00.000-00:00"
        total_items = 0
        for cuenta in cuentas:
            _jobs[job_id]["log"].append(f"Escaneando órdenes pagadas ({cuenta})...")
            ultimas = ventas_recientes_por_item(ml, cuenta, desde, hasta)
            for item_id, info in ultimas.items():
                _ultima_venta_cache[item_id] = {**info, "cuenta": cuenta}
            total_items += len(ultimas)
            _jobs[job_id]["log"].append(f"{len(ultimas)} publicaciones con venta reciente ({cuenta}).")
        _jobs[job_id]["result"] = {"publicaciones_actualizadas": total_items}
        _jobs[job_id]["status"] = "done"
        _jobs[job_id]["log"].append(f"Listo: {total_items} publicaciones con dato de envío congelado.")
    except Exception as e:
        _jobs[job_id]["status"] = "error"
        _jobs[job_id]["log"].append(f"Error: {e}")
