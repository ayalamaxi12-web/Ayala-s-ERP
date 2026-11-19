import ml_ofertas as mo
from ml_ofertas import MLOfertasClient

TOKEN = lambda cuenta: "FAKE"


class _ML(MLOfertasClient):
    def __init__(self):
        super().__init__(get_fn=None, token_fn=TOKEN)

    def promociones_seller(self, cuenta):
        return [{"id": "L1", "type": "LIGHTNING", "name": "Relámpago 20/11", "status": "pending", "start_date": "2026-11-20", "finish_date": "2026-11-21"},
                {"id": "L0", "type": "LIGHTNING", "name": "Vieja", "status": "finished"},
                {"id": "C1", "type": "SELLER_CAMPAIGN", "name": "Propia", "status": "started"}]

    def items_candidatos_promocion(self, promotion_id, promotion_type, cuenta, tope=3000):
        assert (promotion_id, promotion_type) == ("L1", "LIGHTNING")          # solo las relámpago vigentes
        return [{"id": "MLA1", "status": "candidate", "original_price": 20000, "suggested_discounted_price": 15000, "max_discounted_price": 16000, "min_discounted_price": 12000, "stock": {"min": 5, "max": 20}},
                {"id": "MLA2", "status": "candidate", "original_price": 10000, "max_discounted_price": 8000}]

    def detalle_items_ofertas(self, ids, cuenta, progreso_cb=None):
        return [{"id": "MLA1", "title": "Uno", "price": 20000, "seller_custom_field": "SKU-1", "available_quantity": 30, "status": "active", "permalink": "https://x/1"},
                {"id": "MLA2", "title": "Dos", "price": 10000, "seller_custom_field": "SKU-2", "available_quantity": 0, "status": "paused"}]


def test_detecta_los_mla_candidatos_de_las_campanas_relampago_vigentes():
    r = mo.detectar_relampago(_ML(), "IT")
    assert [c["id"] for c in r["campanas"]] == ["L1"] and r["campanas"][0]["candidatos"] == 2 and not r["sin_campanas"]
    f = {x["item_id"]: x for x in r["filas"]}
    assert f["MLA1"]["sku"] == "SKU-1" and f["MLA1"]["precio_sugerido"] == 15000.0 and f["MLA1"]["desc_sugerido_pct"] == 25.0
    assert (f["MLA1"]["stock_pedido_min"], f["MLA1"]["stock_pedido_max"], f["MLA1"]["stock_disponible"]) == (5.0, 20.0, 30)
    assert f["MLA2"]["desc_sugerido_pct"] == 20.0 and f["MLA2"]["estado_publicacion"] == "paused"      # sin sugerido usa el máximo; se lista con su estado
    assert [x["item_id"] for x in r["filas"]] == ["MLA1", "MLA2"]                                       # más descuento primero


def test_sin_campanas_relampago_lo_dice():
    class _Sin(_ML):
        def promociones_seller(self, cuenta): return [{"id": "C1", "type": "SELLER_CAMPAIGN", "status": "started"}]
    r = mo.detectar_relampago(_Sin(), "IT")
    assert r["sin_campanas"] and r["filas"] == []


def test_el_job_termina_y_guarda_el_resultado():
    mo.iniciar_job_relampago("rel_test", "IT", _ML())
    j = mo.estado_job("rel_test")
    assert j["status"] == "done" and len(j["result"]["filas"]) == 2 and "Listo: 2 MLA" in j["log"][-1]
