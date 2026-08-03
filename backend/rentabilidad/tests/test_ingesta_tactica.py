"""Adaptador SQL de Táctica — prueba la traducción de filas crudas (inyectadas
vía `ejecutar_query`, sin red/SQL Server real) a `FilaTactica`/`LineaTacticaInput`,
y la regla de régimen de TACTICA_SQL_RELEVAMIENTO.md §5 (CAE decide Cuenta 1
vs Cuenta 2 — no la letra fiscal, ni ninguna inferencia estadística)."""
from datetime import date, datetime
from decimal import Decimal

import pytest

from rentabilidad.calculators import LineaTacticaInput
from rentabilidad.ingesta_tactica import TacticaSqlAdapter, _nro_factura, _tipo_factura


def _row(**overrides) -> dict:
    base = dict(
        FechaEmision=datetime(2026, 7, 31),
        Empresa="Sign Solutions SA",
        Codigo="SKU1",
        Descripcion="Producto de prueba",
        Fabricante="Fabricante X",
        TipoProducto="Productos para la venta",
        Vendedor="Brian Avila",
        NroSucursal=3,
        Numero=127128,
        CAE=86316189981185.0,
        Cantidad=6,
        PrecioVenta=31153.50,
        TC=1500,
    )
    base.update(overrides)
    return base


# ── _nro_factura / _tipo_factura (unidades puras) ──

def test_nro_factura_arma_prefijo_con_padding():
    assert _nro_factura(3, 127071) == "00003-00127071"
    assert _nro_factura(5001, 2057831) == "05001-02057831"
    assert _nro_factura(7, 14) == "00007-00000014"


def test_tipo_factura_electronica_positiva_es_fea():
    assert _tipo_factura(86316189981185.0, Decimal(6)) == "FEA"


def test_tipo_factura_electronica_negativa_es_cea():
    # Nota de crédito electrónica — reverso Cuenta 1 (Maxx, 2026-07-31)
    assert _tipo_factura(86316189981185.0, Decimal(-2)) == "CEA"


def test_tipo_factura_no_electronica_positiva_es_fae():
    # CAE=0 -> AFIP no autorizó comprobante electrónico -> Cuenta 2
    assert _tipo_factura(0, Decimal(3)) == "FAE"


def test_tipo_factura_no_electronica_negativa_es_cve():
    assert _tipo_factura(0.0, Decimal(-1)) == "CVE"


def test_tipo_factura_cae_none_se_trata_como_no_electronica():
    assert _tipo_factura(None, Decimal(1)) == "FAE"


# ── TacticaSqlAdapter.lineas (inyectando ejecutar_query, sin red) ──

def test_lineas_traduce_fila_factura_a_cuenta_1():
    adapter = TacticaSqlAdapter(ejecutar_query=lambda desde, hasta: [_row()])
    [fila] = adapter.lineas(date(2026, 7, 1), date(2026, 7, 31))
    assert fila.codigo == "SKU1"
    assert fila.nro_factura == "00003-00127128"
    assert fila.tipo_factura == "FEA"
    assert fila.cantidad == Decimal(6)
    assert fila.precio_venta == Decimal("31153.50")
    assert fila.tc == Decimal(1500)
    assert fila.empresa == "Sign Solutions SA"
    assert fila.fecha == date(2026, 7, 31)


def test_lineas_traduce_nota_de_credito_no_electronica_a_cuenta_2():
    fila_cruda = _row(CAE=0, Cantidad=-1, PrecioVenta=-4315.75, NroSucursal=5001, Numero=19036008)
    adapter = TacticaSqlAdapter(ejecutar_query=lambda desde, hasta: [fila_cruda])
    [fila] = adapter.lineas(date(2026, 7, 1), date(2026, 7, 31))
    assert fila.tipo_factura == "CVE"
    assert fila.nro_factura == "05001-19036008"


def test_a_linea_input_produce_el_contrato_del_calculador():
    adapter = TacticaSqlAdapter(ejecutar_query=lambda desde, hasta: [_row()])
    [fila] = adapter.lineas(date(2026, 7, 1), date(2026, 7, 31))
    linea = fila.a_linea_input()
    assert linea == LineaTacticaInput(
        codigo="SKU1", tipo_factura="FEA", nro_factura="00003-00127128",
        cantidad=Decimal(6), precio_venta=Decimal("31153.50"), tc=Decimal(1500),
    )


def test_lineas_sin_cotizacion_de_moneda_falla_explicito_no_asume_tc():
    fila_cruda = _row(TC=None)
    adapter = TacticaSqlAdapter(ejecutar_query=lambda desde, hasta: [fila_cruda])
    with pytest.raises(ValueError, match="sin cotización"):
        adapter.lineas(date(2026, 7, 1), date(2026, 7, 31))


def test_lineas_pasa_el_rango_de_fechas_recibido():
    capturado = {}

    def fake_query(desde, hasta):
        capturado["desde"], capturado["hasta"] = desde, hasta
        return []

    TacticaSqlAdapter(ejecutar_query=fake_query).lineas(date(2026, 7, 1), date(2026, 7, 31))
    assert capturado == {"desde": date(2026, 7, 1), "hasta": date(2026, 7, 31)}
