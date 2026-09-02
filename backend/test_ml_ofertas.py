"""Tests de `ml_ofertas.py` — sin red real. La fórmula (`calcular_margen_oferta`)
se verifica a mano contra un caso calculado con Decimal por fuera del código
(ver el módulo para el porqué de cada base imponible)."""
from decimal import Decimal

import requests

import ml_ofertas
from ml_ofertas import (
    MLOfertasClient,
    MLOfertasEscritura,
    ParametrosMargen,
    activar_en_campana_tradicional,
    calcular_margen_oferta,
    costo_envio_real,
    costo_envio_real_item,
    detectar_skus_sin_oferta,
    estado_job,
    iniciar_job,
    iniciar_job_alertas,
    iniciar_job_costos_envio,
    listar_promociones_item,
    ofertas_activas,
    ofertas_propias_activas,
    resolver_item_para_gestion,
    ventas_por_item,
    ventas_recientes_por_item,
)

_FAKE_TOKEN_FN = lambda cuenta: "FAKE-TOKEN"


class _CostoProviderFalso:
    def __init__(self, costos: dict):
        self._costos = costos

    def obtener(self, sku):
        return self._costos.get(sku)


class _IvaProviderFalso:
    def __init__(self, factores: dict):
        self._factores = factores

    def factor(self, sku):
        return self._factores.get(sku)


def test_formula_canonica_caso_toner():
    # Precio de oferta $40.000, categoría Tóners (15,5%), sin cuotas,
    # costo de producto ya en ARS $15.000. Verificado con Decimal aparte:
    # base_sin_iva=33057.85..., comisión=6200, envío=7000 (tramo 33k-50k),
    # imp.cheque=480 (sobre precio CON IVA), iibb=1652.89 (sobre precio
    # SIN IVA -- corregido 2026-08-27, antes era 2000 sobre precio_oferta),
    # costo_fijo=0 (>=33k), margen=2724.96..., margen%=8,243%.
    params = ParametrosMargen()
    r = calcular_margen_oferta(
        precio_oferta=Decimal(40000), iva_factor=Decimal("1.21"), costo_producto_ars=Decimal(15000),
        domain_id="MLA-TONERS", cuotas_ofrecidas=None, params=params,
    )
    assert r.base_sin_iva == Decimal("33057.85123966942148760330579")
    assert r.comision == Decimal("6200.0")
    assert r.costo_fijo == Decimal(0)
    assert r.cuotas == Decimal(0)
    assert r.envio == Decimal(7000)
    assert r.imp_cheque == Decimal("480.0")
    assert r.iibb == Decimal("1652.89256198347107438016529")
    assert r.margen == Decimal("2724.95867768595041322314050")
    assert r.margen_pct == Decimal("0.08243000000000000000000000011")


def test_comision_general_si_el_dominio_no_esta_en_la_tabla():
    params = ParametrosMargen()
    r = calcular_margen_oferta(
        precio_oferta=Decimal(10000), iva_factor=Decimal("1.21"), costo_producto_ars=Decimal(0),
        domain_id="MLA-ALGO-NO-MAPEADO", cuotas_ofrecidas=None, params=params,
    )
    assert r.comision == Decimal(10000) * params.comision_general / 100


def test_domain_id_none_usa_comision_general():
    params = ParametrosMargen()
    r = calcular_margen_oferta(
        precio_oferta=Decimal(10000), iva_factor=Decimal("1.21"), costo_producto_ars=Decimal(0),
        domain_id=None, cuotas_ofrecidas=None, params=params,
    )
    assert r.comision == Decimal(10000) * params.comision_general / 100


def test_costo_fijo_por_tramo_de_precio():
    params = ParametrosMargen()
    casos = [(Decimal(10000), Decimal(1255)), (Decimal(20000), Decimal(2500)),
             (Decimal(30000), Decimal(3030)), (Decimal(33000), Decimal(0)), (Decimal(50000), Decimal(0))]
    for precio, esperado in casos:
        r = calcular_margen_oferta(precio, Decimal("1.21"), Decimal(0), None, None, params)
        assert r.costo_fijo == esperado, f"precio={precio}"


def test_envio_por_tramo_de_precio():
    # Corregido 2026-08-27: por debajo de $33.000 no hay envío gratis
    # obligado -- el costo es 0, no $9.800 (ver comentario de
    # ENVIO_TRAMOS_DEFAULT en el módulo).
    params = ParametrosMargen()
    casos = [(Decimal(10000), Decimal(0)), (Decimal(33000), Decimal(7000)),
             (Decimal(49999), Decimal(7000)), (Decimal(50000), Decimal(7470))]
    for precio, esperado in casos:
        r = calcular_margen_oferta(precio, Decimal("1.21"), Decimal(0), None, None, params)
        assert r.envio == esperado, f"precio={precio}"


def test_cuotas_suman_solo_si_se_ofrecen():
    params = ParametrosMargen()
    sin_cuotas = calcular_margen_oferta(Decimal(10000), Decimal("1.21"), Decimal(0), None, None, params)
    con_6_cuotas = calcular_margen_oferta(Decimal(10000), Decimal("1.21"), Decimal(0), None, 6, params)
    assert sin_cuotas.cuotas == Decimal(0)
    assert con_6_cuotas.cuotas == Decimal(10000) * Decimal("12.30") / 100
    assert con_6_cuotas.margen < sin_cuotas.margen


def test_cuotas_18_no_existe_devuelve_cero():
    # REQ §1.2.b: "18 cuotas NO existe en ML Argentina hoy" -- si algo pide
    # 18, no hay tasa cargada, no se inventa una -- cae a 0.
    params = ParametrosMargen()
    r = calcular_margen_oferta(Decimal(10000), Decimal("1.21"), Decimal(0), None, 18, params)
    assert r.cuotas == Decimal(0)
    assert 18 not in params.cuotas_pct


def test_flags_en_false_anulan_el_componente():
    params = ParametrosMargen(
        usar_comision=False, usar_costo_fijo=False, usar_cuotas=False,
        usar_envio=False, usar_imp_cheque=False, usar_iibb=False,
    )
    r = calcular_margen_oferta(Decimal(10000), Decimal("1.21"), Decimal(0), "MLA-TONERS", 6, params)
    assert (r.comision, r.costo_fijo, r.cuotas, r.envio, r.imp_cheque, r.iibb) == (Decimal(0),) * 6
    assert r.margen == r.base_sin_iva  # nada se resta salvo el costo (acá 0)


def test_margen_pct_none_si_base_sin_iva_es_cero():
    params = ParametrosMargen()
    r = calcular_margen_oferta(Decimal(0), Decimal("1.21"), Decimal(0), None, None, params)
    assert r.base_sin_iva == Decimal(0)
    assert r.margen_pct is None


def test_mapeo_de_las_15_categorias_del_req():
    # Confirmado uno por uno contra domain_discovery/search en la cuenta
    # real (2026-08-27) -- ver docstring del módulo para la tabla completa.
    from ml_ofertas import COMISION_POR_DOMINIO_DEFAULT
    esperado = {
        "MLA-TONERS": Decimal("15.5"), "MLA-INK_CARTRIDGES": Decimal("15.5"),
        "MLA-VINYL_ROLLS_AND_SHEETS": Decimal("14.3"), "MLA-PRINTER_INKS": Decimal("15.5"),
        "MLA-SCHOOL_AND_OFFICE_PAPERS": Decimal("15.0"), "MLA-3D_PRINTER_FILAMENTS": Decimal("15.5"),
        "MLA-LAPTOP_CASES": Decimal("15.5"), "MLA-HEADPHONES": Decimal("15.5"),
        "MLA-SCREEN_PRINTERS": Decimal("14.5"), "MLA-CONTINUOUS_INK_SYSTEMS": Decimal("15.5"),
        "MLA-PRINTER_RIBBONS": Decimal("15.5"), "MLA-CALCULATORS": Decimal("15.0"),
        "MLA-HATS_AND_CAPS": Decimal("15.5"), "MLA-BINDING_COVERS": Decimal("15.0"),
        "MLA-COIL_BINDING_MACHINES": Decimal("15.0"),
    }
    assert COMISION_POR_DOMINIO_DEFAULT == esperado
    assert len(COMISION_POR_DOMINIO_DEFAULT) == 15


# ── MLOfertasClient + orquestación ──

def _item_ofertas(item_id, sku, domain_id, titulo="T", installments=None):
    return {"id": item_id, "title": titulo, "seller_custom_field": sku, "domain_id": domain_id,
            "installments": installments or {}}


def test_items_de_promocion_pagina_con_search_after():
    paginas = []

    def fake_get(url, params, headers):
        paginas.append(params.get("search_after"))
        assert params["status"] == "started"
        if "search_after" not in params:
            return {"results": [{"id": "MLA1", "status": "started", "price": 100, "original_price": 200}],
                    "paging": {"total": 2, "searchAfter": "TOKEN-1"}}
        if params["search_after"] == "TOKEN-1":
            return {"results": [{"id": "MLA2", "status": "started", "price": 90, "original_price": 180}],
                    "paging": {"total": 2, "searchAfter": "TOKEN-2"}}
        return {"results": [], "paging": {"total": 2, "searchAfter": None}}

    client = MLOfertasClient(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN)
    items = client.items_de_promocion("C-MLA1", "SELLER_CAMPAIGN", "IT")
    assert paginas == [None, "TOKEN-1", "TOKEN-2"]
    assert [i["id"] for i in items] == ["MLA1", "MLA2"]


def test_promociones_item_devuelve_lista_plana_no_envuelta():
    def fake_get(url, params, headers):
        assert url.endswith("/seller-promotions/items/MLA1")
        return [{"type": "PRICE_DISCOUNT", "status": "candidate"}]

    client = MLOfertasClient(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN)
    assert client.promociones_item("MLA1", "IT") == [{"type": "PRICE_DISCOUNT", "status": "candidate"}]


def test_ofertas_activas_toma_la_de_mejor_precio_si_esta_en_dos_campanas():
    def fake_get(url, params, headers):
        if "seller-promotions/users" in url:
            return {"results": [
                {"id": "C-1", "type": "SELLER_CAMPAIGN", "status": "started", "name": "Campaña A"},
                {"id": "C-2", "type": "DEAL", "status": "started", "name": "Campaña B"},
                {"id": "C-3", "type": "SELLER_CAMPAIGN", "status": "pending", "name": "Todavía no arrancó"},
            ]}
        if "seller-promotions/promotions/C-1/items" in url:
            return {"results": [{"id": "MLA1", "status": "started", "price": 9000, "original_price": 10000}],
                    "paging": {"total": 1, "searchAfter": None}}
        if "seller-promotions/promotions/C-2/items" in url:
            return {"results": [{"id": "MLA1", "status": "started", "price": 8500, "original_price": 10000}],
                    "paging": {"total": 1, "searchAfter": None}}
        if "seller-promotions/promotions/C-3" in url:
            raise AssertionError("no debería consultar una campaña con status=pending")
        if url.endswith("/items"):
            return [{"body": _item_ofertas("MLA1", "SKU-A", "MLA-TONERS")}]
        raise AssertionError(url)

    ml = MLOfertasClient(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN)
    costo = _CostoProviderFalso({"SKU-A": Decimal(10)})
    iva = _IvaProviderFalso({"SKU-A": Decimal("1.21")})

    filas, incidencias = ofertas_activas(ml, costo, iva, cuentas=["IT"], tc=Decimal(1000))

    assert len(filas) == 1
    fila = filas[0]
    assert fila.tipo_oferta == "DEAL"  # la de $8500, no la de $9000 de C-1
    assert fila.precio_oferta == Decimal(8500)
    assert fila.margen is not None
    assert incidencias == []


def test_ofertas_activas_marca_incidencia_sin_costo_tactica():
    def fake_get(url, params, headers):
        if "seller-promotions/users" in url:
            return {"results": [{"id": "C-1", "type": "SELLER_CAMPAIGN", "status": "started", "name": "X"}]}
        if "seller-promotions/promotions/C-1/items" in url:
            return {"results": [{"id": "MLA1", "status": "started", "price": 9000, "original_price": 10000}],
                    "paging": {"total": 1, "searchAfter": None}}
        if url.endswith("/items"):
            return [{"body": _item_ofertas("MLA1", "SKU-SIN-COSTO", "MLA-TONERS")}]
        raise AssertionError(url)

    ml = MLOfertasClient(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN)
    costo = _CostoProviderFalso({})  # SKU-SIN-COSTO no está
    iva = _IvaProviderFalso({"SKU-SIN-COSTO": Decimal("1.21")})

    filas, incidencias = ofertas_activas(ml, costo, iva, cuentas=["IT"])

    assert filas[0].margen is None
    assert filas[0].incidencia == "SIN_COSTO_TACTICA"
    assert incidencias == [{"item_id": "MLA1", "cuenta": "IT", "sku": "SKU-SIN-COSTO", "motivo": "SIN_COSTO_TACTICA"}]


def test_ofertas_activas_sin_promociones_activas_no_pide_items():
    def fake_get(url, params, headers):
        if "seller-promotions/users" in url:
            return {"results": [{"id": "C-1", "type": "SELLER_CAMPAIGN", "status": "pending", "name": "X"}]}
        raise AssertionError(f"no debería llamar: {url}")

    ml = MLOfertasClient(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN)
    filas, incidencias = ofertas_activas(ml, _CostoProviderFalso({}), _IvaProviderFalso({}), cuentas=["IT"])
    assert filas == []
    assert incidencias == []


def test_ofertas_activas_results_null_explicito_no_rompe():
    """Bug real 2026-08-27: ML puede devolver `"results": null` (clave
    presente, valor None) en vez de `[]` u omitir la clave -- `.get(key, [])`
    NO cubre ese caso porque el default de `.get` solo aplica si la clave
    falta. Reventaba con "'NoneType' object is not iterable" en la primera
    corrida real contra el backend desplegado."""
    def fake_get(url, params, headers):
        if "seller-promotions/users" in url:
            return {"results": None}
        raise AssertionError(f"no debería llamar: {url}")

    ml = MLOfertasClient(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN)
    filas, incidencias = ofertas_activas(ml, _CostoProviderFalso({}), _IvaProviderFalso({}), cuentas=["IT"])
    assert filas == []
    assert incidencias == []


def test_ofertas_propias_activas_filtra_price_discount_started():
    def fake_get(url, params, headers):
        if url.endswith("/items"):
            return [{"body": _item_ofertas("MLA1", "SKU-A", "MLA-TONERS")},
                    {"body": _item_ofertas("MLA2", "SKU-B", "MLA-TONERS")}]
        if url.endswith("/seller-promotions/items/MLA1"):
            return [{"type": "PRICE_DISCOUNT", "status": "started", "price": 8000, "original_price": 10000}]
        if url.endswith("/seller-promotions/items/MLA2"):
            return [{"type": "PRICE_DISCOUNT", "status": "candidate", "price": 0, "original_price": 10000},
                    {"type": "SELLER_CAMPAIGN", "status": "started", "price": 7000, "original_price": 10000}]
        raise AssertionError(url)

    ml = MLOfertasClient(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN)
    costo = _CostoProviderFalso({"SKU-A": Decimal(5), "SKU-B": Decimal(5)})
    iva = _IvaProviderFalso({"SKU-A": Decimal("1.21"), "SKU-B": Decimal("1.21")})

    filas, incidencias = ofertas_propias_activas(ml, costo, iva, "IT", item_ids=["MLA1", "MLA2"])

    # MLA1 tiene PRICE_DISCOUNT started -> entra. MLA2 tiene PRICE_DISCOUNT
    # candidate (no activo) y una SELLER_CAMPAIGN activa que no es de este
    # tipo -> no entra acá (la cubre ofertas_activas, no esta función).
    assert len(filas) == 1
    assert filas[0].item_id == "MLA1"
    assert filas[0].tipo_oferta == "PRICE_DISCOUNT"


def test_ofertas_propias_activas_un_item_con_error_no_tumba_el_resto():
    """Bug real 2026-08-27: `seller-promotions/items/{id}` devolvió 400
    para un ítem real en medio de un escaneo de ~6.200 -- antes eso hacía
    `raise_for_status()` y tumbaba TODO el job. Un ítem problemático se
    salta (y queda registrado en incidencias), los demás se procesan."""
    def fake_get(url, params, headers):
        if url.endswith("/items"):
            return [{"body": _item_ofertas("MLA1", "SKU-A", "MLA-TONERS")},
                    {"body": _item_ofertas("MLA2", "SKU-B", "MLA-TONERS")}]
        if url.endswith("/seller-promotions/items/MLA1"):
            raise requests.exceptions.HTTPError("400 Client Error: Bad Request")
        if url.endswith("/seller-promotions/items/MLA2"):
            return [{"type": "PRICE_DISCOUNT", "status": "started", "price": 8000, "original_price": 10000}]
        raise AssertionError(url)

    ml = MLOfertasClient(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN)
    costo = _CostoProviderFalso({"SKU-A": Decimal(5), "SKU-B": Decimal(5)})
    iva = _IvaProviderFalso({"SKU-A": Decimal("1.21"), "SKU-B": Decimal("1.21")})

    filas, incidencias = ofertas_propias_activas(ml, costo, iva, "IT", item_ids=["MLA1", "MLA2"])

    assert len(filas) == 1 and filas[0].item_id == "MLA2"
    assert any(i["item_id"] == "MLA1" and "ERROR_ML_ITEM" in i["motivo"] for i in incidencias)


def test_ofertas_propias_activas_reporta_progreso_en_las_dos_fases():
    """Bug real 2026-08-27: `detalle_items_ofertas` (la fase "catalogo",
    hasta ~310 llamadas para un escaneo completo) corría entera SIN
    reportar nada -- Maxx la veía como "corriendo... (0 líneas)" congelado
    antes de que arrancara la fase "promociones", que sí reportaba."""
    def fake_get(url, params, headers):
        if url.endswith("/items"):
            return [{"body": _item_ofertas("MLA1", "SKU-A", "MLA-TONERS")},
                    {"body": _item_ofertas("MLA2", "SKU-B", "MLA-TONERS")}]
        if url.startswith("https://api.mercadolibre.com/seller-promotions/items/"):
            return []
        raise AssertionError(url)

    ml = MLOfertasClient(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN)
    llamadas = []
    ofertas_propias_activas(ml, _CostoProviderFalso({}), _IvaProviderFalso({}), "IT",
                             item_ids=["MLA1", "MLA2"], progreso_cb=lambda a, t, f: llamadas.append((a, t, f)))

    fases = [f for (_, _, f) in llamadas]
    assert "catalogo" in fases and "promociones" in fases
    assert llamadas[0] == (0, 2, "catalogo")
    assert llamadas[-1] == (2, 2, "promociones")


# ── Fase 2 — detección de SKUs sin oferta ──
# El wrapper de job (`iniciar_job`/`iniciar_job_alertas`) no se testea acá,
# igual que en ml_full.py/ml_reposicion.py: es pegamento fino que instancia
# clientes/providers reales (red + Táctica), se valida corriendo el job de
# verdad contra el backend desplegado, no con fakes.

def test_ventas_por_item_pagina_por_offset_y_suma_cantidades():
    llamadas = []

    def fake_get(url, params, headers):
        llamadas.append(params["offset"])
        if params["offset"] == 0:
            return {"results": [
                {"order_items": [{"item": {"id": "MLA1"}, "quantity": 2}]},
                {"order_items": [{"item": {"id": "MLA1"}, "quantity": 1}, {"item": {"id": "MLA2"}, "quantity": 3}]},
            ], "paging": {"total": 3}}
        return {"results": [
            {"order_items": [{"item": {"id": "MLA2"}, "quantity": 1}]},
        ], "paging": {"total": 3}}

    ml = MLOfertasClient(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN)
    ventas = ventas_por_item(ml, "IT", "2026-07-01T00:00:00.000-00:00", "2026-08-01T00:00:00.000-00:00")

    assert ventas == {"MLA1": 3, "MLA2": 4}
    assert llamadas == [0, 2]


# ── ventas_recientes_por_item / costo_envio_real / costo_envio_real_item ──

def test_ventas_recientes_por_item_se_queda_con_la_orden_mas_nueva():
    def fake_get(url, params, headers):
        return {"results": [
            {"date_closed": "2026-08-01T10:00:00Z", "shipping": {"id": 111},
             "order_items": [{"item": {"id": "MLA1"}}]},
            {"date_closed": "2026-08-05T10:00:00Z", "shipping": {"id": 222},
             "order_items": [{"item": {"id": "MLA1"}}]},
            {"date_closed": "2026-08-03T10:00:00Z", "shipping": {"id": 333},
             "order_items": [{"item": {"id": "MLA2"}}]},
        ], "paging": {"total": 3}}

    ml = MLOfertasClient(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN)
    ultimas = ventas_recientes_por_item(ml, "IT", "2026-08-01T00:00:00.000-00:00", "2026-08-06T00:00:00.000-00:00")

    assert ultimas["MLA1"]["shipping_id"] == 222  # la del 5/8, no la del 1/8
    assert ultimas["MLA2"]["shipping_id"] == 333


def test_ventas_recientes_por_item_ignora_ordenes_sin_shipping():
    def fake_get(url, params, headers):
        return {"results": [
            {"date_closed": "2026-08-01T10:00:00Z", "shipping": {},
             "order_items": [{"item": {"id": "MLA1"}}]},
        ], "paging": {"total": 1}}

    ml = MLOfertasClient(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN)
    ultimas = ventas_recientes_por_item(ml, "IT", "2026-08-01T00:00:00.000-00:00", "2026-08-06T00:00:00.000-00:00")

    assert ultimas == {}


def test_costo_envio_real_envio_gratis_usa_list_cost():
    # Caso real confirmado en vivo 2026-09-01 (MLA680197251, orden
    # 2000018227607384): Maxx cruzó el detalle real de la venta y
    # coincidió centavo a centavo con list_cost ($8.890).
    def fake_get(url, params, headers):
        assert headers.get("x-format-new") == "true"
        return {"lead_time": {"cost_type": "free", "list_cost": 8890.0}}

    ml = MLOfertasClient(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN)
    r = costo_envio_real(ml, "IT", 47907342840)

    assert r == {"cost_type": "free", "costo_envio_real": 8890.0}


def test_costo_envio_real_comprador_pago_no_hay_costo():
    def fake_get(url, params, headers):
        return {"lead_time": {"cost_type": "charged", "cost": 8990.0, "list_cost": 8990.0}}

    ml = MLOfertasClient(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN)
    r = costo_envio_real(ml, "IT", 47907447494)

    assert r == {"cost_type": "charged", "costo_envio_real": 0.0}


def test_costo_envio_real_item_usa_la_cache_congelada():
    ml_ofertas._ultima_venta_cache.clear()
    ml_ofertas._ultima_venta_cache["MLA1"] = {
        "fecha": "2026-08-05T10:00:00Z", "shipping_id": 222, "orden_id": 999, "cuenta": "IT",
    }
    try:
        def fake_get(url, params, headers):
            assert "222" in url
            return {"lead_time": {"cost_type": "free", "list_cost": 5000.0}}

        ml = MLOfertasClient(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN)
        r = costo_envio_real_item(ml, "MLA1", "IT")

        assert r["costo_envio_real"] == 5000.0
        assert r["orden_id"] == 999
    finally:
        ml_ofertas._ultima_venta_cache.clear()


def test_costo_envio_real_item_none_si_no_esta_en_cache():
    ml_ofertas._ultima_venta_cache.clear()
    ml = MLOfertasClient(get_fn=lambda u, p, h: {}, token_fn=_FAKE_TOKEN_FN)
    assert costo_envio_real_item(ml, "MLA-SIN-VENTAS", "IT") is None


def test_iniciar_job_costos_envio_congela_la_cache():
    ml_ofertas._ultima_venta_cache.clear()
    ml_ofertas._jobs.clear()

    def fake_get(url, params, headers):
        return {"results": [
            {"date_closed": "2026-08-05T10:00:00Z", "shipping": {"id": 222},
             "order_items": [{"item": {"id": "MLA1"}}]},
        ], "paging": {"total": 1}}

    import ml_full as ml_full_mod
    original = ml_full_mod.MLFullClient
    class _MLFullFalso(original):
        def __init__(self):
            super().__init__(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN)
    ml_ofertas.MLFullClient = _MLFullFalso
    try:
        iniciar_job_costos_envio("job-1", cuentas=["IT"], dias=10)
        assert ml_ofertas._ultima_venta_cache["MLA1"]["shipping_id"] == 222
        assert estado_job("job-1")["status"] == "done"
    finally:
        ml_ofertas.MLFullClient = original
        ml_ofertas._ultima_venta_cache.clear()


def test_detectar_skus_sin_oferta_filtra_por_ventas_stock_y_oferta_activa():
    def fake_get(url, params, headers):
        if "orders/search" in url:
            return {"results": [
                {"order_items": [{"item": {"id": "MLA1"}, "quantity": 6}]},
                {"order_items": [{"item": {"id": "MLA2"}, "quantity": 10}]},
                {"order_items": [{"item": {"id": "MLA3"}, "quantity": 1}]},
            ], "paging": {"total": 3}}
        if url.endswith("/items"):
            return [
                {"body": {"id": "MLA2", "title": "T2", "seller_custom_field": "SKU-2", "available_quantity": 5}},
            ]
        raise AssertionError(url)

    ml = MLOfertasClient(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN)
    ml.items_activos = lambda cuenta: ["MLA1", "MLA2", "MLA3"]

    candidatos = detectar_skus_sin_oferta(ml, "IT", item_ids_con_oferta={"MLA1"}, min_ventas=5)

    # MLA1 tiene >= min_ventas pero ya está en oferta -> afuera.
    # MLA3 no llega a min_ventas -> afuera. Solo MLA2 califica.
    assert len(candidatos) == 1
    assert candidatos[0].item_id == "MLA2"
    assert candidatos[0].sku == "SKU-2"
    assert candidatos[0].ventas_periodo == 10
    assert candidatos[0].stock == 5


# ── Fase 3 — escritura ──

def _fake_put(url, headers, body):
    _fake_put.calls.append((url, headers, body))
    return _fake_put.responder(url, headers, body)
_fake_put.calls = []


def _fake_delete(url, params, headers):
    _fake_delete.calls.append((url, params, headers))
    return _fake_delete.responder(url, params, headers)
_fake_delete.calls = []


def _fake_get_verificacion(url, params, headers):
    _fake_get_verificacion.calls.append((url, params, headers))
    return _fake_get_verificacion.responder(url, params, headers)
_fake_get_verificacion.calls = []


def test_activar_oferta_propia_ok_con_tachado():
    """El PUT ya no alcanza como prueba de éxito (ver docstring del
    método: ML puede devolver 200 e ignorar el cambio) -- hace falta que
    el GET de verificación aparte confirme el precio y el tachado reales."""
    _fake_put.calls = []
    _fake_put.responder = lambda url, headers, body: {"id": "MLA1", "price": body["price"], "original_price": body["original_price"]}
    _fake_get_verificacion.calls = []
    _fake_get_verificacion.responder = lambda url, params, headers: {"id": "MLA1", "price": 9000.0, "original_price": 12000.0}
    ml = MLOfertasEscritura(get_fn=_fake_get_verificacion, token_fn=_FAKE_TOKEN_FN, put_fn=_fake_put)

    r = ml.activar_oferta_propia("MLA1", "IT", Decimal(9000), Decimal(12000))

    assert r == {"ok": True, "modo": "con_tachado"}
    assert _fake_put.calls[0][0] == "https://api.mercadolibre.com/items/MLA1"
    assert _fake_put.calls[0][2] == {"price": 9000.0, "original_price": 12000.0}
    assert len(_fake_get_verificacion.calls) == 1  # se verificó con un GET aparte, no se confió en el PUT


def test_activar_oferta_propia_ml_acepta_pero_no_aplica_tachado():
    """Caso real 2026-08-27 (MLA875537547): ML devuelve 200 con `id`
    (aceptó el PUT) pero el GET de verificación no refleja el tachado
    pedido -- antes esto se reportaba como éxito completo sin avisar nada."""
    _fake_put.calls = []
    _fake_put.responder = lambda url, headers, body: {"id": "MLA1", "price": body["price"], "original_price": body["original_price"]}
    _fake_get_verificacion.responder = lambda url, params, headers: {"id": "MLA1", "price": 9000.0, "original_price": None}
    ml = MLOfertasEscritura(get_fn=_fake_get_verificacion, token_fn=_FAKE_TOKEN_FN, put_fn=_fake_put)

    r = ml.activar_oferta_propia("MLA1", "IT", Decimal(9000), Decimal(12000))

    assert r["ok"] is True
    assert r["modo"] == "sin_tachado_ml"
    assert "Precio real confirmado" in r["aviso"]


def test_activar_oferta_propia_fallback_has_bids():
    _fake_put.calls = []
    respuestas = [
        {"error": "validation_error", "message": "Item has_bids, cannot update original_price"},
        {"id": "MLA1", "price": 12000.0},
    ]
    _fake_put.responder = lambda url, headers, body: respuestas.pop(0)
    _fake_get_verificacion.responder = lambda url, params, headers: {"id": "MLA1", "price": 12000.0, "original_price": None}
    ml = MLOfertasEscritura(get_fn=_fake_get_verificacion, token_fn=_FAKE_TOKEN_FN, put_fn=_fake_put)

    r = ml.activar_oferta_propia("MLA1", "IT", Decimal(9000), Decimal(12000))

    assert r["ok"] is True
    assert r["modo"] == "sin_tachado_bids"
    assert "Item has_bids, cannot update original_price" in r["aviso"]
    assert len(_fake_put.calls) == 2
    assert _fake_put.calls[1][2] == {"price": 12000.0, "original_price": 12000.0}  # segundo intento, sin descuento real (no "solo price": eso da 400 directo)


def test_activar_oferta_propia_fallback_has_bids_pero_tampoco_se_aplica():
    """Caso real 2026-08-27 (MLA852181648, publicación con precio
    mayorista): ML devolvió el mismo error "has_bids", pero el GET de
    verificación muestra que el precio TAMPOCO se aplicó -- antes esto se
    reportaba como éxito solo por tener `id` en la respuesta del PUT."""
    _fake_put.calls = []
    respuestas = [
        {"error": "validation_error", "message": "has_bids"},
        {"id": "MLA1", "price": 12000.0},  # el PUT hace eco del valor pedido, pero no significa que se aplicó de verdad
    ]
    _fake_put.responder = lambda url, headers, body: respuestas.pop(0)
    _fake_get_verificacion.responder = lambda url, params, headers: {"id": "MLA1", "price": 9000.0, "original_price": None}  # sigue en el precio viejo
    ml = MLOfertasEscritura(get_fn=_fake_get_verificacion, token_fn=_FAKE_TOKEN_FN, put_fn=_fake_put)

    r = ml.activar_oferta_propia("MLA1", "IT", Decimal(9000), Decimal(12000))

    assert r["ok"] is False
    assert "tampoco confirma el precio base" in r["error"]


def test_activar_oferta_propia_error_no_recuperable():
    _fake_put.calls = []
    _fake_put.responder = lambda url, headers, body: {"error": "validation_error", "message": "invalid price"}
    ml = MLOfertasEscritura(get_fn=None, token_fn=_FAKE_TOKEN_FN, put_fn=_fake_put)

    r = ml.activar_oferta_propia("MLA1", "IT", Decimal(9000), Decimal(12000))

    assert r == {"ok": False, "error": "invalid price"}


def test_sacar_de_promocion_price_discount_no_manda_promotion_id():
    _fake_delete.calls = []
    _fake_delete.responder = lambda url, params, headers: {"successful_ids": ["MLA1"]}
    ml = MLOfertasEscritura(get_fn=None, token_fn=_FAKE_TOKEN_FN, delete_fn=_fake_delete)

    r = ml.sacar_de_promocion("MLA1", "IT", "PRICE_DISCOUNT")

    assert r == {"ok": True, "successful_ids": ["MLA1"]}
    url, params, headers = _fake_delete.calls[0]
    assert url == "https://api.mercadolibre.com/seller-promotions/items/MLA1"
    assert params == {"app_version": "v2", "promotion_type": "PRICE_DISCOUNT"}


def test_sacar_de_promocion_campana_manda_promotion_id():
    _fake_delete.calls = []
    _fake_delete.responder = lambda url, params, headers: {"successful_ids": ["MLA1"]}
    ml = MLOfertasEscritura(get_fn=None, token_fn=_FAKE_TOKEN_FN, delete_fn=_fake_delete)

    r = ml.sacar_de_promocion("MLA1", "IT", "SELLER_CAMPAIGN", promotion_id="C-1")

    assert r["ok"] is True
    params = _fake_delete.calls[0][1]
    assert params == {"app_version": "v2", "promotion_type": "SELLER_CAMPAIGN", "promotion_id": "C-1"}


def test_sacar_de_promocion_error():
    _fake_delete.calls = []
    _fake_delete.responder = lambda url, params, headers: {"errors": [{"error": "promotion_not_found"}]}
    ml = MLOfertasEscritura(get_fn=None, token_fn=_FAKE_TOKEN_FN, delete_fn=_fake_delete)

    r = ml.sacar_de_promocion("MLA1", "IT", "SELLER_CAMPAIGN", promotion_id="C-999")

    assert r == {"ok": False, "error": "promotion_not_found"}


def _fake_post(url, headers, body):
    _fake_post.calls.append((url, headers, body))
    return _fake_post.responder(url, headers, body)
_fake_post.calls = []


def test_fijar_precio_base_ok():
    _fake_put.calls = []
    _fake_put.responder = lambda url, headers, body: {"id": "MLA1", "price": body["price"]}
    fake_get = lambda url, params, headers: {"id": "MLA1", "price": 12000.0}
    ml = MLOfertasEscritura(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN, put_fn=_fake_put)

    r = ml.fijar_precio_base("MLA1", "IT", Decimal(12000))

    assert r == {"ok": True}
    # Corregido 2026-08-31: solo `price`, sin `original_price` -- mandar
    # los dos juntos era la causa real del rechazo `field_not_updatable`.
    assert _fake_put.calls[0][2] == {"price": 12000.0}


def test_fijar_precio_base_no_confirma_por_get():
    _fake_put.responder = lambda url, headers, body: {"id": "MLA1", "price": body["price"]}
    fake_get = lambda url, params, headers: {"id": "MLA1", "price": 9000.0}  # no cambió
    ml = MLOfertasEscritura(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN, put_fn=_fake_put)

    r = ml.fijar_precio_base("MLA1", "IT", Decimal(12000))

    assert r["ok"] is False
    assert "no confirma el precio base" in r["error"]


def test_fijar_precio_base_has_bids_no_reintenta():
    """Caso real 2026-08-28 (MLA627267951): ML rechaza con `has_bids`
    igual que en activar_oferta_propia, pero acá no hay una combinación
    de campos distinta para reintentar (ya se mandaron price+
    original_price juntos) -- se devuelve un error claro, sin reintento
    inútil ni texto crudo de ML sin explicar. Sin tag de mayorista -> no
    se afirma esa causa (Maxx marcó bien 2026-08-28 que la hipótesis de
    "ofertas pendientes" no explica que ML sí deje editar a mano en ML)."""
    _fake_put.responder = lambda url, headers, body: {
        "error": "validation_error",
        "message": "Cannot update item MLA627267951 [status:active, has_bids:true]",
    }
    fake_get = lambda url, params, headers: {"id": "MLA627267951", "tags": ["good_quality_picture"]}
    ml = MLOfertasEscritura(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN, put_fn=_fake_put)

    r = ml.fijar_precio_base("MLA627267951", "IT", Decimal(15811))

    assert r["ok"] is False
    assert "has_bids:true" in r["error"]
    # Sin `cause` en la respuesta (no se puede confirmar `field_not_updatable`)
    # y sin tag de mayorista -> cae al fallback genérico, que no afirma
    # ninguna causa ya confirmada (ver `_explicar_has_bids`). El texto
    # exacto de este assert quedó desactualizado de un refactor anterior
    # (afirmaba "ninguna de las dos hipótesis", frase que ya no existe en
    # el código) -- corregido 2026-08-31 para reflejar el mensaje real.
    assert "ninguna causa ya confirmada explica esto" in r["error"]
    assert "buying_mode=" in r["error"]  # diagnóstico crudo para no seguir adivinando a ciegas


def test_fijar_precio_base_has_bids_con_tag_mayorista():
    """Caso real 2026-08-28 (MLA852181648, la misma publicación con
    precio mayorista de antes en la sesión): el tag `standard_price_by_
    quantity` confirma que la causa más probable es esa, no pujas ni
    ofertas pendientes."""
    _fake_put.responder = lambda url, headers, body: {
        "error": "validation_error",
        "message": "Cannot update item MLA852181648 [status:active, has_bids:true]",
    }
    fake_get = lambda url, params, headers: {"id": "MLA852181648", "tags": ["standard_price_by_quantity"]}
    ml = MLOfertasEscritura(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN, put_fn=_fake_put)

    r = ml.fijar_precio_base("MLA852181648", "IT", Decimal(17819))

    assert r["ok"] is False
    assert "precio mayorista/por cantidad" in r["error"]
    assert "standard_price_by_quantity" in r["error"]


def test_meter_en_campana_ok():
    _fake_post.calls = []
    _fake_post.responder = lambda url, headers, body: {"price": 9000.0, "original_price": 12000.0}
    ml = MLOfertasEscritura(get_fn=None, token_fn=_FAKE_TOKEN_FN, post_fn=_fake_post)

    r = ml.meter_en_campana("MLA1", "IT", "C-1", Decimal(9000))

    assert r == {"ok": True, "price": 9000.0, "original_price": 12000.0}
    # Corregido 2026-08-31: faltaba `?app_version=v2` -- confirmado en vivo
    # que sin este parámetro ML responde "Invalid app_version".
    assert _fake_post.calls[0][0] == "https://api.mercadolibre.com/seller-promotions/items/MLA1?app_version=v2"
    assert _fake_post.calls[0][2] == {"promotion_id": "C-1", "promotion_type": "SELLER_CAMPAIGN", "deal_price": 9000.0}


def test_meter_en_campana_error():
    _fake_post.responder = lambda url, headers, body: {"message": "New deal_price must be lower than current deal_price"}
    ml = MLOfertasEscritura(get_fn=None, token_fn=_FAKE_TOKEN_FN, post_fn=_fake_post)

    r = ml.meter_en_campana("MLA1", "IT", "C-1", Decimal(9000))

    assert r == {"ok": False, "error": "New deal_price must be lower than current deal_price"}


def test_activar_en_campana_tradicional_flujo_completo():
    """Fórmula corregida 2026-08-28 (bug real, MLA627267951: 25% de
    descuento sobre $16.865 en Promociones de ML dio $12.648,75, NO
    precio*1.25): tachado = precio_pm / (1 - descuento_pct/100), no
    precio_pm * (1 + descuento_pct/100) -- 10000/0.75 = 13333, no 12500."""
    def fake_get(url, params, headers):
        if "seller-promotions/users" in url:
            return {"results": [{"id": "C-1", "type": "SELLER_CAMPAIGN", "status": "started", "name": "Oferta Tradicional Agosto"}]}
        if url.endswith("/seller-promotions/items/MLA1"):
            return []  # sin candidato para C-1 -- sin rango, no hay ajuste que hacer
        if url.endswith("/items/MLA1"):
            return {"id": "MLA1", "price": 13333.0}
        raise AssertionError(url)

    _fake_put.calls = []
    _fake_put.responder = lambda url, headers, body: {"id": "MLA1", "price": body["price"]}
    _fake_post.calls = []
    _fake_post.responder = lambda url, headers, body: {"price": 10000.0, "original_price": 13333.0}

    ml = MLOfertasEscritura(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN, put_fn=_fake_put, post_fn=_fake_post)

    r = activar_en_campana_tradicional(ml, "IT", "MLA1", Decimal(10000))

    assert r["ok"] is True
    assert r["promotion_id"] == "C-1"
    assert r["nombre_campana"] == "Oferta Tradicional Agosto"
    assert r["precio_tachado_pedido"] == 13333.0  # 10000 / 0.75
    assert "aviso" not in r  # sin candidato en el rango, no hubo que ajustar el % estándar
    assert _fake_put.calls[0][2] == {"price": 13333.0}  # sin original_price, ver fijar_precio_base
    assert _fake_post.calls[0][2] == {"promotion_id": "C-1", "promotion_type": "SELLER_CAMPAIGN", "deal_price": 10000.0}


def test_activar_en_campana_tradicional_sin_campana_activa():
    fake_get = lambda url, params, headers: {"results": []}
    ml = MLOfertasEscritura(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN)

    r = activar_en_campana_tradicional(ml, "IT", "MLA1", Decimal(10000))

    assert r["ok"] is False
    assert "ninguna campaña propia" in r["error"]


def test_activar_en_campana_tradicional_no_sigue_si_falla_precio_base():
    fake_get_campana = lambda url, params, headers: {"results": [{"id": "C-1", "type": "SELLER_CAMPAIGN", "status": "started", "name": "Oferta Tradicional X"}]}
    _fake_put.responder = lambda url, headers, body: {"error": "validation_error", "message": "invalid price"}
    _fake_post.calls = []

    ml = MLOfertasEscritura(get_fn=fake_get_campana, token_fn=_FAKE_TOKEN_FN, put_fn=_fake_put, post_fn=_fake_post)

    r = activar_en_campana_tradicional(ml, "IT", "MLA1", Decimal(10000))

    assert r["ok"] is False
    assert "No se pudo fijar el precio base" in r["error"]
    assert _fake_post.calls == []  # no se intentó enrolar si el precio base falló


def test_activar_en_campana_tradicional_infla_tachado_si_ml_exige_mas_descuento():
    """El 25% estándar (tachado $13.333 para precio_pm=$10.000) no le
    alcanza a ML para esta campaña sobre este ítem -- `max_discounted_price`
    (leído DESPUÉS de fijar el tachado estándar) da $9.500, por debajo de
    los $10.000 que precio_pm tiene que valer. Se recalcula el tachado
    necesario ($14.035, ver cálculo exacto con Decimal) para que precio_pm
    siga siendo el precio final -- nunca se toca precio_pm -- y se avisa
    (no bloqueante) que quedó a ~28.7%, no al 25% de siempre."""
    # Estado mutable: `fijar_precio_base` verifica con un GET aparte
    # después de cada PUT (nunca confía en el eco) -- acá se llama DOS
    # veces con precios distintos (13333, después 14035), así que el fake
    # de items/MLA1 tiene que reflejar el último precio puesto, no un
    # valor fijo, para que ambas verificaciones puedan pasar.
    estado_item = {"price": 20000.0}  # precio previo, antes de esta operación

    def fake_get(url, params, headers):
        if "seller-promotions/users" in url:
            return {"results": [{"id": "C-1", "type": "SELLER_CAMPAIGN", "status": "started", "name": "Oferta Tradicional Agosto"}]}
        if url.endswith("/seller-promotions/items/MLA1"):
            return [{"id": "C-1", "type": "SELLER_CAMPAIGN", "min_discounted_price": 2000.0, "max_discounted_price": 9500.0}]
        if url.endswith("/items/MLA1"):
            return {"id": "MLA1", "price": estado_item["price"]}
        raise AssertionError(url)

    def fake_put(url, headers, body):
        estado_item["price"] = body["price"]
        return {"id": "MLA1", "price": body["price"]}

    _fake_put.calls = []
    _fake_put.responder = fake_put
    _fake_post.calls = []
    _fake_post.responder = lambda url, headers, body: {"price": 10000.0, "original_price": 14035.0}

    ml = MLOfertasEscritura(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN, put_fn=_fake_put, post_fn=_fake_post)

    r = activar_en_campana_tradicional(ml, "IT", "MLA1", Decimal(10000))

    assert r["ok"] is True
    assert r["precio_tachado_pedido"] == 14035.0  # no 13333 -- el 25% estándar no alcanzaba
    assert "28.7%" in r["aviso"]
    assert "no al 25%" in r["aviso"]
    assert "$10000" in r["aviso"] or "10000" in r["aviso"]  # precio final, sin cambios
    # dos PUT de precio: el estándar (13333) y el ajustado (14035) -- nunca uno solo.
    assert [c[2]["price"] for c in _fake_put.calls] == [13333.0, 14035.0]
    assert _fake_post.calls[0][2] == {"promotion_id": "C-1", "promotion_type": "SELLER_CAMPAIGN", "deal_price": 10000.0}


def test_activar_en_campana_tradicional_revierte_si_precio_pm_bajo_el_piso():
    """precio_pm ($10.000) queda por DEBAJO de `min_discounted_price`
    ($15.000) -- inflar el tachado no mueve el piso, así que no hay ajuste
    posible. Se revierte el precio al que tenía antes ($20.000) y se corta
    sin intentar `meter_en_campana`."""
    # Mismo motivo que en el test anterior: el fake de items/MLA1 tiene
    # que reflejar el último precio puesto (13333 al fijar el tachado
    # estándar, después 20000 al revertir), no un valor fijo.
    estado_item = {"price": 20000.0}

    def fake_get(url, params, headers):
        if "seller-promotions/users" in url:
            return {"results": [{"id": "C-1", "type": "SELLER_CAMPAIGN", "status": "started", "name": "Oferta Tradicional X"}]}
        if url.endswith("/seller-promotions/items/MLA1"):
            return [{"id": "C-1", "type": "SELLER_CAMPAIGN", "min_discounted_price": 15000.0, "max_discounted_price": 19000.0}]
        if url.endswith("/items/MLA1"):
            return {"id": "MLA1", "price": estado_item["price"]}
        raise AssertionError(url)

    def fake_put(url, headers, body):
        estado_item["price"] = body["price"]
        return {"id": "MLA1", "price": body["price"]}

    _fake_put.calls = []
    _fake_put.responder = fake_put
    _fake_post.calls = []

    ml = MLOfertasEscritura(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN, put_fn=_fake_put, post_fn=_fake_post)

    r = activar_en_campana_tradicional(ml, "IT", "MLA1", Decimal(10000))

    assert r["ok"] is False
    assert "por DEBAJO del piso" in r["error"]
    assert "Precio restaurado a $20000.0" in r["error"]
    assert r["min_discounted_price"] == 15000.0
    assert _fake_post.calls == []  # nunca se intentó enrolar
    assert _fake_put.calls[-1][2] == {"price": 20000.0}  # reversión al precio previo


def test_activar_en_campana_tradicional_corta_por_challenge_seguridad():
    """Si ML devuelve un mensaje que huele a verificación de seguridad
    (QR/facial, heurística no confirmada contra la API real -- ver
    docstring de `_es_challenge_seguridad`), se revierte lo tocado y se
    corta con `requiere_verificacion_manual` -- nunca se reintenta solo."""
    def fake_get(url, params, headers):
        if "seller-promotions/users" in url:
            return {"results": [{"id": "C-1", "type": "SELLER_CAMPAIGN", "status": "started", "name": "Oferta Tradicional X"}]}
        if url.endswith("/items/MLA1"):
            return {"id": "MLA1", "price": 20000.0}
        raise AssertionError(url)

    def fake_put(url, headers, body):
        if body["price"] == 20000.0:
            return {"id": "MLA1", "price": 20000.0}  # la reversión sí anda
        return {"error": "forbidden", "message": "Additional security challenge required: TOTP verification"}

    _fake_put.calls = []
    _fake_put.responder = fake_put
    _fake_post.calls = []

    ml = MLOfertasEscritura(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN, put_fn=_fake_put, post_fn=_fake_post)

    r = activar_en_campana_tradicional(ml, "IT", "MLA1", Decimal(10000))

    assert r["ok"] is False
    assert r["requiere_verificacion_manual"] is True
    assert "verificación de seguridad" in r["error"]
    assert "Precio restaurado a $20000.0" in r["error"]
    assert _fake_post.calls == []  # nunca se intentó meter en campaña


def test_activar_en_campana_tradicional_revierte_en_primer_rechazo_por_credibilidad():
    """Caso real 2026-09-01 (MLA1625270713 y MLA751588750): la escalada de
    tachado (30->70%, sacada este mismo día) nunca lograba nada -- ML
    rechazaba por `ERROR_CREDIBILITY_DISCOUNTED_PRICE` en los dos ítems
    reales pasara lo que pasara con el tachado. Ahora un solo rechazo por
    credibilidad revierte de una, sin insistir con más intentos."""
    estado_item = {"price": 20000.0}
    intentos_post = {"n": 0}

    def fake_get(url, params, headers):
        if "seller-promotions/users" in url:
            return {"results": [{"id": "C-1", "type": "SELLER_CAMPAIGN", "status": "started", "name": "Oferta Tradicional X"}]}
        if url.endswith("/seller-promotions/items/MLA1"):
            return []  # sin candidato en ninguna lectura -- sin techo para avisar
        if url.endswith("/items/MLA1"):
            return {"id": "MLA1", "price": estado_item["price"]}
        raise AssertionError(url)

    def fake_put(url, headers, body):
        estado_item["price"] = body["price"]
        return {"id": "MLA1", "price": body["price"]}

    def fake_post(url, headers, body):
        intentos_post["n"] += 1
        return {"message": "Errors: ERROR_CREDIBILITY_DISCOUNTED_PRICE - The discounted price is not credible."}

    _fake_put.calls = []
    _fake_put.responder = fake_put
    _fake_post.calls = []
    _fake_post.responder = fake_post

    ml = MLOfertasEscritura(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN, put_fn=_fake_put, post_fn=_fake_post)

    r = activar_en_campana_tradicional(ml, "IT", "MLA1", Decimal(10000))

    assert r["ok"] is False
    assert intentos_post["n"] == 1  # un solo intento -- nada de escalar
    assert "rechazo de credibilidad" in r["error"]
    assert "escaló" not in r["error"] and "escalando" not in r["error"]
    assert estado_item["price"] == 20000.0  # revertido al precio previo
    assert r["precio_pm"] == 10000.0
    assert r["techo_acreditado_ml"] is None  # sin candidato disponible, no hay techo que avisar


def test_activar_en_campana_tradicional_credibilidad_informa_techo_real():
    """Cuando SÍ se puede releer el rango después de revertir, el aviso
    tiene que traer el techo real que acredita ML -- no un número
    inventado. `promociones_item` se llama dos veces: la del paso 2
    (antes de intentar, sin candidato -- no ajusta nada) y esta nueva,
    después de la reversión, con el precio YA restaurado."""
    estado_item = {"price": 20000.0}
    llamadas_rango = {"n": 0}

    def fake_get(url, params, headers):
        if "seller-promotions/users" in url:
            return {"results": [{"id": "C-1", "type": "SELLER_CAMPAIGN", "status": "started", "name": "Oferta Tradicional X"}]}
        if url.endswith("/seller-promotions/items/MLA1"):
            llamadas_rango["n"] += 1
            if llamadas_rango["n"] == 1:
                return []  # paso 2: sin candidato, no ajusta el tachado estándar
            return [{"id": "C-1", "max_discounted_price": 15000.0}]  # después de revertir
        if url.endswith("/items/MLA1"):
            return {"id": "MLA1", "price": estado_item["price"]}
        raise AssertionError(url)

    def fake_put(url, headers, body):
        estado_item["price"] = body["price"]
        return {"id": "MLA1", "price": body["price"]}

    def fake_post(url, headers, body):
        return {"message": "Errors: ERROR_CREDIBILITY_DISCOUNTED_PRICE - The discounted price is not credible."}

    _fake_put.calls = []
    _fake_put.responder = fake_put
    _fake_post.calls = []
    _fake_post.responder = fake_post

    ml = MLOfertasEscritura(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN, put_fn=_fake_put, post_fn=_fake_post)

    r = activar_en_campana_tradicional(ml, "IT", "MLA1", Decimal(10000))

    assert r["ok"] is False
    assert r["techo_acreditado_ml"] == 15000.0
    assert "$15000" in r["error"]
    assert "25.0%" in r["error"]  # 1 - 15000/20000 = 25% de descuento real mínimo


def test_activar_en_campana_tradicional_no_escala_si_rechazo_no_es_credibilidad():
    """Si ML rechaza `meter_en_campana` por otro motivo (no de
    credibilidad), escalar el % no lo va a arreglar -- se revierte y
    corta en el primer intento, sin probar 30/35/40..."""
    estado_item = {"price": 20000.0}

    def fake_get(url, params, headers):
        if "seller-promotions/users" in url:
            return {"results": [{"id": "C-1", "type": "SELLER_CAMPAIGN", "status": "started", "name": "Oferta Tradicional X"}]}
        if url.endswith("/seller-promotions/items/MLA1"):
            return []
        if url.endswith("/items/MLA1"):
            return {"id": "MLA1", "price": estado_item["price"]}
        raise AssertionError(url)

    def fake_put(url, headers, body):
        estado_item["price"] = body["price"]
        return {"id": "MLA1", "price": body["price"]}

    _fake_put.calls = []
    _fake_put.responder = fake_put
    _fake_post.calls = []
    _fake_post.responder = lambda url, headers, body: {"message": "New deal_price must be lower than current deal_price"}

    ml = MLOfertasEscritura(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN, put_fn=_fake_put, post_fn=_fake_post)

    r = activar_en_campana_tradicional(ml, "IT", "MLA1", Decimal(10000))

    assert r["ok"] is False
    assert len(_fake_post.calls) == 1  # un solo intento -- no escaló
    assert "incluso escalando" not in r["error"]  # no se llegó a escalar nada


def test_listar_promociones_item_cruza_nombre_de_campana():
    def fake_get(url, params, headers):
        if "seller-promotions/users" in url:
            return {"results": [{"id": "C-1", "type": "SELLER_CAMPAIGN", "status": "started",
                                  "name": "Oferta Tradicional Agosto", "date_from": "2026-08-01", "date_to": "2026-08-31"}]}
        if url.endswith("/seller-promotions/items/MLA1"):
            return [
                {"type": "SELLER_CAMPAIGN", "promotion_id": "C-1", "status": "started", "price": 9000, "original_price": 12000},
                {"type": "PRICE_DISCOUNT", "status": "started", "price": 8500, "original_price": 12000},
            ]
        raise AssertionError(url)

    ml = MLOfertasClient(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN)
    promos = listar_promociones_item(ml, "IT", "MLA1")

    assert len(promos) == 2
    campana = next(p for p in promos if p["promotion_type"] == "SELLER_CAMPAIGN")
    assert campana["nombre"] == "Oferta Tradicional Agosto"
    assert campana["fecha_desde"] == "2026-08-01" and campana["fecha_hasta"] == "2026-08-31"
    descuento = next(p for p in promos if p["promotion_type"] == "PRICE_DISCOUNT")
    assert descuento["nombre"] == "Descuento propio"


def test_listar_promociones_item_sin_nada_activo_no_rompe():
    """MLA sin ninguna promoción/candidata -- `promociones_item` puede
    devolver `null` en vez de `[]` (mismo tipo de bug que `results: null`
    en `promociones_seller`, ver test de arriba)."""
    def fake_get(url, params, headers):
        if "seller-promotions/users" in url:
            return {"results": []}
        if url.endswith("/seller-promotions/items/MLA1"):
            return None
        raise AssertionError(url)

    ml = MLOfertasClient(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN)
    assert listar_promociones_item(ml, "IT", "MLA1") == []


# ── Buscador puntual (MLA sin oferta activa) ──

def test_resolver_item_para_gestion_ok():
    def fake_get(url, params, headers):
        assert url.endswith("/items/MLA1")
        return {"id": "MLA1", "title": "T1", "price": 15000, "seller_custom_field": "SKU-1", "domain_id": "MLA-TONERS"}
    ml = MLOfertasClient(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN)
    costo = _CostoProviderFalso({"SKU-1": Decimal(5)})
    iva = _IvaProviderFalso({"SKU-1": Decimal("1.21")})

    r = resolver_item_para_gestion(ml, costo, iva, "MLA1", "IT", Decimal(1000))

    assert r["encontrado"] is True
    assert r["item_id"] == "MLA1" and r["sku"] == "SKU-1" and r["domain_id"] == "MLA-TONERS"
    assert r["precio_actual"] == 15000 and r["costo_sin_iva"] == Decimal(5) and r["iva_factor"] == Decimal("1.21")
    assert r["incidencia"] is None
    assert r["cuotas_ofrecidas"] is None


def test_resolver_item_para_gestion_trae_cuotas_ofrecidas():
    """Caso real detectado por Maxx en vivo (2026-09-01, MLA en 12 cuotas):
    el buscador puntual traía `installments` en el GET pero no lo usaba --
    el panel de "Oferta Tradicional" quedaba ciego a que la publicación
    estaba vendiéndose en cuotas."""
    def fake_get(url, params, headers):
        return {"id": "MLA1", "title": "T1", "price": 15000, "seller_custom_field": "SKU-1",
                "domain_id": "MLA-TONERS", "installments": {"quantity": 12, "rate": 0}}
    ml = MLOfertasClient(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN)
    costo = _CostoProviderFalso({"SKU-1": Decimal(5)})
    iva = _IvaProviderFalso({"SKU-1": Decimal("1.21")})

    r = resolver_item_para_gestion(ml, costo, iva, "MLA1", "IT", Decimal(1000))

    assert r["cuotas_ofrecidas"] == 12


def test_resolver_item_para_gestion_no_encontrado():
    ml = MLOfertasClient(get_fn=lambda u, p, h: {}, token_fn=_FAKE_TOKEN_FN)
    r = resolver_item_para_gestion(ml, _CostoProviderFalso({}), _IvaProviderFalso({}), "MLA1", "IT", Decimal(1000))
    assert r == {"encontrado": False}


def test_resolver_item_para_gestion_sin_sku():
    def fake_get(url, params, headers):
        return {"id": "MLA1", "title": "T1", "price": 15000, "seller_custom_field": None, "domain_id": None}
    ml = MLOfertasClient(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN)
    r = resolver_item_para_gestion(ml, _CostoProviderFalso({}), _IvaProviderFalso({}), "MLA1", "IT", Decimal(1000))
    assert r["incidencia"] == "SIN_SKU"


def test_resolver_item_para_gestion_sin_costo_tactica():
    def fake_get(url, params, headers):
        return {"id": "MLA1", "title": "T1", "price": 15000, "seller_custom_field": "SKU-X", "domain_id": "MLA-TONERS"}
    ml = MLOfertasClient(get_fn=fake_get, token_fn=_FAKE_TOKEN_FN)
    r = resolver_item_para_gestion(ml, _CostoProviderFalso({}), _IvaProviderFalso({"SKU-X": Decimal("1.21")}), "MLA1", "IT", Decimal(1000))
    assert r["incidencia"] == "SIN_COSTO_TACTICA"
