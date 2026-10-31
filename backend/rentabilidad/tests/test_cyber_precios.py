"""Cyber: rangos de ML + envío histórico (con ML falso) y persistencia en Cyber_Precios (con Sheet falso)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import cyber_precios as cp


class MLFalso:
    def promociones_item(self, item_id, cuenta):
        if item_id == "MLA2":
            raise RuntimeError("boom")
        if item_id == "MLA3":
            return [{"id": "OTRA", "min_discounted_price": 1, "max_discounted_price": 2}]
        return [{"id": "P1", "min_discounted_price": 50, "max_discounted_price": 90, "suggested_discounted_price": 70, "status": "candidate", "price": 100}]


def test_rangos_y_envios_con_avisos(monkeypatch):
    import ml_campanas_participar
    monkeypatch.setattr(ml_campanas_participar, "_id_promo", lambda p: p.get("id"))
    items = [{"item_id": i, "promo_id": "P1", "sku": "X", "categoria": None} for i in ("MLA1", "MLA2", "MLA3")]
    r = cp.rangos_y_envios(MLFalso(), "IT", items, {"real": {}, "ceros": set(), "categoria": {}, "general": None}, workers=1)
    assert r["rangos"]["MLA1"] == {"min": 50, "max": 90, "sugerido": 70, "estado": "candidate", "precio": 100}
    assert "MLA2" not in r["rangos"] and "MLA3" not in r["rangos"]
    assert any("sin rango" in a for a in r["avisos"]) and any("fallaron" in a for a in r["avisos"])
    assert set(r["envios"]) == {"MLA1", "MLA2", "MLA3"}


class WsFalsa:
    def __init__(self):
        self.vals = []
    def clear(self):
        self.vals = []
    def update(self, values, range_name):
        self.vals = values
    def get_all_records(self):
        h = self.vals[0]
        return [dict(zip(h, r)) for r in self.vals[1:]]
    def get_all_values(self):
        return self.vals


class SsFalso:
    def __init__(self):
        self.ws = WsFalsa()
        self.ws.vals = [cp.COLS_PRECIOS]
    def worksheet(self, t):
        return self.ws


def fila(sku, precio, estado="ok"):
    return {"sku": sku, "mla": "MLA" + sku, "grupo": "medio", "precio": precio, "margen3": 12.0, "estado": estado, "regla": "r"}


def test_guardar_reemplaza_la_cuenta_y_conserva_la_otra():
    ss = SsFalso()
    cp.guardar_precios(ss, "IT", [fila("A", 100), fila("B", 200, "no_participa")])
    r = cp.guardar_precios(ss, "MT", [fila("A", 90)])
    assert r["guardadas"] == 1 and r["otras_cuentas"] == 2
    r = cp.guardar_precios(ss, "IT", [fila("A", 120)])           # reemplaza solo IT
    assert r["guardadas"] == 1 and r["otras_cuentas"] == 1
    cuentas = sorted(x[1] for x in ss.ws.vals[1:])
    assert cuentas == ["IT", "MT"]


def test_precios_otra_cuenta_toma_el_mas_alto_y_ignora_no_participa():
    ss = SsFalso()
    cp.guardar_precios(ss, "MT", [fila("A", 90), fila("B", 200, "no_participa")])
    assert cp.precios_otra_cuenta(ss, "IT") == {"A": 90.0}
    assert cp.precios_otra_cuenta(ss, "MT") == {}
