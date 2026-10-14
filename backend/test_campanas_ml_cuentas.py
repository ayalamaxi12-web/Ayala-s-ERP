"""Detección de cuenta IT/MT por ITEM_ID (sin red real)."""
import campanas_ml_cuentas as cc
import pytest
from ml_auth import SELLERS


@pytest.fixture(autouse=True)
def _sin_cache():
    cc.limpiar_cache()
    yield
    cc.limpiar_cache()


def _fake(items):
    def get(url, params, headers):
        assert url.endswith("/items") and "seller_id" in params["attributes"]
        assert headers["Authorization"] == "Bearer T"
        return [({"code": 200, "body": items[i]} if i in items else {"code": 404, "body": {"message": "not found"}})
                for i in params["ids"].split(",")]
    return get


def test_detecta_cuenta_y_sku_de_ml():
    items = {"MLA1": {"id": "MLA1", "seller_id": int(SELLERS["IT"]), "seller_custom_field": "SKU-A"},
             "MLA2": {"id": "MLA2", "seller_id": int(SELLERS["MT"]), "attributes": [{"id": "SELLER_SKU", "value_name": "SKU-B"}]},
             "MLA3": {"id": "MLA3", "seller_id": 999}}
    det, av = cc.detectar(["MLA1", "MLA2", "MLA3", "MLA4", "MLA1"], _fake(items), lambda c: "T")
    assert det["MLA1"] == {"seller_id": SELLERS["IT"], "cuenta": "IT", "sku_ml": "SKU-A", "category_id": None, "listing_type_id": None}
    assert det["MLA2"]["cuenta"] == "MT" and det["MLA2"]["sku_ml"] == "SKU-B"
    assert det["MLA3"]["cuenta"] is None and "MLA4" not in det
    assert any("1 publicaciones" in a for a in av)


def test_lotes_de_20_y_un_lote_caido_no_tira_el_resto():
    ids = [f"MLA{i}" for i in range(45)]
    llamadas = []

    def get(url, params, headers):
        llamadas.append(len(params["ids"].split(",")))
        if "MLA20" in params["ids"].split(","):
            raise RuntimeError("503")
        return [{"code": 200, "body": {"id": i, "seller_id": int(SELLERS["IT"])}} for i in params["ids"].split(",")]

    det, av = cc.detectar(ids, get, lambda c: "T", workers=1)
    assert sorted(llamadas) == [5, 20, 20] and len(det) == 25 and any("503" in a for a in av)


def test_resumen_cuenta_sugerida_por_mayoria():
    det = {"A": {"cuenta": "IT"}, "B": {"cuenta": "IT"}, "C": {"cuenta": "MT"}}
    r = cc.resumen_cuentas(det, ["A", "B", "C", "D"])
    assert r["sugerida"] == "IT" and r["mixta"] and r["conteo"] == {"IT": 2, "MT": 1, "?": 1}
    assert cc.resumen_cuentas({}, ["A"])["sugerida"] is None


def test_la_segunda_subida_no_vuelve_a_pedirle_a_ml():
    items = {f"MLA{i}": {"id": f"MLA{i}", "seller_id": int(SELLERS["IT"]), "category_id": "MLA1", "listing_type_id": "gold_special"} for i in range(45)}
    llamadas = []

    def get(url, params, headers):
        llamadas.append(len(params["ids"].split(",")))
        return [{"code": 200, "body": items[i]} for i in params["ids"].split(",")]

    a, _ = cc.detectar(list(items), get, lambda c: "T")
    b, _ = cc.detectar(list(items), get, lambda c: "T")
    assert len(llamadas) == 3 and a == b and b["MLA7"]["category_id"] == "MLA1"      # 45 ítems = 3 lotes, solo la primera vez
    # un ítem nuevo pide solo el lote que falta
    items["MLA99"] = {"id": "MLA99", "seller_id": int(SELLERS["MT"])}
    c, _ = cc.detectar(list(items), get, lambda t: "T")
    assert llamadas[3:] == [1] and c["MLA99"]["cuenta"] == "MT"
