from decimal import Decimal as D
from fastapi.testclient import TestClient

import main
import mercados as mk


class _Costos:
    def precargar(self): pass
    def obtener(self, sku): return D("10") if sku == "A1" else None


class _Iva:
    def precargar(self): pass
    def factor(self, sku): return D("1.21")


def test_margen_web_3_cuotas_al_precio_puesto(monkeypatch):
    monkeypatch.setenv("ERP_API_KEY", "k")
    monkeypatch.setattr(main.costos_ecom, "proveedores_de_costo_e_iva", lambda: (_Costos(), _Iva()))
    monkeypatch.setattr(main, "tc_info_rapido", lambda: {"tc": D("1000")})
    filas = mk.filas_iniciales_parseadas()
    monkeypatch.setattr(main, "_tarifas_actuales", lambda: ({"filas": filas}, {"origen": "test"}))
    c = TestClient(main.app)
    r = c.post("/ayala-core/margenes-precio", headers={"X-ERP-Key": "k"}, json={"condiciones": {"web": "3"}, "items": [{"sku": "A1", "web": 31259, "ml": 27449}, {"sku": "ZZ", "web": 1000}]})
    assert r.status_code == 200, r.text
    m = r.json()["margenes"]
    assert m["ZZ"]["error"] == "sin costo en Ecom"
    w = m["A1"]["web"]
    # a mano (todo lo de la plataforma SIN IVA, ÷ 1,21): precio sin IVA - costo 10000 - comisión 6,05 % - cuotas 3 (3,40 × 1,21 = 4,114 %) - IIBB 5 % s/ sin IVA - cheque 1,2 % s/ con IVA - costo por orden
    p = D("31259"); sin = p / D("1.21")
    esperado = sin - 10000 - p * D("0.0605") / D("1.21") - p * D("0.04114") / D("1.21") - sin * D("0.05") - p * D("0.012") - D("149.12")
    assert w["condicion"] == "3" and abs(D(str(w["renta"])) - esperado) < D("0.05"), (w, esperado)
    assert abs(w["pct"] - float(esperado / sin * 100)) < 0.01
    assert "ml" in m["A1"] and m["A1"]["ml"]["condicion"] == "contado"
    assert c.post("/ayala-core/margenes-precio", headers={"X-ERP-Key": "k"}, json={"condiciones": {"web": "99"}, "items": []}).status_code == 422
