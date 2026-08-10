"""Cliente GraphQL de EcomExperts — prueba transporte (login, cache de
cookie con expiración fija a las 00:06 UTC, reautenticación) inyectando
`post_fn`/`ahora_fn`, sin red ni credenciales reales.

La traducción Order (API) -> FilaEcom (`_fila_desde_orden`, `EcomApiAdapter`)
se prueba contra fixtures con la FORMA REAL de la respuesta, capturada
mediante introspección + una muestra de órdenes reales el 2026-08-10 (ver
docstring de ingesta_ecom_api.py) — no inventada."""
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from rentabilidad.config import ConfiguracionFaltante
from rentabilidad.ingesta_ecom_api import (
    EcomApiAdapter,
    EcomApiClient,
    EcomApiError,
    _Respuesta,
    _cookie_de_headers,
    _fila_desde_orden,
    _proxima_expiracion,
    _sku_de_linea,
    _tabla_de_filtro,
    buscar_ordenes,
)

# Traducciones reales, capturadas de orders.findSettings.filters (2026-08-10) —
# no es una tabla inventada, es la respuesta real recortada a lo usado en tests.
_CANALES = {"MlShipping": "Mercadolibre Carrito", "MlOrder": "Mercadolibre", "Posventa": "Posventa"}
_ESTADOS_PAGO = {
    "paid": "Cobrado", "partially_paid": "Cobro Parcial ", "not_paid": "Sin Cobro",
    "in_mediation": "En Mediación", "refunded": "Reembolsado", "cancelled": "Cancelado",
}


def _orden(**overrides) -> dict:
    """Forma real de un `Order` normal (ML, pagado, sin incidencias) —
    recortada de la muestra real del 2026-08-10."""
    base = {
        "id": "78672152",
        "owner": "MlShipping",
        "paymentStatus": "paid",
        "shipping": {"listCost": 7821},
        "payments": [{"totalFeeAmount": 7392.8}, {"totalFeeAmount": 122.94}],
        "orderLists": [{
            "quantity": 1, "subtotal": 20618.4, "subtotalSinImpuestos": 17040,
            "variant": {"sku": "CF217ACOMP", "costUsd": 0.002, "product": {"sku": None}},
        }],
    }
    base.update(overrides)
    return base


def _post_login_ok(cookie="CAKEPHP=abc123"):
    llamadas = []

    def post(url, json_body, cookie_enviada):
        llamadas.append((url, json_body, cookie_enviada))
        if url.endswith("/doLogin.json"):
            return _Respuesta(200, {"set-cookie": f"{cookie}; Path=/, otracosa=1"}, {"success": True})
        return _Respuesta(200, {}, {"data": {"orders": {"find": {"pageInfo": {"page": 1, "pageCount": 1, "count": 0}, "data": []}}}})

    return post, llamadas


# ── _cookie_de_headers — bug real encontrado contra la API real (2026-08-10):
# el separador ", " entre cookies deja un espacio inicial que `requests`
# rechaza como header inválido si no se lo quita en el origen. ──

def test_cookie_de_headers_quita_el_espacio_que_deja_el_separador_entre_cookies():
    # Forma real observada: cookies separadas por ", " (coma + espacio), no
    # solo "," como en el resto de los fixtures de este archivo.
    headers = {"set-cookie": "CAKEPHP=1nbn4nbikjndekgo6sbse353m2; Path=/, otracosa=1; Path=/"}
    assert _cookie_de_headers(headers) == "CAKEPHP=1nbn4nbikjndekgo6sbse353m2"


def test_cookie_de_headers_devuelve_un_valor_valido_como_header_http():
    import requests
    headers = {"set-cookie": "algo=1; Path=/, CAKEPHP=abc123; Path=/"}
    cookie = _cookie_de_headers(headers)
    # No debe lanzar InvalidHeader — es la regresión exacta que se rompió
    # en el primer contacto real con la API.
    req = requests.Request("POST", "https://api.ecomexperts.com/graphql", headers={"Cookie": cookie})
    req.prepare()


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


# ── buscar_ordenes — pagina orders.find, "data" es el wrapper confirmado ──

def test_buscar_ordenes_arma_el_rango_de_fechas():
    post, llamadas = _post_login_ok()
    cliente = EcomApiClient(email="x@x.com", password="s", post_fn=post)
    resultado = buscar_ordenes(cliente, date(2026, 7, 23), date(2026, 8, 22))
    assert resultado == []
    _, body_graphql, _ = llamadas[-1]
    assert body_graphql["variables"]["start"] < body_graphql["variables"]["end"]


def test_buscar_ordenes_pagina_hasta_pagecount():
    paginas_pedidas = []

    def post(url, json_body, cookie):
        if url.endswith("doLogin.json"):
            return _Respuesta(200, {"set-cookie": "CAKEPHP=abc"}, {"success": True})
        pagina = json_body["variables"]["page"]
        paginas_pedidas.append(pagina)
        ordenes = [_orden(id=str(pagina))]
        return _Respuesta(200, {}, {"data": {"orders": {"find": {
            "pageInfo": {"page": pagina, "pageCount": 3, "count": 3}, "data": ordenes,
        }}}})

    cliente = EcomApiClient(email="x@x.com", password="s", post_fn=post)
    ordenes = buscar_ordenes(cliente, date(2026, 7, 1), date(2026, 7, 31))
    assert paginas_pedidas == [1, 2, 3]
    assert [o["id"] for o in ordenes] == ["1", "2", "3"]


# ── _tabla_de_filtro — traducción código->etiqueta en vivo, sin hardcodear ──

def test_tabla_de_filtro_extrae_id_a_nombre():
    def post(url, json_body, cookie):
        if url.endswith("doLogin.json"):
            return _Respuesta(200, {"set-cookie": "CAKEPHP=abc"}, {"success": True})
        return _Respuesta(200, {}, {"data": {"orders": {"findSettings": {"filters": [
            {"id": "owner", "options": [{"id": "MlShipping", "name": "Mercadolibre Carrito"}]},
            {"id": "payment", "options": [{"id": "paid", "name": "Cobrado"}]},
        ]}}}})

    cliente = EcomApiClient(email="x@x.com", password="s", post_fn=post)
    assert _tabla_de_filtro(cliente, "owner") == {"MlShipping": "Mercadolibre Carrito"}
    assert _tabla_de_filtro(cliente, "payment") == {"paid": "Cobrado"}
    assert _tabla_de_filtro(cliente, "no_existe") == {}


# ── _sku_de_linea — variant.sku, con fallback a variant.product.sku ──

def test_sku_de_linea_usa_el_sku_de_la_variante_si_esta():
    assert _sku_de_linea({"variant": {"sku": "ABC123", "product": {"sku": "MADRE"}}}) == "ABC123"


def test_sku_de_linea_cae_al_producto_padre_si_la_variante_no_tiene_sku():
    # Caso real observado: variant.sku=null, variant.product.sku poblado.
    assert _sku_de_linea({"variant": {"sku": None, "product": {"sku": "CIZALLA-A4-12EN1"}}}) == "CIZALLA-A4-12EN1"


def test_sku_de_linea_sin_variante_devuelve_none():
    assert _sku_de_linea({"variant": None}) is None


# ── _fila_desde_orden — traducción completa, mismas reglas que el Excel ──

def test_fila_desde_orden_normal_reproduce_los_campos_esperados():
    fila = _fila_desde_orden(_orden(), Decimal(1500), _CANALES, _ESTADOS_PAGO)
    assert fila.numero_orden == "78672152"
    assert fila.canal_de_venta == "Mercadolibre Carrito"
    assert fila.estado_pago == "Cobrado"
    assert fila.skus_vendidos == "CF217ACOMP"
    assert fila.costo_envio == Decimal("7821")
    assert fila.comision_venta == Decimal(str(7392.8 + 122.94))
    assert fila.precio_final == Decimal("20618.4")
    assert fila.precio_sin_iva == Decimal("17040")
    assert fila.costo_sin_iva == Decimal("0.002") * Decimal("1")
    assert fila.incidencia is None


def test_fila_desde_orden_traduce_estado_de_pago_y_le_quita_el_espacio():
    # 'partially_paid' -> 'Cobro Parcial ' (espacio real de la API) -> strip()
    fila = _fila_desde_orden(_orden(paymentStatus="partially_paid"), Decimal(1500), _CANALES, _ESTADOS_PAGO)
    assert fila.estado_pago == "Cobro Parcial"


def test_fila_desde_orden_postventa_fuerza_precios_a_cero_conserva_costo():
    fila = _fila_desde_orden(_orden(owner="Posventa"), Decimal(1500), _CANALES, _ESTADOS_PAGO)
    assert fila.precio_final == Decimal(0)
    assert fila.precio_sin_iva == Decimal(0)
    assert fila.costo_sin_iva > 0  # se conserva la pérdida del costo


def test_fila_desde_orden_costo_cero_es_incidencia():
    orden = _orden(orderLists=[{
        "quantity": 1, "subtotal": 100, "subtotalSinImpuestos": 90,
        "variant": {"sku": "X", "costUsd": 0, "product": {"sku": None}},
    }])
    fila = _fila_desde_orden(orden, Decimal(1500), _CANALES, _ESTADOS_PAGO)
    assert fila.incidencia == "COSTO_NO_RESUELTO"


def test_fila_desde_orden_sin_variante_en_ninguna_linea_es_incidencia():
    orden = _orden(orderLists=[{"quantity": 1, "subtotal": 100, "subtotalSinImpuestos": 90, "variant": None}])
    fila = _fila_desde_orden(orden, Decimal(1500), _CANALES, _ESTADOS_PAGO)
    assert fila.incidencia == "COSTO_NO_RESUELTO"
    assert fila.costo_sin_iva == Decimal(0)


def test_fila_desde_orden_canal_desconocido_usa_el_codigo_crudo():
    fila = _fila_desde_orden(_orden(owner="AlgoNuevo"), Decimal(1500), _CANALES, _ESTADOS_PAGO)
    assert fila.canal_de_venta == "AlgoNuevo"


# ── EcomApiAdapter.periodo — mismo contrato de salida que EcomExcelAdapter ──

def _post_adapter(ordenes, canales=None, estados_pago=None):
    def post(url, json_body, cookie):
        if url.endswith("doLogin.json"):
            return _Respuesta(200, {"set-cookie": "CAKEPHP=abc"}, {"success": True})
        query = json_body["query"]
        if "findSettings" in query:
            filtros = [
                {"id": "owner", "options": [{"id": k, "name": v} for k, v in (canales or _CANALES).items()]},
                {"id": "payment", "options": [{"id": k, "name": v} for k, v in (estados_pago or _ESTADOS_PAGO).items()]},
            ]
            return _Respuesta(200, {}, {"data": {"orders": {"findSettings": {"filters": filtros}}}})
        return _Respuesta(200, {}, {"data": {"orders": {"find": {
            "pageInfo": {"page": 1, "pageCount": 1, "count": len(ordenes)}, "data": ordenes,
        }}}})

    return post


def test_adapter_periodo_separa_lineas_excluidas_e_incidencias():
    ordenes = [
        _orden(id="1"),  # normal, paid
        _orden(id="2", paymentStatus="refunded"),  # excluida por estado
        _orden(id="3", orderLists=[{  # incidencia de costo
            "quantity": 1, "subtotal": 100, "subtotalSinImpuestos": 90,
            "variant": {"sku": "X", "costUsd": 0, "product": {"sku": None}},
        }]),
    ]
    adaptador = EcomApiAdapter(EcomApiClient(email="x@x.com", password="s", post_fn=_post_adapter(ordenes)))
    resultado = adaptador.periodo(date(2026, 7, 1), date(2026, 7, 31), Decimal(1500))

    assert [f.numero_orden for f in resultado.lineas] == ["1"]
    assert [f.numero_orden for f in resultado.excluidas_por_estado_pago] == ["2"]
    assert [f.numero_orden for f in resultado.incidencias_costo] == ["3"]


def test_adapter_periodo_devuelve_resultadoingestaecom_compatible_con_persistencia():
    from rentabilidad.ingesta_ecom import ResultadoIngestaEcom
    adaptador = EcomApiAdapter(EcomApiClient(email="x@x.com", password="s", post_fn=_post_adapter([_orden()])))
    resultado = adaptador.periodo(date(2026, 7, 1), date(2026, 7, 31), Decimal(1500))
    assert isinstance(resultado, ResultadoIngestaEcom)
