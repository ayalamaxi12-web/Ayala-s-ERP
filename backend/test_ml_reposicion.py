"""Tests de `ml_reposicion.py` — mismos fakes que `test_ml_full.py`
(`get_fn`/`token_fn` inyectables del lado ML, cliente GraphQL falso del
lado Ecom, `leer_fn` inyectable del lado Táctica), sin red real."""
from datetime import date

from ml_full import EcomFullAdapter, MLFullClient, TacticaStockSheetAdapter
from ml_reposicion import calcular_reposicion_mla

_FAKE_TOKEN_FN = lambda cuenta: "FAKE-TOKEN"


class _ClienteGraphQLFalso:
    def __init__(self, respuestas: dict):
        self._respuestas = respuestas

    def graphql(self, query, variables=None):
        for clave, respuesta in self._respuestas.items():
            if clave in query:
                return respuesta(variables) if callable(respuesta) else respuesta
        raise AssertionError(f"Query no esperada en el fake: {query[:60]}")


class _ClienteGraphQLFalsoDirecto:
    def __init__(self, fn):
        self._fn = fn

    def graphql(self, query, variables=None):
        return self._fn(query, variables)


def _item_simple(item_id, sku, inventory_id):
    return {"id": item_id, "title": f"Item {item_id}", "shipping": {"logistic_type": "fulfillment"},
            "seller_custom_field": sku, "inventory_id": inventory_id, "variations": []}


def _armar_ml(items_por_cuenta: dict, stock_por_inventory: dict, ventas_por_cuenta: dict):
    """`items_por_cuenta`: {cuenta: [item, ...]}. `ventas_por_cuenta`:
    {cuenta: {inventory_id: {"unidades": N, "primera": "YYYY-MM-DD", "ultima": "YYYY-MM-DD"}}}
    -- por `inventory_id`, no por `item_id` (ver `ventas_full_por_inventory`,
    scopeada a ventas realmente despachadas desde Full)."""
    cuenta_actual = {}

    def get_fn(url, params, headers):
        if "items/search" in url:
            return {"results": []}
        raise AssertionError(f"no debería llamarse (usar detalle_items directo): {url}")

    class _MLConCuentaActual(MLFullClient):
        def items_activos(self, cuenta):
            cuenta_actual["cuenta"] = cuenta
            return [i["id"] for i in items_por_cuenta.get(cuenta, [])]

        def detalle_items(self, item_ids, cuenta):
            cuenta_actual["cuenta"] = cuenta
            return [i for i in items_por_cuenta.get(cuenta, []) if i["id"] in item_ids]

        def stock_fulfillment(self, inventory_id, cuenta):
            return stock_por_inventory.get(inventory_id, {"available_quantity": 0})

        def ventas_full_por_inventory(self, cuenta, inventory_ids, desde, hasta):
            return {k: v for k, v in ventas_por_cuenta.get(cuenta, {}).items() if k in inventory_ids}

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


def _tactica_simple(stock_por_sku: dict):
    filas = [["SKU", "Titulo", "Familia", "Iva", "Stock Tactica", "Stock Ecom"]]
    for sku, stock in stock_por_sku.items():
        filas.append([sku, "", "", "", str(stock), ""])
    return TacticaStockSheetAdapter(leer_fn=lambda sheet_id, tab: filas)


def test_replica_el_ejemplo_de_la_planilla_sin_censura():
    # 30 unidades vendidas parejo en 30 días -> 1/día. Objetivo 3 semanas
    # (21 días), llega hoy mismo (fecha_llegada=hoy) -> stock objetivo 21,
    # stock a la llegada = stock actual (1) -> cantidad a enviar 20.
    ml = _armar_ml(
        items_por_cuenta={"IT": [_item_simple("MLA1", "SKU-A", "INV-1")]},
        stock_por_inventory={"INV-1": {"available_quantity": 1}},
        ventas_por_cuenta={"IT": {"INV-1": {"unidades": 30, "primera": "2026-07-20", "ultima": "2026-08-18"}}},
    )
    ecom = _ecom_simple(stock_full={"SKU-A": 1}, stock_pitec={"SKU-A": 100})
    tactica = _tactica_simple({"SKU-A": 0})

    resultado = calcular_reposicion_mla(
        ml, ecom, tactica, cuentas=["IT"], dias_ventas=30, semanas_objetivo=3,
        fecha_llegada=date(2026, 8, 19), hoy=date(2026, 8, 19),
    )

    fila = resultado.filas[0]
    assert fila.item_id == "MLA1"
    assert fila.inventory_id == "INV-1"
    assert fila.cuenta == "IT"
    assert fila.sku == "SKU-A"
    assert fila.sku_ml == "SKU-A"
    assert fila.censurado is False
    assert fila.ventas_diarias == 1.0
    assert fila.stock_objetivo == 21.0
    assert fila.stock_a_llegada == 1.0
    assert fila.cantidad_enviar == 20
    assert fila.stock_ecom == 100
    assert fila.stock_tactica == 0
    assert fila.sugerido == 20  # alcanza con lo disponible (100)


def test_detecta_censura_y_corrige_la_tasa_diaria():
    # Las mismas 30 unidades, pero vendidas en 5 días y después stock 0 --
    # tasa real 6/día, no 1/día (el ejemplo central de 03_MODULO_FULL.md §2).
    ml = _armar_ml(
        items_por_cuenta={"IT": [_item_simple("MLA1", "SKU-A", "INV-1")]},
        stock_por_inventory={"INV-1": {"available_quantity": 0}},
        ventas_por_cuenta={"IT": {"INV-1": {"unidades": 30, "primera": "2026-08-01", "ultima": "2026-08-06"}}},
    )
    ecom = _ecom_simple(stock_full={"SKU-A": 0}, stock_pitec={"SKU-A": 200})
    tactica = _tactica_simple({})

    resultado = calcular_reposicion_mla(
        ml, ecom, tactica, cuentas=["IT"], dias_ventas=30, semanas_objetivo=3,
        fecha_llegada=date(2026, 8, 19), hoy=date(2026, 8, 19),
    )

    fila = resultado.filas[0]
    assert fila.censurado is True
    assert fila.ventas_diarias == 6.0  # 30 / 5, no 30 / 30
    assert fila.stock_tactica is None  # SKU no está en el Sheet


def test_no_censura_si_el_stock_actual_no_esta_en_cero():
    ml = _armar_ml(
        items_por_cuenta={"IT": [_item_simple("MLA1", "SKU-A", "INV-1")]},
        stock_por_inventory={"INV-1": {"available_quantity": 50}},
        ventas_por_cuenta={"IT": {"INV-1": {"unidades": 30, "primera": "2026-08-01", "ultima": "2026-08-06"}}},
    )
    ecom = _ecom_simple(stock_full={"SKU-A": 50}, stock_pitec={"SKU-A": 200})
    tactica = _tactica_simple({})

    resultado = calcular_reposicion_mla(
        ml, ecom, tactica, cuentas=["IT"], dias_ventas=30, hoy=date(2026, 8, 19),
    )

    assert resultado.filas[0].censurado is False
    assert resultado.filas[0].ventas_diarias == 1.0  # 30 / 30 (días del período), no la ventana


def test_aplica_el_factor_de_pack_a_las_ventas_y_al_stock():
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
    tactica = _tactica_simple({})
    ml = _armar_ml(
        items_por_cuenta={"IT": [_item_simple("MLA1", "PACK-SKU-ML", "INV-1")]},
        stock_por_inventory={"INV-1": {"available_quantity": 2}},
        ventas_por_cuenta={"IT": {"INV-1": {"unidades": 10, "primera": "2026-08-01", "ultima": "2026-08-15"}}},
    )

    resultado = calcular_reposicion_mla(ml, ecom, tactica, cuentas=["IT"], dias_ventas=30, hoy=date(2026, 8, 19))

    fila = resultado.filas[0]
    assert fila.sku == "SKU-COMPONENTE"
    assert fila.sku_ml == "PACK-SKU-ML"
    assert fila.stock_full == 4  # 2 disponibles x factor 2
    assert fila.ventas_periodo == 20  # 10 paquetes x factor 2, no 10


def test_cantidad_enviar_y_sugerido_se_muestran_en_paquetes_no_en_unidades_reales():
    # Caso real que motivó el fix (2026-08-26): una publicación "X2" con
    # necesidad real de 205 unidades tiene que sugerir enviar en
    # PAQUETES (103, redondeado para arriba), no 205 -- si la persona
    # prepara 205 paquetes manda el doble de lo necesario.
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
                {"warehouse_id": "4023", "warehouse_title": "ML Full", "warehouse_qty": 0},
                {"warehouse_id": "297", "warehouse_title": "Pitec", "warehouse_qty": 1000},
            ]}]}}}
        raise AssertionError(query[:60])

    ecom = EcomFullAdapter(_ClienteGraphQLFalsoDirecto(graphql_con_pack))
    tactica = _tactica_simple({"SKU-COMPONENTE": 0})
    ml = _armar_ml(
        items_por_cuenta={"IT": [_item_simple("MLA1", "PACK-SKU-ML", "INV-1")]},
        stock_por_inventory={"INV-1": {"available_quantity": 0}},
        # 32 "paquetes" vendidos x factor 2 = 64 unidades reales, igual que
        # el caso real (COCF22823 / MLA1607512661).
        ventas_por_cuenta={"IT": {"INV-1": {"unidades": 32, "primera": "2026-07-26", "ultima": "2026-08-05"}}},
    )

    resultado = calcular_reposicion_mla(
        ml, ecom, tactica, cuentas=["IT"], dias_ventas=30, semanas_objetivo=3,
        fecha_llegada=date(2026, 8, 19), hoy=date(2026, 8, 19),
    )

    fila = resultado.filas[0]
    assert fila.factor == 2
    assert fila.ventas_periodo == 64
    # 64 unidades reales en 10 días de ventana (censurado) -> 6.4/día ->
    # objetivo 3 semanas = 134.4 -> round() = 134 unidades reales (stock
    # full 0, nada que restar) -> 134/2 = 67 paquetes.
    assert fila.cantidad_enviar == 67
    assert fila.sugerido == 67  # Pitec tiene de sobra (1000), no lo topea


def test_stock_a_llegada_resta_las_ventas_del_transito():
    # Creado hoy (2026-08-22), llega el 2026-09-03 -> 12 días de tránsito.
    # Vende 6/día -> en tránsito se consumen 72. Stock actual 40 -> a la
    # llegada quedarían -32 (ya en cero antes de que llegue el envío).
    # Objetivo 3 semanas = 6*21 = 126. Cantidad a enviar = 126 - (-32) = 158.
    ml = _armar_ml(
        items_por_cuenta={"IT": [_item_simple("MLA1", "SKU-A", "INV-1")]},
        stock_por_inventory={"INV-1": {"available_quantity": 40}},
        ventas_por_cuenta={"IT": {"INV-1": {"unidades": 180, "primera": "2026-07-24", "ultima": "2026-08-22"}}},
    )
    ecom = _ecom_simple(stock_full={"SKU-A": 40}, stock_pitec={"SKU-A": 1000})
    tactica = _tactica_simple({"SKU-A": 0})

    resultado = calcular_reposicion_mla(
        ml, ecom, tactica, cuentas=["IT"], dias_ventas=30, semanas_objetivo=3,
        fecha_llegada=date(2026, 9, 3), hoy=date(2026, 8, 22),
    )

    fila = resultado.filas[0]
    assert fila.ventas_diarias == 6.0
    assert fila.stock_a_llegada == -32.0
    assert fila.stock_objetivo == 126.0
    assert fila.cantidad_enviar == 158


def test_fecha_llegada_en_el_pasado_no_da_dias_negativos():
    ml = _armar_ml(
        items_por_cuenta={"IT": [_item_simple("MLA1", "SKU-A", "INV-1")]},
        stock_por_inventory={"INV-1": {"available_quantity": 10}},
        ventas_por_cuenta={"IT": {"INV-1": {"unidades": 30, "primera": "2026-07-20", "ultima": "2026-08-18"}}},
    )
    ecom = _ecom_simple(stock_full={"SKU-A": 10}, stock_pitec={"SKU-A": 100})
    tactica = _tactica_simple({})

    resultado = calcular_reposicion_mla(
        ml, ecom, tactica, cuentas=["IT"], dias_ventas=30, semanas_objetivo=3,
        fecha_llegada=date(2026, 8, 1), hoy=date(2026, 8, 19),
    )

    fila = resultado.filas[0]
    # días_hasta_llegada clampeado a 0 -> stock_a_llegada = stock_full tal cual.
    assert fila.stock_a_llegada == 10.0


def test_reparto_sugerido_prioriza_la_publicacion_que_mas_vende():
    # Mismo SKU, dos publicaciones (distintas cuentas). MLA1 vende más
    # (3/día) que MLA2 (1/día). Cada una pide su objetivo completo, pero el
    # disponible combinado (Ecom+Táctica=50) no alcanza para las dos.
    ml = _armar_ml(
        items_por_cuenta={
            "IT": [_item_simple("MLA1", "SKU-A", "INV-1")],
            "MT": [_item_simple("MLA2", "SKU-A", "INV-2")],
        },
        stock_por_inventory={
            "INV-1": {"available_quantity": 0},
            "INV-2": {"available_quantity": 0},
        },
        ventas_por_cuenta={
            "IT": {"INV-1": {"unidades": 90, "primera": "2026-07-20", "ultima": "2026-08-18"}},
            "MT": {"INV-2": {"unidades": 30, "primera": "2026-07-20", "ultima": "2026-08-18"}},
        },
    )
    ecom = _ecom_simple(stock_full={"SKU-A": 0}, stock_pitec={"SKU-A": 30})
    tactica = _tactica_simple({"SKU-A": 20})

    resultado = calcular_reposicion_mla(
        ml, ecom, tactica, cuentas=["IT", "MT"], dias_ventas=30, semanas_objetivo=3,
        fecha_llegada=date(2026, 8, 19), hoy=date(2026, 8, 19),
    )

    por_item = {f.item_id: f for f in resultado.filas}
    # MLA1: 3/día -> objetivo 63, cantidad_enviar 63. MLA2: 1/día -> objetivo 21.
    assert por_item["MLA1"].ventas_diarias == 3.0
    assert por_item["MLA1"].cantidad_enviar == 63
    assert por_item["MLA2"].cantidad_enviar == 21
    # Disponible combinado = 50. MLA1 (la que más vende) se sirve completa
    # primero -- pero solo hay 50, menos que sus 63 -> se lleva los 50.
    assert por_item["MLA1"].sugerido == 50
    # No queda nada para MLA2.
    assert por_item["MLA2"].sugerido == 0


def test_reparto_sugerido_no_cambia_si_alcanza_para_todas():
    ml = _armar_ml(
        items_por_cuenta={
            "IT": [_item_simple("MLA1", "SKU-A", "INV-1")],
            "MT": [_item_simple("MLA2", "SKU-A", "INV-2")],
        },
        stock_por_inventory={
            "INV-1": {"available_quantity": 0},
            "INV-2": {"available_quantity": 0},
        },
        ventas_por_cuenta={
            "IT": {"INV-1": {"unidades": 90, "primera": "2026-07-20", "ultima": "2026-08-18"}},
            "MT": {"INV-2": {"unidades": 30, "primera": "2026-07-20", "ultima": "2026-08-18"}},
        },
    )
    ecom = _ecom_simple(stock_full={"SKU-A": 0}, stock_pitec={"SKU-A": 1000})
    tactica = _tactica_simple({"SKU-A": 0})

    resultado = calcular_reposicion_mla(
        ml, ecom, tactica, cuentas=["IT", "MT"], dias_ventas=30, semanas_objetivo=3,
        fecha_llegada=date(2026, 8, 19), hoy=date(2026, 8, 19),
    )

    por_item = {f.item_id: f for f in resultado.filas}
    assert por_item["MLA1"].sugerido == por_item["MLA1"].cantidad_enviar == 63
    assert por_item["MLA2"].sugerido == por_item["MLA2"].cantidad_enviar == 21


def test_sin_ventas_en_el_periodo():
    ml = _armar_ml(
        items_por_cuenta={"IT": [_item_simple("MLA1", "SKU-A", "INV-1")]},
        stock_por_inventory={"INV-1": {"available_quantity": 10}},
        ventas_por_cuenta={"IT": {}},
    )
    ecom = _ecom_simple(stock_full={"SKU-A": 10}, stock_pitec={"SKU-A": 0})
    tactica = _tactica_simple({})

    resultado = calcular_reposicion_mla(ml, ecom, tactica, cuentas=["IT"], dias_ventas=30, hoy=date(2026, 8, 19))

    fila = resultado.filas[0]
    assert fila.ventas_periodo == 0
    assert fila.ventas_diarias == 0.0
    assert fila.cantidad_enviar == 0
    assert fila.sugerido == 0
