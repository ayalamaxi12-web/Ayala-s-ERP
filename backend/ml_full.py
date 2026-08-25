"""
Conciliación de stock Full — Mercado Libre vs depósito Full de Ecom.

Fase 6 de `docs/00_LEEME_PRIMERO.md`, detallada en
`docs/business/COMERCIAL/canales/mercadolibre/03_MODULO_FULL.md`. Reemplaza
la planilla `FULL_TABLA_OPERATIVA.xlsx` (bajada de reportes a mano) por una
consulta en vivo. **Solo lectura** — no escribe a ningún canal ni a Ecom
(la puerta de escritura del dominio Comercial sigue cerrada, ver
`docs/business/COMERCIAL/00_LEEME.md` §5; esto no la necesita).

Endpoints de Mercado Libre usados (confirmados contra la documentación real
del portal, ver `01_MAPA_API.md` §2.1 y §2.3 — no de memoria):
- `/users/{seller_id}/items/search?status=active` — reproduce la paginación
  de tres pasadas de `/ml-proxy/all-ids` en `main.py` (el límite de ~1000
  resultados de este buscador es el motivo del truco de 3 sorts).
- `/items?ids=ID1,ID2,...` (máx. 20 por request) — trae `inventory_id`,
  `variations`, `seller_custom_field`, `shipping.logistic_type`.
- `/inventories/{inventory_id}/stock/fulfillment` — `total`,
  `available_quantity`, `not_available_quantity`, `not_available_detail`.

Lado Ecom, descubierto por introspección GraphQL contra la cuenta real
(2026-08-20, no estaba en ningún lado de este repo todavía):
- Depósito Full: existe un warehouse real llamado "ML Full"
  (`ProductWarehouse.typeFull == true`) — nunca hardcodear su `id`, se
  resuelve en cada corrida por si cambia.
- Stock por SKU en ese depósito: `Product.variants[].variantWarehouses[]`
  (`warehouse_title`, `warehouse_qty`), vía `products.readBySku(sku)`.
- Factor de pack: **confirmado contra un ítem real** (Maxx dio
  `MLA2693713220`, la publicación "X2 CB435A-436A-CE285AUNIVCOMP", cuenta
  MT/group). El primer intento fue `mlListings.getKitComponents(itemId)`
  ("kits virtuales" de `01_MAPA_API.md` §2.1) — **descartado**: para este
  mismo ítem devuelve el error real `"La publicación no es un kit."` ("kit"
  es otra función de ML, combina productos DISTINTOS en una publicación,
  no packs de un mismo SKU). El dato correcto es
  `mlListings.read(id).productListings[].{qty, product.sku}` — devuelve
  exacto `qty=2`, `sku="CB435A-436A-CE285AUNIVCOMP"` contra el ítem real.
  Sigue cumpliendo la regla del doc (el factor sale del sistema que
  gestiona el vínculo, nunca del sufijo `X2`/`X5`) — el campo vive en
  Ecom aunque describe una relación nativa de Mercado Libre. Una
  publicación sin vincular da `linked: false` y `productListings: []`
  (visto en dos ítems reales sin pack) — se trata como incidencia, nunca
  como factor 1 asumido.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

import requests

from ml_auth import SELLERS, token_de
from rentabilidad import gsheets
from rentabilidad.ingesta_ecom_api import EcomApiClient, EcomApiError

# ── Transporte ML — inyectable para tests, sin red real ──

GetFn = Callable[[str, dict, dict], object]


def _get_real(url: str, params: dict, headers: dict):
    r = requests.get(url, params=params, headers=headers, timeout=20)
    r.raise_for_status()
    return r.json()


@dataclass
class ItemFullML:
    """Una fila = una variación (o el ítem entero si no tiene variaciones)
    de una publicación con `logistic_type == 'fulfillment'`."""
    item_id: str
    cuenta: str
    sku: str | None
    inventory_id: str | None
    titulo: str
    variacion_attrs: dict[str, str] | None = None  # {"Color": "Negro"} -- None si no es una variación


class MLFullClient:
    """Solo lectura del lado Mercado Libre. `get_fn` inyectable — mismo
    patrón que `PostFn` en `rentabilidad/ingesta_ecom_api.py`."""

    def __init__(self, get_fn: GetFn | None = None, token_fn: Callable[[str], str] | None = None):
        self._get = get_fn or _get_real
        self._token = token_fn or token_de

    def items_activos(self, cuenta: str) -> list[str]:
        """Pagina con `search_type=scan` + `scroll_id` -- confirmado
        contra `01_MAPA_API.md` §2.1 ("Para más de 1000 resultados usar
        `search_type=scan` con `scroll_id`") y contra la cuenta real
        (2026-08-20).

        **Reemplaza un bug real, no una limpieza cosmética**: la versión
        anterior pedía tres pasadas con distintos `sort` (offset 0-1000
        cada una) asumiendo que entre las tres se cubría todo. Se probó
        en producción contra la cuenta IT (2043 ítems activos) y **perdió
        un ítem real** -- `MLA1980317090` (SKU `KG002BKMINIPADWLS`,
        inventory_id `KZLL71843`, 76 unidades) no apareció en ninguna de
        las tres pasadas, y la conciliación reportó una diferencia falsa
        de -75 contra Ecom que en realidad era ~1. `scan` es el mecanismo
        que ML documenta para este caso exacto -- no una aproximación con
        más pasadas."""
        seller_id = SELLERS[cuenta]
        headers = {"Authorization": f"Bearer {self._token(cuenta)}"}
        ids: list[str] = []
        params = {"search_type": "scan", "status": "active", "limit": 100}
        while True:
            d = self._get(
                f"https://api.mercadolibre.com/users/{seller_id}/items/search", params, headers
            )
            resultados = d.get("results", [])
            if not resultados:
                break
            ids.extend(resultados)
            scroll_id = d.get("scroll_id")
            if not scroll_id:
                break
            params = {"search_type": "scan", "limit": 100, "scroll_id": scroll_id}
        return ids

    def detalle_items(self, item_ids: list[str], cuenta: str) -> list[dict]:
        """Máximo 20 ids por request — límite documentado
        (`01_MAPA_API.md` §2.1, "Traer varios ítems de una vez").

        **Bug real corregido (2026-08-26)**: el filtro de campos no pedía
        `attributes`, así que `item.attributes` volvía SIEMPRE vacío en este
        endpoint batch -- `_sku_de_item()` ya tenía el fallback al atributo
        `SELLER_SKU` escrito, pero nunca podía encontrarlo porque el dato ni
        siquiera llegaba. Caso real que lo expuso: `MLA1607512661`
        (inventory_id `COCF22823`) reportaba "sin SKU en ML" cuando en
        realidad tiene `SELLER_SKU = "X2 EMERLIGHT-30LED"` -- confirmado
        pidiendo el ítem sin ese filtro de campos."""
        headers = {"Authorization": f"Bearer {self._token(cuenta)}"}
        salida = []
        for i in range(0, len(item_ids), 20):
            lote = item_ids[i:i + 20]
            d = self._get(
                "https://api.mercadolibre.com/items",
                {"ids": ",".join(lote),
                 "attributes": "id,title,inventory_id,seller_custom_field,variations,shipping,attributes"},
                headers,
            )
            for entrada in d:
                cuerpo = entrada.get("body") if isinstance(entrada, dict) and "body" in entrada else entrada
                if cuerpo:
                    salida.append(cuerpo)
        return salida

    def stock_fulfillment(self, inventory_id: str, cuenta: str) -> dict:
        headers = {"Authorization": f"Bearer {self._token(cuenta)}"}
        return self._get(
            f"https://api.mercadolibre.com/inventories/{inventory_id}/stock/fulfillment", {}, headers
        )

    def ventas_full_por_inventory(
        self, cuenta: str, inventory_ids: list[str], desde: str, hasta: str,
    ) -> dict[str, dict]:
        """Ventas realmente despachadas DESDE FULL, agregadas por
        `inventory_id` -- en UNIDADES DE PAQUETE (mismo criterio que el
        stock: el llamador aplica el factor de pack, acá no).

        **Reemplaza un bug real de sobreconteo, no `/orders/search`+filtro
        de estado** (encontrado en producción 2026-08-25): una publicación
        `fulfillment` puede tener coexistencia Full/Flex (tag
        `self_service_in`) y despachar ALGUNAS ventas desde el depósito
        propio del vendedor, no desde Full. `/orders/search?order.status=
        paid` cuenta esas ventas igual que las de Full -- verificado con un
        caso real: la publicación `MLA1876051914` (inventory_id
        `FZBZ18741`) tiene 6 unidades vendidas y pagadas el 17/08 según
        `/orders/search`, pero el envío de esa orden específica
        (`/shipments/{id}`) da `"logistic_type": "self_service"`, no
        `"fulfillment"` -- esa venta nunca salió de Full y no debería
        contar para decidir cuánto reponerle a Full.

        La fuente correcta es `stock/fulfillment/operations/search`
        (confirmado contra la cuenta real, no de memoria):
        - Filtrado a `type=SALE_CONFIRMATION` está scopeado por diseño a
          movimientos del depósito Full -- no puede traer una venta
          self-service aunque quisiera. Confirmado con el mismo caso: para
          `inventory_id=FZBZ18741` en agosto completo devuelve `total: 0`.
        - `date_from`/`date_to` son fechas simples (`YYYY-MM-DD`), NO
          timestamps ISO como `/orders/search` -- y el rango tiene un tope
          real de 60 días (pedir más tira 400 "Date range can't be greater
          than 60 days"), lo clampea el llamador.
        - `inventory_id` acepta una lista separada por comas -- confirmado
          batcheando de a 20 (mismo tope que `detalle_items`).
        - Cada resultado trae `detail.available_quantity` (negativo = las
          unidades que descontó ESA operación puntual) y `date_created`
          (`YYYY-MM-DDTHH:MM:SSZ`).
        - Pagina con el token `scroll` de `paging.scroll` de la respuesta
          anterior -- confirmado que el nombre real es `scroll`, no
          `scroll_id` (se probó `scroll_id` primero: el servidor lo
          ignoraba en silencio y devolvía siempre la primera página)."""
        seller_id = SELLERS[cuenta]
        headers = {"Authorization": f"Bearer {self._token(cuenta)}"}
        acumulado: dict[str, dict] = {}
        for i in range(0, len(inventory_ids), 20):
            lote = inventory_ids[i:i + 20]
            params = {
                "seller_id": seller_id, "inventory_id": ",".join(lote),
                "date_from": desde, "date_to": hasta, "type": "SALE_CONFIRMATION",
            }
            paginas = 0
            while paginas < 50:  # tope de seguridad -- nunca debería hacer falta en un lote de 20
                paginas += 1
                d = self._get(
                    "https://api.mercadolibre.com/stock/fulfillment/operations/search", params, headers
                )
                resultados = d.get("results", [])
                for op in resultados:
                    inv = op.get("inventory_id")
                    if not inv:
                        continue
                    cantidad = abs((op.get("detail") or {}).get("available_quantity") or 0)
                    fecha = (op.get("date_created") or "")[:10]
                    entrada = acumulado.setdefault(inv, {"unidades": 0, "primera": fecha, "ultima": fecha})
                    entrada["unidades"] += cantidad
                    if fecha and (not entrada["primera"] or fecha < entrada["primera"]):
                        entrada["primera"] = fecha
                    if fecha and (not entrada["ultima"] or fecha > entrada["ultima"]):
                        entrada["ultima"] = fecha
                scroll = (d.get("paging") or {}).get("scroll")
                if not scroll or not resultados:
                    break
                params = {**params, "scroll": scroll}
        return acumulado


def _sku_de_item(item: dict) -> str | None:
    """El SKU propio puede vivir en `seller_custom_field` o en el atributo
    `SELLER_SKU` (pregunta abierta #1 de `02_MCP.md`, sin resolver
    todavía) — se intentan los dos, nunca se asume uno solo. Si ninguno
    resuelve, el llamador debe tratarlo como incidencia, no como SKU
    vacío silencioso."""
    scf = item.get("seller_custom_field")
    if scf:
        return scf
    for attr in item.get("attributes") or []:
        if attr.get("id") == "SELLER_SKU" and attr.get("value_name"):
            return attr["value_name"]
    return None


def extraer_items_full(items: list[dict], cuenta: str) -> tuple[list[ItemFullML], list[dict]]:
    """Filtra a `shipping.logistic_type == 'fulfillment'` y expande por
    variación (una variación = un `inventory_id` propio, nunca uno por
    publicación — confirmado en `01_MAPA_API.md` §2.3 y en
    `03_MODULO_FULL.md` §3.3). Devuelve (filas, incidencias de SKU no
    resuelto) — nunca descarta en silencio un ítem sin SKU."""
    filas: list[ItemFullML] = []
    incidencias: list[dict] = []
    for item in items:
        shipping = item.get("shipping") or {}
        if shipping.get("logistic_type") != "fulfillment":
            continue
        item_id = item.get("id")
        titulo = item.get("title", "")
        variaciones = item.get("variations") or []
        if variaciones:
            for var in variaciones:
                sku = var.get("seller_custom_field")
                for attr in var.get("attributes") or []:
                    if attr.get("id") == "SELLER_SKU" and attr.get("value_name"):
                        sku = sku or attr["value_name"]
                sku = sku or _sku_de_item(item)
                # {"Color": "Negro", ...} -- identifica la variación para
                # matchear contra la vinculación por variante de Ecom
                # (`EcomFullAdapter.factor_pack`), ver su docstring.
                attrs_variacion = {
                    a["name"]: a["value_name"]
                    for a in (var.get("attribute_combinations") or [])
                    if a.get("name") and a.get("value_name")
                } or None
                fila = ItemFullML(item_id=item_id, cuenta=cuenta, sku=sku,
                                   inventory_id=var.get("inventory_id"), titulo=titulo,
                                   variacion_attrs=attrs_variacion)
                filas.append(fila)
                if not sku:
                    incidencias.append({"item_id": item_id, "cuenta": cuenta, "motivo": "SIN_SKU"})
        else:
            sku = _sku_de_item(item)
            fila = ItemFullML(item_id=item_id, cuenta=cuenta, sku=sku,
                               inventory_id=item.get("inventory_id"), titulo=titulo)
            filas.append(fila)
            if not sku:
                incidencias.append({"item_id": item_id, "cuenta": cuenta, "motivo": "SIN_SKU"})
    return filas, incidencias


# ── Lado Ecom — depósito Full y factor de pack ──

_QUERY_WAREHOUSES = "{ productWarehouses { getAllWarehouses { id title typeFull } } }"

_QUERY_PRODUCT_STOCK = """
query($sku: String!) {
  products {
    readBySku(sku: $sku) {
      id
      variants { id variantWarehouses { warehouse_id warehouse_title warehouse_qty } }
    }
  }
}
"""

_QUERY_ML_LISTING = """
query($id: ID!) {
  mlListings {
    read(id: $id) {
      linked
      productListings { qty productId product { sku } }
    }
  }
}
"""


class EcomFullAdapter:
    """Lado Ecom de la conciliación. Un `EcomApiClient` inyectado (mismo
    cliente que usa `rentabilidad/ingesta_ecom_api.py` — no se reimplementa
    login ni manejo de cookie)."""

    def __init__(self, cliente: EcomApiClient):
        self._cliente = cliente
        self._warehouse_full_id: str | None = None
        self._deposito_disponible_id: str | None = None
        self._producto_cache: dict[str, dict | None] = {}

    def warehouse_full_id(self) -> str:
        """Nunca hardcodear el id del depósito Full — se resuelve en cada
        corrida por `typeFull`, no por nombre ni por id fijo (el nombre
        "ML Full" confirmado hoy podría cambiar). Si no hay exactamente
        uno marcado `typeFull`, es una configuración ambigua y se
        reporta, no se adivina cuál usar."""
        if self._warehouse_full_id is not None:
            return self._warehouse_full_id
        data = self._cliente.graphql(_QUERY_WAREHOUSES)
        candidatos = [w for w in data["productWarehouses"]["getAllWarehouses"] if w.get("typeFull")]
        if len(candidatos) != 1:
            raise EcomApiError(
                f"Se esperaba exactamente un depósito con typeFull=true, se encontraron {len(candidatos)}: {candidatos}"
            )
        self._warehouse_full_id = candidatos[0]["id"]
        return self._warehouse_full_id

    def deposito_disponible_id(self) -> str:
        """Depósito de Ecom con el stock realmente disponible para armar
        un envío a Full -- confirmado con Maxx (2026-08-20): es **Pitec**
        (antes se llamaba "Magaldi", mismo lugar, solo cambió de nombre).
        NO es "todo lo que no es Full": los depósitos Gaona/Outlet/
        Exposiciones/Showroom son marginales (exhibición, outlet) y no
        cuentan como stock enviable. Se resuelve por título contra la
        lista real de depósitos, igual que `warehouse_full_id`, nunca por
        id fijo."""
        if self._deposito_disponible_id is not None:
            return self._deposito_disponible_id
        data = self._cliente.graphql(_QUERY_WAREHOUSES)
        candidatos = [w for w in data["productWarehouses"]["getAllWarehouses"] if w.get("title") == "Pitec"]
        if len(candidatos) != 1:
            raise EcomApiError(
                f"Se esperaba exactamente un depósito 'Pitec', se encontraron {len(candidatos)}: {candidatos}"
            )
        self._deposito_disponible_id = candidatos[0]["id"]
        return self._deposito_disponible_id

    def _producto_por_sku(self, sku: str) -> dict | None:
        """Cachea la respuesta cruda por SKU dentro de la instancia --
        tanto `stock_full_por_sku` como `stock_disponible_por_sku` piden
        el mismo producto (`variantWarehouses` trae todos los depósitos
        en una sola llamada), así que el segundo pedido para el mismo SKU
        no vuelve a golpear la red."""
        if sku not in self._producto_cache:
            data = self._cliente.graphql(_QUERY_PRODUCT_STOCK, {"sku": sku})
            self._producto_cache[sku] = data.get("products", {}).get("readBySku")
        return self._producto_cache[sku]

    def _stock_en_deposito(self, sku: str, deposito_id: str, parent_sku: str | None = None) -> int | None:
        """`parent_sku` -- cuando `sku` es una variante puntual (color,
        talle), `readBySku` no la resuelve directo (confirmado contra la
        cuenta real: `readBySku("HTV-PVC-BLACK-G-50X1MT")` da `None`,
        solo el SKU padre `"HTV-PVC-G-50X1MT"` es una entrada real de
        `products`) -- hay que pedir el padre y quedarse con SU variante
        puntual, nunca sumar todas (eso tapa el stock de una variante con
        el de las demás, ver docstring de `factor_pack`)."""
        producto = self._producto_por_sku(parent_sku or sku)
        if not producto:
            return None
        variantes = producto.get("variants") or []
        if parent_sku and parent_sku != sku:
            variantes = [v for v in variantes if v.get("sku") == sku]
            if not variantes:
                return None
        total = 0
        for variante in variantes:
            for wh in variante.get("variantWarehouses") or []:
                if wh.get("warehouse_id") == deposito_id:
                    total += wh.get("warehouse_qty") or 0
        return total

    def stock_full_por_sku(self, sku: str, parent_sku: str | None = None) -> int | None:
        """`None` = el SKU no existe en Ecom (incidencia para el
        llamador, no un 0 silencioso). Si `sku` es una variante puntual
        (color/talle), pasar `parent_sku` -- ver `_stock_en_deposito`."""
        return self._stock_en_deposito(sku, self.warehouse_full_id(), parent_sku)

    def stock_disponible_por_sku(self, sku: str, parent_sku: str | None = None) -> int | None:
        """Stock en Pitec -- lo que hay para armar el próximo envío a
        Full. `None` = el SKU no existe en Ecom, igual que
        `stock_full_por_sku`."""
        return self._stock_en_deposito(sku, self.deposito_disponible_id(), parent_sku)

    def factor_pack(self, item_id: str) -> "FactorPack | None":
        """Factor real de multiplicación por venta.

        **Corregido 2026-08-20 contra un ítem real** (Maxx dio
        `MLA2693713220`, la publicación "X2 CB435A-436A-CE285AUNIVCOMP"):
        `mlListings.getKitComponents(itemId)` — mi primer intento — tira
        el error real `"La publicación no es un kit."` para ESTE mismo
        ítem, que sí es un pack. "Kits virtuales" es otra función de ML
        (combina productos DISTINTOS en una publicación), no esto.

        El dato correcto está en `mlListings.read(id).productListings[]`
        — confirmado con el ítem real: `qty=2`, `product.sku=
        "CB435A-436A-CE285AUNIVCOMP"`, coincide exacto con lo que Maxx
        describió. Un publicación simple vinculada debería dar `qty=1`
        sobre su propio SKU (no se probó contra un caso real todavía,
        pero se infiere de la semántica del campo).

        **Extendido 2026-08-26 para variaciones reales de ML** (Maxx
        reportó "me mostrás el stock del SKU madre, necesito la
        variante") -- confirmado contra un caso real (`MLA1516769711`,
        vinilo termotransferible con 2 colores activos en Full): a nivel
        ítem `product.sku` da un solo SKU "madre" (`HTV-PVC-G-50X1MT`)
        que en Ecom es apenas el contenedor de 18 variantes de color,
        cada una con su propio SKU y su propio stock -- confirmado por
        introspección directa del schema real de Ecom (no de memoria):
        `ProductListing.productVariantListings[].variant.{sku,
        variantAttributes}`. Usar solo `product.sku` para un ítem con
        variaciones reales colapsa el stock de todos los colores en un
        solo número, tapando el de la variante puntual que hay que
        reponer -- confirmado con el caso real: Blanco tenía 0 en Full,
        Negro tenía 3, pero las dos publicaciones de ML mostraban el
        mismo "SKU madre" sin distinguir cuál era cuál.

        `variantAttributes` (ej. `{"name": "Color", "options": "Negro"}`)
        es lo único que permite matchear cada variante de Ecom contra la
        variación real de ML (`ItemFullML.variacion_attrs`, extraído de
        `attribute_combinations`) -- no hay ningún id compartido entre
        los dos sistemas (`Variant.simIds` existe en el schema de Ecom
        para justamente esto, pero vino vacío en el caso real probado,
        así que no es una fuente confiable hoy).

        `None` = la publicación no está vinculada a ningún producto de
        Ecom (`linked: false`, `productListings` vacío — visto también
        en la realidad, en dos ítems sin pack). Es una incidencia de
        vinculación para el llamador, nunca un factor 1 asumido en
        silencio."""
        data = self._cliente.graphql(_QUERY_ML_LISTING, {"id": item_id})
        listing = (data.get("mlListings") or {}).get("read")
        entradas = (listing or {}).get("productListings") or []
        if not entradas:
            return None
        item_sku: dict[str, int] = {}
        variantes: list[dict] = []
        for pl in entradas:
            producto = pl.get("product")
            sku_padre = producto.get("sku") if producto else None
            if sku_padre:
                item_sku[sku_padre] = item_sku.get(sku_padre, 0) + (pl.get("qty") or 0)
            for pvl in pl.get("productVariantListings") or []:
                variante = pvl.get("variant") or {}
                sku_variante = variante.get("sku")
                atributos = {
                    a["name"]: a["options"] for a in (variante.get("variantAttributes") or [])
                    if a.get("name") and a.get("options")
                }
                if sku_variante and atributos:
                    variantes.append({
                        "atributos": atributos, "sku": sku_variante,
                        "qty": pl.get("qty") or 0, "parent_sku": sku_padre,
                    })
        if not item_sku and not variantes:
            return None
        return FactorPack(item_sku=item_sku, variantes=variantes)


@dataclass
class FactorPack:
    item_sku: dict[str, int]              # sku "madre" -> qty, resolución a nivel ítem (packs, publicaciones simples)
    variantes: list[dict] = field(default_factory=list)  # [{"atributos", "sku", "qty", "parent_sku"}]


# ── Táctica — stock, sin fuente SQL/API todavía ──

# Sheet externo "Stock e Importaciones" (cuenta personal, no de este repo),
# pestaña "Global". Confirmado con Maxx (2026-08-25): columna A=SKU,
# columna E=Stock Táctica -- se actualiza todas las mañanas, no es en vivo.
# Es la misma situación que ya resolvió `rentabilidad/` para costo/IVA de
# Táctica (ver memoria `project_rentabilidad-architecture`): un Sheet es
# solo la fuente ACTUAL porque no hay SQL/API para stock todavía, no una
# fuente permanente -- reemplazar cuando Táctica exponga esto directo.
_SHEET_STOCK_IMPORTACIONES = "1xtD_C07rN9Oesn277mD8x-ERPgsZxup3WqF_c_qXJp8"
_TAB_STOCK_TACTICA = "Global"

LeerValoresFn = Callable[[str, str], list]


class TacticaStockSheetAdapter:
    """Lee el Sheet una sola vez por instancia (una corrida de job) y cachea
    en memoria -- el mismo patrón de cache-por-instancia que
    `EcomFullAdapter._producto_cache`. `leer_fn` inyectable para tests, sin
    red real (mismo patrón que `GetFn` de `MLFullClient`)."""

    def __init__(self, leer_fn: LeerValoresFn | None = None):
        self._leer = leer_fn or gsheets.leer_valores
        self._stock_por_sku: dict[str, int] | None = None

    def _cargar(self) -> dict[str, int]:
        if self._stock_por_sku is not None:
            return self._stock_por_sku
        filas = self._leer(_SHEET_STOCK_IMPORTACIONES, _TAB_STOCK_TACTICA)
        idx_header = gsheets.encontrar_fila_headers(filas, ["SKU"])
        mapa = gsheets.mapa_columnas(filas[idx_header])
        idx_sku = gsheets.indice_columna(mapa, ["sku"])
        idx_stock = gsheets.indice_columna(mapa, ["stock tactica"])
        resultado: dict[str, int] = {}
        if idx_sku is not None and idx_stock is not None:
            for fila in filas[idx_header + 1:]:
                sku = gsheets.valor(fila, idx_sku)
                if not sku:
                    continue
                crudo = gsheets.valor(fila, idx_stock).replace(",", "").replace("$", "")
                if crudo in ("", "-"):
                    resultado[sku] = 0
                    continue
                try:
                    resultado[sku] = int(float(crudo))
                except ValueError:
                    continue
        self._stock_por_sku = resultado
        return resultado

    def stock_por_sku(self, sku: str) -> int | None:
        """`None` = el SKU no aparece en el Sheet -- igual criterio que
        `EcomFullAdapter.stock_full_por_sku` (incidencia, no 0 silencioso)."""
        return self._cargar().get(sku)


# ── Conciliación ──

@dataclass
class FilaConciliacion:
    sku: str
    stock_ml: int
    stock_ecom: int | None
    diferencia: int | None
    publicaciones: list[dict] = field(default_factory=list)  # [{item_id, cuenta, inventory_id, cantidad_en_full}]
    parent_sku: str | None = None  # si `sku` es una variante puntual, el SKU "madre" para consultar Ecom (ver factor_pack)


@dataclass
class ResultadoConciliacion:
    filas: list[FilaConciliacion]
    incidencias_sku: list[dict]  # items ML sin SKU resuelto (ver extraer_items_full)
    incidencias_sin_vincular: list[dict]  # items ML sin vinculación en Ecom -- factor 1 asumido, no confirmado
    skus_no_en_ecom: list[str]


def conciliar(ml: MLFullClient, ecom: EcomFullAdapter, cuentas: list[str] | None = None) -> ResultadoConciliacion:
    """Orquesta todo el módulo (puntos 1 a 4 de `03_MODULO_FULL.md` §10):
    traer publicaciones Full de las DOS cuentas, deduplicar por
    `inventory_id` (§3.3 — dos publicaciones de la misma variación
    comparten inventario y sumarlas lo duplicaría), resolver el factor real
    contra la vinculación de Ecom (`EcomFullAdapter.factor_pack`, cubre
    packs, publicaciones simples vinculadas, Y variaciones reales de ML
    vinculadas por variante -- ver `_resolver_vinculacion`), sumar por SKU
    (el SKU real de la variante cuando aplica, nunca el "SKU madre"), y
    comparar contra el depósito Full de Ecom."""
    cuentas = cuentas or list(SELLERS.keys())

    filas_ml: list[ItemFullML] = []
    incidencias_sku: list[dict] = []
    for cuenta in cuentas:
        ids = ml.items_activos(cuenta)
        items = ml.detalle_items(ids, cuenta)
        filas, incid = extraer_items_full(items, cuenta)
        filas_ml.extend(filas)
        incidencias_sku.extend(incid)

    # Deduplicar por inventory_id — nunca sumar por publicación (§3.3).
    vistos: set[str] = set()
    filas_dedup: list[ItemFullML] = []
    for fila in filas_ml:
        clave = fila.inventory_id or f"sin-inventory-id:{fila.item_id}"
        if clave in vistos:
            continue
        vistos.add(clave)
        filas_dedup.append(fila)

    # Stock por inventory_id (una llamada por inventario único).
    stock_por_inventory: dict[str, dict] = {}
    for fila in filas_dedup:
        if not fila.inventory_id:
            continue
        stock_por_inventory[fila.inventory_id] = ml.stock_fulfillment(fila.inventory_id, fila.cuenta)

    # Factor real por item_id único (una llamada por publicación única) --
    # `factor_pack` ya cubre packs Y publicaciones simples vinculadas, con
    # el mismo mecanismo (`mlListings.read(id).productListings`), y ahora
    # también variaciones reales de ML (`productVariantListings`).
    factor_por_item: dict[str, FactorPack | None] = {}
    for fila in filas_dedup:
        if fila.item_id not in factor_por_item:
            factor_por_item[fila.item_id] = ecom.factor_pack(fila.item_id)

    # Sumar por SKU. Si Ecom confirma vinculación (a nivel ítem o a nivel
    # variante), se usa SU sku+factor (autoritativo). Si no está vinculada
    # -- o si la variación real de ML no matchea contra ninguna variante
    # vinculada -- se cae al SKU que ya trajo ML con factor 1, pero eso es
    # una ASUNCIÓN sin confirmar y se registra como incidencia aparte
    # (nunca en silencio, ver `_resolver_vinculacion`).
    acumulado: dict[str, int] = {}
    parent_sku_por_sku: dict[str, str | None] = {}
    publicaciones_por_sku: dict[str, list[dict]] = {}
    incidencias_sin_vincular: list[dict] = []
    for fila in filas_dedup:
        if not fila.inventory_id:
            continue
        disponible = (stock_por_inventory.get(fila.inventory_id) or {}).get("available_quantity", 0) or 0
        factor_ecom = factor_por_item.get(fila.item_id)
        pares, vinculado, incidencia = _resolver_vinculacion(fila, factor_ecom)
        if incidencia:
            incidencias_sin_vincular.append(incidencia)
        for sku_resuelto, cantidad, parent_sku in pares:
            acumulado[sku_resuelto] = acumulado.get(sku_resuelto, 0) + disponible * cantidad
            parent_sku_por_sku[sku_resuelto] = parent_sku
            publicaciones_por_sku.setdefault(sku_resuelto, []).append({
                "item_id": fila.item_id, "cuenta": fila.cuenta, "inventory_id": fila.inventory_id,
                "disponible": disponible, "factor": cantidad, "vinculado": vinculado,
                "titulo": fila.titulo, "sku_ml": fila.sku,
            })

    filas_resultado: list[FilaConciliacion] = []
    skus_no_en_ecom: list[str] = []
    for sku, total_ml in acumulado.items():
        parent_sku = parent_sku_por_sku.get(sku)
        stock_ecom = ecom.stock_full_por_sku(sku, parent_sku)
        if stock_ecom is None:
            skus_no_en_ecom.append(sku)
        diferencia = None if stock_ecom is None else total_ml - stock_ecom
        filas_resultado.append(FilaConciliacion(
            sku=sku, stock_ml=total_ml, stock_ecom=stock_ecom, diferencia=diferencia,
            publicaciones=publicaciones_por_sku.get(sku, []), parent_sku=parent_sku,
        ))

    return ResultadoConciliacion(
        filas=filas_resultado, incidencias_sku=incidencias_sku,
        incidencias_sin_vincular=incidencias_sin_vincular, skus_no_en_ecom=skus_no_en_ecom,
    )


def _resolver_vinculacion(
    fila: ItemFullML, factor_ecom: "FactorPack | None",
) -> tuple[list[tuple[str, int, str | None]], bool, dict | None]:
    """Resuelve UNA publicación/variación a `[(sku, factor, parent_sku), ...]`
    -- nunca cae en silencio al SKU madre cuando ML trae una variación real
    y Ecom no la vincula a ese nivel (ver docstring de `factor_pack`).

    Orden de resolución:
    1. Es una variación de ML (`variacion_attrs`) y Ecom vinculó por
       variante (`factor_ecom.variantes`) -- matchea por atributos
       (Color/Talle/etc). Si matchea, autoritativo. Si NO matchea
       ninguna, es una incidencia propia (`VARIANTE_SIN_MATCH_EN_ECOM`) --
       nunca se asume la variante que sea, cae al SKU de ML con factor 1.
    2. Vinculación a nivel ítem (`factor_ecom.item_sku`, caso de siempre:
       packs y publicaciones simples). Si la fila SÍ es una variación de
       ML pero acá no hay desglose por variante, se usa igual (mejor que
       nada) pero se deja una incidencia visible
       (`VARIANTE_VINCULADA_SOLO_A_NIVEL_ITEM`) en vez de tapar el hueco.
    3. Sin vinculación en Ecom -- cae al SKU de ML, factor 1, incidencia
       (comportamiento de siempre)."""
    if factor_ecom and fila.variacion_attrs and factor_ecom.variantes:
        for v in factor_ecom.variantes:
            if all(v["atributos"].get(k) == val for k, val in fila.variacion_attrs.items()):
                return [(v["sku"], v["qty"], v["parent_sku"])], True, None
        incidencia = {
            "item_id": fila.item_id, "cuenta": fila.cuenta, "sku_ml": fila.sku,
            "motivo": "VARIANTE_SIN_MATCH_EN_ECOM_FACTOR_1_ASUMIDO",
        }
        return ([(fila.sku, 1, None)] if fila.sku else []), False, incidencia

    if factor_ecom and factor_ecom.item_sku:
        pares = [(sku, cantidad, None) for sku, cantidad in factor_ecom.item_sku.items()]
        incidencia = None
        if fila.variacion_attrs:
            incidencia = {
                "item_id": fila.item_id, "cuenta": fila.cuenta, "sku_ml": fila.sku,
                "motivo": "VARIANTE_VINCULADA_SOLO_A_NIVEL_ITEM",
            }
        return pares, True, incidencia

    if fila.sku:
        incidencia = {
            "item_id": fila.item_id, "cuenta": fila.cuenta, "sku_ml": fila.sku,
            "motivo": "SIN_VINCULAR_EN_ECOM_FACTOR_1_ASUMIDO",
        }
        return [(fila.sku, 1, None)], False, incidencia

    return [], False, None


# ── Job en background — mismo patrón que /ml/tracker/run y /ml/vendedor/run
# de main.py (job_status propio, no compartido, para no acoplar con main). ──

_jobs: dict[str, dict] = {}


def iniciar_job(job_id: str, ecom_email: str | None = None, ecom_password: str | None = None) -> None:
    _jobs[job_id] = {"status": "running", "log": ["Iniciando conciliación Full..."], "result": None}
    try:
        ml = MLFullClient()
        ecom = EcomFullAdapter(EcomApiClient(email=ecom_email, password=ecom_password))
        resultado = conciliar(ml, ecom)
        _jobs[job_id]["result"] = {
            "filas": [
                {"sku": f.sku, "stock_ml": f.stock_ml, "stock_ecom": f.stock_ecom,
                 "diferencia": f.diferencia, "publicaciones": f.publicaciones}
                for f in resultado.filas
            ],
            "incidencias_sku": resultado.incidencias_sku,
            "incidencias_sin_vincular": resultado.incidencias_sin_vincular,
            "skus_no_en_ecom": resultado.skus_no_en_ecom,
        }
        _jobs[job_id]["status"] = "done"
        _jobs[job_id]["log"].append(f"Listo: {len(resultado.filas)} SKUs conciliados.")
    except Exception as e:
        _jobs[job_id]["status"] = "error"
        _jobs[job_id]["log"].append(f"Error: {e}")


def estado_job(job_id: str) -> dict | None:
    return _jobs.get(job_id)
