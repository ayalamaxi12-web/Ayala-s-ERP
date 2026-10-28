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
             _fila(ITEM_ID="MLA4", SELLER_PERCENTAGE=4.5, MELI_PERCENTAGE=None, DISCOUNT_PERCENTAGE=4.5, editable=False)]
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


# ── Validación contra el "Recibís" (NEW_RECEIVES) del Excel real de Día de la Madre ──
# (precio de lista, precio final, Recibís de ML, extra fijo del primer tramo). Sin aporte de ML, contado.
# El "Recibís" del Excel = final − comisión 15,5% − costo fijo − 0,904% del final (impuestos/retenciones
# que ML descuenta aparte) y, en el primer tramo, $60 más (a verificar con una venta real). La comisión
# 15,5% y el costo fijo de 2.740 coinciden con una venta real desglosada por ML.
_RECIBIS_ML = [(10499, "9974.05", "6947.91", 60), (19459, "18486.05", "12713.59", 0),
               (10499, "8159", "5430.60", 60), (22499, "15117", "9897.21", 0)]


@pytest.mark.parametrize("lista,final,recibis,extra", _RECIBIS_ML)
def test_recibis_de_ml_es_el_motor_menos_0_904_pct_del_precio(par, lista, final, recibis, extra):
    r = cm.margen_oferta(d(final), d(final), "contado", d("1000"), d("1.21"), par, d(0), lista)
    assert abs(r.cargos["comision"] - d(final) * d("0.155")) <= d("0.01")  # la comisión NO cambia: 15,5%
    esperado = cm.recibis(r, d(final)) - extra   # recibis ya descuenta el 0,904% de impuestos de ML
    assert abs(float(esperado) - float(recibis)) < 0.05


def test_venta_real_de_ml_comision_y_costo_fijo(par):
    # Venta real TN1060COMP: $21.202,80 → cargo por vender 15,5% = 3.286,43 + costo fijo 2.740
    r = cm.margen_oferta(d("21202.80"), d("21202.80"), "contado", d("1000"), d("1.21"), par)
    assert r.cargos["comision"] == d("3286.43") and r.cargos["costo_fijo"] == d("2740.00")


def test_el_tramo_del_costo_fijo_es_el_de_la_lista_no_el_rebajado(par):
    # lista 22.499 (tramo 2.740) con precio final 14.900 (< 15.000, tramo 1.330 si fuera por el final)
    r = cm.margen_oferta(d("14900"), d("14900"), "contado", d("1000"), d("1.21"), par, d(0), 22499)
    assert r.cargos["costo_fijo"] == 2740
    assert cm.margen_oferta(d("14900"), d("14900"), "contado", d("1000"), d("1.21"), par, d(0)).cargos["costo_fijo"] == 1330


def test_envio_por_umbral_de_la_lista(par):
    # fila #4: lista 34.403 (≥ 33.000) con final 32.682,85: ML cobra envío y no costo fijo
    r = cm.margen_oferta(d("32682.85"), d("32682.85"), "contado", d("1000"), d("1.21"), par, d("14265.7"), 34403)
    assert r.cargos["envio"] == d("14265.70") and r.cargos["costo_fijo"] == 0
    assert abs(float(cm.recibis(r, d("32682.85"))) - float(d("32682.85") * (1 - d("0.155") - cm.IMPUESTOS_ML_PCT) - d("14265.7"))) < 0.01


def test_analizar_expone_recibis_motor_vs_ml(db_session):
    f = _fila(ORIGINAL_PRICE=10499.0, SELLER_PERCENTAGE=5.0, SELLER_AMOUNT=524.95, MELI_PERCENTAGE=None, MELI_AMOUNT=None,
              FINAL_PRICE=9974.05, NEW_RECEIVES="$\xa06,947.91")
    r = _analizar(db_session, [f], {"PV-AB1": DatosSku(d("1"), d("1.21"), None, None, None)})["filas"][0]
    assert r["recibis_ml"] == 6947.91 and r["recibis_motor"] == 7007.9 and r["recibis_dif"] == 59.99   # los $60 del primer tramo


def test_la_regla_de_enteros_de_ml_es_sobre_el_descuento_total_no_sobre_el_del_vendedor(db_session):
    # real (Con aporte de ML): vendedor 4,5% + ML 0,5% = 5% total → válido aunque el vendedor tenga decimales
    ok = _fila(SELLER_PERCENTAGE=4.5, MELI_PERCENTAGE=0.5, DISCOUNT_PERCENTAGE=5.0)
    mal = _fila(ITEM_ID="MLA2", SELLER_PERCENTAGE=4.5, MELI_PERCENTAGE=0.7, DISCOUNT_PERCENTAGE=5.2)
    r = _analizar(db_session, [ok, mal], {})["filas"]
    assert not any("TOTAL" in a for a in r[0]["avisos"]) and r[0]["descuento_total_pct"] == 5.0
    assert any("TOTAL entero" in a for a in r[1]["avisos"])


def test_pct_max_es_el_total_y_el_vendedor_pone_el_resto(par):
    costo, iva = d("2000"), d("1.21")
    sin_ml = cm.pct_max_para_margen(10000, 0, d("0.20"), "contado", costo, iva, par)
    con_ml = cm.pct_max_para_margen(10000, 2, d("0.20"), "contado", costo, iva, par)
    assert isinstance(con_ml, int) and con_ml >= sin_ml  # con aporte de ML se puede dar más descuento total
    o = cm.precios_oferta(10000, seller_pct=con_ml - 2, meli_pct=2)
    assert cm.margen_oferta(o["precio_vendedor"], o["precio_cliente"], "contado", costo, iva, par).margen >= d("0.20")
    assert cm.pct_max_para_margen(10000, 6, d("0.20"), "contado", d("9500"), iva, par) is None


def test_el_aporte_de_ml_es_un_monto_fijo_y_el_pct_max_lo_respeta(db_session):
    # real (Con aporte de ML): lista 41.699, ML pone $202,35 (el 0,5% del Excel viene redondeado: es 0,4853%)
    f = _fila(ORIGINAL_PRICE=41699.0, SELLER_PERCENTAGE=4.5, SELLER_AMOUNT=1882.6, MELI_PERCENTAGE=0.5, MELI_AMOUNT=202.35,
              DISCOUNT_PERCENTAGE=5.0, FINAL_PRICE=39614.05)
    r = _analizar(db_session, [f], {"PV-AB1": DatosSku(d("2"), d("1.21"), None, None, None)}, margen_objetivo=d("0.05"))["filas"][0]
    assert r["meli_monto"] == 202.35 and r["precio_cliente"] == 39614.05
    t = r["pct_max_para_margen"]
    assert t is not None
    # con ese total, ML sigue poniendo $202,35 (no el 0,5% redondeado): vendedor = total − 0,4853%
    o = cm.precios_oferta(41699, seller_pct=t - 202.35 / 41699 * 100, meli_monto=202.35)
    assert abs(float(o["precio_cliente"]) - 41699 * (1 - t / 100)) < 0.01


def test_la_comision_es_la_unica_del_criterio_y_no_depende_de_la_categoria(par):
    """Criterios de precio: 15,5% único para ML. La tabla por categoría ya no se usa."""
    for cat in ("Comercial y Oficinas", " comercial y oficinas ", "Insumo De Impresion", "Categoría nueva", None):
        assert cm.comision_de(par, cat) == (d("0.155"), "general")


def test_analizar_usa_la_comision_unica_aunque_la_categoria_tenga_fila(db_session):
    datos = {"PV-AB1": DatosSku(d("2"), d("1.21"), None, "Comercial y Oficinas", None)}
    r = _analizar(db_session, [_fila()], datos)["filas"][0]
    assert r["comision_pct"] == 15.5 and r["comision_origen"] == "general" and r["calc"]["comision"] == 0.155


def test_la_comision_real_de_ml_manda_sobre_la_tabla(db_session):
    """SEW-MINI: 'Textil' en la planilla, 'Electrodomésticos y Aires Ac.' en ML, 15% real. La real gana a la tabla y a la general."""
    datos = {"PV-AB1": DatosSku(d("2"), d("1.21"), None, "Textil", None)}
    real = _analizar(db_session, [_fila(comision_real=d("0.15"), comision_origen="ml")], datos)["filas"][0]
    assert real["comision_pct"] == 15.0 and real["comision_origen"] == "ml" and real["calc"]["comision"] == 0.15
    assert not any("Comisión ML" in a for a in real["avisos"])
    tabla = _analizar(db_session, [_fila()], datos)["filas"][0]                  # sin dato real: 'Textil' no está → general 15,5%
    assert tabla["comision_pct"] == 15.5 and tabla["comision_origen"] == "general"
    assert real["margenes"]["contado"]["margen"] > tabla["margenes"]["contado"]["margen"]
    assert cm.comision_de(m.cargar_parametros(db_session, HOY), "Textil", d("0.15")) == (d("0.15"), "ml")


def test_electrodomesticos_quedo_en_15_con_vigencia_nueva(db_session, par):
    """Corrección con la venta real de SEW-MINI: fila nueva con vigencia, la de 14% queda en el historial."""
    from rentabilidad.motor_precios import cargar_parametros
    assert par.comision_categoria[("ML", "electrodomesticos")] == d("0.14")                        # antes de la vigencia
    assert cargar_parametros(db_session, date(2026, 10, 14)).comision_categoria[("ML", "electrodomesticos")] == d("0.15")
    from rentabilidad.models import PricingComisionCategoria as C
    filas = db_session.query(C).filter(C.categoria == "Electrodomesticos").all()
    assert sorted(f.pct for f in filas) == [d("0.14"), d("0.15")]
    from rentabilidad import seed
    seed.seed(db_session)       # idempotente: no duplica el ajuste
    assert db_session.query(C).filter(C.categoria == "Electrodomesticos").count() == 2


# ── Combos y cantidades en el SKU de ML («INKCARTHP74XL INKCARTHP75XL», «X2 CB435A…») ──

def test_descomponer_sku_cantidades_y_combos():
    assert cm.descomponer_sku("PLANCHA-SUB-GORRA") == [("PLANCHA-SUB-GORRA", 1)]
    assert cm.descomponer_sku("X2 CB435A-436A-CE285AUNIVCOMP") == [("CB435A-436A-CE285AUNIVCOMP", 2)]
    assert cm.descomponer_sku("X10 AUTOR-80G-A4") == [("AUTOR-80G-A4", 10)] and cm.descomponer_sku("X2-CF230ACOMP") == [("CF230ACOMP", 2)]
    assert cm.descomponer_sku("INKCARTHP74XL INKCARTHP75XL") == [("INKCARTHP74XL", 1), ("INKCARTHP75XL", 1)]
    assert cm.descomponer_sku("EMERLIGHT-60LED, EMERLIGHT-60LED") == [("EMERLIGHT-60LED", 2)]      # repetido = cantidad
    assert cm.descomponer_sku("") == []


def _precio_pm(db, sku, web, pct="1.3"):
    db.add(PricingSku(sku=sku, precio_web=d(web), pct_ml=d(pct), forma_pago_web="1", condicion_ml="contado",
                      vigente_desde=date(2026, 9, 1), cargado_por="Sheet Laura"))


def test_combo_suma_costo_y_precio_pm_de_sus_componentes(db_session):
    _precio_pm(db_session, "AAA", "7000")
    _precio_pm(db_session, "BBB", "3000")
    db_session.flush()
    datos = {"AAA": DatosSku(d("2"), d("1.21"), "Laura", "Insumo", None), "BBB": DatosSku(d("3"), d("1.21"), "Veronica", "Insumo", None)}
    solo = _analizar(db_session, [_fila(SKU="AAA")], datos)["filas"][0]
    r = _analizar(db_session, [_fila(SKU="AAA BBB")], datos)["filas"][0]
    assert r["combo"] == [{"sku": "AAA", "cantidad": 1}, {"sku": "BBB", "cantidad": 1}] and r["sku"] == "AAA + BBB"
    assert r["calc"]["costo_usd"] == 5.0 and r["pm"] == "Laura"                          # 2 + 3 USD
    assert r["precio_pm"] > solo["precio_pm"] and not any("Sin costo" in a for a in r["avisos"])
    assert r["margenes"]["contado"]["margen"] != solo["margenes"]["contado"]["margen"]


def test_sku_con_cantidad_multiplica_el_costo(db_session):
    _precio_pm(db_session, "AAA", "7000")
    db_session.flush()
    datos = {"AAA": DatosSku(d("2"), d("1.21"), "Laura", "Insumo", None)}
    uno = _analizar(db_session, [_fila(SKU="AAA")], datos)["filas"][0]
    dos = _analizar(db_session, [_fila(SKU="X2 AAA")], datos)["filas"][0]
    assert dos["calc"]["costo_usd"] == 4.0 and dos["sku"] == "2×AAA"
    assert dos["precio_pm"] == round(uno["precio_pm"] * 2, 2) or abs(dos["precio_pm"] - uno["precio_pm"] * 2) < 20   # el PM ML por unidad × 2 (redondeo a decena)


def test_combo_con_un_componente_sin_costo_no_inventa_y_dice_cual(db_session):
    _precio_pm(db_session, "AAA", "7000")
    db_session.flush()
    r = _analizar(db_session, [_fila(SKU="AAA BBB")], {"AAA": DatosSku(d("2"), d("1.21"), "Laura", "Insumo", None)})["filas"][0]
    assert r["margenes"] == {} and any("sin costo vigente en Ecom de BBB" in a for a in r["avisos"]) and any("sin precio en el PM de BBB" in a for a in r["avisos"])


def test_un_sku_con_espacio_propio_sigue_siendo_uno_solo(db_session):
    _precio_pm(db_session, "PV-AB 1", "7000")
    db_session.flush()
    r = _analizar(db_session, [_fila(SKU="PV-AB 1")], {"PV-AB1": DatosSku(d("2"), d("1.21"), "Laura", "Insumo", None)})["filas"][0]
    assert r["sku"] == "PV-AB1" and "combo" not in r and r["margenes"]
