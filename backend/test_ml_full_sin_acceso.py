import pytest
from ml_full import MLFullClient, MLSinAcceso


def _cliente(ajenos):
    llamadas = []

    def get(url, params, headers):
        llamadas.append(params["inventory_id"])
        ids = params["inventory_id"].split(",")
        if any(i in ajenos for i in ids):
            raise MLSinAcceso(url)
        return {"results": [{"inventory_id": i, "date_created": "2026-11-01T10:00:00Z", "detail": {"available_quantity": -1}} for i in ids], "paging": {}}
    return MLFullClient(get_fn=get, token_fn=lambda c: "t"), llamadas


def test_un_inventario_ajeno_no_tira_toda_la_lectura():
    ml, _ = _cliente({"INV3"})
    r = ml.ventas_full_por_inventory("IT", [f"INV{i}" for i in range(8)], "2026-10-01", "2026-11-01")
    assert set(r) == {f"INV{i}" for i in range(8)} - {"INV3"}
    assert ml.sin_acceso == [{"cuenta": "IT", "tipo": "SALE_CONFIRMATION", "inventory_id": "INV3"}]


def test_si_todo_da_403_se_corta_y_avisa_el_endpoint():
    ml, ll = _cliente({f"INV{i}" for i in range(2000)})
    ml._presupuesto_403 = 10
    with pytest.raises(MLSinAcceso) as e:
        ml.ventas_full_por_inventory("IT", [f"INV{i}" for i in range(40)], "2026-10-01", "2026-11-01")
    assert "403" in str(e.value) and "operations/search" in str(e.value) and "115764017" not in str(e.value)


def test_el_403_sigue_siendo_un_http_error_para_quien_lo_atrapaba():
    import requests
    from ml_ofertas import MLOfertasClient
    e = MLSinAcceso("https://api.mercadolibre.com/items?ids=MLA1")
    assert isinstance(e, requests.HTTPError) and e.response.status_code == 403 and "/items" in str(e)

    def get(url, params, headers):
        if "MLA2" in params["ids"].split(","):
            raise MLSinAcceso(url)
        return [{"code": 200, "body": {"id": i}} for i in params["ids"].split(",")]
    ml = MLOfertasClient(get_fn=get, token_fn=lambda c: "t")
    r = ml._lote_items(["MLA1", "MLA2", "MLA3"], "IT", {})
    assert [x["body"]["id"] for x in r] == ["MLA1", "MLA3"] and ml.items_sin_acceso[0]["item_id"] == "MLA2"
