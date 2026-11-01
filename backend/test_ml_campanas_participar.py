"""Participar en una campaña de ML desde el ERP (ej. Cyber): diagnóstico de solo lectura y participación una por una con ML simulado."""
import ml_campanas_participar as mp
from ml_ofertas import MLOfertasClient, MLOfertasEscritura

TOKEN = lambda cuenta: "FAKE"
PID = "P-MLA18145042"


class _ML(MLOfertasEscritura):
    def __init__(self, campanas, estados, respuestas):
        super().__init__(get_fn=None, token_fn=TOKEN, post_fn=self._post_fake)
        self._c, self._e, self._r, self.posts = campanas, estados, respuestas, []

    def promociones_seller(self, cuenta):
        return self._c

    def promociones_item(self, item_id, cuenta):
        e = self._e.get(item_id)
        return [] if e is None else [{"id": PID, "type": "MARKETPLACE_CAMPAIGN", "status": e, "price": 9000, "original_price": 10499}]

    def _post_fake(self, url, headers, body):
        item = url.split("/items/")[1].split("?")[0]
        self.posts.append((item, body, url))
        return self._r(item)


CAMP = [{"id": PID, "type": "MARKETPLACE_CAMPAIGN", "name": "Sumate al Cyber Monday", "status": "started", "start_date": "2026-11-02", "finish_date": "2026-11-12"}]


def test_diagnostico_lee_el_tipo_real_y_marca_las_que_no_son_candidatas():
    ml = _ML(CAMP, {"MLA1": "candidate"}, lambda i: {})
    r = mp.diagnosticar(ml, "IT", {PID: ["MLA1", "MLA2"], "P-OTRA": ["MLA1"]})["campanas"]
    a, b = r
    assert a["listada_por_ml"] and a["tipo_api"] == "MARKETPLACE_CAMPAIGN" and a["muestras"][0]["candidata"] is True and a["muestras"][1]["candidata"] is False
    assert any("no figura" in x for x in a["avisos"])
    assert b["listada_por_ml"] is False and "usá el Excel" in b["avisos"][0]


def test_participar_manda_el_tipo_que_informa_ml_y_el_precio_solo_si_cambio():
    ml = _ML(CAMP, {"MLA1": "started", "MLA2": "started"}, lambda i: {"price": 9000})                 # MARKETPLACE_CAMPAIGN: ML fija el precio
    r = mp.participar(ml, "IT", PID, [{"item_id": "MLA1", "deal_price": 9659.08}, {"item_id": "MLA2", "deal_price": 8500.5, "cambiado": True}])
    assert [x["estado"] for x in r["resultados"]] == ["ok", "ok"]
    assert ml.posts[0][1] == {"promotion_id": PID, "promotion_type": "MARKETPLACE_CAMPAIGN"}            # sin precio: la propuesta de ML
    assert ml.posts[1][1] == {"promotion_id": PID, "promotion_type": "MARKETPLACE_CAMPAIGN", "deal_price": 8500.5}
    assert ml.posts[0][2].endswith("?app_version=v2")


def test_en_un_deal_el_precio_va_siempre_y_no_se_manda_sin_precio():
    """Verificado en vivo: el «TIERS» del Cyber es un DEAL en la API de ML y exige deal_price."""
    camp = [{"id": PID, "type": "DEAL", "name": "MKP T1 CYBER MONDAY NOV", "status": "pending"}]
    ml = _ML(camp, {"MLA1": "pending"}, lambda i: {"price": 9659.08})
    r = mp.participar(ml, "IT", PID, [{"item_id": "MLA1", "deal_price": 9659.08, "cambiado": False}, {"item_id": "MLA2"}])
    assert ml.posts[0][1] == {"promotion_id": PID, "promotion_type": "DEAL", "deal_price": 9659.08}   # aunque no se haya cambiado
    assert r["resultados"][1]["estado"] == "error" and "exige el precio" in r["resultados"][1]["mensaje"] and len(ml.posts) == 1


def test_en_smart_no_va_precio_si_no_se_cambio():
    camp = [{"id": PID, "type": "SMART", "name": "Ofertas compartidas CM", "status": "pending"}]
    ml = _ML(camp, {"MLA1": "pending"}, lambda i: {"price": 1})
    mp.participar(ml, "IT", PID, [{"item_id": "MLA1", "deal_price": 32682.85, "cambiado": False}])
    assert ml.posts[0][1] == {"promotion_id": PID, "promotion_type": "SMART"}


def test_la_prueba_de_una_solo_hace_una_y_la_verifica_en_ml():
    ml = _ML(CAMP, {"MLA1": "started"}, lambda i: {"price": 9000})
    r = mp.participar(ml, "IT", PID, [{"item_id": "MLA1"}, {"item_id": "MLA2"}], solo_probar=True)
    assert len(ml.posts) == 1 and r["resultados"][0]["estado"] == "ok" and r["resultados"][0]["verificado"] == "started"
    dudosa = mp.participar(_ML(CAMP, {}, lambda i: {"price": 9000}), "IT", PID, [{"item_id": "MLA9"}], solo_probar=True)
    assert dudosa["resultados"][0]["estado"] == "dudosa"                                                  # ML dijo OK pero no la muestra adentro


def test_errores_de_ml_por_fila_y_corte_tras_varios_seguidos():
    ml = _ML(CAMP, {}, lambda i: {"message": "no candidata", "error": "bad_request", "status": 400, "cause": []})
    r = mp.participar(ml, "IT", PID, [{"item_id": f"MLA{n}"} for n in range(8)])
    est = [x["estado"] for x in r["resultados"]]
    assert est[:5] == ["error"] * 5 and est[5:] == ["pendiente"] * 3 and len(ml.posts) == 5 and "no candidata" in r["resultados"][0]["mensaje"]


def test_si_ml_no_lista_la_campana_no_se_escribe_nada():
    ml = _ML([], {}, lambda i: {})
    r = mp.participar(ml, "IT", PID, [{"item_id": "MLA1"}])
    assert r["resultados"] == [] and "Usá el Excel" in r["error"] and ml.posts == []


def test_historial_una_sola_vez_con_las_que_entraron():
    ml = _ML(CAMP, {"MLA1": "started"}, lambda i: {"price": 1} if i == "MLA1" else {"message": "x", "error": "e", "status": 400})
    anotado = []
    mp.participar(ml, "IT", PID, [{"item_id": "MLA1", "sku": "S1"}, {"item_id": "MLA2"}], historial_cb=anotado.append, operador="Natalia")
    assert len(anotado) == 1 and len(anotado[0]) == 1 and anotado[0][0]["Item ID"] == "MLA1" and anotado[0][0]["Origen"] == "Campañas ML" and anotado[0][0]["Fecha"]


def test_oferta_ya_existente_no_corta_la_corrida_ni_cuenta_como_fallo():
    def resp(item):
        if item in ("MLA1", "MLA2", "MLA3", "MLA4", "MLA5", "MLA6"):
            return {"message": "Errors: OFFER_ALREADY_EXISTS - Offer already exists", "error": "bad_request", "status": 400, "cause": []}
        return {"status": "candidate"}
    ml = _ML(CAMP, {}, resp)
    r = mp.participar(ml, "IT", PID, [{"item_id": f"MLA{n}"} for n in range(1, 9)])
    est = [x["estado"] for x in r["resultados"]]
    assert est == ["ya_tiene"] * 6 + ["ok", "ok"] and len(ml.posts) == 8


def test_campana_que_pide_offer_id_lo_toma_de_las_promociones_del_item_y_reintenta():
    llamadas = []

    def resp(item):
        llamadas.append(item)
        return {"message": "Offer id is required", "error": "bad_request", "status": 400, "cause": []} if len(llamadas) == 1 else {"status": "started"}

    class ML(_ML):
        def promociones_item(self, item_id, cuenta):
            return [{"id": PID, "type": "SMART", "status": "candidate", "offer_id": "OFFER-123"}]
    ml = ML(CAMP, {}, resp)
    r = mp.participar(ml, "IT", PID, [{"item_id": "MLA9"}], solo_probar=True)
    assert r["resultados"][0]["estado"] == "ok" and len(ml.posts) == 2 and ml.posts[1][1]["offer_id"] == "OFFER-123" and "offer_id" not in ml.posts[0][1]
