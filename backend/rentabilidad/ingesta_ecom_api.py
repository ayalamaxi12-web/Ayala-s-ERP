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
- Antes de filtrar un recurso hay que consultar su `findSettings` (no
  implementado acá todavía — no hay filtro que resolver mientras
  `buscar_ordenes()` no arma más que un `dateRange`).

Reutiliza el mismo host/endpoint de login que `ecom_login()` en
`backend/main.py`, pero es un cliente independiente: `main.py` recibe el
email/password del pedido HTTP (la sesión interactiva del operador, guardada
en `localStorage` del frontend); este cliente es para un job de servidor sin
usuario delante, así que las credenciales solo pueden venir de variable de
entorno (`RENT_ECOM_EMAIL` / `RENT_ECOM_PASSWORD`) — nunca hardcodeadas
(pedido explícito de Maxx).

GAP DOCUMENTAL — no inventado, pendiente de confirmar (ver reporte a Maxx):
la forma exacta de la respuesta de `orders.find(...)` (¿la lista de
resultados viene en `items`, `data`, `rows`...? no está en el relevamiento)
y varios campos a nivel de línea (comisión de venta, costo de envío exacto,
marca de canal Postventa, valores reales del enum de `paymentStatus`). Por
eso `buscar_ordenes()` devuelve el `dict` crudo de `data.orders.find` sin
intentar mapearlo a `LineaEcomInput` — esa traducción (equivalente a
`_fila_desde_row` en `ingesta_ecom.py`) queda para cuando esos campos estén
confirmados, no se inventa acá.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable

from . import config

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
    `CAKEPHP=` que no sea de borrado."""
    set_cookie = headers.get("set-cookie") or headers.get("Set-Cookie") or ""
    partes = [c.split(";")[0] for c in set_cookie.split(",") if "CAKEPHP=" in c and "deleted" not in c]
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


# ── orders.find — solo los campos que Maxx confirmó (2026-08-10) ──
#
# GAP: no se agregan comisión de línea, costo de envío, ni marca de canal
# Postventa porque no están confirmados (ver docstring del módulo). El
# nombre del campo que envuelve los resultados dentro de `find()` (¿items?
# ¿data? ¿rows?) TAMPOCO está confirmado — por eso esta query no se
# ejecuta todavía desde ningún llamador real; queda lista para correr en
# cuanto Maxx (o una introspección en vivo con credenciales reales)
# confirme esa forma.
_QUERY_ORDERS_FIND = """
query BuscarOrdenes($start: Int!, $end: Int!) {
  orders {
    find(dateRange: { field: "MtOrder.created", byDate: { start: $start, end: $end } }) {
      pageInfo { current count page nextPage prevPage pageCount limit }
    }
  }
}
"""


def _unix(d: date) -> int:
    return int(datetime.combine(d, time.min, tzinfo=timezone.utc).timestamp())


def buscar_ordenes(cliente: EcomApiClient, desde: date, hasta: date) -> dict:
    """Devuelve `data["orders"]["find"]` crudo — sin traducir a
    `LineaEcomInput` todavía (ver GAP en el docstring del módulo)."""
    data = cliente.graphql(_QUERY_ORDERS_FIND, {"start": _unix(desde), "end": _unix(hasta)})
    return data.get("orders", {}).get("find", {})
