"""Reportes del motor de precios para n8n: desvío de precios (Maca) y
control de ofertas (Natalia)."""
from contextlib import contextmanager
from datetime import date

import pytest

from rentabilidad import api, motor_precios as motor, reportes_pricing as rp
from rentabilidad.ingesta_ecom_api import _cargo_cuotas_vendedor, _cuotas_del_pago
from rentabilidad.models import PricingSku, VentaEcom

from .conftest import d
from .test_fravega import db_multihilo  # noqa: F401 (fixture)

HOY = date(2026, 10, 3)
P = "2026-09-23_2026-10-22"
TC = d("1540")


def _precio(db, sku="TONER-1", web="100000", pct="1.2", cargado_por="Sheet Verónica"):
    db.add(PricingSku(sku=sku, precio_web=d(web), pct_ml=d(pct), forma_pago_web="1", condicion_ml="contado",
                      vigente_desde=date(2026, 9, 1), cargado_por=cargado_por))


def _real(db, orden, precio_unit, unidades=1, canal="Mercadolibre", sku="TONER-1", cargo_cuotas=None, cuotas=1,
          es_full=False, costo_usd="30", envio="0", proy_igual=True):
    """Venta guardada con la rentabilidad que daría el motor a ese precio
    (con un ajuste opcional para simular cargos de más)."""
    iva = d("1.21")
    par = motor.cargar_parametros(db, HOY)
    pf = d(precio_unit) * unidades
    canal_motor = "ML" if canal.startswith("Mercadolibre") else "WEB"
    r = motor.precio_a_margen(d(precio_unit), motor.EntradaMotor(
        canal=canal_motor, costo=d(costo_usd) * TC, iva_factor=iva, categoria="Insumo De Impresion",
        cuotas_pct_final=(d(cargo_cuotas) / pf) if cargo_cuotas else d(0)), par)
    rent = r.rentabilidad * unidades - d("149.12") - d(envio)
    db.add(VentaEcom(
        periodo=P, numero_orden=orden, skus_vendidos=sku, canal_de_venta=canal, fecha_creacion_venta=date(2026, 10, 1),
        costo_sin_iva=d(costo_usd) * unidades, comision_venta=d(0), costo_envio=d(envio), precio_final=pf,
        precio_sin_iva=pf / iva, rentabilidad=rent, tc=TC, iva=iva, excluido=False, es_full=es_full,
        unidades=unidades, cuotas=cuotas, cargo_cuotas=d(cargo_cuotas) if cargo_cuotas else d(0),
        categoria="Insumo De Impresion", pm="Veronica",
    ))


def _fila(res, sku="TONER-1", canal="ML"):
    return next(f for f in res["filas"] if f["sku"] == sku and f["canal"] == canal)


# ── Desvío de precios (Maca) ──

def test_venta_a_precio_del_pm_no_tiene_desvio(db_session):
    _precio(db_session)
    _real(db_session, "1", "120009", unidades=2)  # ML del PM: ROUNDDOWN(100000 × 1,2) + 9
    db_session.flush()
    f = _fila(rp.desvio_precios(db_session, P, HOY))
    assert f["diferencia_pts"] == 0 and not f["revisar"] and f["precio_pm"] == 120009
    assert f["pm"] == "Veronica" and f["unidades"] == 2


def test_vendiendo_barato_se_marca_con_prioridad_1(db_session):
    _precio(db_session)
    _real(db_session, "1", "90009")
    db_session.flush()
    f = _fila(rp.desvio_precios(db_session, P, HOY))
    assert f["revisar"] and f["prioridad"] == 1 and f["motivo"] == "precio_por_debajo_del_pm"
    assert f["diferencia_pts"] < -5 and f["diferencia_precio_pct"] == pytest.approx(-25, abs=0.1)


def test_venta_en_cuotas_no_se_marca_por_pagar_cuotas(db_session):
    _precio(db_session)
    _real(db_session, "1", "120009", cargo_cuotas=str(d("120009") * d("0.134")), cuotas=6)  # 6 cuotas, 13,4%
    db_session.flush()
    f = _fila(rp.desvio_precios(db_session, P, HOY))
    assert f["diferencia_pts"] == 0 and not f["revisar"] and f["ordenes_en_cuotas"] == 1


def test_precio_inflado_por_cuotas_no_se_marca_aunque_el_margen_baje(db_session):
    _precio(db_session)
    _real(db_session, "1", "140009", cargo_cuotas=str(d("140009") * d("0.216")), cuotas=12)
    db_session.flush()
    db_session.query(VentaEcom).one().rentabilidad -= d("30000")
    db_session.flush()
    f = _fila(rp.desvio_precios(db_session, P, HOY))
    assert f["diferencia_pts"] < -5 and not f["revisar"] and f["motivo"] == "precio_inflado_por_cuotas"


def test_cargos_de_mas_con_precio_correcto_es_prioridad_2(db_session):
    _precio(db_session)
    _real(db_session, "1", "120009")
    db_session.flush()
    db_session.query(VentaEcom).one().rentabilidad -= d("15000")  # ej. comisión más alta que la de la categoría
    db_session.flush()
    f = _fila(rp.desvio_precios(db_session, P, HOY))
    assert f["revisar"] and f["prioridad"] == 2 and f["motivo"] == "cargos_o_costo_mayores_al_proyectado"


def test_ml_se_compara_sin_envio(db_session):
    _precio(db_session)
    _real(db_session, "1", "120009", envio="9000")
    db_session.flush()
    assert _fila(rp.desvio_precios(db_session, P, HOY))["diferencia_pts"] == 0


def test_web_usa_el_precio_web_y_excluye_full_fravega_kits(db_session):
    _precio(db_session)
    _real(db_session, "1", "100000", canal="Woocommerce")
    _real(db_session, "2", "120009", es_full=True)
    _real(db_session, "3", "120009", canal="Fravega")
    _real(db_session, "4", "120009", sku="TONER-1, OTRO")
    db_session.flush()
    res = rp.desvio_precios(db_session, P, HOY)
    assert [(f["sku"], f["canal"]) for f in res["filas"]] == [("TONER-1", "WEB")]
    assert _fila(res, canal="WEB")["diferencia_pts"] == 0
    assert res["resumen"]["excluidas_full"] == 1 and res["resumen"]["excluidas_kits_o_carritos"] == 1


def test_umbral_orden_y_solo_revisar(db_session):
    _precio(db_session)
    _precio(db_session, sku="TONER-2")
    _precio(db_session, sku="TONER-3")
    _real(db_session, "1", "120009")
    _real(db_session, "2", "100009", sku="TONER-2")
    _real(db_session, "3", "80009", sku="TONER-3")
    _real(db_session, "4", "120009", sku="SIN-PRECIO")
    db_session.flush()
    res = rp.desvio_precios(db_session, P, HOY)
    assert [f["sku"] for f in res["filas"]] == ["TONER-3", "TONER-2", "TONER-1"]
    assert res["sin_precio_pm"] == ["SIN-PRECIO"]
    assert [f["sku"] for f in rp.desvio_precios(db_session, P, HOY, solo_revisar=True)["filas"]] == ["TONER-3", "TONER-2"]
    assert rp.desvio_precios(db_session, P, HOY, umbral_pts=d(100))["resumen"]["a_revisar"] == 0


def test_orden_sin_unidades_se_avisa(db_session):
    _precio(db_session)
    _real(db_session, "1", "120009")
    db_session.flush()
    db_session.query(VentaEcom).one().unidades = None
    db_session.flush()
    res = rp.desvio_precios(db_session, P, HOY)
    assert res["filas"] == [] and "próxima corrida" in res["avisos"][0]


# ── Datos de cuotas de la API de Ecom ──

def test_cuotas_y_cargo_de_cuotas_de_la_orden():
    orden = {"payments": [{"transactionAmount": 60000, "installmentAmount": 10000, "details": {"charges_details": [
        {"name": "financing_add_on_fee", "accounts": {"from": "collector"}, "amounts": {"original": 8040, "refunded": 0}},
        {"name": "financing_fee", "accounts": {"from": "payer"}, "amounts": {"original": 999}},
        {"name": "meli_percentage_fee", "accounts": {"from": "collector"}, "amounts": {"original": 9000}},
    ]}}]}
    assert _cuotas_del_pago(orden) == 6
    assert _cargo_cuotas_vendedor(orden) == d("8040")
    assert _cuotas_del_pago({"payments": [{"transactionAmount": 1}]}) is None
    assert _cargo_cuotas_vendedor({"payments": [{"details": None}]}) is None


# ── Control de ofertas (Natalia) ──

def _oferta(sku, oferta, normal="150000", cuotas=None, **k):
    return {"sku": sku, "precio_oferta": oferta, "precio_normal": normal, "cuotas_ofrecidas": cuotas,
            "cuenta": "IT", "item_id": "MLA1", "descuento_pct": 20, **k}


def test_ofertas_contra_precio_base_del_pm(db_session):
    _precio(db_session)  # base ML 120.009
    _precio(db_session, sku="T2")
    _precio(db_session, sku="T3")
    _precio(db_session, sku="T4")
    db_session.flush()
    res = rp.control_ofertas(db_session, [
        _oferta("toner-1", 120009), _oferta("T2", 99000), _oferta("T3", 130000),
        _oferta("T4", 130000, cuotas=6), _oferta("NO-EXISTE", 1), _oferta(None, 1),
    ], HOY)
    est = {f["sku"]: f for f in res["filas"]}
    assert est["TONER-1"]["estado"] == "ok" and not est["TONER-1"]["revisar"]
    assert est["T2"]["estado"] == "por_debajo" and est["T2"]["prioridad"] == 1 and est["T2"]["diferencia"] == -21009
    assert est["T3"]["estado"] == "por_encima" and est["T3"]["prioridad"] == 2
    assert est["T4"]["estado"] == "por_encima_con_cuotas" and not est["T4"]["revisar"]
    assert est["T2"]["descuento_que_cuadra_pct"] == 19.99 and est["T2"]["pm"] == "Verónica"
    assert [f["sku"] for f in res["filas"]][:2] == ["T2", "T3"]
    assert res["sin_precio_pm"] == ["NO-EXISTE"] and res["resumen"]["sin_sku"] == 1


# ── Endpoints ──

@pytest.fixture()
def cliente(db_multihilo, monkeypatch):  # noqa: F811
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    @contextmanager
    def _sesion():
        yield db_multihilo
        db_multihilo.flush()

    monkeypatch.setattr(api, "sesion", _sesion)
    monkeypatch.setattr(api, "_periodo_en_curso", lambda: P)
    monkeypatch.setenv("RENT_REPORTE_TOKEN", "secreto")
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def test_endpoints_con_token(cliente, db_multihilo, monkeypatch):
    _precio(db_multihilo)
    _real(db_multihilo, "1", "90009")
    db_multihilo.flush()
    url = "/rentabilidad/reporte/pricing/desvio-precios"
    assert cliente.get(url).status_code == 401
    r = cliente.get(url, headers={"X-Reporte-Token": "secreto"}, params={"umbral_pts": 3})
    assert r.status_code == 200, r.text
    assert r.json()["filas"][0]["revisar"] and r.json()["umbral_pts"] == 3

    monkeypatch.setattr(api, "_ofertas_ml_activas", lambda incluir_propias: [_oferta("TONER-1", 99000)])
    r = cliente.get("/rentabilidad/reporte/pricing/ofertas", params={"token": "secreto"})
    assert r.status_code == 200, r.text
    assert r.json()["filas"][0]["estado"] == "por_debajo"

    def falla(incluir_propias):
        raise RuntimeError("sin token de ML")
    monkeypatch.setattr(api, "_ofertas_ml_activas", falla)
    assert cliente.get("/rentabilidad/reporte/pricing/ofertas", params={"token": "secreto"}).status_code == 502
