"""Etapa 7 — casos E-1 a E-3 de RENTABILIDAD_FUNCIONAL.md §13.2, columna por
columna, tolerancia 0,01. E-4 queda `xfail` — pendiente de la verificación
V-02 del funcional §16 (adjustment #4: no bloquea, se marca pendiente).
"""
from decimal import Decimal

import pytest

from rentabilidad.adapters import IvaProvider
from rentabilidad.calculators import (
    LineaEcomInput,
    RentabilidadEcomCalculator,
    calcular_facturacion_iva,
    resolver_ao_orden,
)

TOLERANCIA = Decimal("0.01")


def _cerca(actual, esperado):
    if esperado is None or actual is None:
        return actual == esperado
    return abs(Decimal(actual) - Decimal(esperado)) <= TOLERANCIA


def test_e1_ml_carrito_iva_10_5(db_session):
    calc = RentabilidadEcomCalculator(db_session)
    linea = LineaEcomInput(
        numero_orden="1405031",
        costo_sin_iva=Decimal("130.27"),
        comision_venta=Decimal("98898.56"),
        costo_envio=Decimal("7821"),
        precio_sin_iva=Decimal("620053.636"),
        precio_final=Decimal("682059"),
        tc=Decimal(1500),
    )
    r = calc.calcular(linea)
    assert _cerca(r.imp_cheque, "8184.708")
    assert _cerca(r.iibb, "31002.6818")
    assert _cerca(r.neto, "474146.686")
    assert _cerca(r.costo_total, "195405.00")
    assert _cerca(r.rentabilidad, "278741.686")
    assert _cerca(r.rentabilidad_usd, "185.83")
    assert _cerca(r.facturacion_usd, "454.71")
    assert _cerca(r.pct_rentabilidad, "0.5879")

    iva_provider = IvaProvider(consultar=lambda: [{"sku": "SKU-E1", "iva_descripcion": "IVA Debito 10.5%"}])
    ao = resolver_ao_orden(iva_provider, "SKU-E1")
    ap = calcular_facturacion_iva(linea.precio_final, ao)
    assert _cerca(ap, "753675.195")


def test_e2_ml_carrito_iva_21(db_session):
    calc = RentabilidadEcomCalculator(db_session)
    linea = LineaEcomInput(
        numero_orden="1405030",
        costo_sin_iva=Decimal("4.98"),
        comision_venta=Decimal("7456.35"),
        costo_envio=Decimal("0"),
        precio_sin_iva=Decimal("24387.603"),
        precio_final=Decimal("29509"),
        tc=Decimal(1500),
    )
    r = calc.calcular(linea)
    assert _cerca(r.imp_cheque, "354.108")
    assert _cerca(r.iibb, "1219.38015")
    assert _cerca(r.neto, "15357.765")
    assert _cerca(r.costo_total, "7470.00")
    assert _cerca(r.rentabilidad, "7887.765")
    assert _cerca(r.pct_rentabilidad, "0.5136")


def test_e3_fravega_sin_retenciones_deducidas_igual_que_siempre(db_session):
    """El título del caso ("sin retenciones") es la etiqueta del canal, no una
    instrucción de saltear IIBB — la fórmula general aplica igual (nota del
    funcional bajo T-4/E-3: no hay ramas especiales por canal)."""
    calc = RentabilidadEcomCalculator(db_session)
    linea = LineaEcomInput(
        numero_orden="frave-1",
        costo_sin_iva=Decimal("2.96"),
        comision_venta=Decimal("2249.85"),
        costo_envio=Decimal("0"),
        precio_sin_iva=Decimal("12395.868"),
        precio_final=Decimal("14999"),
        tc=Decimal(1500),
    )
    r = calc.calcular(linea)
    assert _cerca(r.imp_cheque, "179.988")
    assert _cerca(r.iibb, "619.7934")
    assert _cerca(r.neto, "9346.2366")
    assert _cerca(r.costo_total, "4440.00")
    assert _cerca(r.rentabilidad, "4906.2366")


@pytest.mark.xfail(reason="E-4 (Posventa) pendiente de verificación V-02 (funcional §16) — no bloquea el motor", strict=False)
def test_e4_posventa_pendiente_verificacion():
    raise NotImplementedError("Sin datos reales del libro todavía (V-02)")
