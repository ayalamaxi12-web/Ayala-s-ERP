"""Etapa 5 — la puerta real: casos T-1 a T-8 de RENTABILIDAD_FUNCIONAL.md §13.1,
verificados columna por columna (no solo AA), tolerancia 0,01, sin
redondeos intermedios (§5.7). T-9 queda `xfail` — pendiente de la
verificación V-02 del funcional §16 (adjustment #4: no bloquea, se marca
pendiente).

Si T-1..T-8 no cierran al centavo acá, no se avanza al motor ECOM
(RENTABILIDAD_IMPLEMENTACION.md §9, paso 5).
"""
from decimal import Decimal

import pytest

from rentabilidad.adapters import CostoVigenteProvider, IvaProvider
from rentabilidad.calculators import LineaTacticaInput, RentabilidadTacticaCalculator
from rentabilidad.models import Regimen

TOLERANCIA = Decimal("0.01")


def _cerca(actual, esperado):
    if esperado is None or actual is None:
        return actual == esperado
    return abs(Decimal(actual) - Decimal(esperado)) <= TOLERANCIA


def _calculador(db_session, costo_l: str, iva_texto: str | None):
    catalogo = [{"sku": "SKU", "costo": costo_l, "iva_descripcion": iva_texto}]
    consultar = lambda: catalogo
    costo_provider = CostoVigenteProvider(consultar=consultar)
    iva_provider = IvaProvider(consultar=consultar)
    return RentabilidadTacticaCalculator(db_session, costo_provider, iva_provider)


def test_t1_cuenta1_fea(db_session):
    calc = _calculador(db_session, "2.65", "IVA Debito 21%")
    linea = LineaTacticaInput("SKU", "FEA", "00003-00127071", Decimal(6), Decimal("31153.50"), Decimal(1500))
    r = calc.calcular(linea)
    assert r.regimen == Regimen.CUENTA_1
    assert _cerca(r.costo_total_dolares, "15.90")
    assert _cerca(r.iva, "6542.235")
    assert _cerca(r.precio_venta_iva, "37695.735")
    assert _cerca(r.imp_cheque, "-452.35")
    assert _cerca(r.iibb, "-1557.675")
    assert _cerca(r.costo_total_pesos, "-23850.00")
    assert _cerca(r.costo_financiero_1, "-1130.87")
    assert r.costo_financiero_2 == Decimal(0)
    assert _cerca(r.margen_real, "4162.60")
    assert _cerca(r.margen_pct, "0.1336")


def test_t2_cuenta1_fea(db_session):
    calc = _calculador(db_session, "2.14", "IVA Debito 21%")
    linea = LineaTacticaInput("SKU", "FEA", "00003-00000000", Decimal(3), Decimal("13138.65"), Decimal(1500))
    r = calc.calcular(linea)
    assert _cerca(r.costo_total_dolares, "6.42")
    assert _cerca(r.iva, "2759.12")
    assert _cerca(r.imp_cheque, "-190.77")
    assert _cerca(r.iibb, "-656.93")
    assert _cerca(r.costo_total_pesos, "-9630.00")
    assert _cerca(r.costo_financiero_1, "-476.93")
    assert r.costo_financiero_2 == Decimal(0)
    assert _cerca(r.margen_real, "2184.01")
    assert _cerca(r.margen_pct, "0.1662")


def test_t3_cuenta2_fae(db_session):
    calc = _calculador(db_session, "63.3", None)  # L = O/N = 189.90/3
    linea = LineaTacticaInput("SKU", "FAE", "05001-02057831", Decimal(3), Decimal("363439.95"), Decimal(1500))
    r = calc.calcular(linea)
    assert r.regimen == Regimen.CUENTA_2
    assert r.iva is None and r.imp_cheque is None and r.iibb is None
    assert _cerca(r.costo_total_pesos, "-284850.00")
    assert r.costo_financiero_1 == Decimal(0)
    assert _cerca(r.costo_financiero_2, "-10903.20")
    assert _cerca(r.margen_real, "67686.75")
    assert _cerca(r.margen_pct, "0.1862")


def test_t4_cuenta2_iva_10_5_irrelevante(db_session):
    # "En Cuenta 2 el factor de IVA es irrelevante porque S queda vacío" (nota T-4)
    calc = _calculador(db_session, "17.60", None)  # N=1, L=O
    linea = LineaTacticaInput("SKU", "FAE", "05001-00000000", Decimal(1), Decimal("65291.80"), Decimal(1500))
    r = calc.calcular(linea)
    assert _cerca(r.costo_total_pesos, "-26400.00")
    assert _cerca(r.costo_financiero_2, "-1958.75")
    assert _cerca(r.margen_real, "36933.05")
    assert _cerca(r.margen_pct, "0.5657")


def test_t5_nc_cuenta1_cea(db_session):
    calc = _calculador(db_session, "2.64", "IVA Debito 21%")  # L = O/N = -5.28/-2
    linea = LineaTacticaInput("SKU", "CEA", "00003-00009750", Decimal(-2), Decimal("-14208.00"), Decimal(1500))
    r = calc.calcular(linea)
    assert r.regimen == Regimen.CUENTA_1
    assert _cerca(r.iva, "-2983.68")
    assert _cerca(r.imp_cheque, "206.30")
    assert _cerca(r.iibb, "710.40")
    assert _cerca(r.costo_total_pesos, "7920.00")
    assert _cerca(r.costo_financiero_1, "515.75")
    assert r.costo_financiero_2 == Decimal(0)
    assert _cerca(r.margen_real, "-4855.55")


def test_t6_nc_cuenta2_cve(db_session):
    calc = _calculador(db_session, "2.69", None)  # L = O/N = -2.69/-1
    linea = LineaTacticaInput("SKU", "CVE", "05001-19036008", Decimal(-1), Decimal("-4315.75"), Decimal(1500))
    r = calc.calcular(linea)
    assert r.regimen == Regimen.CUENTA_2
    assert r.iva is None and r.imp_cheque is None and r.iibb is None
    assert _cerca(r.costo_total_pesos, "4035.00")
    assert _cerca(r.costo_financiero_2, "129.47")
    assert _cerca(r.margen_real, "-151.28")


def test_t7_perdida_definitiva_sin_costo(db_session):
    calc = _calculador(db_session, "0", None)
    linea = LineaTacticaInput("SKU", "CVA", "00007-00000014", Decimal(0), Decimal("-299325.00"), Decimal(1500))
    r = calc.calcular(linea)
    assert r.regimen == Regimen.PERDIDA_DEFINITIVA
    assert r.costo_total_pesos is None
    assert r.iva is None
    assert _cerca(r.margen_real, "-299325.00")


def test_t8_perdida_definitiva_con_costo_anulado(db_session):
    calc = _calculador(db_session, "3.02", None)  # L=O/N=-18.12/-6, no debería importar
    linea = LineaTacticaInput("SKU", "CVA", "00007-00000008", Decimal(-6), Decimal("-42450.00"), Decimal(1500))
    r = calc.calcular(linea)
    assert r.regimen == Regimen.PERDIDA_DEFINITIVA
    assert r.costo_total_pesos is None  # "W anulado aunque O tenga valor"
    assert _cerca(r.margen_real, "-42450.00")


@pytest.mark.xfail(reason="T-9 pendiente de verificación V-02 (funcional §16) — no bloquea el motor", strict=False)
def test_t9_preventa_cuenta2_pendiente_verificacion():
    raise NotImplementedError("Sin datos reales del libro todavía (V-02)")
