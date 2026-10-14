"""Endpoints /campanas-ml/analizar y /simular, con ML, Ecom y la base simulados."""
import io
from contextlib import contextmanager
from datetime import date

import openpyxl
import pytest
from fastapi.testclient import TestClient

import campanas_ml_cuentas
from ml_auth import SELLERS
from rentabilidad.models import PricingSku
from rentabilidad.pricing_pm import DatosSku

from .conftest import d
from test_campanas_ml_xlsx import _ml_sintetico
from .test_fravega import db_multihilo  # noqa: F401 (fixture)


@pytest.fixture()
def cli(db_multihilo, monkeypatch):
    db_session = db_multihilo
    import main
    from rentabilidad import api, db as rdb
    db_session.add(PricingSku(sku="SKU-1", precio_web=d("7000"), pct_ml=d("1.3"), forma_pago_web="1", condicion_ml="contado",
                              vigente_desde=date(2026, 9, 1), cargado_por="Sheet Laura"))
    db_session.flush()

    @contextmanager
    def sesion():
        yield db_session

    monkeypatch.setattr(rdb, "sesion", sesion)
    monkeypatch.setattr(api, "_datos_sku_fn", lambda avisos: (lambda sku: DatosSku(d("2"), d("1.21"), "Laura", "Insumo", None)))
    monkeypatch.setattr(api, "_resolver_tc", lambda tc: d("1500"))
    monkeypatch.setattr(campanas_ml_cuentas, "detectar", lambda ids: (
        {"MLA1": {"seller_id": SELLERS["IT"], "cuenta": "IT", "sku_ml": None},
         "MLA2": {"seller_id": SELLERS["IT"], "cuenta": "IT", "sku_ml": "SKU-1"}}, []))
    monkeypatch.delenv("ERP_API_KEY", raising=False)
    monkeypatch.setitem(main._CAMP_CTX, "datos", None)  # el contexto de costos se cachea 5 min: aislar cada test
    return TestClient(main.app)


def test_analizar_detecta_cuenta_completa_sku_y_calcula(cli):
    r = cli.post("/campanas-ml/analizar", files={"archivo": ("a.xlsx", _ml_sintetico())})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["cuentas"]["sugerida"] == "IT" and j["cuentas"]["conteo"] == {"IT": 2}
    f1, f2 = j["filas"]
    assert f1["cuenta"] == "IT" and f1["sku"] == "SKU-1" and f1["sku_origen"] is None  # MLA1 ya traía SKU en el Excel
    assert f2["sku"] == "SKU-1" and f2["sku_origen"] == "ml" and f2["margenes"]["contado"]["margen"] is not None
    assert any("completaron con el SKU" in a for a in j["avisos"])
    assert len(j["avisos_generales"]) == 2 and "1.330" in j["avisos_generales"][0] and "envío" in j["avisos_generales"][1]


def test_simular_recalcula_con_el_porcentaje_jugado(cli):
    fila = {"item_id": "MLA9", "sku": "SKU-1", "precio_original": 10000, "descuento_pct": 10, "meli_pct": 0, "editable": True}
    a = cli.post("/campanas-ml/simular", json={"filas": [fila]}).json()["filas"][0]
    b = cli.post("/campanas-ml/simular", json={"filas": [dict(fila, descuento_pct=20)]}).json()["filas"][0]
    assert a["precio_cliente"] == 9000 and b["precio_cliente"] == 8000
    assert b["margenes"]["contado"]["margen"] < a["margenes"]["contado"]["margen"]
    c = cli.post("/campanas-ml/simular", json={"filas": [fila], "margen_objetivo": "30", "plan_objetivo": "6"}).json()["filas"][0]
    assert c["pct_max_para_margen"] is None or 5 <= c["pct_max_para_margen"] <= 80


def test_simular_valida_entrada(cli):
    assert cli.post("/campanas-ml/simular", json={"filas": [], "margen_objetivo": "abc"}).status_code == 422


def test_campana_simple_calcula_el_margen_sobre_el_descuento_total(cli):
    from test_campanas_ml_xlsx import _ml_simple
    r = cli.post("/campanas-ml/analizar", files={"archivo": ("a.xlsx", _ml_simple())})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["tipo"] == "simple" and j["col_editable"] == "DISCOUNT_PERCENTAGE"
    f = j["filas"][0]
    assert f["seller_pct"] == 10.0 and f["meli_pct"] is None and f["meli_monto"] == 0
    assert f["precio_vendedor"] == f["precio_cliente"] == 18000.0  # sin aporte de ML: todo del vendedor
    assert "margen_contado_sin_aporte_ml" not in f
    # mismo margen que una campaña con reparto de ML en 0
    s = cli.post("/campanas-ml/simular", json={"filas": [{"item_id": "MLA9", "sku": "SKU-1", "precio_original": 20000, "descuento_pct": 10, "meli_pct": 0}]}).json()["filas"][0]
    assert s["margenes"] == f["margenes"]


def test_simular_juega_el_total_y_ml_mantiene_su_aporte(cli):
    fila = {"item_id": "MLA9", "sku": "SKU-1", "precio_original": 10000, "descuento_pct": 10, "meli_pct": 0.5, "editable": True}
    f = cli.post("/campanas-ml/simular", json={"filas": [fila]}).json()["filas"][0]
    assert f["precio_cliente"] == 9000 and f["precio_vendedor"] == 9050 and f["seller_pct"] == 9.5 and f["descuento_total_pct"] == 10
    # si ML informó el monto, manda sobre el %
    g = cli.post("/campanas-ml/simular", json={"filas": [dict(fila, meli_pct=None, meli_monto=100)]}).json()["filas"][0]
    assert g["meli_monto"] == 100 and g["seller_pct"] == 9.0 and g["precio_cliente"] == 9000


def test_el_contexto_de_costos_se_arma_una_vez_y_se_reutiliza(cli, monkeypatch):
    from rentabilidad import api
    llamadas = []
    monkeypatch.setattr(api, "_datos_sku_fn", lambda avisos: (llamadas.append(1), avisos.append("aviso de carga"),
                                                              (lambda sku: DatosSku(d("2"), d("1.21"), "Laura", "Insumo", None)))[2])
    fila = {"item_id": "MLA9", "sku": "SKU-1", "precio_original": 10000, "descuento_pct": 10, "meli_pct": 0, "editable": True}
    a = cli.post("/campanas-ml/simular", json={"filas": [fila]}).json()
    b = cli.post("/campanas-ml/simular", json={"filas": [fila]}).json()
    assert len(llamadas) == 1 and a["avisos"] == b["avisos"] == ["aviso de carga"]


def test_analizar_devuelve_los_parametros_y_el_costo_para_recalcular_en_la_pantalla(cli):
    j = cli.post("/campanas-ml/analizar", files={"archivo": ("a.xlsx", _ml_sintetico())}).json()
    m = j["motor_ml"]
    assert m["comision"] == 0.155 and m["umbral_envio"] == 33000 and m["cuotas"]["contado"] == 0 and m["cuotas"]["3"] > 0
    assert m["tramos_costo_fijo"][0] == {"desde": 0.0, "hasta": 16000.0, "valor": 1330.0}
    assert j["filas"][1]["calc"] == {"costo": 3000.0, "costo_usd": 2.0, "iva": 1.21, "envio": 0.0, "comision": 0.155}


def test_analizar_lee_la_comision_real_de_ml_y_simular_respeta_la_que_manda_la_pantalla(cli, monkeypatch):
    import campanas_ml_comision
    monkeypatch.setattr(campanas_ml_comision, "comisiones", lambda items: (
        {i: {"pct": d("0.15"), "categoria": "MLA-X", "tipo": "gold_special", "raw": {}} for i in items}, []))
    j = cli.post("/campanas-ml/analizar", files={"archivo": ("a.xlsx", _ml_sintetico())}).json()
    f = j["filas"][1]
    assert f["comision_pct"] == 15.0 and f["comision_origen"] == "ml" and f["calc"]["comision"] == 0.15
    assert j["comisiones_ml"] == [["MLA-X", "gold_special", 15.0]]
    # la pantalla manda la comisión que usó en la vista previa: el backend confirma con ESA, no con la tabla
    fila = {"item_id": "MLA9", "sku": "SKU-1", "precio_original": 10000, "descuento_pct": 10, "meli_pct": 0, "editable": True}
    a = cli.post("/campanas-ml/simular", json={"filas": [dict(fila, comision=0.15, comision_origen="ml")]}).json()["filas"][0]
    b = cli.post("/campanas-ml/simular", json={"filas": [fila]}).json()["filas"][0]
    assert a["comision_pct"] == 15.0 and a["comision_origen"] == "ml" and b["comision_pct"] == 15.5
    assert a["margenes"]["contado"]["margen"] > b["margenes"]["contado"]["margen"]


def test_si_ml_no_responde_cae_a_la_tabla_y_avisa(cli, monkeypatch):
    import campanas_ml_comision

    def boom(items):
        raise RuntimeError("sin red")
    monkeypatch.setattr(campanas_ml_comision, "comisiones", boom)
    j = cli.post("/campanas-ml/analizar", files={"archivo": ("a.xlsx", _ml_sintetico())}).json()
    assert any("No se pudo leer la comisión real de ML" in a for a in j["avisos"])
    assert j["filas"][1]["comision_origen"] in ("categoria", "general")
