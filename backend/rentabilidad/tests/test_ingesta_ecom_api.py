"""Cliente GraphQL de EcomExperts — prueba transporte (login, cache de
cookie con expiración fija a las 00:06 UTC, reautenticación) inyectando
`post_fn`/`ahora_fn`, sin red ni credenciales reales. La traducción a
`LineaEcomInput` no se testea acá porque todavía no existe (ver GAP en
ingesta_ecom_api.py) — `buscar_ordenes()` solo se prueba hasta donde llega:
arma la query y devuelve el dict crudo."""
from datetime import date, datetime, timezone

import pytest

from rentabilidad.config import ConfiguracionFaltante
from rentabilidad.ingesta_ecom_api import (
    EcomApiClient,
    EcomApiError,
    _Respuesta,
    _proxima_expiracion,
    buscar_ordenes,
)


def _post_login_ok(cookie="CAKEPHP=abc123"):
    llamadas = []

    def post(url, json_body, cookie_enviada):
        llamadas.append((url, json_body, cookie_enviada))
        if url.endswith("/doLogin.json"):
            return _Respuesta(200, {"set-cookie": f"{cookie}; Path=/, otracosa=1"}, {"success": True})
        return _Respuesta(200, {}, {"data": {"orders": {"find": {"pageInfo": {"count": 0}}}}})

    return post, llamadas


# ── _proxima_expiracion — la regla de negocio confirmada por Maxx ──

def test_expiracion_mismo_dia_si_login_es_antes_de_las_0006_utc():
    login = datetime(2026, 8, 10, 0, 3, tzinfo=timezone.utc)
    assert _proxima_expiracion(login) == datetime(2026, 8, 10, 0, 6, tzinfo=timezone.utc)


def test_expiracion_dia_siguiente_si_login_es_despues_de_las_0006_utc():
    login = datetime(2026, 8, 10, 14, 0, tzinfo=timezone.utc)
    assert _proxima_expiracion(login) == datetime(2026, 8, 11, 0, 6, tzinfo=timezone.utc)


# ── EcomApiClient.graphql — login perezoso, cache, reautenticación ──

def test_no_hace_login_hasta_la_primera_llamada_a_graphql():
    post, llamadas = _post_login_ok()
    cliente = EcomApiClient(email="x@x.com", password="secreto", post_fn=post)
    assert llamadas == []
    cliente.graphql("query { x }")
    assert [l[0] for l in llamadas] == [
        "https://api.ecomexperts.com/users/users/doLogin.json",
        "https://api.ecomexperts.com/graphql",
    ]


def test_reutiliza_la_cookie_mientras_no_venza():
    post, llamadas = _post_login_ok()
    ahora = {"t": datetime(2026, 8, 10, 10, 0, tzinfo=timezone.utc)}
    cliente = EcomApiClient(email="x@x.com", password="s", post_fn=post, ahora_fn=lambda: ahora["t"])
    cliente.graphql("query { x }")
    cliente.graphql("query { x }")
    logins = [l for l in llamadas if l[0].endswith("doLogin.json")]
    assert len(logins) == 1  # un solo login para las dos llamadas


def test_reautentica_sola_cuando_la_cookie_vencio_por_reloj():
    post, llamadas = _post_login_ok()
    ahora = {"t": datetime(2026, 8, 10, 0, 3, tzinfo=timezone.utc)}
    cliente = EcomApiClient(email="x@x.com", password="s", post_fn=post, ahora_fn=lambda: ahora["t"])
    cliente.graphql("query { x }")
    ahora["t"] = datetime(2026, 8, 10, 5, 0, tzinfo=timezone.utc)  # ya pasaron las 00:06 UTC
    cliente.graphql("query { x }")
    logins = [l for l in llamadas if l[0].endswith("doLogin.json")]
    assert len(logins) == 2


def test_reautentica_una_vez_si_el_server_rechaza_la_cookie_vigente():
    intentos_graphql = {"n": 0}

    def post(url, json_body, cookie):
        if url.endswith("doLogin.json"):
            return _Respuesta(200, {"set-cookie": "CAKEPHP=nueva"}, {"success": True})
        intentos_graphql["n"] += 1
        if intentos_graphql["n"] == 1:
            return _Respuesta(200, {}, {"errors": [{"message": "Invalid session, please login"}]})
        return _Respuesta(200, {}, {"data": {"ok": True}})

    cliente = EcomApiClient(email="x@x.com", password="s", post_fn=post)
    resultado = cliente.graphql("query { x }")
    assert resultado == {"ok": True}
    assert intentos_graphql["n"] == 2


def test_falla_claro_si_el_login_no_devuelve_cookie():
    def post(url, json_body, cookie):
        return _Respuesta(401, {}, {"success": False})

    cliente = EcomApiClient(email="x@x.com", password="s", post_fn=post)
    with pytest.raises(EcomApiError):
        cliente.graphql("query { x }")


def test_falla_con_error_claro_si_graphql_devuelve_errores_no_de_auth():
    def post(url, json_body, cookie):
        if url.endswith("doLogin.json"):
            return _Respuesta(200, {"set-cookie": "CAKEPHP=abc"}, {"success": True})
        return _Respuesta(200, {}, {"errors": [{"message": "Field 'x' doesn't exist"}]})

    cliente = EcomApiClient(email="x@x.com", password="s", post_fn=post)
    with pytest.raises(EcomApiError):
        cliente.graphql("query { x }")


def test_sin_credenciales_ni_variable_de_entorno_levanta_configuracion_faltante(monkeypatch):
    monkeypatch.delenv("RENT_ECOM_EMAIL", raising=False)
    monkeypatch.delenv("RENT_ECOM_PASSWORD", raising=False)
    cliente = EcomApiClient(post_fn=lambda *a: (_ for _ in ()).throw(AssertionError("no debería llamar a la red")))
    with pytest.raises(ConfiguracionFaltante):
        cliente.graphql("query { x }")


# ── buscar_ordenes — arma la query con dateRange, todavía sin traducir ──

def test_buscar_ordenes_devuelve_el_find_crudo():
    post, llamadas = _post_login_ok()
    cliente = EcomApiClient(email="x@x.com", password="s", post_fn=post)
    resultado = buscar_ordenes(cliente, date(2026, 7, 23), date(2026, 8, 22))
    assert resultado == {"pageInfo": {"count": 0}}
    _, body_graphql, _ = llamadas[-1]
    assert body_graphql["variables"]["start"] < body_graphql["variables"]["end"]
