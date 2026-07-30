"""Etapa 6 — cobertura de mecánica del calculador ECOM. La paridad numérica
exacta es Etapa 7 (test_ecom_regresion.py)."""
from decimal import Decimal

from rentabilidad.calculators import LineaEcomInput, RentabilidadEcomCalculator


def test_av_es_cero_ante_error_no_none(db_session):
    """§7.1 paso 7: AV = 1-(AA/Z), 'con 0 ante error' — literal, no None."""
    calc = RentabilidadEcomCalculator(db_session)
    # Z=0: Q-M-O-S-T se anula exactamente.
    linea = LineaEcomInput(
        numero_orden="1",
        costo_sin_iva=Decimal("10"),
        comision_venta=Decimal("0"),
        costo_envio=Decimal("0"),
        precio_sin_iva=Decimal("0"),
        precio_final=Decimal("0"),
        tc=Decimal("1500"),
    )
    r = calc.calcular(linea)
    assert r.neto == Decimal(0)
    assert r.pct_rentabilidad == Decimal(0)


def test_comision_cobro_no_es_parte_del_input_ni_de_la_formula(db_session):
    """§7.5 — Comisión Cobro no participa nunca del cálculo; ni siquiera es
    un campo de entrada del calculador (se persiste aparte en el modelo)."""
    assert not hasattr(LineaEcomInput, "comision_cobro")


def test_posventa_da_perdida_total_por_costo(db_session):
    """§7.4 — Q=0, U=0, G>0 (sin comisión/envío) -> Z=0, AB=-AA."""
    calc = RentabilidadEcomCalculator(db_session)
    linea = LineaEcomInput(
        numero_orden="2",
        costo_sin_iva=Decimal("50"),
        comision_venta=Decimal("0"),
        costo_envio=Decimal("0"),
        precio_sin_iva=Decimal("0"),
        precio_final=Decimal("0"),
        tc=Decimal("1500"),
    )
    r = calc.calcular(linea)
    assert r.neto == Decimal(0)
    assert r.costo_total == Decimal("75000")
    assert r.rentabilidad == -r.costo_total
