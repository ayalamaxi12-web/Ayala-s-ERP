"""Tests de `ml_reposicion.py` — mismos fakes que `test_ml_full.py`
(`get_fn`/`token_fn` inyectables del lado ML, cliente GraphQL falso del
lado Ecom), sin red real."""
from datetime import date

from ml_full import EcomFullAdapter, MLFullClient
from ml_reposicion import calcular_reposicion

_FAKE_TOKEN_FN = lambda cuenta: "FAKE-TOKEN"


class _ClienteGraphQLFalso:
    def __init__(self, respuestas: dict):
        self._respuestas = respuestas

    def graphql(self, query, variables=None):
        for clave, respuesta in self._respuestas.items():
            if clave in query:
                return respuesta(variables) if callable(respuesta) else respuesta
        raise AssertionError(f"Query no esperada en el fake: {query[:60]}")


def _item_simple(item_id, sku, inventory_id):
    return {"id": item_id, "title": f"Item {item_id}", "shipping": {"logistic_type": "fulfillment"},
            "seller_custom_field": sku, "inventory_id": inventory_id, "variations": []}


def _armar_ml(items_por_cuenta: dict, stock_por_inventory: dict, ventas_por_cuenta: dict):
    """`items_por_cuenta`: {cuenta: [item, ...]}. `ventas_por_cuenta`:
    {cuenta: {item_id: {"unidades": N, "primera": "YYYY-MM-DD", "ultima": "YYYY-MM-DD"}}}."""
    def fake_get(url, params, headers):
        if "items/search" in url:
            return {"results": []}
        raise AssertionError(f"no debería llamarse (usar detalle_items directo): {url}")
    # No se usa items_activos/detalle_items reales acá -- se arma MLFullClient
    # con un get_fn que sabe responder los tres tipos de llamada que hace
    # conciliar()+calcular_reposicion() según la URL.
    cuenta_actual = {}

    def get_fn(url, params, headers):
        if "items/search" in url:
            cuenta = cuenta_actual["cuenta"]
            if params["offset"] == 0 and params["sort"] == "start_time_desc":
                return {"results": [i["id"] for i in items_por_cuenta.get(cuenta, [])]}
            return {"results": []}
        if url.endswith("/items"):
            cuenta = cuenta_actual["cuenta"]
            return [{"body": i} for i in items_por_cuenta.get(cuenta, [])]
        if "stock/fulfillment" in url:
            inv = url.rsplit("/inventories/", 1)[1].split("/")[0]
            return stock_por_inventory.get(inv, {"available_quantity": 0})
        if "orders/search" in url:
            cuenta = cuenta_actual["cuenta"]
            return {"results": [], "paging": {"total": 0, "offset": 0, "limit": 50}}
        raise AssertionError(url)

    class _MLConCuentaActual(MLFullClient):
        def items_activos(self, cuenta):
            cuenta_actual["cuenta"] = cuenta
            return [i["id"] for i in items_por_cuenta.get(cuenta, [])]

        def detalle_items(self, item_ids, cuenta):
            cuenta_actual["cuenta"] = cuenta
            return [i for i in items_por_cuenta.get(cuenta, []) if i["id"] in item_ids]

        def stock_fulfillment(self, inventory_id, cuenta):
            return stock_por_inventory.get(inventory_id, {"available_quantity": 0})

        def ventas_por_item(self, cuenta, desde_iso, hasta_iso):
            return ventas_por_cuenta.get(cuenta, {})

    return _MLConCuentaActual(get_fn=get_fn, token_fn=_FAKE_TOKEN_FN)


def _ecom_simple(stock_full: dict, stock_pitec: dict):
    cliente = _ClienteGraphQLFalso({
        "getAllWarehouses": {"productWarehouses": {"getAllWarehouses": [
            {"id": "297", "title": "Pitec", "typeFull": False},
            {"id": "4023", "title": "ML Full", "typeFull": True},
        ]}},
        "mlListings": {"mlListings": {"read": {"linked": False, "productListings": []}}},
        "readBySku": lambda variables: {"products": {"readBySku": {
            "id": "1",
            "variants": [{"id": "v1", "variantWarehouses": [
                {"warehouse_id": "4023", "warehouse_title": "ML Full",
                 "warehouse_qty": stock_full.get(variables["sku"], 0)},
                {"warehouse_id": "297", "warehouse_title": "Pitec",
                 "warehouse_qty": stock_pitec.get(variables["sku"], 0)},
            ]},
            ],
        }}} if variables["sku"] in stock_full or variables["sku"] in stock_pitec else {"products": {"readBySku": None}},
    })
    return EcomFullAdapter(cliente)


def test_replica_el_ejemplo_de_la_planilla_sin_censura():
    # 30 unidades vendidas parejo en 30 días -> 1/día. Objetivo 3 semanas
    # (21 días) -> stock objetivo 21. Stock actual en Full = 1 -> falta 20.
    ml = _armar_ml(
        items_por_cuenta={"IT": [_item_simple("MLA1", "SKU-A", "INV-1")]},
        stock_por_inventory={"INV-1": {"available_quantity": 1}},
        ventas_por_cuenta={"IT": {"MLA1": {"unidades": 30, "primera": "2026-07-20", "ultima": "2026-08-18"}}},
    )
    ecom = _ecom_simple(stock_full={"SKU-A": 1}, stock_pitec={"SKU-A": 100})

    resultado = calcular_reposicion(ml, ecom, cuentas=["IT"], dias_ventas=30, semanas_objetivo=3,
                                     hoy=date(2026, 8, 19))

    fila = resultado.filas[0]
    assert fila.sku == "SKU-A"
    assert fila.censurado is False
    assert fila.ventas_diarias == 1.0
    assert fila.stock_objetivo == 21.0
    assert fila.falta_enviar == 20
    assert fila.disponible_pitec == 100
    assert fila.enviar_posible == 20
    assert fila.alerta_revisar_tactica is False


def test_detecta_censura_y_corrige_la_tasa_diaria():
    # Las mismas 30 unidades, pero vendidas en 5 días y después stock 0 --
    # tasa real 6/día, no 1/día (el ejemplo central de 03_MODULO_FULL.md §2).
    ml = _armar_ml(
        items_por_cuenta={"IT": [_item_simple("MLA1", "SKU-A", "INV-1")]},
        stock_por_inventory={"INV-1": {"available_quantity": 0}},
        ventas_por_cuenta={"IT": {"MLA1": {"unidades": 30, "primera": "2026-08-01", "ultima": "2026-08-06"}}},
    )
    ecom = _ecom_simple(stock_full={"SKU-A": 0}, stock_pitec={"SKU-A": 200})

    resultado = calcular_reposicion(ml, ecom, cuentas=["IT"], dias_ventas=30, semanas_objetivo=3,
                                     hoy=date(2026, 8, 19))

    fila = resultado.filas[0]
    assert fila.censurado is True
    assert fila.ventas_diarias == 6.0  # 30 / 5, no 30 / 30


def test_no_censura_si_el_stock_actual_no_esta_en_cero():
    # Mismo patrón de ventas concentradas, pero con stock > 0 hoy -- no
    # aplica la corrección (la condición exige stock=0 actual).
    ml = _armar_ml(
        items_por_cuenta={"IT": [_item_simple("MLA1", "SKU-A", "INV-1")]},
        stock_por_inventory={"INV-1": {"available_quantity": 50}},
        ventas_por_cuenta={"IT": {"MLA1": {"unidades": 30, "primera": "2026-08-01", "ultima": "2026-08-06"}}},
    )
    ecom = _ecom_simple(stock_full={"SKU-A": 50}, stock_pitec={"SKU-A": 200})

    resultado = calcular_reposicion(ml, ecom, cuentas=["IT"], dias_ventas=30, hoy=date(2026, 8, 19))

    assert resultado.filas[0].censurado is False
    assert resultado.filas[0].ventas_diarias == 1.0  # 30 / 30 (días del período), no la ventana


def test_aplica_el_factor_de_pack_a_las_ventas_no_solo_al_stock():
    # Una publicación pack x2 vendió 10 "paquetes" -> son 20 unidades
    # reales del SKU vinculado, igual que el stock ya se multiplica.
    def graphql_con_pack(query, variables=None):
        if "getAllWarehouses" in query:
            return {"productWarehouses": {"getAllWarehouses": [
                {"id": "297", "title": "Pitec", "typeFull": False},
                {"id": "4023", "title": "ML Full", "typeFull": True},
            ]}}
        if "mlListings" in query:
            return {"mlListings": {"read": {"linked": True, "productListings": [
                {"qty": 2, "productId": "P1", "product": {"sku": "SKU-COMPONENTE"}},
            ]}}}
        if "readBySku" in query:
            return {"products": {"readBySku": {"id": "1", "variants": [{"id": "v1", "variantWarehouses": [
                {"warehouse_id": "4023", "warehouse_title": "ML Full", "warehouse_qty": 4},
                {"warehouse_id": "297", "warehouse_title": "Pitec", "warehouse_qty": 300},
            ]}]}}}
        raise AssertionError(query[:60])

    ecom = EcomFullAdapter(_ClienteGraphQLFalsoDirecto(graphql_con_pack))
    ml = _armar_ml(
        items_por_cuenta={"IT": [_item_simple("MLA1", "PACK-SKU-ML", "INV-1")]},
        stock_por_inventory={"INV-1": {"available_quantity": 2}},
        ventas_por_cuenta={"IT": {"MLA1": {"unidades": 10, "primera": "2026-08-01", "ultima": "2026-08-15"}}},
    )

    resultado = calcular_reposicion(ml, ecom, cuentas=["IT"], dias_ventas=30, hoy=date(2026, 8, 19))

    fila = resultado.filas[0]
    assert fila.sku == "SKU-COMPONENTE"
    assert fila.stock_full == 4  # 2 disponibles x factor 2
    assert fila.ventas_periodo == 20  # 10 paquetes x factor 2, no 10


class _ClienteGraphQLFalsoDirecto:
    def __init__(self, fn):
        self._fn = fn

    def graphql(self, query, variables=None):
        return self._fn(query, variables)


def test_enviar_posible_topeado_por_disponible_en_pitec_y_marca_alerta_tactica():
    ml = _armar_ml(
        items_por_cuenta={"IT": [_item_simple("MLA1", "SKU-A", "INV-1")]},
        stock_por_inventory={"INV-1": {"available_quantity": 0}},
        ventas_por_cuenta={"IT": {"MLA1": {"unidades": 30, "primera": "2026-07-20", "ultima": "2026-08-18"}}},
    )
    # Falta enviar = 21 - 0 = 21, pero Pitec solo tiene 5.
    ecom = _ecom_simple(stock_full={"SKU-A": 0}, stock_pitec={"SKU-A": 5})

    resultado = calcular_reposicion(ml, ecom, cuentas=["IT"], dias_ventas=30, semanas_objetivo=3,
                                     hoy=date(2026, 8, 19))

    fila = resultado.filas[0]
    assert fila.falta_enviar == 21
    assert fila.disponible_pitec == 5
    assert fila.enviar_posible == 5
    assert fila.alerta_revisar_tactica is True


def test_cobertura_y_quiebre_estimado():
    ml = _armar_ml(
        items_por_cuenta={"IT": [_item_simple("MLA1", "SKU-A", "INV-1")]},
        stock_por_inventory={"INV-1": {"available_quantity": 10}},
        ventas_por_cuenta={"IT": {"MLA1": {"unidades": 30, "primera": "2026-07-20", "ultima": "2026-08-18"}}},
    )
    ecom = _ecom_simple(stock_full={"SKU-A": 10}, stock_pitec={"SKU-A": 0})

    resultado = calcular_reposicion(ml, ecom, cuentas=["IT"], dias_ventas=30, hoy=date(2026, 8, 19))

    fila = resultado.filas[0]
    # Ventas diarias 1/día, stock 10 -> cobertura 10 días -> quiebre 2026-08-29
    assert fila.cobertura_dias == 10.0
    assert fila.quiebre_estimado == "2026-08-29"


def test_sin_ventas_en_el_periodo_no_calcula_cobertura():
    ml = _armar_ml(
        items_por_cuenta={"IT": [_item_simple("MLA1", "SKU-A", "INV-1")]},
        stock_por_inventory={"INV-1": {"available_quantity": 10}},
        ventas_por_cuenta={"IT": {}},
    )
    ecom = _ecom_simple(stock_full={"SKU-A": 10}, stock_pitec={"SKU-A": 0})

    resultado = calcular_reposicion(ml, ecom, cuentas=["IT"], dias_ventas=30, hoy=date(2026, 8, 19))

    fila = resultado.filas[0]
    assert fila.ventas_periodo == 0
    assert fila.cobertura_dias is None
    assert fila.quiebre_estimado is None
