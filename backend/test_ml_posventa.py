import ml_posventa as P
from ml_full import MLFullClient


def _o(i, st, items, f="2026-11-10T10:00:00.000-03:00"):
    return {"id": i, "status": st, "date_created": f, "order_items": [{"item": {"id": it, "title": "T" + it, "seller_sku": sk}, "quantity": q} for it, sk, q in items]}


def _c(i, orden, f, tipo="mediations", etapa="claim", st="opened", reason="PNR9999"):
    return {"id": i, "resource": "order", "resource_id": orden, "date_created": f, "type": tipo, "stage": etapa, "status": st, "reason_id": reason,
            "resolution": {"reason": "x", "date_created": "2026-11-12T00:00:00.000-03:00", "benefited": "complainant"} if st == "closed" else None}


def test_calcular_cuenta_reclamos_cancelaciones_y_ranking():
    ords = [_o(1, "paid", [("MLA1", "SKU1", 2)]), _o(2, "paid", [("MLA2", "SKU2", 1)]), _o(3, "cancelled", [("MLA1", "SKU1", 1)])]
    recl = [_c(10, "1", "2026-11-11T00:00:00.000-03:00"), _c(11, "1", "2026-11-12T00:00:00.000-03:00", "returns", "dispute", "closed", "PDD1"),
            _c(12, "99", "2026-11-12T00:00:00.000-03:00")]
    sueltas = []
    r = P.calcular(ords, recl, lambda oid: sueltas.append(oid) or _o(99, "paid", [("MLA7", "SKU7", 1)]))
    s = r["resumen"]
    assert (s["ventas_pagadas"], s["unidades"], s["canceladas"], s["reclamos"], s["abiertos"], s["mediaciones"], s["devoluciones"]) == (2, 3, 1, 3, 2, 1, 1)
    assert s["tasa_cancelacion"] == 33.33 and s["tasa_reclamos"] == 150.0
    assert sueltas == ["99"]
    assert r["ranking_sku"][0]["item_id"] == "MLA1" and r["ranking_sku"][0]["reclamos"] == 2 and r["ranking_sku"][0]["sku"] == "SKU1"
    assert r["ranking_sku"][0]["tasa"] == 100.0
    assert {m["clave"] for m in r["por_motivo"]} == {"Producto no recibido (PNR9999)", "Producto defectuoso o distinto (PDD1)"}
    assert [d["reclamos"] for d in r["por_dia"]] == [1, 2]


def test_traer_reclamos_filtra_por_fecha_y_corta_paginacion():
    paginas = {0: [_c(i, "1", f"2026-11-{20 - i:02d}T00:00:00.000-03:00") for i in range(4)], 4: [_c(i, "1", f"2026-11-{20 - i:02d}T00:00:00.000-03:00") for i in range(4, 8)]}
    llamadas = []

    def get(url, params, headers):
        llamadas.append(params["offset"])
        return {"paging": {"total": 8}, "data": paginas[params["offset"]]}
    r = P.traer_reclamos(MLFullClient(get_fn=get, token_fn=lambda c: "t"), "IT", "2026-11-14", "2026-11-18")
    assert [c["id"] for c in r] == [2, 3, 4, 5, 6]
    assert llamadas == [0, 4]


def test_metricas_de_punta_a_punta_con_reputacion():
    def get(url, params, headers):
        if url.endswith("/orders/search"):
            return {"paging": {"total": 1}, "results": [_o(1, "paid", [("MLA1", "S1", 1)])]}
        if "claims/search" in url:
            return {"paging": {"total": 1}, "data": [_c(5, "1", "2026-11-11T00:00:00.000-03:00")]}
        if "/users/" in url:
            return {"seller_reputation": {"level_id": "5_green", "power_seller_status": "gold", "metrics": {"sales": {"period": "60 days", "completed": 10}, "claims": {"rate": 0.01, "value": 1}}}}
    r = P.metricas_posventa(MLFullClient(get_fn=get, token_fn=lambda c: "t"), "IT", "2026-11-01", "2026-11-17")
    assert r["resumen"]["reclamos"] == 1 and r["reputacion"]["nivel"] == "5_green" and r["reputacion"]["reclamos"]["tasa"] == 0.01


def test_endpoint_valida_rango(monkeypatch):
    from fastapi.testclient import TestClient
    import main
    c = TestClient(main.app)
    h = {"X-ERP-Key": "k"}
    monkeypatch.setenv("ERP_API_KEY", "k")
    assert c.post("/ml-posventa/run?cuenta=XX&desde=2026-11-01&hasta=2026-11-02", headers=h).status_code == 422
    assert c.post("/ml-posventa/run?cuenta=IT&desde=2026-11-05&hasta=2026-11-02", headers=h).status_code == 422
    assert c.post("/ml-posventa/run?cuenta=IT&desde=malo&hasta=2026-11-02", headers=h).status_code == 422
