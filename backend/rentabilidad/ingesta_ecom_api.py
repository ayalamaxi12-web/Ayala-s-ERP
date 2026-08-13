"""Cliente GraphQL de la API V2 de EcomExperts — mismo origen de datos que
`ingesta_ecom.py` (el Excel que hoy se descarga a mano), transporte
distinto. No reemplaza al adaptador de Excel: ambos coexisten (Excel sigue
siendo la fuente de prueba/regresión — pedido explícito de Maxx, 2026-08-10).

Contrato relevado por Maxx contra la documentación real de EcomExperts V2
(no de memoria — mandato de `docs/00_LEEME_PRIMERO.md` §4):

- Login: `POST https://api.ecomexperts.com/users/users/doLogin.json` con
  `{"User": {"email_address": ..., "password": ...}}` — devuelve una cookie
  `CAKEPHP` por `Set-Cookie`.
- La cookie expira todos los días a las 00:06 UTC (hora fija, confirmada).
- GraphQL: `POST https://api.ecomexperts.com/graphql` con `Cookie:
  CAKEPHP=<valor>`.
Reutiliza el mismo host/endpoint de login que `ecom_login()` en
`backend/main.py`, pero es un cliente independiente: `main.py` recibe el
email/password del pedido HTTP (la sesión interactiva del operador, guardada
en `localStorage` del frontend); este cliente es para un job de servidor sin
usuario delante, así que las credenciales solo pueden venir de variable de
entorno (`RENT_ECOM_EMAIL` / `RENT_ECOM_PASSWORD`) — nunca hardcodeadas
(pedido explícito de Maxx).

CONTRATO CONFIRMADO CONTRA LA API REAL (introspección + muestra de órdenes
reales, 2026-08-10, con `RENT_ECOM_EMAIL`/`RENT_ECOM_PASSWORD` de Maxx — no
de memoria, mandato de `docs/00_LEEME_PRIMERO.md` §4):

- `orders.find(...)` devuelve `OrderFindResult { pageInfo, data }` — el
  wrapper de resultados es **`data`**, no `items`.
- `dateRange.field` acepta `"MtOrder.created"` y `"MtOrder.close_date"`
  (confirmado en `findSettings.dateRange.availableFields`); `byDate.start/
  end` son Unix timestamp, límite de 100 días por consulta
  (`customRangeLimit`, tal como ya sabía Maxx) — la API corta con error
  explícito (`"'dateRange': límite máximo en días excedido"`) si se supera,
  no trunca en silencio (confirmado 2026-08-12).
- **Tab**: `find(tab: ID, ...)` filtra por `findSettings.tabs.options` —
  confirmado 2026-08-12: `active` (Abiertas), `closed` (Cerradas), `draft`
  (Presupuestos), `inactive` (Inactivas), `trash` (Eliminadas). **Sin
  especificar `tab`, la API usa `active` por defecto** — es la causa
  confirmada de que una consulta sin `tab` traía solo un puñado de órdenes
  (las abiertas del momento) en vez del universo real del período. Para
  Rentabilidad participan `active` + `closed` (decisión de Maxx,
  2026-08-12: son las órdenes que representan una venta real, en curso o
  cerrada); `draft`/`inactive`/`trash` no participan.
- **Paginación engañosa pasado un techo**: confirmado contra la API real
  (2026-08-12, rango 2026-06-10..2026-08-10, tab=`closed`, sin filtrar
  cuenta): de la página 1 a la 9, `pageInfo` repite siempre
  `count=300, pageCount=10` sin importar cuántas órdenes reales haya más
  allá de eso; recién en la página 10 empieza a corregirse de a 30 por
  página (`count` 330, 360, 390...) y así indefinidamente — nunca informa
  el total real por adelantado. `buscar_ordenes()` no confía en
  `pageCount`: usa `count` de la página 1 solo como señal de "esto puede
  estar truncado" para decidir si partir el rango de fechas, y cada
  sub-rango sigue paginando hasta que la API devuelve una página vacía.
- **Multi-cuenta**: `findSettings.filters` expone `ch_account` ("Cuenta")
  con 5 valores reales (`GLOBALELECTRONICSGROUP`, `GLOBALELECTRONICSARG`,
  `Globalecom`, `MERCADOECOMSA`, `FRAVEGA`) — sin filtrar, `orders.find`
  mezcla pedidos de las 5. Decisión explícita de Maxx (2026-08-12): **no
  se filtra por cuenta**, se incluyen las 5 tal cual las devuelve la API.
- **`MtOrder.created` se compara en huso horario Argentina (UTC-3), no
  UTC** — causa raíz confirmada (2026-08-12, no una hipótesis) de que
  pedir un solo día con límites en UTC devolvía sistemáticamente ese día
  MÁS el día anterior completo (nunca el día siguiente): la medianoche UTC
  de un día D son las 21:00 ART del día D-1, y Ecom redondea el inicio del
  rango al día ART que contiene ese instante. Verificado con 3 consultas
  de un solo día sin ninguna recursión de por medio (`tab=closed`):
  pedir 2026-07-23 con límites UTC trajo 293 órdenes de 2026-07-22 + 292 de
  2026-07-23; pedir 2026-08-11 trajo 347 de 2026-08-10 + 329 de 2026-08-11
  — nunca se coló el día siguiente en ningún caso. Repitiendo la misma
  consulta con los límites calculados en ART (UTC-3) en vez de UTC, cada
  día devolvió *exactamente* sus propias órdenes (292 y 329
  respectivamente, sin arrastre). `_unix()`/`_unix_fin_de_dia()` calculan
  los límites en `_ZONA_HORARIA_ARGENTINA`, no en UTC, por esto. (Esto
  también explica el ~47% de "duplicados" que se veían antes de este fix:
  cada día arrastraba el día anterior completo, que a su vez ya había sido
  devuelto por la consulta de ESE día — `buscar_ordenes()` sigue
  deduplicando por id como defensa en profundidad, pero ya no debería
  hacer falta con los límites corregidos.)
- **Estado de pago**: `Order.paymentStatus` es un `String` con las claves en
  inglés (`paid`, `partially_paid`, `not_paid`, `in_mediation`, `refunded`,
  `cancelled`). El filtro `orders.findSettings.filters` (id=`"payment"`)
  da la traducción real a las etiquetas en español del Excel: `paid` →
  `"Cobrado"`, `partially_paid` → `"Cobro Parcial "` (**con espacio final
  real** — hay que `.strip()`), `not_paid` → `"Sin Cobro"`, `in_mediation`
  → `"En Mediación"`, `refunded` → `"Reembolsado"`. `cancelled` → `"Cancelado"`
  no tiene equivalente en el Excel — cae excluido igual, por la misma
  lista blanca (`ESTADOS_PAGO_QUE_PARTICIPAN` de `ingesta_ecom.py`, **sin
  duplicarla**: se traduce la clave de la API a la etiqueta española y se
  compara contra la misma regla ya validada).
- **Número de orden**: `Order.id` NO es el "Número Orden" que se ve en
  Ecom/Excel — es la clave interna de la API, de una escala totalmente
  distinta (~71 millones, y probablemente compartida entre las cuentas del
  mismo EcomExperts, ver hallazgo de multi-cuenta más abajo). El campo que
  coincide exactamente con la columna "Número Orden" del Excel es
  `Order.customOrderId` (confirmado 2026-08-13: `id=71583764` →
  `customOrderId='1307639'`, primera fila de un Excel real del
  2026-01-01). `_fila_desde_orden` usa `customOrderId` para
  `FilaEcom.numero_orden`; `id` se sigue usando tal cual para el dedupe
  interno de `buscar_ordenes()` porque es la clave que la propia API
  garantiza única, y no se confirmó que `customOrderId` lo sea entre
  cuentas.
- **Canal de venta**: `Order.owner` es el código crudo (`"MlShipping"`,
  `"MlOrder"`, `"ChChannelOrder"`, `"Venta Interna"`, nombres de empleado
  para ventas manuales...). El filtro `orders.findSettings.filters`
  (id=`"owner"`, nombre visible "Canal") da la etiqueta real — `MlShipping`
  → `"Mercadolibre Carrito"` — que es la que aparece en el Excel. Se
  resuelve **en vivo contra `findSettings`**, no hardcodeada (mandato de
  Maxx: nunca asumir un mapeo de canal).
- **Costo de envío**: `Shipping.cost` casi siempre viene en `0` en la
  muestra real. `Shipping.listCost` por sí solo NO alcanza — corrección
  2026-08-13, contra un Excel real (2026-01-01): `listCost` es el costo de
  catálogo del método de envío, pero solo lo paga el vendedor (y por lo
  tanto solo cuenta como "Costo Envío" en el Excel) cuando
  `Shipping.freeShipping` es `true` (el vendedor ofreció envío gratis al
  comprador — práctica real de MercadoLibre — y por eso absorbe el costo
  él mismo). Cuando `freeShipping` es `false` (el comprador paga su propio
  envío), "Costo Envío" es `0` para el vendedor sin importar cuánto diga
  `listCost`. Confirmado sin excepciones contra 19 órdenes reales de una
  muestra del 2026-01-01: `costo_envio = listCost if freeShipping else 0`.
  (La afirmación anterior, de que `listCost` solo bastaba, se apoyaba en
  una única coincidencia de valor —7821— que resultó ser, por casualidad,
  un caso con `freeShipping=true`; no estaba mal el valor, sí la regla
  general que se infirió de un solo dato.)
- **Precio Sin IVA con IVA real por línea, no un % fijo**: confirmado
  2026-08-13 contra un Excel real (orden 1307526, un kit) — cada
  `OrderList` trae su propio `taxTag` (ej. `"10.5"`, `"21"`) y
  `taxSubtotalPrice` ya descuenta el IVA usando ESA tasa real, no una
  fija; `subtotalSinImpuestos = subtotal - taxSubtotalPrice` por línea ya
  es el desglose correcto por SKU que pidió Maxx (2026-08-13: "tomemos
  siempre el IVA del producto... si está compuesto por skus de ambos,
  hacer el desglose de cada monto"). Sumar `subtotalSinImpuestos` de todas
  las líneas (lo que ya hace este adaptador) es exactamente esa regla —
  **no hace falta ningún cambio acá**. El propio reporte de Ecom (both
  "Precio Neto" del export básico y "Precio SIN IVA" del export
  "Rentabilidad") usa en cambio un divisor fijo de 1,10 sin importar el
  `taxTag` real de la orden — confirmado que ES el propio Ecom el que se
  aparta de la regla real, no este adaptador: para la orden 1307526
  (`taxTag="10.5"`), el Excel de Ecom da `93797.4/1.10=85270.364`, mientras
  que la fórmula con la tasa real da `93797.4-8912.875=84884.525` (el
  `taxSubtotalPrice` real que trae la propia API para esa línea). No
  comparar "Precio Sin IVA" 1:1 contra esos exports de Ecom esperando que
  coincida — es una divergencia esperada, no un bug de este adaptador.
- **Comisión de venta**: no hay un campo único — se resuelve como
  `sum(payments[].totalFeeAmount)`. Confirmado por Maxx (2026-08-10): la
  fórmula real de la planilla toma comisión de venta + envío y descuenta el
  costo total, además de imp. cheque/IIBB — coincide con esta suma. Los
  "impuestos informativos" que trae Ecom (`Payment.retenciones`) son parte
  de lo que ya cubren el 1,2%/5% calculados por el motor — no se suman
  aparte, mismo criterio que ya regía para el Excel.
- **Postventa/RMA**: la API usa `"Posventa"` (sin "t"), el Excel
  `"Postventa"` (con "t") — **Maxx confirmó (2026-08-10) que son el mismo
  concepto.** Se detecta con `owner == "Posventa"` (valor real de la API).
  Verificado además contra una orden real de la muestra: forzó Precio
  Final/Precio Sin IVA a 0 y conservó el costo, tal como especifica la regla.
- **SKU por línea**: `OrderList.variant.sku` viene `null` en una porción
  real de las líneas (variantes sin SKU propio cargado en Ecom). Fallback
  confirmado con datos reales: `OrderList.variant.product.sku` (el
  producto padre) SÍ está poblado en esos casos — mismo concepto que "SKU
  madre" del Excel, resuelto acá con una relación explícita en vez de
  heurística de texto.
- **Costo del producto**: `Variant.costUsd` — es un costo por unidad del
  catálogo (la variante no conoce la cantidad de una orden puntual), se
  multiplica por `OrderList.quantity` y se suma entre líneas para el total
  de la orden (equivalente a "Costo Sin Iva (total de productos)").
- **Precio Final / Precio Sin IVA**: no vienen a nivel de orden, se
  reconstruyen sumando `OrderList.subtotal` / `OrderList.subtotalSinImpuestos`
  de todas las líneas — confirmado contra un pago real de la misma orden
  (`payments[0].transactionAmount` coincidía exactamente con la suma de
  `subtotal`).
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Callable

from . import config
from .ingesta_ecom import ESTADOS_PAGO_QUE_PARTICIPAN, FilaEcom, ResultadoIngestaEcom

# `ingesta_ecom.CANAL_POSVENTA` ("Postventa", con "t") es el valor
# verificado por Maxx contra el Excel real. El filtro `owner` de la API
# real lista "Posventa" (sin "t") — no confirmado que sean el mismo
# concepto (ver docstring del módulo). Se usa el valor real observado en la
# API, no el de Excel, porque es contra lo que esta clase compara.
_OWNER_POSVENTA_API = "Posventa"

_BASE_URL = "https://api.ecomexperts.com"
_LOGIN_PATH = "/users/users/doLogin.json"
_GRAPHQL_PATH = "/graphql"

# Confirmado por Maxx (2026-08-10): la cookie CAKEPHP expira todos los días
# a esta hora fija, no un TTL relativo al momento del login.
_HORA_EXPIRACION_UTC = time(0, 6)


class EcomApiError(RuntimeError):
    """Error de transporte u autenticación contra la API de EcomExperts."""


@dataclass
class _Respuesta:
    """Forma mínima y uniforme que necesita este módulo de una respuesta
    HTTP — permite inyectar `post_fn` en los tests sin depender de
    `requests` ni de credenciales reales."""

    status_code: int
    headers: dict
    body: dict | str


PostFn = Callable[[str, dict, str | None], _Respuesta]


_REINTENTOS_TRANSPORTE = 3

# Falla real observada (2026-08-12): al paginar un rango con muchas órdenes
# (~190 requests seguidos, sin filtrar cuenta) la conexión se corta a mitad
# de un handshake TLS (`ConnectionResetError`) — no es hipotético, ocurre
# en la práctica al traer el universo completo de un período. Un solo
# reintento con espera corta la resuelve (confirmado); no confundir con un
# error de autenticación/GraphQL, que no se reintenta acá.
def _post_real(url: str, json_body: dict, cookie: str | None) -> _Respuesta:
    """Import perezoso de requests — mismo principio que `gsheets.get_client()`
    y `ingesta_tactica._ejecutar_query_real()`: el resto del módulo no
    depende de red para testearse."""
    import time as _time

    import requests

    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if cookie:
        headers["Cookie"] = cookie

    ultimo_error = None
    for intento in range(_REINTENTOS_TRANSPORTE):
        try:
            resp = requests.post(url, json=json_body, headers=headers, timeout=30)
            break
        except requests.exceptions.ConnectionError as error:
            ultimo_error = error
            if intento == _REINTENTOS_TRANSPORTE - 1:
                raise EcomApiError(f"Fallo de conexión persistente contra EcomExperts: {error}") from error
            _time.sleep(1.5 * (intento + 1))
    try:
        body = resp.json()
    except ValueError:
        body = resp.text
    return _Respuesta(status_code=resp.status_code, headers=dict(resp.headers), body=body)


def _cookie_de_headers(headers: dict) -> str | None:
    """Misma lógica que `ecom_login()` de `backend/main.py`: puede haber
    varias cookies en `Set-Cookie` (coma-separadas); se toma la última
    `CAKEPHP=` que no sea de borrado.

    BUG real encontrado en el primer contacto con la API real (2026-08-10,
    no en tests): el separador ", " entre cookies deja un espacio inicial
    en cada fragmento después del primero (`" CAKEPHP=..."`), que
    `requests` rechaza como header inválido. `main.py` lo esconde
    aplicando `.strip()` en `ecom_request()` justo antes de usarlo — acá
    se aplica en el origen, para que el valor guardado en `self._cookie`
    ya sea válido para cualquier `post_fn`, no solo para `requests`."""
    set_cookie = headers.get("set-cookie") or headers.get("Set-Cookie") or ""
    partes = [c.split(";")[0].strip() for c in set_cookie.split(",") if "CAKEPHP=" in c and "deleted" not in c]
    return partes[-1] if partes else None


def _proxima_expiracion(desde: datetime) -> datetime:
    """Si el login ocurrió antes de las 00:06 UTC de hoy, la cookie expira
    hoy a esa hora; si ocurrió después, expira a esa hora de mañana."""
    hoy_0006 = datetime.combine(desde.date(), _HORA_EXPIRACION_UTC, tzinfo=timezone.utc)
    return hoy_0006 if desde < hoy_0006 else hoy_0006 + timedelta(days=1)


def _parece_error_de_autenticacion(resp: _Respuesta) -> bool:
    """Heurística — no confirmada contra una respuesta real de cookie
    vencida (pendiente, ver docstring del módulo): además del 401/403 HTTP,
    EcomExperts puede devolver 200 con un array `errors` de GraphQL. Si
    algún mensaje menciona autenticación/sesión, se reintenta una vez con
    login nuevo en vez de fallar directo."""
    if resp.status_code in (401, 403):
        return True
    if isinstance(resp.body, dict):
        errores = resp.body.get("errors") or []
        texto = " ".join(str(e.get("message", "")) for e in errores if isinstance(e, dict)).lower()
        return any(palabra in texto for palabra in ("auth", "sesión", "sesion", "login", "unauthorized"))
    return False


class EcomApiClient:
    """Solo transporte: login + cache de cookie + `graphql()` genérico. No
    decide qué preguntar — eso es `buscar_ordenes()` u otro método que se
    agregue con el mismo cliente inyectado."""

    def __init__(
        self,
        email: str | None = None,
        password: str | None = None,
        post_fn: PostFn | None = None,
        ahora_fn: Callable[[], datetime] | None = None,
    ):
        self._email = email
        self._password = password
        self._post = post_fn or _post_real
        self._ahora = ahora_fn or (lambda: datetime.now(timezone.utc))
        self._cookie: str | None = None
        self._expira: datetime | None = None

    def _credenciales(self) -> tuple[str, str]:
        return (
            self._email or config.requerido("RENT_ECOM_EMAIL"),
            self._password or config.requerido("RENT_ECOM_PASSWORD"),
        )

    def _login(self) -> None:
        email, password = self._credenciales()
        resp = self._post(
            _BASE_URL + _LOGIN_PATH,
            {"User": {"email_address": email, "password": password}},
            None,
        )
        cookie = _cookie_de_headers(resp.headers) if resp.status_code == 200 else None
        if not cookie:
            raise EcomApiError(f"Login de EcomExperts falló (status {resp.status_code}).")
        self._cookie = cookie
        self._expira = _proxima_expiracion(self._ahora())

    def _cookie_vigente(self) -> bool:
        return self._cookie is not None and self._expira is not None and self._ahora() < self._expira

    def graphql(self, query: str, variables: dict | None = None) -> dict:
        """Ejecuta una query/mutation. Reautentica sola si la cookie venció
        por reloj (proactivo) o si el server la rechazó (reactivo, una sola
        vez — evita loop infinito si las credenciales están mal)."""
        if not self._cookie_vigente():
            self._login()
        resp = self._post(_BASE_URL + _GRAPHQL_PATH, {"query": query, "variables": variables or {}}, self._cookie)
        if _parece_error_de_autenticacion(resp):
            self._login()
            resp = self._post(_BASE_URL + _GRAPHQL_PATH, {"query": query, "variables": variables or {}}, self._cookie)
        if not isinstance(resp.body, dict):
            raise EcomApiError(f"Respuesta no-JSON de GraphQL (status {resp.status_code}): {resp.body!r}")
        if resp.body.get("errors"):
            raise EcomApiError(f"GraphQL devolvió errores: {resp.body['errors']}")
        return resp.body.get("data", {})


# ── orders.find — campos confirmados contra la API real (2026-08-10) ──

_QUERY_ORDERS_PAGE = """
query BuscarOrdenes($page: Int, $start: Int!, $end: Int!, $tab: ID) {
  orders {
    find(page: $page, tab: $tab, dateRange: { field: "MtOrder.created", byDate: { start: $start, end: $end } }) {
      pageInfo { page pageCount count }
      data {
        id
        customOrderId
        owner
        paymentStatus
        shipping { listCost cost }
        payments { totalFeeAmount }
        orderLists {
          quantity
          subtotal
          subtotalSinImpuestos
          variant { sku cost product { sku } }
        }
      }
    }
  }
}
"""

_QUERY_FILTROS = """
query { orders { findSettings { filters { id options { id name } } } } }
"""

_QUERY_LIMITE_DIAS = """
query { orders { findSettings { dateRange { customRangeLimit } } } }
"""

# `logistic_type` no es un campo legible por orden (no está en el tipo
# `Shipping` ni en `Order` — confirmado por introspección, 2026-08-13) solo
# existe como filtro de búsqueda. Por eso se arma un set de ids con este
# filtro aparte, en vez de leerlo por orden como el resto de los campos.
_QUERY_IDS_PAGE = """
query BuscarIds($page: Int, $start: Int!, $end: Int!, $tab: ID, $filters: [FindFilterInput]) {
  orders {
    find(page: $page, tab: $tab, filters: $filters, dateRange: { field: "MtOrder.created", byDate: { start: $start, end: $end } }) {
      pageInfo { count }
      data { id }
    }
  }
}
"""

_LOGISTIC_TYPE_FULFILLMENT = "fulfillment"

# `findSettings.tabs.options` real (2026-08-12): active/closed/draft/
# inactive/trash. Para Rentabilidad participan las órdenes activas
# (en curso) y cerradas (ya facturadas) — draft/inactive/trash no son
# ventas reales (decisión de Maxx, 2026-08-12).
TAB_ACTIVE = "active"
TAB_CLOSED = "closed"
_TABS_QUE_PARTICIPAN = (TAB_ACTIVE, TAB_CLOSED)

# Techo a partir del cual `pageInfo.count`/`pageCount` de `orders.find` dejan
# de ser confiables como total real (ver docstring del módulo — confirmado
# contra la API real 2026-08-12). No es un límite de cuántos resultados se
# traen: se usa solo como señal para decidir si partir el rango de fechas
# antes de paginar; cada sub-rango sigue paginando hasta página vacía.
_TECHO_CONTEO_CONFIABLE = 300

# Ecom compara `MtOrder.created` en huso horario Argentina, no UTC —
# confirmado contra la API real (2026-08-12, ver docstring del módulo).
# Argentina no tiene horario de verano desde 2009: UTC-3 todo el año, no
# hace falta una tzdata de zona con reglas de DST.
_ZONA_HORARIA_ARGENTINA = timezone(timedelta(hours=-3))


def _unix(d: date) -> int:
    return int(datetime.combine(d, time.min, tzinfo=_ZONA_HORARIA_ARGENTINA).timestamp())


def _unix_fin_de_dia(d: date) -> int:
    return int(datetime.combine(d, time.max, tzinfo=_ZONA_HORARIA_ARGENTINA).timestamp())


def _limite_dias_de_rango(cliente: EcomApiClient) -> int:
    """`dateRange.customRangeLimit` de `findSettings`, consultado en vivo —
    mismo principio que `_tabla_de_filtro`: nunca se hardcodea un límite de
    la API, aunque ya se lo haya confirmado una vez (100 días, 2026-08-10)."""
    data = cliente.graphql(_QUERY_LIMITE_DIAS)
    return data["orders"]["findSettings"]["dateRange"]["customRangeLimit"]


def _mitad_de_rango(desde: date, hasta: date) -> date:
    return desde + timedelta(days=(hasta - desde).days // 2)


def _buscar_ordenes_de_tab(cliente: EcomApiClient, desde: date, hasta: date, tab: str, limite_dias: int) -> list[dict]:
    """Trae TODAS las órdenes de un `tab` en `[desde, hasta]`, partiendo el
    rango recursivamente cuando: (a) excede el límite duro de días de la
    API, o (b) la página 1 reporta un `count` que puede estar truncado
    (`_TECHO_CONTEO_CONFIABLE` — ver docstring del módulo). Nunca decide
    cuántas páginas pedir por `pageCount`: cada sub-rango que sí se pagina
    lo hace hasta que la API devuelve una página vacía."""
    if (hasta - desde).days + 1 > limite_dias:
        mitad = _mitad_de_rango(desde, hasta)
        return _buscar_ordenes_de_tab(cliente, desde, mitad, tab, limite_dias) + _buscar_ordenes_de_tab(
            cliente, mitad + timedelta(days=1), hasta, tab, limite_dias
        )

    variables = {"start": _unix(desde), "end": _unix_fin_de_dia(hasta), "tab": tab, "page": 1}
    data = cliente.graphql(_QUERY_ORDERS_PAGE, variables)
    resultado = data["orders"]["find"]
    primera_pagina = list(resultado["data"])

    if resultado["pageInfo"]["count"] >= _TECHO_CONTEO_CONFIABLE and desde != hasta:
        mitad = _mitad_de_rango(desde, hasta)
        return _buscar_ordenes_de_tab(cliente, desde, mitad, tab, limite_dias) + _buscar_ordenes_de_tab(
            cliente, mitad + timedelta(days=1), hasta, tab, limite_dias
        )

    ordenes = primera_pagina
    pagina = 2
    while True:
        data = cliente.graphql(_QUERY_ORDERS_PAGE, {**variables, "page": pagina})
        lote = data["orders"]["find"]["data"]
        if not lote:
            break
        ordenes.extend(lote)
        pagina += 1
    return ordenes


def _ids_fulfillment_de_tab(cliente: EcomApiClient, desde: date, hasta: date, tab: str, limite_dias: int) -> set[str]:
    """Ids de órdenes con `logistic_type=fulfillment` (ML Full) en `[desde,
    hasta]` — mismo algoritmo de partición que `_buscar_ordenes_de_tab`
    (límite de días + techo de conteo), pero solo pide `id` (consulta
    liviana) porque acá no hace falta traducir la orden completa, solo
    saber cuáles son Full."""
    filtro = [{"filter": "logistic_type", "values": [_LOGISTIC_TYPE_FULFILLMENT]}]

    if (hasta - desde).days + 1 > limite_dias:
        mitad = _mitad_de_rango(desde, hasta)
        return _ids_fulfillment_de_tab(cliente, desde, mitad, tab, limite_dias) | _ids_fulfillment_de_tab(
            cliente, mitad + timedelta(days=1), hasta, tab, limite_dias
        )

    variables = {"start": _unix(desde), "end": _unix_fin_de_dia(hasta), "tab": tab, "filters": filtro, "page": 1}
    data = cliente.graphql(_QUERY_IDS_PAGE, variables)
    resultado = data["orders"]["find"]
    primera_pagina = list(resultado["data"])

    if resultado["pageInfo"]["count"] >= _TECHO_CONTEO_CONFIABLE and desde != hasta:
        mitad = _mitad_de_rango(desde, hasta)
        return _ids_fulfillment_de_tab(cliente, desde, mitad, tab, limite_dias) | _ids_fulfillment_de_tab(
            cliente, mitad + timedelta(days=1), hasta, tab, limite_dias
        )

    ids = {o["id"] for o in primera_pagina}
    pagina = 2
    while True:
        data = cliente.graphql(_QUERY_IDS_PAGE, {**variables, "page": pagina})
        lote = data["orders"]["find"]["data"]
        if not lote:
            break
        ids.update(o["id"] for o in lote)
        pagina += 1
    return ids


def ids_fulfillment(cliente: EcomApiClient, desde: date, hasta: date, limite_dias: int) -> set[str]:
    """Ids Full de ambos tabs (`active`+`closed`) del período — se consulta
    una sola vez por período en `EcomApiAdapter.periodo()`, no por orden."""
    ids: set[str] = set()
    for tab in _TABS_QUE_PARTICIPAN:
        ids |= _ids_fulfillment_de_tab(cliente, desde, hasta, tab, limite_dias)
    return ids


def buscar_ordenes(cliente: EcomApiClient, desde: date, hasta: date) -> list[dict]:
    """Universo completo de órdenes del período para Rentabilidad: `active`
    + `closed` (`draft`/`inactive`/`trash` no participan), siempre filtrado
    por `MtOrder.created`, sin límite artificial de resultados ni de rango
    de fechas — se parte el período automáticamente cuando hace falta.
    Deduplica por id (una orden no debería aparecer en dos tabs a la vez,
    pero el dedupe es la garantía, no un supuesto)."""
    limite_dias = _limite_dias_de_rango(cliente)
    vistos: set[str] = set()
    ordenes: list[dict] = []
    for tab in _TABS_QUE_PARTICIPAN:
        for orden in _buscar_ordenes_de_tab(cliente, desde, hasta, tab, limite_dias):
            id_orden = orden["id"]
            if id_orden in vistos:
                continue
            vistos.add(id_orden)
            ordenes.append(orden)
    return ordenes


def _tabla_de_filtro(cliente: EcomApiClient, filtro_id: str) -> dict[str, str]:
    """Trae la traducción código→etiqueta de un filtro de `findSettings` en
    vivo — nunca hardcodeada (mandato de Maxx, 2026-08-10: un mapeo de
    canal o de estado no se asume, se consulta)."""
    data = cliente.graphql(_QUERY_FILTROS)
    for f in data["orders"]["findSettings"]["filters"]:
        if f["id"] == filtro_id:
            return {o["id"]: o["name"] for o in f["options"]}
    return {}


def _sku_de_linea(linea: dict) -> str | None:
    variante = linea.get("variant") or {}
    if variante.get("sku"):
        return variante["sku"]
    producto = variante.get("product") or {}
    return producto.get("sku") or None


def _decimal(v) -> Decimal:
    return Decimal(str(v)) if v not in (None, "") else Decimal(0)


def _fila_desde_orden(
    orden: dict, tc: Decimal, canales: dict[str, str], estados_pago: dict[str, str], ids_full: set[str] = frozenset()
) -> FilaEcom:
    """Traduce un `Order` de la API a `FilaEcom` — mismas 3 reglas que
    `ingesta_ecom._fila_desde_row` (Postventa fuerza precios a 0, costo <=0
    es incidencia), sobre datos de otra fuente. No se re-decide la regla,
    solo se re-implementa la traducción de campos.

    `numero_orden` usa `Order.customOrderId`, NO `Order.id` — bug real
    encontrado al cruzar contra un Excel real (2026-08-13, período
    2026-01-01): `id` es la clave interna de la API (única mismo entre
    cuentas, útil para el dedupe de `buscar_ordenes()`, pero de una escala
    de números totalmente distinta — ~71 millones — a la que Ecom muestra
    como "Número Orden" al usuario). `customOrderId` sí coincide
    exactamente con la columna "Número Orden" del Excel real (confirmado:
    `id=71583764` → `customOrderId='1307639'`, primera fila del Excel de
    ese período). Si falta (no debería, según la muestra real), cae a `id`
    antes que dejar el campo vacío.

    `costo_sin_iva` usa `Variant.cost`, NO `Variant.costUsd` — segundo bug
    real encontrado en el mismo cruce (2026-08-13): `costUsd` da valores
    minúsculos (0.001-0.016) que NO coinciden con la columna "Costo Sin
    Iva" del Excel bajo ninguna conversión de TC consistente (la
    proporción variaba orden a orden, entre 1290 y 1910, nunca el TC real
    de 1495). `Variant.cost` sí coincide EXACTO con esa columna en 6 de 9
    órdenes de una muestra real (ej. costo unitario `4.1` × cantidad `2` =
    `8.2`, igual al Excel al centavo). Las 3 que no coincidieron
    exactamente compartían un patrón distinto: el costo actual del
    catálogo (consultado en vivo, 7 meses después) ya no es el mismo que
    regía el 2026-01-01 — `Variant.cost`/`costUsd` son el costo VIGENTE
    HOY, no un valor histórico congelado por orden; no se encontró ningún
    campo de costo a nivel de `OrderList` ni datos útiles en
    `variantCostLogs` para reconstruir el costo histórico (ver hallazgo
    completo reportado a Maxx el 2026-08-13). Para períodos recientes esto
    no debería importar (poca ventana para que el costo cambie); para
    reprocesar períodos viejos, es una limitación real de la API, no de
    este adaptador.

    `costo_envio = Shipping.listCost - Shipping.cost`, salvo Full — tercera
    corrección real (2026-08-13, cruce contra el Excel real del
    2026-08-12): la primera versión (`listCost` si `freeShipping`, si no
    0) fallaba en ambos sentidos contra datos reales (Maxx lo confirmó
    revisando órdenes en vivo: por encima de cierto monto ML da envío
    gratis al comprador y el vendedor lo absorbe, tenga o no marcado
    `freeShipping`). `listCost` es la tarifa de lista; `cost` es lo que
    realmente paga el comprador; la diferencia es lo que absorbe el
    vendedor — confirmado contra 315 órdenes reales (2026-08-12): coincide
    en 296 (94%) sin ningún tratamiento especial. De las 12 que no
    coincidían (todas mostraban Costo Envío=0 en el Excel), las 12 eran
    órdenes `logistic_type=fulfillment` (ML Full) — por eso se agregó la
    excepción de abajo. **Pero no es una regla limpia**: al menos 2 órdenes
    Full más (1409820, 1409866 — ambas `PLANCHA-SUB-AUTO-GORRA`) SÍ tenían
    Costo Envío real igual a `listCost-cost`, no 0 — la excepción de Full
    rompe esos 2 casos. Medido en conjunto sobre las 315 órdenes: CON la
    excepción de Full, 225 coinciden (vs. 215 SIN ella) — es la opción
    neta mejor pero no 100% correcta.

    La excepción es por **SKU/producto, no por orden**: confirmado
    revisando otras órdenes reales del mismo día — toda orden con SKU
    `PLANCHA-SUB-*` (planchas de sublimación, un producto grande/pesado)
    cobra el envío real dentro de Full; SKUs chicos (`CB435A...`,
    `WEEDINGTOOLS...`) dan 0 de forma consistente en Full. Coincide con la
    sospecha de Maxx (2026-08-13): parece un cargo de sobre-volumen/peso
    que ML cobra igual dentro de Full. **No se puede derivar del catálogo
    de Ecom**: `Product.width/height/length/weight` vienen `null` para
    estos SKUs (confirmado por introspección) — Ecom no tiene cargados
    esos datos. Resolver esto bien necesita el dato de peso/dimensión (o
    la clasificación de "envío especial") del lado de Mercado Libre, no de
    Ecom — queda para cuando se conecte la API de ML directamente (fase ya
    planeada por Maxx), no se inventa un umbral de peso/tamaño acá.

    `logistic_type=fulfillment` no es un campo legible por orden (solo
    existe como filtro de búsqueda, confirmado por introspección) — por
    eso se arma el set `ids_fulfillment`
    aparte (`ids_fulfillment()`, una consulta por período, no por orden) y
    se pasa acá."""
    lineas = orden.get("orderLists") or []

    costo = sum(
        (_decimal(l["variant"]["cost"]) * _decimal(l["quantity"]) for l in lineas if l.get("variant")),
        Decimal(0),
    )
    comision = sum((_decimal(p.get("totalFeeAmount")) for p in (orden.get("payments") or [])), Decimal(0))
    shipping = orden.get("shipping") or {}
    if orden["id"] in ids_full:
        costo_envio = Decimal(0)
    else:
        costo_envio = _decimal(shipping.get("listCost")) - _decimal(shipping.get("cost"))

    owner_code = orden.get("owner") or ""
    canal = canales.get(owner_code, owner_code) or None
    es_postventa = owner_code == _OWNER_POSVENTA_API

    if es_postventa:
        precio_sin_iva = Decimal(0)
        precio_final = Decimal(0)
    else:
        precio_sin_iva = sum((_decimal(l.get("subtotalSinImpuestos")) for l in lineas), Decimal(0))
        precio_final = sum((_decimal(l.get("subtotal")) for l in lineas), Decimal(0))

    skus = ", ".join(sku for sku in (_sku_de_linea(l) for l in lineas) if sku)

    return FilaEcom(
        numero_orden=str(orden.get("customOrderId") or orden["id"]),
        skus_vendidos=skus,
        canal_de_venta=canal,
        # Traduce la clave en inglés de la API a la misma etiqueta española
        # que compara `ESTADOS_PAGO_QUE_PARTICIPAN` — sin duplicar la regla.
        estado_pago=estados_pago.get(orden.get("paymentStatus") or "", orden.get("paymentStatus") or "").strip(),
        costo_sin_iva=costo,
        comision_venta=comision,
        costo_envio=costo_envio,
        precio_sin_iva=precio_sin_iva,
        precio_final=precio_final,
        tc=tc,
        incidencia="COSTO_NO_RESUELTO" if costo <= 0 else None,
    )


class EcomApiAdapter:
    """Mismo contrato de salida que `EcomExcelAdapter` (`ResultadoIngestaEcom`
    con `lineas`/`excluidas_por_estado_pago`/`incidencias_costo`) — la capa
    de persistencia (`persistencia.py`) no necesita saber si el origen fue
    la API o el Excel."""

    def __init__(self, cliente: EcomApiClient | None = None):
        self._cliente = cliente or EcomApiClient()

    def periodo(self, desde: date, hasta: date, tc: Decimal) -> ResultadoIngestaEcom:
        canales = _tabla_de_filtro(self._cliente, "owner")
        estados_pago = _tabla_de_filtro(self._cliente, "payment")
        ordenes = buscar_ordenes(self._cliente, desde, hasta)
        limite_dias = _limite_dias_de_rango(self._cliente)
        fulfillment = ids_fulfillment(self._cliente, desde, hasta, limite_dias)

        lineas: list[FilaEcom] = []
        excluidas: list[FilaEcom] = []
        incidencias: list[FilaEcom] = []
        for orden in ordenes:
            fila = _fila_desde_orden(orden, tc, canales, estados_pago, fulfillment)
            if fila.estado_pago not in ESTADOS_PAGO_QUE_PARTICIPAN:
                excluidas.append(fila)
            elif fila.incidencia is not None:
                incidencias.append(fila)
            else:
                lineas.append(fila)

        return ResultadoIngestaEcom(lineas=lineas, excluidas_por_estado_pago=excluidas, incidencias_costo=incidencias)
