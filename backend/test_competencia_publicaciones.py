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
