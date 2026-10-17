import pytest

import competencia_publicaciones as cp
from ml_full import MLFullClient


def cliente(respuestas, fallar=()):
    llamadas = []

    def get(url, params, headers):
        llamadas.append((url, dict(params), headers["Authorization"]))
        if url.endswith("/items/search"):
            cuenta = "IT" if "115764017" in url else "MT"
            if cuenta in fallar:
                raise RuntimeError("403 forbidden")
            return {"results": respuestas.get(cuenta, [])}
        ids = params["ids"].split(",")
        return [{"code": 200, "body": respuestas["items"][i]} for i in ids if i in respuestas["items"]]
    c = MLFullClient(get_fn=get, token_fn=lambda cuenta: "T-" + cuenta)
    c.llamadas = llamadas
    return c


def item(i, sku, precio=1000, status="active", via="custom"):
    d = {"id": i, "title": "Toner " + i, "price": precio, "original_price": None, "permalink": f"https://articulo.mercadolibre.com.ar/{i}",
         "status": status, "catalog_listing": False, "available_quantity": 5}
    if via == "custom":
        d["seller_custom_field"] = sku
    else:
        d["attributes"] = [{"id": "SELLER_SKU", "value_name": sku}]
    return d


R = {"IT": ["MLA1", "MLA2"], "MT": ["MLA3"],
     "items": {"MLA1": item("MLA1", "PV-100", 24990), "MLA2": item("MLA2", "PV-1000"), "MLA3": item("MLA3", "pv-100", 25500, "paused", via="attr")}}


def test_busca_en_las_dos_cuentas_confirma_el_sku_exacto_y_ordena_activas_primero():
    c = cliente(R)
    r = cp.publicaciones_por_sku("PV-100", c)
    assert [(p["item_id"], p["cuenta"], p["estado"]) for p in r["publicaciones"]] == [("MLA1", "IT", "active"), ("MLA3", "MT", "paused")]   # MLA2 (PV-1000) no es el SKU
    assert r["errores"] == [] and r["publicaciones"][0]["precio"] == 24990
    busquedas = [x for x in c.llamadas if x[0].endswith("/items/search")]
    assert {x[2] for x in busquedas} == {"Bearer T-IT", "Bearer T-MT"} and all(x[1]["seller_sku"] == "PV-100" for x in busquedas)


def test_una_cuenta_con_error_no_corta_la_otra():
    r = cp.publicaciones_por_sku("PV-100", cliente(R, fallar=("IT",)))
    assert [p["item_id"] for p in r["publicaciones"]] == ["MLA3"] and r["errores"][0]["cuenta"] == "IT" and "403" in r["errores"][0]["error"]


def test_sku_sin_publicaciones_y_sku_vacio():
    assert cp.publicaciones_por_sku("NO-EXISTE", cliente({"IT": [], "MT": [], "items": {}})) == {"sku": "NO-EXISTE", "publicaciones": [], "errores": []}
    with pytest.raises(ValueError):
        cp.publicaciones_por_sku("  ")


# ── precio real (E2) ──
from ml_ofertas import MLOfertasClient


def cliente_ofertas(promos, fallar_promos=()):
    llamadas = []

    def get(url, params, headers):
        llamadas.append(url)
        if url.endswith("/items/search"):
            return {"results": R["IT"] if "115764017" in url else R["MT"]}
        if "/seller-promotions/items/" in url:
            i = url.rsplit("/", 1)[1]
            if i in fallar_promos:
                raise RuntimeError("500")
            return promos.get(i, [])
        if "/seller-promotions/users/" in url:
            return {"results": [{"id": "C1", "name": "Hot Sale"}]}
        ids = params["ids"].split(",")
        return [{"code": 200, "body": R["items"][i]} for i in ids if i in R["items"]]
    c = MLOfertasClient(get_fn=get, token_fn=lambda cuenta: "T-" + cuenta)
    c.llamadas = llamadas
    return c


def test_precio_real_usa_la_promocion_activa_y_el_precio_de_lista_es_el_tachado():
    c = cliente_ofertas({"MLA1": [{"type": "SELLER_CAMPAIGN", "promotion_id": "C1", "status": "started", "price": 21000, "original_price": 24990},
                                  {"type": "DEAL", "status": "candidate", "price": 15000}]})
    r = cp.precio_real_por_sku("PV-100", c)
    a, b = r["publicaciones"]
    assert (a["item_id"], a["precio_real"], a["precio_tachado"], a["precio_lista"]) == ("MLA1", 21000.0, 24990.0, 24990.0)
    assert a["campana"] == {"nombre": "Hot Sale", "tipo": "SELLER_CAMPAIGN"}
    assert b["item_id"] == "MLA3" and b["precio_real"] == 25500.0 and b["campana"] is None          # pausada: no se consultan promociones
    assert not any(u.endswith("/MLA3") for u in c.llamadas if "seller-promotions/items" in u)


def test_sin_promocion_el_precio_real_es_el_de_lista_y_error_de_promos_se_avisa():
    r = cp.precio_real_por_sku("PV-100", cliente_ofertas({}))
    assert r["publicaciones"][0]["precio_real"] == 24990.0 and r["publicaciones"][0]["campana"] is None
    r = cp.precio_real_por_sku("PV-100", cliente_ofertas({}, fallar_promos=("MLA1",)))
    assert r["publicaciones"][0]["precio_real"] == 24990.0 and "MLA1" in r["errores"][0]["error"]


def test_cache_5_min_y_no_cachea_con_errores():
    cp._cache_precio.clear()
    c = cliente_ofertas({})
    t = [1000.0]
    cp.precio_real_cacheado("PV-100", cliente=c, ahora=lambda: t[0])
    n = len(c.llamadas)
    cp.precio_real_cacheado("PV-100", cliente=c, ahora=lambda: t[0] + 10)
    assert len(c.llamadas) == n                                              # cache
    cp.precio_real_cacheado("PV-100", cliente=c, ahora=lambda: t[0] + 400)
    assert len(c.llamadas) > n                                               # venció
    cp._cache_precio.clear()
    e = cliente_ofertas({}, fallar_promos=("MLA1",))
    cp.precio_real_cacheado("PV-100", cliente=e, ahora=lambda: t[0]); m = len(e.llamadas)
    cp.precio_real_cacheado("PV-100", cliente=e, ahora=lambda: t[0] + 1)
    assert len(e.llamadas) > m
    cp._cache_precio.clear()
