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
        costo_operacion=Decimal(0),
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
        costo_operacion=Decimal(0),
    )
    r = calc.calcular(linea)
    assert r.neto == Decimal(0)
    assert r.costo_total == Decimal("75000")
    assert r.rentabilidad == -r.costo_total


def test_costo_operacion_por_defecto_es_el_sembrado(db_session):
    """§7.7 OP — sin valor explícito se descuenta el vigente de
    `parametro_tasa` (149,12 por orden, desde 23/08/2026)."""
    calc = RentabilidadEcomCalculator(db_session)
    linea = LineaEcomInput(
        numero_orden="3", costo_sin_iva=Decimal("0"), comision_venta=Decimal("0"),
        costo_envio=Decimal("0"), precio_sin_iva=Decimal("0"), precio_final=Decimal("0"),
        tc=Decimal("1500"),
    )
    r = calc.calcular(linea)
    assert r.costo_operacion == Decimal("149.12")
    assert r.neto == Decimal("-149.12")
    assert r.rentabilidad == Decimal("-149.12")


def test_costo_operacion_explicito_pisa_el_sembrado(db_session):
    calc = RentabilidadEcomCalculator(db_session)
    linea = LineaEcomInput(
        numero_orden="4", costo_sin_iva=Decimal("0"), comision_venta=Decimal("0"),
        costo_envio=Decimal("0"), precio_sin_iva=Decimal("1000"), precio_final=Decimal("1000"),
        tc=Decimal("1500"), costo_operacion=Decimal("10"),
    )
    r = calc.calcular(linea)
    # Z = 1000 - 0 - 0 - 12 (1,2%) - 50 (5%) - 10
    assert r.neto == Decimal("928")
    assert r.costo_operacion == Decimal("10")


def test_orden_real_ago_sep_con_costo_operacion(db_session):
    """Paridad con `Agosto - Septiembre ECOM`, orden 1421677 (fila 5096,
    una de las que el libro sí descuenta OP): Neto/Costo Total/Rentabilidad
    al centavo."""
    calc = RentabilidadEcomCalculator(db_session)
    linea = LineaEcomInput(
        numero_orden="1421677", costo_sin_iva=Decimal("6.23"),
        comision_venta=Decimal("7594.85"), costo_envio=Decimal("0"),
        precio_sin_iva=Decimal("22726.446"), precio_final=Decimal("27499"),
        tc=Decimal("1530"),
    )
    r = calc.calcular(linea)
    assert abs(r.imp_cheque - Decimal("329.988")) <= Decimal("0.01")
    assert abs(r.iibb - Decimal("1136.3223")) <= Decimal("0.01")
    assert abs(r.neto - Decimal("13516.1657")) <= Decimal("0.01")
    assert abs(r.costo_total - Decimal("9531.90")) <= Decimal("0.01")
    assert abs(r.rentabilidad - Decimal("3984.2657")) <= Decimal("0.01")
