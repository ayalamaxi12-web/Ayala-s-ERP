"""Cliente GraphQL de EcomExperts — prueba transporte (login, cache de
cookie con expiración fija a las 00:06 UTC, reautenticación) inyectando
`post_fn`/`ahora_fn`, sin red ni credenciales reales.

La traducción Order (API) -> FilaEcom (`_fila_desde_orden`, `EcomApiAdapter`)
se prueba contra fixtures con la FORMA REAL de la respuesta, capturada
mediante introspección + una muestra de órdenes reales el 2026-08-10 (ver
docstring de ingesta_ecom_api.py) — no inventada."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from rentabilidad.config import ConfiguracionFaltante
from rentabilidad.ingesta_ecom_api import (
    TAB_ACTIVE,
    TAB_CLOSED,
    EcomApiAdapter,
    EcomApiClient,
    EcomApiError,
    _Respuesta,
    _buscar_ordenes_de_tab,
    _cookie_de_headers,
    _fila_desde_orden,
    _limite_dias_de_rango,
    _proxima_expiracion,
    _sku_de_linea,
    _tabla_de_filtro,
    _unix,
    _unix_fin_de_dia,
    buscar_ordenes,
    ids_fulfillment,
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
        "customOrderId": "1234567",
        "owner": "MlShipping",
        "paymentStatus": "paid",
        "shipping": {"listCost": 7821, "cost": 0},
        "payments": [{"totalFeeAmount": 7392.8}, {"totalFeeAmount": 122.94}],
        "orderLists": [{
            "quantity": 1, "subtotal": 20618.4, "subtotalSinImpuestos": 17040,
            "variant": {"sku": "CF217ACOMP", "cost": 0.002, "product": {"sku": None}},
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
        if "customRangeLimit" in json_body["query"]:
            return _Respuesta(200, {}, {"data": {"orders": {"findSettings": {"dateRange": {"customRangeLimit": 100}}}}})
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


# ── _unix/_unix_fin_de_dia — límites en huso ART, no UTC ──
# Bug real confirmado contra la API (2026-08-12): calcular los límites en
# UTC hacía que pedir "un solo día" trajera ESE día + el día anterior
# completo (nunca el siguiente) — porque Ecom compara `MtOrder.created` en
# huso Argentina (UTC-3): la medianoche UTC de un día son las 21:00 ART del
# día anterior. Confirmado con 3 consultas de un solo día contra la API real
# sin ninguna recursión de por medio (ver docstring del módulo).

def test_unix_calcula_medianoche_en_huso_argentino_no_utc():
    ART = timezone(timedelta(hours=-3))
    dia = date(2026, 7, 23)
    assert _unix(dia) == int(datetime(2026, 7, 23, 0, 0, 0, tzinfo=ART).timestamp())
    # Si se calculara en UTC (bug real, 2026-08-12), este valor sería 3
    # horas menor -- exactamente lo que hacía que Ecom lo bucketeara como
    # el día anterior.
    assert _unix(dia) != int(datetime(2026, 7, 23, 0, 0, 0, tzinfo=timezone.utc).timestamp())


def test_unix_fin_de_dia_calcula_el_cierre_del_dia_en_huso_argentino():
    ART = timezone(timedelta(hours=-3))
    dia = date(2026, 7, 23)
    assert _unix_fin_de_dia(dia) == int(datetime(2026, 7, 23, 23, 59, 59, tzinfo=ART).timestamp())


# ── buscar_ordenes — pagina orders.find, "data" es el wrapper confirmado ──

def test_buscar_ordenes_arma_el_rango_de_fechas():
    post, llamadas = _post_login_ok()
    cliente = EcomApiClient(email="x@x.com", password="s", post_fn=post)
    resultado = buscar_ordenes(cliente, date(2026, 7, 23), date(2026, 8, 22))
    assert resultado == []
    llamadas_find = [l for l in llamadas if "byDate" in l[1].get("query", "")]
    for _, body_graphql, _ in llamadas_find:
        assert body_graphql["variables"]["start"] < body_graphql["variables"]["end"]


def test_buscar_ordenes_de_tab_filtra_siempre_por_fecha_de_creacion():
    def post(url, json_body, cookie):
        if url.endswith("doLogin.json"):
            return _Respuesta(200, {"set-cookie": "CAKEPHP=abc"}, {"success": True})
        assert 'field: "MtOrder.created"' in json_body["query"]
        return _Respuesta(200, {}, {"data": {"orders": {"find": {
            "pageInfo": {"page": 1, "pageCount": 1, "count": 0}, "data": [],
        }}}})

    cliente = EcomApiClient(email="x@x.com", password="s", post_fn=post)
    _buscar_ordenes_de_tab(cliente, date(2026, 7, 1), date(2026, 7, 31), TAB_ACTIVE, limite_dias=100)


def test_buscar_ordenes_de_tab_pagina_hasta_pagina_vacia_sin_confiar_en_pagecount():
    # pageCount "engañoso": siempre dice que hay una página más de las que
    # en realidad quedan -- si el código confiara en pageCount, seguiría
    # pidiendo para siempre. El corte real es la página vacía (comportamiento
    # confirmado contra la API real, 2026-08-12 — ver docstring del módulo).
    paginas_pedidas = []

    def post(url, json_body, cookie):
        if url.endswith("doLogin.json"):
            return _Respuesta(200, {"set-cookie": "CAKEPHP=abc"}, {"success": True})
        pagina = json_body["variables"]["page"]
        paginas_pedidas.append(pagina)
        datos = [_orden(id=str(pagina))] if pagina <= 2 else []
        return _Respuesta(200, {}, {"data": {"orders": {"find": {
            "pageInfo": {"page": pagina, "pageCount": pagina + 1, "count": 30 * (pagina + 1)}, "data": datos,
        }}}})

    cliente = EcomApiClient(email="x@x.com", password="s", post_fn=post)
    ordenes = _buscar_ordenes_de_tab(cliente, date(2026, 7, 1), date(2026, 7, 31), TAB_ACTIVE, limite_dias=100)
    assert paginas_pedidas == [1, 2, 3]
    assert [o["id"] for o in ordenes] == ["1", "2"]


def test_buscar_ordenes_de_tab_parte_el_rango_si_la_pagina_1_reporta_el_techo():
    # Comportamiento real confirmado 2026-08-12: cuando el conteo real supera
    # el techo, la página 1 de CUALQUIER rango con más de un día reporta
    # count=300 (el valor "truncado"); un rango de 1 día exacto ya da el
    # total real, siempre por debajo del techo en este escenario de prueba.
    def post(url, json_body, cookie):
        if url.endswith("doLogin.json"):
            return _Respuesta(200, {"set-cookie": "CAKEPHP=abc"}, {"success": True})
        v = json_body["variables"]
        dias = round((v["end"] - v["start"]) / 86400)
        if dias >= 2 and v["page"] == 1:
            return _Respuesta(200, {}, {"data": {"orders": {"find": {
                "pageInfo": {"page": 1, "pageCount": 10, "count": 300}, "data": [_orden(id="nunca_deberia_sobrevivir")],
            }}}})
        datos = [_orden(id=f"{v['start']}-{v['page']}")] if v["page"] == 1 else []
        return _Respuesta(200, {}, {"data": {"orders": {"find": {
            "pageInfo": {"page": v["page"], "pageCount": 1, "count": 1}, "data": datos,
        }}}})

    cliente = EcomApiClient(email="x@x.com", password="s", post_fn=post)
    ordenes = _buscar_ordenes_de_tab(cliente, date(2026, 7, 1), date(2026, 7, 4), TAB_CLOSED, limite_dias=100)
    # se partió hasta rangos de 1 día -- la "página 1 truncada" de cualquier
    # rango más ancho nunca llega a formar parte del resultado final.
    assert "nunca_deberia_sobrevivir" not in [o["id"] for o in ordenes]
    assert len(ordenes) == 4  # 4 días -> 4 rangos de 1 día -> 1 orden real cada uno


def test_buscar_ordenes_de_tab_parte_el_rango_si_excede_el_limite_de_dias():
    rangos = []

    def post(url, json_body, cookie):
        if url.endswith("doLogin.json"):
            return _Respuesta(200, {"set-cookie": "CAKEPHP=abc"}, {"success": True})
        v = json_body["variables"]
        rangos.append((v["start"], v["end"]))
        datos = [_orden(id=str(len(rangos)))] if v["page"] == 1 else []
        return _Respuesta(200, {}, {"data": {"orders": {"find": {
            "pageInfo": {"page": v["page"], "pageCount": 1, "count": 1}, "data": datos,
        }}}})

    cliente = EcomApiClient(email="x@x.com", password="s", post_fn=post)
    ordenes = _buscar_ordenes_de_tab(cliente, date(2026, 1, 1), date(2026, 4, 1), TAB_ACTIVE, limite_dias=30)
    # 90 días con límite de 30 -> tuvo que partirse en más de un sub-rango,
    # ninguno de más de 30 días (el límite real de la API, §docstring).
    assert len(rangos) > 1
    for start, end in rangos:
        dias = (end - start) // 86400 + 1
        assert dias <= 30


def test_limite_dias_de_rango_lee_customrangelimit_de_findsettings():
    def post(url, json_body, cookie):
        if url.endswith("doLogin.json"):
            return _Respuesta(200, {"set-cookie": "CAKEPHP=abc"}, {"success": True})
        return _Respuesta(200, {}, {"data": {"orders": {"findSettings": {"dateRange": {"customRangeLimit": 100}}}}})

    cliente = EcomApiClient(email="x@x.com", password="s", post_fn=post)
    assert _limite_dias_de_rango(cliente) == 100


def test_buscar_ordenes_combina_active_y_closed_sin_pedir_draft_inactive_trash():
    tabs_pedidos = []

    def post(url, json_body, cookie):
        if url.endswith("doLogin.json"):
            return _Respuesta(200, {"set-cookie": "CAKEPHP=abc"}, {"success": True})
        query = json_body["query"]
        if "customRangeLimit" in query:
            return _Respuesta(200, {}, {"data": {"orders": {"findSettings": {"dateRange": {"customRangeLimit": 100}}}}})
        v = json_body["variables"]
        tabs_pedidos.append(v["tab"])
        datos = [_orden(id=f"{v['tab']}-1")] if v["page"] == 1 else []
        return _Respuesta(200, {}, {"data": {"orders": {"find": {
            "pageInfo": {"page": v["page"], "pageCount": 1, "count": 1}, "data": datos,
        }}}})

    cliente = EcomApiClient(email="x@x.com", password="s", post_fn=post)
    ordenes = buscar_ordenes(cliente, date(2026, 7, 1), date(2026, 7, 31))
    # nunca se pide draft/inactive/trash -- solo los dos tabs que representan
    # ventas reales (decisión de Maxx, 2026-08-12).
    assert set(tabs_pedidos) == {TAB_ACTIVE, TAB_CLOSED}
    assert sorted(o["id"] for o in ordenes) == ["active-1", "closed-1"]


def test_buscar_ordenes_deduplica_por_id_si_aparece_en_mas_de_un_tab():
    def post(url, json_body, cookie):
        if url.endswith("doLogin.json"):
            return _Respuesta(200, {"set-cookie": "CAKEPHP=abc"}, {"success": True})
        query = json_body["query"]
        if "customRangeLimit" in query:
            return _Respuesta(200, {}, {"data": {"orders": {"findSettings": {"dateRange": {"customRangeLimit": 100}}}}})
        v = json_body["variables"]
        datos = [_orden(id="99")] if v["page"] == 1 else []
        return _Respuesta(200, {}, {"data": {"orders": {"find": {
            "pageInfo": {"page": v["page"], "pageCount": 1, "count": 1}, "data": datos,
        }}}})

    cliente = EcomApiClient(email="x@x.com", password="s", post_fn=post)
    ordenes = buscar_ordenes(cliente, date(2026, 7, 1), date(2026, 7, 31))
    assert [o["id"] for o in ordenes] == ["99"]  # una sola vez, no dos aunque haya salido de ambos tabs


# ── ids_fulfillment — logistic_type=fulfillment no es un campo legible por
# orden, solo un filtro de búsqueda (confirmado por introspección,
# 2026-08-13) — se arma un set aparte para poder forzar Costo Envío=0. ──

def test_ids_fulfillment_filtra_por_logistic_type_y_combina_ambos_tabs():
    filtros_pedidos = []

    def post(url, json_body, cookie):
        if url.endswith("doLogin.json"):
            return _Respuesta(200, {"set-cookie": "CAKEPHP=abc"}, {"success": True})
        query = json_body["query"]
        if "customRangeLimit" in query:
            return _Respuesta(200, {}, {"data": {"orders": {"findSettings": {"dateRange": {"customRangeLimit": 100}}}}})
        v = json_body["variables"]
        filtros_pedidos.append((v["tab"], v["filters"]))
        datos = [{"id": f"{v['tab']}-1"}] if v["page"] == 1 else []
        return _Respuesta(200, {}, {"data": {"orders": {"find": {
            "pageInfo": {"page": v["page"], "pageCount": 1, "count": 1}, "data": datos,
        }}}})

    cliente = EcomApiClient(email="x@x.com", password="s", post_fn=post)
    limite_dias = _limite_dias_de_rango(cliente)
    ids = ids_fulfillment(cliente, date(2026, 7, 1), date(2026, 7, 31), limite_dias)

    assert ids == {"active-1", "closed-1"}
    for tab, filtros in filtros_pedidos:
        assert filtros == [{"filter": "logistic_type", "values": ["fulfillment"]}]
    assert {f[0] for f in filtros_pedidos} == {TAB_ACTIVE, TAB_CLOSED}


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
    # numero_orden viene de customOrderId, NO de id (bug real 2026-08-13 —
    # ver docstring del módulo: id=71583764 no es lo que Ecom/Excel llaman
    # "Número Orden", customOrderId sí).
    assert fila.numero_orden == "1234567"
    assert fila.canal_de_venta == "Mercadolibre Carrito"
    assert fila.estado_pago == "Cobrado"
    assert fila.skus_vendidos == "CF217ACOMP"
    assert fila.costo_envio == Decimal("7821")
    assert fila.comision_venta == Decimal(str(7392.8 + 122.94))
    assert fila.precio_final == Decimal("20618.4")
    assert fila.precio_sin_iva == Decimal("17040")
    assert fila.costo_sin_iva == Decimal("0.002") * Decimal("1")
    assert fila.incidencia is None


def test_fila_desde_orden_usa_id_si_falta_customorderid():
    fila = _fila_desde_orden(_orden(customOrderId=None), Decimal(1500), _CANALES, _ESTADOS_PAGO)
    assert fila.numero_orden == "78672152"


def test_fila_desde_orden_traduce_estado_de_pago_y_le_quita_el_espacio():
    # 'partially_paid' -> 'Cobro Parcial ' (espacio real de la API) -> strip()
    fila = _fila_desde_orden(_orden(paymentStatus="partially_paid"), Decimal(1500), _CANALES, _ESTADOS_PAGO)
    assert fila.estado_pago == "Cobro Parcial"


def test_fila_desde_orden_costo_envio_es_listcost_menos_cost():
    # Segunda corrección real 2026-08-13 (la primera, basada en
    # freeShipping, fallaba en ambos sentidos contra órdenes reales del
    # 2026-08-12 -- ver docstring del módulo): listCost es la tarifa de
    # lista, cost es lo que paga el comprador, la diferencia es lo que
    # absorbe el vendedor. Confirmado en 296 de 315 órdenes reales.
    fila = _fila_desde_orden(
        _orden(shipping={"listCost": 11173.09, "cost": 3943.09}),
        Decimal(1500), _CANALES, _ESTADOS_PAGO,
    )
    assert fila.costo_envio == Decimal("7230.00")


def test_fila_desde_orden_costo_envio_es_cero_si_es_fulfillment():
    # Las 12 órdenes reales que no cerraban con listCost-cost eran, las 12,
    # órdenes Full (logistic_type=fulfillment) -- ahí Costo Envío es
    # siempre 0 sin importar listCost/cost (el costo de Full se cobra
    # aparte, no por orden).
    orden = _orden(id="99", shipping={"listCost": 18251.87, "cost": 0})
    fila = _fila_desde_orden(orden, Decimal(1500), _CANALES, _ESTADOS_PAGO, ids_full={"99"})
    assert fila.costo_envio == Decimal(0)


def test_fila_desde_orden_postventa_fuerza_precios_a_cero_conserva_costo():
    fila = _fila_desde_orden(_orden(owner="Posventa"), Decimal(1500), _CANALES, _ESTADOS_PAGO)
    assert fila.precio_final == Decimal(0)
    assert fila.precio_sin_iva == Decimal(0)
    assert fila.costo_sin_iva > 0  # se conserva la pérdida del costo


def test_fila_desde_orden_costo_cero_es_incidencia():
    orden = _orden(orderLists=[{
        "quantity": 1, "subtotal": 100, "subtotalSinImpuestos": 90,
        "variant": {"sku": "X", "cost": 0, "product": {"sku": None}},
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
        if "customRangeLimit" in query:
            return _Respuesta(200, {}, {"data": {"orders": {"findSettings": {"dateRange": {"customRangeLimit": 100}}}}})
        if "findSettings" in query:
            filtros = [
                {"id": "owner", "options": [{"id": k, "name": v} for k, v in (canales or _CANALES).items()]},
                {"id": "payment", "options": [{"id": k, "name": v} for k, v in (estados_pago or _ESTADOS_PAGO).items()]},
            ]
            return _Respuesta(200, {}, {"data": {"orders": {"findSettings": {"filters": filtros}}}})
        # Se llama una vez por tab (active, closed); ambas devuelven el mismo
        # fixture -- el dedupe de `buscar_ordenes` es quien evita que cuente
        # doble, no este fake (mismo principio que en los tests de arriba).
        variables = json_body["variables"]
        datos = ordenes if variables["page"] == 1 else []
        return _Respuesta(200, {}, {"data": {"orders": {"find": {
            "pageInfo": {"page": variables["page"], "pageCount": 1, "count": len(datos)}, "data": datos,
        }}}})

    return post


def test_adapter_periodo_separa_lineas_excluidas_e_incidencias():
    ordenes = [
        _orden(id="1", customOrderId="1"),  # normal, paid
        _orden(id="2", customOrderId="2", paymentStatus="refunded"),  # excluida por estado
        _orden(id="3", customOrderId="3", orderLists=[{  # incidencia de costo
            "quantity": 1, "subtotal": 100, "subtotalSinImpuestos": 90,
            "variant": {"sku": "X", "cost": 0, "product": {"sku": None}},
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
