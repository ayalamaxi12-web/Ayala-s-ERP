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
  (`customRangeLimit`, tal como ya sabía Maxx).
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
- **Canal de venta**: `Order.owner` es el código crudo (`"MlShipping"`,
  `"MlOrder"`, `"ChChannelOrder"`, `"Venta Interna"`, nombres de empleado
  para ventas manuales...). El filtro `orders.findSettings.filters`
  (id=`"owner"`, nombre visible "Canal") da la etiqueta real — `MlShipping`
  → `"Mercadolibre Carrito"` — que es la que aparece en el Excel. Se
  resuelve **en vivo contra `findSettings`**, no hardcodeada (mandato de
  Maxx: nunca asumir un mapeo de canal).
- **Costo de envío**: `Shipping.cost` casi siempre viene en `0` en la
  muestra real — el valor que coincide con "Costo Envío" del Excel es
  `Shipping.listCost` (confirmado por coincidencia exacta de un valor real,
  7821, contra el fixture de `ingesta_ecom.py`/`test_ingesta_ecom.py`).
- **Comisión de venta**: no hay un campo único — se resuelve como
  `sum(payments[].totalFeeAmount)`. Confirmado que el campo existe y tiene
  magnitud consistente con una comisión (varios miles sobre ventas de
  decenas de miles); **no confirmado 1:1 contra un valor real del Excel**
  de Maxx — queda para la comparación de período real (pedido de Maxx,
  §6 de su instrucción del 2026-08-10).
- **Postventa/RMA**: `orders.findSettings` (filtro `owner`) lista
  `"Posventa"` (sin "t") como canal válido — pero el adaptador de Excel
  (`ingesta_ecom.py`) usa `"Postventa"` (con "t"), verificado por Maxx
  contra archivos reales. **No se pudo observar una orden real con
  `owner="Posventa"` en 300 órdenes de los últimos 3 meses** para confirmar
  que son el mismo concepto. Se implementa contra el valor real de la API
  (`"Posventa"`) y se lo señala a Maxx explícitamente — no se inventa cuál
  de los dos "gana".
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


def _post_real(url: str, json_body: dict, cookie: str | None) -> _Respuesta:
    """Import perezoso de requests — mismo principio que `gsheets.get_client()`
    y `ingesta_tactica._ejecutar_query_real()`: el resto del módulo no
    depende de red para testearse."""
    import requests

    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    resp = requests.post(url, json=json_body, headers=headers, timeout=30)
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
query BuscarOrdenes($page: Int, $start: Int!, $end: Int!) {
  orders {
    find(page: $page, dateRange: { field: "MtOrder.created", byDate: { start: $start, end: $end } }) {
      pageInfo { page pageCount count }
      data {
        id
        owner
        paymentStatus
        shipping { listCost }
        payments { totalFeeAmount }
        orderLists {
          quantity
          subtotal
          subtotalSinImpuestos
          variant { sku costUsd product { sku } }
        }
      }
    }
  }
}
"""

_QUERY_FILTROS = """
query { orders { findSettings { filters { id options { id name } } } } }
"""


def _unix(d: date) -> int:
    return int(datetime.combine(d, time.min, tzinfo=timezone.utc).timestamp())


def _unix_fin_de_dia(d: date) -> int:
    return int(datetime.combine(d, time.max, tzinfo=timezone.utc).timestamp())


def buscar_ordenes(cliente: EcomApiClient, desde: date, hasta: date) -> list[dict]:
    """Pagina `orders.find` completo para el rango — `data` es el campo
    confirmado que envuelve los resultados (no `items`/`rows`). El límite
    real de la API es 100 días por consulta (`customRangeLimit`); no se
    valida acá el rango porque `EcomApiAdapter.periodo()` es quien decide
    cómo partir un rango más largo si hiciera falta."""
    variables = {"start": _unix(desde), "end": _unix_fin_de_dia(hasta), "page": 1}
    data = cliente.graphql(_QUERY_ORDERS_PAGE, variables)
    resultado = data["orders"]["find"]
    ordenes = list(resultado["data"])
    page_count = resultado["pageInfo"]["pageCount"]
    for pagina in range(2, page_count + 1):
        data = cliente.graphql(_QUERY_ORDERS_PAGE, {**variables, "page": pagina})
        ordenes.extend(data["orders"]["find"]["data"])
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


def _fila_desde_orden(orden: dict, tc: Decimal, canales: dict[str, str], estados_pago: dict[str, str]) -> FilaEcom:
    """Traduce un `Order` de la API a `FilaEcom` — mismas 3 reglas que
    `ingesta_ecom._fila_desde_row` (Postventa fuerza precios a 0, costo <=0
    es incidencia), sobre datos de otra fuente. No se re-decide la regla,
    solo se re-implementa la traducción de campos."""
    lineas = orden.get("orderLists") or []

    costo = sum(
        (_decimal(l["variant"]["costUsd"]) * _decimal(l["quantity"]) for l in lineas if l.get("variant")),
        Decimal(0),
    )
    comision = sum((_decimal(p.get("totalFeeAmount")) for p in (orden.get("payments") or [])), Decimal(0))
    costo_envio = _decimal((orden.get("shipping") or {}).get("listCost"))

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
        numero_orden=str(orden["id"]),
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

        lineas: list[FilaEcom] = []
        excluidas: list[FilaEcom] = []
        incidencias: list[FilaEcom] = []
        for orden in ordenes:
            fila = _fila_desde_orden(orden, tc, canales, estados_pago)
            if fila.estado_pago not in ESTADOS_PAGO_QUE_PARTICIPAN:
                excluidas.append(fila)
            elif fila.incidencia is not None:
                incidencias.append(fila)
            else:
                lineas.append(fila)

        return ResultadoIngestaEcom(lineas=lineas, excluidas_por_estado_pago=excluidas, incidencias_costo=incidencias)
