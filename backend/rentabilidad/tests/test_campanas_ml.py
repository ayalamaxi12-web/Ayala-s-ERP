"""Campañas ML: el margen de una oferta con aporte de ML se calcula sobre el precio
del descuento del VENDEDOR; comisión/cuotas/costo fijo/envío, sobre lo que paga el cliente."""
from datetime import date
from decimal import Decimal

import pytest

from rentabilidad import campanas_ml as cm, motor_precios as m
from rentabilidad.models import PricingSku
from rentabilidad.pricing_pm import DatosSku

from .conftest import d

HOY = date(2026, 10, 13)
TC = d("1500")


@pytest.fixture()
def par(db_session):
    return m.cargar_parametros(db_session, HOY)


def test_precios_ejemplo_del_usuario():
    # lista 10.000, total 10%: vendedor 9,5% y ML 0,5% → cliente 9.000, precio del vendedor 9.050
    o = cm.precios_oferta(10000, seller_pct=Decimal("9.5"), meli_pct=Decimal("0.5"))
    assert (o["seller_monto"], o["meli_monto"]) == (d("950"), d("50"))
    assert o["precio_vendedor"] == d("9050") and o["precio_cliente"] == d("9000")


def test_precios_coinciden_con_filas_reales_del_excel():
    o = cm.precios_oferta(75303.1, seller_pct=1.5, seller_monto=1129.55, meli_pct=3.5, meli_monto=2635.61)
    assert float(o["precio_cliente"]) == pytest.approx(71537.94, abs=0.005)
    o = cm.precios_oferta(148039.0, seller_monto=51140.7, meli_monto=4614.2)
    assert float(o["precio_cliente"]) == pytest.approx(92284.1, abs=0.005)


def test_sin_aporte_de_ml_es_el_motor_de_siempre(par):
    e = m.EntradaMotor(canal="ML", costo=d("4000"), iva_factor=d("1.21"), plan="3")
    base = m.precio_a_margen(d("9000"), e, par)
    r = cm.margen_oferta(d("9000"), d("9000"), "3", d("4000"), d("1.21"), par)
    assert r.margen == base.margen and r.cargos == base.cargos


def test_con_aporte_de_ml_la_cuenta_separa_las_bases(par):
    r = cm.margen_oferta(d("9050"), d("9000"), "3", d("4000"), d("1.21"), par)
    iva = 1 + par.valor("ML", "iva_cargos")
    n = d("9050") / d("1.21")
    assert r.venta_sin_iva == n.quantize(d("0.01"))
    assert r.cargos["comision"] == (d("9000") * par.valor("ML", "comision_general") * iva).quantize(d("0.01"))
    assert r.cargos["cuotas"] == (d("9000") * par.cuota("ML", "3") * iva).quantize(d("0.01"))
    assert r.cargos["imp_cheque"] == (d("9050") * par.valor("ML", "imp_cheque")).quantize(d("0.01"))
    assert r.cargos["iibb"] == (n * par.valor("ML", "iibb")).quantize(d("0.01"))
    # ML acredita su parte: mejor margen que si el cliente pagara 9.000 sin aporte
    sin = cm.margen_oferta(d("9000"), d("9000"), "3", d("4000"), d("1.21"), par)
    assert r.margen > sin.margen


def test_costo_fijo_y_envio_siguen_al_precio_del_cliente(par):
    # el vendedor queda en 33.100 pero el cliente paga 32.900: aplica costo fijo y no envío
    r = cm.margen_oferta(d("33100"), d("32900"), "contado", d("10000"), d("1.21"), par, envio=d("8500"))
    assert r.cargos["envio"] == 0 and r.cargos["costo_fijo"] > 0
    r2 = cm.margen_oferta(d("33100"), d("33100"), "contado", d("10000"), d("1.21"), par, envio=d("8500"))
    assert r2.cargos["envio"] == 8500 and r2.cargos["costo_fijo"] == 0


def test_margen_a_precio_rechaza_precio_cliente(par):
    e = m.EntradaMotor(canal="ML", costo=d("100"), iva_factor=d("1.21"), precio_cliente=d("90"))
    with pytest.raises(ValueError):
        m.margen_a_precio(d("0.2"), e, par)


def test_pct_max_para_margen_es_entero_y_cumple(par):
    costo, iva = d("2000"), d("1.21")
    n = cm.pct_max_para_margen(10000, 0, d("0.20"), "contado", costo, iva, par)
    assert isinstance(n, int) and 5 <= n <= 80
    o = cm.precios_oferta(10000, seller_pct=n)
    assert cm.margen_oferta(o["precio_vendedor"], o["precio_cliente"], "contado", costo, iva, par).margen >= d("0.20")
    o = cm.precios_oferta(10000, seller_pct=n + 1)
    assert cm.margen_oferta(o["precio_vendedor"], o["precio_cliente"], "contado", costo, iva, par).margen < d("0.20")
    # costo imposible: ni el 5% alcanza
    assert cm.pct_max_para_margen(10000, 0, d("0.20"), "contado", d("9500"), iva, par) is None


def _fila(**k):
    base = {"fila": 6, "ITEM_ID": "MLA1", "SKU": "PV-AB 1", "TITLE": "Toner", "editable": True, "STATUS": "Nueva propuesta",
            "ACTION": "Aplicar propuesta", "ORIGINAL_PRICE": 10000.0, "SELLER_AMOUNT": None, "SELLER_PERCENTAGE": 9.0,
            "MELI_AMOUNT": None, "MELI_PERCENTAGE": 1.0, "DISCOUNT_PERCENTAGE": 10.0, "FINAL_PRICE": 9000.0, "NEW_RECEIVES": "$ 1"}
    return {**base, **k}


def _analizar(db, filas, datos, **k):
    return cm.analizar(db, filas, HOY, TC, lambda s: datos.get(s, DatosSku(None, None, None, None, None)),
                       m.cargar_parametros(db, HOY), **k)


def test_analizar_cruza_pm_costo_y_margenes_por_cuota(db_session):
    db_session.add(PricingSku(sku="PV-AB 1", precio_web=d("7000"), pct_ml=d("1.3"), forma_pago_web="1", condicion_ml="contado",
                              vigente_desde=date(2026, 9, 1), cargado_por="Sheet Laura"))
    db_session.flush()
    datos = {"PV-AB1": DatosSku(d("2.5"), d("1.21"), "Laura", "Insumo", None)}
    r = _analizar(db_session, [_fila()], datos)
    f = r["filas"][0]
    assert f["sku"] == "PV-AB1" and f["pm"] == "Laura" and f["precio_pm"] == 9109.0  # 7000 × 1,3 → 9100 + 9
    assert f["precio_vendedor"] == 9100.0 and f["precio_cliente"] == 9000.0 and f["costo"] == 3750.0
    assert list(f["margenes"]) == ["contado", "3", "6", "9", "12"]
    ms = [f["margenes"][p]["margen"] for p in ("contado", "3", "6", "9", "12")]
    assert ms == sorted(ms, reverse=True) and ms[0] > ms[-1]  # más cuotas, menos margen
    assert f["margen_contado_sin_aporte_ml"] < f["margenes"]["contado"]["margen"]
    assert f["descuento_que_cuadra_pct"] == pytest.approx(8.91)
    assert r["resumen"]["con_margen"] == 1


def test_analizar_avisos(db_session):
    datos = {"PV-AB1": DatosSku(None, None, None, None, None)}
    filas = [_fila(SKU=None), _fila(ITEM_ID="MLA2"), _fila(ITEM_ID="MLA3", SELLER_PERCENTAGE=None, MELI_PERCENTAGE=None),
             _fila(ITEM_ID="MLA4", SELLER_PERCENTAGE=4.5, editable=False)]
    r = _analizar(db_session, filas, datos)
    a = [x["avisos"] for x in r["filas"]]
    assert any("Sin SKU" in x for x in a[0])
    assert any("Sin precio en el PM" in x for x in a[1]) and any("Sin costo" in x for x in a[1])
    assert any("Sin descuento" in x for x in a[2])
    assert any("entero" in x for x in a[3]) and any("no editable" in x for x in a[3])
    assert r["resumen"]["sin_sku"] == 1 and r["resumen"]["con_margen"] == 0


def test_analizar_usa_los_montos_de_ml_porque_el_porcentaje_viene_redondeado(db_session):
    f = _fila(ORIGINAL_PRICE=148039.0, SELLER_PERCENTAGE=34.846, SELLER_AMOUNT=51140.7, MELI_PERCENTAGE=3.154,
              MELI_AMOUNT=4614.2, FINAL_PRICE=92284.1)
    r = _analizar(db_session, [f], {"PV-AB1": DatosSku(d("2"), d("1.21"), None, None, None)})
    assert r["filas"][0]["precio_cliente"] == 92284.1 and r["filas"][0]["precio_vendedor"] == 96898.3
