"""Mercado Libre en el Motor: comisión 15,5 %, costo por orden de Ecom y costo fijo por unidad vendida (< $33.000) como parte de la cuenta."""
from decimal import Decimal as D

import ayala_core as ac


def _p(costo, renta="30", **kw):
    return ac.calcular_precio_condicion(costo_sin_iva=D(costo), iva_factor=D("1.21"), envio_real=D(0), financiero_pct=D(0), renta_pct=D(renta),
                                        costo_orden=ac.COSTO_ORDEN_ECOM_DEFAULT, **kw)


def test_valores_vigentes():
    assert ac.COMISION_ML_DEFAULT == D("15.5") and ac.COSTO_ORDEN_ECOM_DEFAULT == D("149.12")
    assert [m for _, m in ac.COSTO_FIJO_ML_TRAMOS] == [D(1330), D(2740), D(3320), D(0)]


def test_costo_fijo_para_precio_por_tramo():
    f = ac.costo_fijo_para_precio
    assert [f(D(x)) for x in (1000, 14999, 15000, 23999, 24000, 32999, 33000, 100000)] == [1330, 1330, 2740, 2740, 3320, 3320, 0, 0]


def test_el_precio_cumple_la_renta_con_el_costo_fijo_de_su_tramo():
    """Un ticket bajo: el costo fijo importa mucho. Con el precio resultante, lo que sobra (sin IVA) es la renta pedida de ese tramo."""
    for costo in ("3000", "9000", "13000", "20000", "60000"):
        p = _p(costo, costo_fijo_tramos=ac.COSTO_FIJO_ML_TRAMOS)
        fijo = ac.costo_fijo_para_precio(p)
        sobra = p / D("1.21") - p * D("0.155") / D("1.21") - p / D("1.21") * D("0.05") - p * D("0.012") - D(costo) - ac.COSTO_ORDEN_ECOM_DEFAULT - fijo
        assert sobra >= p * D("0.30") - D("1"), (costo, p, fijo)                # alcanza la renta pedida (en el borde de un escalón sobra un poco)
        if p not in (D(15000), D(24000), D(33000)):
            assert abs(sobra - p * D("0.30")) < D("1"), (costo, p, fijo)       # lejos de un escalón da exacto


def test_el_costo_fijo_sube_el_precio_solo_por_debajo_de_33000():
    sin = _p("3000"); con = _p("3000", costo_fijo_tramos=ac.COSTO_FIJO_ML_TRAMOS)
    assert con > sin and (con - sin) > 1330                                  # no solo el monto: también lo que se lleva en comisión e impuestos
    grande_sin, grande_con = _p("80000"), _p("80000", costo_fijo_tramos=ac.COSTO_FIJO_ML_TRAMOS)
    assert grande_sin == grande_con                                           # por encima de $33.000 no hay costo fijo


def test_el_precio_es_el_minimo_que_alcanza_la_renta_en_el_borde_de_un_tramo():
    """Si con el costo del tramo de abajo el precio se pasa del techo, vale el del tramo siguiente (no hay precios entre medio que cumplan)."""
    for costo in range(9000, 30000, 750):
        p = _p(str(costo), costo_fijo_tramos=ac.COSTO_FIJO_ML_TRAMOS)
        anterior = _p(str(costo), renta="30")   # sin costo fijo: cota inferior
        assert p >= anterior
        p_menos_uno = p - 1
        fijo = ac.costo_fijo_para_precio(p_menos_uno)
        sobra = p_menos_uno / D("1.21") - p_menos_uno * D("0.155") / D("1.21") - p_menos_uno / D("1.21") * D("0.05") - p_menos_uno * D("0.012") - D(costo) - ac.COSTO_ORDEN_ECOM_DEFAULT - fijo
        assert sobra < p_menos_uno * D("0.30") + D("1")                      # un peso menos ya no alcanza (a menos del redondeo)


def test_el_espejo_js_da_el_mismo_precio_que_el_backend():
    from test_front_analisis import _fn, INDEX
    import json, subprocess
    from decimal import Decimal as D
    import ayala_core as ac
    src = open(INDEX, encoding='utf-8').read()
    js = ("const AC_COMISION_PCT=15.5, AC_COSTO_ORDEN=149.12, AC_COSTO_FIJO_TRAMOS=[[15000,1330],[24000,2740],[33000,3320],[null,0]], AC_IIBB_PCT=5, AC_IMPCH_PCT=1.2, AC_IVA_SERVICIOS_ML=1.21;\n"
          + _fn(src, "ayalaCoreCostoFijo") + _fn(src, "ayalaCoreCalcularPrecioJS")
          + "console.log(JSON.stringify([2000,9000,15000,21000,30000,60000].map(c=>ayalaCoreCalcularPrecioJS(c,1.21,0,0,30))));")
    out = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
    esperado = [int(ac.calcular_precio_condicion(costo_sin_iva=D(c), iva_factor=D("1.21"), envio_real=D(0), financiero_pct=D(0), renta_pct=D(30), costo_orden=ac.COSTO_ORDEN_ECOM_DEFAULT, costo_fijo_tramos=ac.COSTO_FIJO_ML_TRAMOS)) for c in (2000, 9000, 15000, 21000, 30000, 60000)]
    assert out == esperado
