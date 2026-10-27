"""Candidatos a Full: activas, con stock propio, que NO son fulfillment y venden >= mínimo."""
from datetime import date

import ml_full_candidatos as mc
from ml_full import MLFullClient

TOKEN = lambda cuenta: "FAKE"


def _items():
    def it(i, tipo, stock, status="active", sku="S"):
        return {"id": i, "title": "T" + i, "permalink": "p", "seller_custom_field": sku + i, "available_quantity": stock, "shipping": {"logistic_type": tipo}, "status": status, "attributes": []}
    return {x["id"]: x for x in [it("MLA1", "cross_docking", 10), it("MLA2", "fulfillment", 10), it("MLA3", "drop_off", 0), it("MLA4", "self_service", 3),
                                  it("MLA5", "cross_docking", 5, status="paused"), it("MLA6", "cross_docking", 5)]}


def _ml():
    items = _items()

    def get(url, params, headers):
        if "orders/search" in url:
            if params["offset"]:
                return {"results": [], "paging": {"total": 0}}
            orden = lambda *l: {"order_items": [{"item": {"id": i}, "quantity": q} for i, q in l]}
            return {"results": [orden(("MLA1", 4), ("MLA2", 9), ("MLA3", 9)), orden(("MLA1", 3), ("MLA4", 6), ("MLA5", 8), ("MLA6", 2))], "paging": {"total": 2}}
        if url.endswith("/items/search"):
            return {"results": list(items) if "scroll_id" not in params else [], "scroll_id": "s"} if "scroll_id" not in params else {"results": []}
        if url.endswith("/items"):
            return [{"body": items[i]} for i in params["ids"].split(",")]
        raise AssertionError(url)
    return MLFullClient(get_fn=get, token_fn=TOKEN)


def test_candidatos_son_activas_con_stock_no_full_y_con_ventas_minimas_ordenadas():
    r = mc.detectar_candidatos_full(_ml(), "IT", 30, 5, hoy=date(2026, 10, 27))
    assert [c["item_id"] for c in r] == ["MLA1", "MLA4"]          # MLA1 vendió 7, MLA4 6; MLA2 es Full, MLA3 sin stock, MLA5 pausada, MLA6 vendió 2
    assert r[0]["ventas_periodo"] == 7 and r[0]["por_dia"] == 0.23 and r[0]["envio"] == "Colecta" and r[1]["envio"] == "Flex"


def test_el_minimo_de_ventas_filtra():
    assert [c["item_id"] for c in mc.detectar_candidatos_full(_ml(), "IT", 30, 7, hoy=date(2026, 10, 27))] == ["MLA1"]


def test_el_job_guarda_resultado_y_errores():
    mc.iniciar_job("j1", "IT", 30, 5, ml=_ml())
    assert mc.estado_job("j1")["status"] == "done" and len(mc.estado_job("j1")["result"]["candidatos"]) == 2
    mc.iniciar_job("j2", "IT", 30, 5, ml=MLFullClient(get_fn=lambda *a: (_ for _ in ()).throw(RuntimeError("boom")), token_fn=TOKEN))
    assert mc.estado_job("j2")["status"] == "error" and "boom" in mc.estado_job("j2")["log"][-1]
