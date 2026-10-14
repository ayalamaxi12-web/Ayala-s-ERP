"""Comisión real de ML por publicación (sin red real: respuestas simuladas con el formato documentado de listing_prices)."""
from decimal import Decimal

import campanas_ml_comision as cc


def _resp(lt="gold_special", meli=15.0, financ=0.0, fijo=3320.0, monto=7309.85):
    return {"listing_type_id": lt, "sale_fee_amount": monto,
            "sale_fee_details": {"percentage_fee": meli + financ, "meli_percentage_fee": meli, "financing_add_on_fee": financ,
                                 "fixed_fee": fijo, "gross_amount": monto}}


def test_parsea_la_comision_base_sin_el_recargo_de_cuotas():
    assert cc.parsear(_resp(meli=15.0), "gold_special", 26599)[0] == Decimal("0.15")
    assert cc.parsear(_resp(meli=15.0, financ=2.0), "gold_special", 26599)[0] == Decimal("0.15")     # el recargo va aparte
    r = {"sale_fee_details": {"percentage_fee": 17.0, "financing_add_on_fee": 2.0}}                  # sin meli_percentage_fee
    assert cc.parsear(r, "x", 100)[0] == Decimal("0.15")
    r = {"sale_fee_amount": 7309.85, "sale_fee_details": {"fixed_fee": 3320}}                        # solo montos
    assert abs(cc.parsear(r, "x", 26599)[0] - Decimal("0.15")) < Decimal("0.0001")


def test_acepta_lista_de_tipos_y_descarta_valores_absurdos():
    lista = [_resp("gold_pro", meli=20.0), _resp("gold_special", meli=15.0)]
    assert cc.parsear(lista, "gold_special", 26599)[0] == Decimal("0.15")
    assert cc.parsear(lista, "otro", 26599)[0] is None
    assert cc.parsear(_resp(meli=90.0), "gold_special", 100)[0] is None
    assert cc.parsear("basura", "x", 100)[0] is None and cc.parsear(None, "x", 100)[0] is None


def test_una_llamada_por_par_categoria_tipo_con_el_precio_mediano():
    llamadas = []

    def get(url, params, headers):
        llamadas.append(params)
        assert url.endswith("/sites/MLA/listing_prices") and headers["Authorization"] == "Bearer T"
        return _resp(params["listing_type_id"], meli=15.0 if params["category_id"] == "MLA1" else 13.5)

    items = {"A": {"category_id": "MLA1", "listing_type_id": "gold_special", "precio": 100},
             "B": {"category_id": "MLA1", "listing_type_id": "gold_special", "precio": 300},
             "C": {"category_id": "MLA1", "listing_type_id": "gold_special", "precio": 200},
             "D": {"category_id": "MLA2", "listing_type_id": "gold_pro", "precio": 50},
             "E": {"category_id": None, "listing_type_id": "gold_pro", "precio": 50}}
    out, av = cc.comisiones(items, get, lambda c: "T")
    assert len(llamadas) == 2 and sorted(p["price"] for p in llamadas) == [50, 200]
    assert out["A"]["pct"] == out["B"]["pct"] == Decimal("0.15") and out["D"]["pct"] == Decimal("0.135") and "E" not in out
    assert out["A"]["raw"]["sale_fee_details"]["meli_percentage_fee"] == 15.0          # la respuesta cruda queda para auditar
    assert any("1 publicaciones sin categoría" in a for a in av)


def test_un_par_que_falla_no_tira_el_resto():
    def get(url, params, headers):
        if params["category_id"] == "MLA2":
            raise RuntimeError("503")
        return _resp(meli=15.0)

    out, av = cc.comisiones({"A": {"category_id": "MLA1", "listing_type_id": "gold_special", "precio": 100},
                             "B": {"category_id": "MLA2", "listing_type_id": "gold_special", "precio": 100}}, get, lambda c: "T")
    assert "A" in out and "B" not in out and any("MLA2" in a and "503" in a for a in av)
