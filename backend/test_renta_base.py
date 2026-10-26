"""Base del % de renta (Bloque 2): «con IVA» es la de siempre (el motor original ya restaba el % de renta sobre el precio con IVA); «sin IVA» es opcional."""
import itertools
from decimal import Decimal as D

import pytest

import ayala_core as ac
import mercados as mk
from fastapi import HTTPException


def _kw(**o):
    base = dict(costo_sin_iva=D("20925"), iva_factor=D("1.105"), envio_real=D("0"), financiero_pct=D("6.8"), renta_pct=D("10"), comision_pct=D("15.5"),
                costo_orden=D("149.12"))
    base.update(o)
    return base


def test_con_iva_explicito_es_identico_al_de_siempre():
    for costo, iva, env, fin, r, full in itertools.product([D("5000"), D("20925"), D("700000")], [D("1.105"), D("1.21")], [D("0"), D("5000")], [D("0"), D("5"), D("16.6")], [D("10"), D("32")], (False, True)):
        kw = dict(costo_sin_iva=costo, iva_factor=iva, envio_real=env, financiero_pct=fin, renta_pct=r, envio_full=full)
        assert ac.calcular_precio_condicion(**kw) == ac.calcular_precio_condicion(**kw, renta_base="con_iva")


def test_todas_las_condiciones_con_iva_igual_sin_pedir_base():
    kw = dict(costo_sin_iva=D("56105.10"), iva_factor=D("1.105"), envio_real=D("29410"))
    assert ac.calcular_precios_todas_condiciones(**kw) == ac.calcular_precios_todas_condiciones(**kw, renta_base="con_iva")


def test_la_renta_es_x_por_ciento_del_precio_con_iva_por_defecto_y_sin_iva_si_se_pide():
    filas = mk.filas_iniciales_parseadas()
    par = mk.parametros_mercado("fravega", filas)
    for cond in par["condiciones"]:
        f = par["financiero"][cond]
        for base in ("con_iva", "sin_iva"):
            p = ac.calcular_precio_condicion(**_kw(financiero_pct=f, renta_base=base))
            cu = mk.cuenta_paso_a_paso(p, costo_sin_iva=D("20925"), iva_factor=D("1.105"), envio_real=D("0"), comision_pct=D("15.5"), financiero_pct=f,
                                       iibb_pct=D("5"), cheque_pct=D("1.2"), costo_orden=D("149.12"))
            clave = "renta_pct_con_iva" if base == "con_iva" else "renta_pct_sin_iva"
            assert abs(cu[clave] - D("10")) < D("0.01"), (cond, base, cu[clave])
            # el equivalente en la otra base es X ÷ IVA (o × IVA)
            otra = cu["renta_pct_sin_iva"] if base == "con_iva" else cu["renta_pct_con_iva"]
            esperado = D("10") * D("1.105") if base == "con_iva" else D("10") / D("1.105")
            assert abs(otra - esperado) < D("0.02")


def test_la_renta_de_la_cuenta_es_la_del_desglose():
    p = ac.calcular_precio_condicion(**_kw())
    args = dict(costo_sin_iva=D("20925"), iva_factor=D("1.105"), envio_real=D("1500"), comision_pct=D("15.5"), financiero_pct=D("6.8"), iibb_pct=D("5"), cheque_pct=D("1.2"), costo_orden=D("149.12"))
    assert abs(mk.cuenta_paso_a_paso(p, **args)["renta"] - mk.desglose(p, **args)["renta"]) < D("0.0001")


def test_la_cuenta_trae_las_lineas_en_orden_con_su_iva():
    cu = mk.cuenta_paso_a_paso(D("41399"), costo_sin_iva=D("20925"), iva_factor=D("1.105"), envio_real=D("1210"), comision_pct=D("15.5"), financiero_pct=D("6.8"),
                               iibb_pct=D("5"), cheque_pct=D("1.2"), costo_orden=D("149.12"))
    assert [l["clave"] for l in cu["lineas"]] == ["precio", "precio_sin_iva", "costo", "comision", "financiero", "envio", "iibb", "cheque", "costo_orden", "renta"]
    por = {l["clave"]: l for l in cu["lineas"]}
    assert por["comision"]["monto"] == por["comision"]["con_iva"] / D("1.21") and "sin IVA" in por["comision"]["iva"]
    assert por["envio"]["monto"] == D("1210") / D("1.21")
    assert por["iibb"]["sobre"] == "precio sin IVA" and por["cheque"]["sobre"] == "precio con IVA"


def test_base_desconocida_se_rechaza():
    with pytest.raises(ValueError):
        ac.calcular_precio_condicion(**_kw(renta_base="otra"))
    import main
    with pytest.raises(HTTPException) as e:
        main._renta_base_valida("otra")
    assert e.value.status_code == 422


# ── endpoints: con IVA = idéntico a no pedir la base; sin IVA cambia el precio y la cuenta lo confirma ──
from test_ayala_core_lote import cliente, RENTAS, _qs  # noqa: E402,F401  (fixture y ayudas del lote)


@pytest.mark.parametrize("renta", RENTAS)
@pytest.mark.parametrize("mercado", ["ml", "fravega", "web"])
def test_endpoint_con_iva_es_identico_a_no_pedir_la_base(cliente, renta, mercado):
    q = {**_qs(renta, None, False), "mercado": mercado}
    a = cliente.get("/ayala-core/motor-lote", params=q).json()
    b = cliente.get("/ayala-core/motor-lote", params={**q, "renta_base": "con_iva"}).json()
    quitar = lambda r: [{k: v for k, v in x.items() if k != "tiempos_ms"} for x in r["resultados"]]
    assert quitar(a) == quitar(b)
    assert all(x["renta_base"] == "con_iva" for x in a["resultados"])


def test_endpoint_sin_iva_da_renta_x_pct_del_precio_sin_iva(cliente):
    q = {**_qs(RENTAS[0], None, False), "mercado": "fravega", "renta_base": "sin_iva"}
    r = cliente.get("/ayala-core/motor-lote", params=q).json()["resultados"][0]
    assert r["renta_base"] == "sin_iva"
    for c, cu in r["cuentas"].items():
        esperado = {"contado": 32, "3": 30, "6": 28, "9": 26, "12": 24}[c]
        assert abs(cu["renta_pct_sin_iva"] - esperado) < 0.01, (c, cu["renta_pct_sin_iva"])
    sinq = {**q}; sinq.pop("renta_base")
    r0 = cliente.get("/ayala-core/motor-lote", params=sinq).json()["resultados"][0]
    assert all(r["precios"][c] < r0["precios"][c] for c in r["precios"])   # la misma renta nominal sobre el neto es menos pesos


def test_endpoint_rechaza_base_desconocida(cliente):
    assert cliente.get("/ayala-core/motor-lote", params={"renta_base": "x"}).status_code == 422
    assert cliente.get(f"/ayala-core/sku/{ac.SKUS_PILOTO[0]}/motor", params={"renta_base": "x"}).status_code == 422
