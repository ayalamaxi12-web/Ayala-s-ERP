"""Tests de `ml_full.py` — sin red real: `MLFullClient` recibe un `get_fn`
falso, `EcomFullAdapter` recibe un cliente GraphQL falso. Mismo patrón que
`rentabilidad/tests/` (fetch_fn/post_fn inyectable, ver
`rentabilidad/ingesta_ecom_api.py`)."""
import pytest

from ml_full import (
    EcomFullAdapter,
    ItemFullML,
    MLFullClient,
    conciliar,
    extraer_items_full,
)

_FAKE_TOKEN_FN = lambda cuenta: "FAKE-TOKEN"


# ── MLFullClient.items_activos — paginación search_type=scan + scroll_id ──

def test_items_activos_pagina_con_scroll_id_hasta_que_no_hay_mas_resultados():
    llamadas = []

    def fake_get(url, params, headers):
        llamadas.append(dict(params))
        if "scroll_id" not in params:
            return {"results": ["MLA1", "MLA2"], "scroll_id": "SCROLL-1"}
        if params["scroll_id"] == "SCROLL-1":
            return {"results": ["MLA3"], "scroll_id": "SCROLL-2"}
        return {"results": [], "scroll_id": "SCROLL-3"}

    client = MLFullClient(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN)
    ids = client.items_activos("IT")
    assert ids == ["MLA1", "MLA2", "MLA3"]
    assert llamadas[0]["search_type"] == "scan"
    assert llamadas[0]["status"] == "active"
    assert llamadas[1]["scroll_id"] == "SCROLL-1"
    assert llamadas[2]["scroll_id"] == "SCROLL-2"
    assert len(llamadas) == 3  # no pide una cuarta página tras results=[]


def test_items_activos_corta_si_no_hay_scroll_id_en_la_respuesta():
    def fake_get(url, params, headers):
        return {"results": ["MLA1"]}  # sin scroll_id -- no hay más para pedir

    client = MLFullClient(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN)
    ids = client.items_activos("IT")
    assert ids == ["MLA1"]


def test_items_activos_sin_resultados_devuelve_vacio():
    def fake_get(url, params, headers):
        return {"results": []}

    client = MLFullClient(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN)
    assert client.items_activos("IT") == []


# ── MLFullClient.detalle_items — lotes de 20 ──

def test_detalle_items_pide_de_a_20():
    lotes_pedidos = []

    def fake_get(url, params, headers):
        lotes_pedidos.append(params["ids"].split(","))
        return [{"body": {"id": i}} for i in params["ids"].split(",")]

    client = MLFullClient(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN)
    ids = [f"MLA{i}" for i in range(25)]
    detalle = client.detalle_items(ids, "IT")
    assert len(lotes_pedidos) == 2
    assert len(lotes_pedidos[0]) == 20 and len(lotes_pedidos[1]) == 5
    assert len(detalle) == 25


# ── extraer_items_full ──

def _item(item_id, logistic_type="fulfillment", scf=None, variations=None, inventory_id=None):
    return {
        "id": item_id, "title": f"Item {item_id}",
        "shipping": {"logistic_type": logistic_type},
        "seller_custom_field": scf, "inventory_id": inventory_id,
        "variations": variations or [],
    }


def test_extraer_items_full_ignora_lo_que_no_es_fulfillment():
    items = [_item("MLA1", logistic_type="drop_off", scf="SKU1")]
    filas, incid = extraer_items_full(items, "IT")
    assert filas == []


def test_extraer_items_full_sin_variaciones_usa_sku_e_inventory_del_item():
    items = [_item("MLA1", scf="SKU1", inventory_id="INV1")]
    filas, incid = extraer_items_full(items, "IT")
    assert filas == [ItemFullML(item_id="MLA1", cuenta="IT", sku="SKU1", inventory_id="INV1", titulo="Item MLA1")]
    assert incid == []


def test_extraer_items_full_expande_por_variacion_con_su_propio_inventory_id():
    items = [_item("MLA1", scf="SKU-BASE", variations=[
        {"inventory_id": "INV-A", "attributes": [{"id": "SELLER_SKU", "value_name": "SKU-A"}]},
        {"inventory_id": "INV-B", "attributes": [{"id": "SELLER_SKU", "value_name": "SKU-B"}]},
    ])]
    filas, incid = extraer_items_full(items, "IT")
    assert len(filas) == 2
    assert {f.inventory_id for f in filas} == {"INV-A", "INV-B"}
    assert {f.sku for f in filas} == {"SKU-A", "SKU-B"}


def test_extraer_items_full_sin_sku_es_incidencia_no_se_descarta_en_silencio():
    items = [_item("MLA1", scf=None, inventory_id="INV1")]
    filas, incid = extraer_items_full(items, "IT")
    assert len(filas) == 1  # la fila se guarda igual
    assert incid == [{"item_id": "MLA1", "cuenta": "IT", "motivo": "SIN_SKU"}]


def test_extraer_items_full_fallback_a_seller_sku_del_item_si_no_hay_scf():
    items = [{
        "id": "MLA1", "title": "x", "shipping": {"logistic_type": "fulfillment"},
        "seller_custom_field": None, "inventory_id": "INV1", "variations": [],
        "attributes": [{"id": "SELLER_SKU", "value_name": "SKU-ATTR"}],
    }]
    filas, incid = extraer_items_full(items, "IT")
    assert filas[0].sku == "SKU-ATTR"
    assert incid == []


# ── EcomFullAdapter ──

class _ClienteGraphQLFalso:
    """Responde según qué query le llega, sin red. Mismo espíritu que
    inyectar `post_fn` en `EcomApiClient` real."""

    def __init__(self, respuestas: dict):
        self._respuestas = respuestas
        self.llamadas = []

    def graphql(self, query, variables=None):
        self.llamadas.append((query, variables))
        for clave, respuesta in self._respuestas.items():
            if clave in query:
                return respuesta(variables) if callable(respuesta) else respuesta
        raise AssertionError(f"Query no esperada en el fake: {query[:60]}")


def test_warehouse_full_id_resuelve_por_typefull_no_por_nombre():
    cliente = _ClienteGraphQLFalso({
        "getAllWarehouses": {"productWarehouses": {"getAllWarehouses": [
            {"id": "297", "title": "Pitec", "typeFull": False},
            {"id": "4023", "title": "ML Full", "typeFull": True},
        ]}},
    })
    adapter = EcomFullAdapter(cliente)
    assert adapter.warehouse_full_id() == "4023"


def test_warehouse_full_id_falla_si_no_hay_exactamente_uno_marcado_full():
    cliente = _ClienteGraphQLFalso({
        "getAllWarehouses": {"productWarehouses": {"getAllWarehouses": [
            {"id": "1", "title": "A", "typeFull": True},
            {"id": "2", "title": "B", "typeFull": True},
        ]}},
    })
    adapter = EcomFullAdapter(cliente)
    with pytest.raises(Exception):
        adapter.warehouse_full_id()


def test_stock_full_por_sku_suma_variantwarehouses_del_deposito_full():
    cliente = _ClienteGraphQLFalso({
        "getAllWarehouses": {"productWarehouses": {"getAllWarehouses": [
            {"id": "4023", "title": "ML Full", "typeFull": True},
        ]}},
        "readBySku": {"products": {"readBySku": {"id": "1", "variants": [
            {"id": "v1", "variantWarehouses": [
                {"warehouse_id": "297", "warehouse_title": "Pitec", "warehouse_qty": 10},
                {"warehouse_id": "4023", "warehouse_title": "ML Full", "warehouse_qty": 78},
            ]},
        ]}}},
    })
    adapter = EcomFullAdapter(cliente)
    assert adapter.stock_full_por_sku("CB435A-436A-CE285AUNIVCOMP") == 78


def test_stock_full_por_sku_none_si_no_existe_en_ecom():
    cliente = _ClienteGraphQLFalso({
        "getAllWarehouses": {"productWarehouses": {"getAllWarehouses": [
            {"id": "4023", "title": "ML Full", "typeFull": True},
        ]}},
        "readBySku": {"products": {"readBySku": None}},
    })
    adapter = EcomFullAdapter(cliente)
    assert adapter.stock_full_por_sku("NO-EXISTE") is None


def test_stock_disponible_resuelve_por_titulo_pitec_no_por_ausencia_de_full():
    # Confirmado con Maxx (2026-08-20): "disponible" es SOLO Pitec, no
    # "todo lo que no es Full" -- Gaona/Outlet no deberían sumar.
    cliente = _ClienteGraphQLFalso({
        "getAllWarehouses": {"productWarehouses": {"getAllWarehouses": [
            {"id": "297", "title": "Pitec", "typeFull": False},
            {"id": "4023", "title": "ML Full", "typeFull": True},
            {"id": "12748", "title": "Gaona", "typeFull": False},
        ]}},
        "readBySku": {"products": {"readBySku": {"id": "1", "variants": [
            {"id": "v1", "variantWarehouses": [
                {"warehouse_id": "297", "warehouse_title": "Pitec", "warehouse_qty": 15},
                {"warehouse_id": "4023", "warehouse_title": "ML Full", "warehouse_qty": 78},
                {"warehouse_id": "12748", "warehouse_title": "Gaona", "warehouse_qty": 999},
            ]},
        ]}}},
    })
    adapter = EcomFullAdapter(cliente)
    assert adapter.stock_disponible_por_sku("CB435A-436A-CE285AUNIVCOMP") == 15


def test_deposito_disponible_falla_si_no_hay_exactamente_un_pitec():
    cliente = _ClienteGraphQLFalso({
        "getAllWarehouses": {"productWarehouses": {"getAllWarehouses": [
            {"id": "4023", "title": "ML Full", "typeFull": True},
        ]}},
    })
    adapter = EcomFullAdapter(cliente)
    with pytest.raises(Exception):
        adapter.deposito_disponible_id()


def test_producto_por_sku_se_cachea_entre_stock_full_y_stock_disponible():
    llamadas_producto = []

    def readbysku(variables):
        llamadas_producto.append(variables["sku"])
        return {"products": {"readBySku": {"id": "1", "variants": [
            {"id": "v1", "variantWarehouses": [
                {"warehouse_id": "297", "warehouse_title": "Pitec", "warehouse_qty": 15},
                {"warehouse_id": "4023", "warehouse_title": "ML Full", "warehouse_qty": 78},
            ]},
        ]}}}

    cliente = _ClienteGraphQLFalso({
        "getAllWarehouses": {"productWarehouses": {"getAllWarehouses": [
            {"id": "297", "title": "Pitec", "typeFull": False},
            {"id": "4023", "title": "ML Full", "typeFull": True},
        ]}},
        "readBySku": readbysku,
    })
    adapter = EcomFullAdapter(cliente)
    assert adapter.stock_full_por_sku("SKU-X") == 78
    assert adapter.stock_disponible_por_sku("SKU-X") == 15
    assert llamadas_producto == ["SKU-X"]  # una sola vez, no dos


# ── MLFullClient.ventas_por_item ──

def test_ventas_por_item_agrega_cantidad_y_rango_de_fechas():
    def fake_get(url, params, headers):
        assert "orders/search" in url
        if params["offset"] == 0:
            return {
                "results": [
                    {"date_closed": "2026-08-01T10:00:00.000-04:00", "order_items": [
                        {"item": {"id": "MLA1"}, "quantity": 3},
                    ]},
                    {"date_closed": "2026-08-05T10:00:00.000-04:00", "order_items": [
                        {"item": {"id": "MLA1"}, "quantity": 2},
                        {"item": {"id": "MLA2"}, "quantity": 1},
                    ]},
                ],
                "paging": {"total": 2, "offset": 0, "limit": 50},
            }
        raise AssertionError("no debería pedir más páginas")

    client = MLFullClient(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN)
    ventas = client.ventas_por_item("IT", "2026-08-01T00:00:00.000-00:00", "2026-08-19T23:00:00.000-00:00")
    assert ventas["MLA1"] == {"unidades": 5, "primera": "2026-08-01", "ultima": "2026-08-05"}
    assert ventas["MLA2"] == {"unidades": 1, "primera": "2026-08-05", "ultima": "2026-08-05"}


def test_ventas_por_item_pagina_hasta_agotar_el_total():
    paginas_pedidas = []

    def fake_get(url, params, headers):
        paginas_pedidas.append(params["offset"])
        if params["offset"] == 0:
            return {"results": [{"date_closed": "2026-08-01T10:00:00.000-04:00",
                                  "order_items": [{"item": {"id": "MLA1"}, "quantity": 1}]}] * 50,
                     "paging": {"total": 60, "offset": 0, "limit": 50}}
        return {"results": [{"date_closed": "2026-08-02T10:00:00.000-04:00",
                              "order_items": [{"item": {"id": "MLA1"}, "quantity": 1}]}] * 10,
                "paging": {"total": 60, "offset": 50, "limit": 50}}

    client = MLFullClient(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN)
    ventas = client.ventas_por_item("IT", "2026-08-01T00:00:00.000-00:00", "2026-08-19T23:00:00.000-00:00")
    assert paginas_pedidas == [0, 50]
    assert ventas["MLA1"]["unidades"] == 60


def test_factor_pack_none_si_no_esta_vinculada():
    # Visto en la realidad (2026-08-20, dos ítems reales sin pack):
    # linked=false, productListings=[].
    cliente = _ClienteGraphQLFalso({
        "mlListings": {"mlListings": {"read": {"linked": False, "productListings": []}}},
    })
    adapter = EcomFullAdapter(cliente)
    assert adapter.factor_pack("MLA1") is None


def test_factor_pack_resuelve_sku_y_factor_via_productlistings():
    # Réplica exacta de la respuesta real contra MLA2693713220 ("X2
    # CB435A-436A-CE285AUNIVCOMP", dato de Maxx, 2026-08-20): qty=2.
    cliente = _ClienteGraphQLFalso({
        "mlListings": {"mlListings": {"read": {
            "linked": True,
            "productListings": [
                {"qty": 2, "productId": "6016092", "product": {"id": "6016092", "sku": "CB435A-436A-CE285AUNIVCOMP"}},
            ],
        }}},
    })
    adapter = EcomFullAdapter(cliente)
    assert adapter.factor_pack("MLA2693713220") == {"CB435A-436A-CE285AUNIVCOMP": 2}


# ── conciliar() end-to-end con fakes ──

def test_conciliar_deduplica_por_inventory_id_y_aplica_factor_de_ecom():
    # Dos publicaciones (cuentas distintas) comparten el mismo inventory_id
    # -- no hay que sumarlas dos veces (§3.3).
    def fake_get(url, params, headers):
        if "items/search" in url:
            if "scroll_id" not in params:
                return {"results": ["MLA1", "MLA2"], "scroll_id": "SCROLL-1"}
            return {"results": []}
        if url.endswith("/items"):
            return [
                {"body": {"id": "MLA1", "title": "Pack x2", "shipping": {"logistic_type": "fulfillment"},
                          "seller_custom_field": "PACK-SKU-ML", "inventory_id": "INV-SHARED", "variations": []}},
                {"body": {"id": "MLA2", "title": "Pack x2 otra cuenta", "shipping": {"logistic_type": "fulfillment"},
                          "seller_custom_field": "PACK-SKU-ML", "inventory_id": "INV-SHARED", "variations": []}},
            ]
        if "stock/fulfillment" in url:
            return {"available_quantity": 50}
        raise AssertionError(url)

    ml = MLFullClient(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN)
    cliente = _ClienteGraphQLFalso({
        "getAllWarehouses": {"productWarehouses": {"getAllWarehouses": [
            {"id": "4023", "title": "ML Full", "typeFull": True},
        ]}},
        "mlListings": {"mlListings": {"read": {
            "linked": True,
            "productListings": [{"qty": 2, "productId": "P1", "product": {"id": "P1", "sku": "SKU-COMPONENTE"}}],
        }}},
        "readBySku": {"products": {"readBySku": {"id": "1", "variants": [
            {"id": "v1", "variantWarehouses": [{"warehouse_id": "4023", "warehouse_title": "ML Full", "warehouse_qty": 90}]},
        ]}}},
    })
    ecom = EcomFullAdapter(cliente)

    resultado = conciliar(ml, ecom, cuentas=["IT"])

    assert len(resultado.filas) == 1
    fila = resultado.filas[0]
    assert fila.sku == "SKU-COMPONENTE"
    # 50 disponibles x factor 2 = 100 -- NO 200 (que daría si no deduplicara por inventory_id)
    assert fila.stock_ml == 100
    assert fila.stock_ecom == 90
    assert fila.diferencia == 10
    assert len(fila.publicaciones) == 1  # una sola, no dos, por el dedup
    assert resultado.incidencias_sin_vincular == []


def test_conciliar_sin_vincular_cae_al_sku_de_ml_y_deja_incidencia():
    def fake_get(url, params, headers):
        if "items/search" in url:
            if "scroll_id" not in params:
                return {"results": ["MLA1"], "scroll_id": "SCROLL-1"}
            return {"results": []}
        if url.endswith("/items"):
            return [{"body": {"id": "MLA1", "title": "Simple", "shipping": {"logistic_type": "fulfillment"},
                              "seller_custom_field": "SKU-ML-SOLO", "inventory_id": "INV-1", "variations": []}}]
        if "stock/fulfillment" in url:
            return {"available_quantity": 30}
        raise AssertionError(url)

    ml = MLFullClient(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN)
    cliente = _ClienteGraphQLFalso({
        "getAllWarehouses": {"productWarehouses": {"getAllWarehouses": [
            {"id": "4023", "title": "ML Full", "typeFull": True},
        ]}},
        "mlListings": {"mlListings": {"read": {"linked": False, "productListings": []}}},
        "readBySku": {"products": {"readBySku": None}},
    })
    ecom = EcomFullAdapter(cliente)

    resultado = conciliar(ml, ecom, cuentas=["IT"])

    assert len(resultado.filas) == 1
    assert resultado.filas[0].sku == "SKU-ML-SOLO"
    assert resultado.filas[0].stock_ml == 30
    assert resultado.incidencias_sin_vincular == [{
        "item_id": "MLA1", "cuenta": "IT", "sku_ml": "SKU-ML-SOLO",
        "motivo": "SIN_VINCULAR_EN_ECOM_FACTOR_1_ASUMIDO",
    }]
