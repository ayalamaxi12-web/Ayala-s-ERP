"""Adaptador de ECOM — traducción de filas crudas (inyectadas vía
`leer_filas`, sin archivo real) a `FilaEcom`/`LineaEcomInput`, y las 3 reglas
de limpieza/exclusión/incidencia que hoy Maxx aplica a mano (ver docstring
de `ingesta_ecom.py`)."""
from decimal import Decimal

from rentabilidad.calculators import LineaEcomInput
from rentabilidad.ingesta_ecom import EcomExcelAdapter


def _row(**overrides) -> dict:
    base = {
        "Número Orden": 1406205.0,
        "Sku's Vendidos": "PLANCHA-SUB-PORTATIL",
        "Estado Venta": "Cerrada",
        "Estado Pago": "Cobrado",
        "Costo Sin Iva (total de productos)": 13.25,
        "Canal De Venta": "Mercadolibre Carrito",
        "Comisión Venta": 20828.7,
        "Costo Envío": 7821.0,
        "Precio Neto": 70653.636,
        "Precio Final": 77719.0,
    }
    base.update(overrides)
    return base


def _adapter(rows):
    return EcomExcelAdapter(leer_filas=lambda path: rows)


def test_linea_normal_pasa_a_lineas_y_produce_el_contrato_del_calculador():
    resultado = _adapter([_row()]).procesar("x.xlsx", Decimal(1500))
    assert resultado.excluidas_por_estado_pago == []
    assert resultado.incidencias_costo == []
    [fila] = resultado.lineas
    assert fila.a_linea_input() == LineaEcomInput(
        numero_orden="1406205", costo_sin_iva=Decimal("13.25"),
        comision_venta=Decimal("20828.7"), costo_envio=Decimal("7821.0"),
        precio_sin_iva=Decimal("70653.636"), precio_final=Decimal("77719.0"),
        tc=Decimal(1500),
    )


def test_numero_orden_sin_decimal_espurio():
    resultado = _adapter([_row(**{"Número Orden": 1406205.0})]).procesar("x.xlsx", Decimal(1500))
    assert resultado.lineas[0].numero_orden == "1406205"


def test_cobro_parcial_participa_igual_que_cobrado():
    resultado = _adapter([_row(**{"Estado Pago": " Cobro Parcial"})]).procesar("x.xlsx", Decimal(1500))
    assert resultado.excluidas_por_estado_pago == []
    assert len(resultado.lineas) == 1


def test_reembolsado_se_excluye_completamente():
    resultado = _adapter([_row(**{"Estado Pago": "Reembolsado"})]).procesar("x.xlsx", Decimal(1500))
    assert resultado.lineas == []
    assert len(resultado.excluidas_por_estado_pago) == 1


def test_en_mediacion_se_excluye():
    resultado = _adapter([_row(**{"Estado Pago": "En Mediación"})]).procesar("x.xlsx", Decimal(1500))
    assert resultado.lineas == []
    assert len(resultado.excluidas_por_estado_pago) == 1


def test_sin_cobro_se_excluye():
    resultado = _adapter([_row(**{"Estado Pago": "Sin cobro"})]).procesar("x.xlsx", Decimal(1500))
    assert resultado.lineas == []


def test_estado_no_reconocido_se_excluye_por_lista_blanca():
    # Cualquier estado futuro no listado se excluye por defecto — nunca se
    # asume que un estado desconocido participa (ver punto 2 del docstring).
    resultado = _adapter([_row(**{"Estado Pago": "Cancelado"})]).procesar("x.xlsx", Decimal(1500))
    assert resultado.lineas == []
    assert len(resultado.excluidas_por_estado_pago) == 1


def test_costo_cero_se_marca_como_incidencia_no_se_calcula():
    resultado = _adapter([_row(**{"Costo Sin Iva (total de productos)": 0})]).procesar("x.xlsx", Decimal(1500))
    assert resultado.lineas == []
    [fila] = resultado.incidencias_costo
    assert fila.incidencia == "COSTO_NO_RESUELTO"


def test_costo_vacio_se_marca_como_incidencia():
    resultado = _adapter([_row(**{"Costo Sin Iva (total de productos)": None})]).procesar("x.xlsx", Decimal(1500))
    assert len(resultado.incidencias_costo) == 1


def test_postventa_fuerza_precio_final_y_sin_iva_a_cero():
    fila_cruda = _row(
        **{"Canal De Venta": "Posventa", "Precio Neto": 12345.0, "Precio Final": 99999.0},
    )
    resultado = _adapter([fila_cruda]).procesar("x.xlsx", Decimal(1500))
    [fila] = resultado.lineas
    assert fila.precio_sin_iva == Decimal(0)
    assert fila.precio_final == Decimal(0)


def test_postventa_igual_se_excluye_si_el_estado_de_pago_no_participa():
    fila_cruda = _row(**{"Canal De Venta": "Posventa", "Estado Pago": "Reembolsado"})
    resultado = _adapter([fila_cruda]).procesar("x.xlsx", Decimal(1500))
    assert resultado.lineas == []
    assert len(resultado.excluidas_por_estado_pago) == 1


def test_columna_precio_sin_iva_alternativa_tambien_funciona():
    # El export crudo usa "Precio Neto"; una variante futura con "Precio SIN
    # IVA" debe resolverse igual, por título — no por posición fija.
    fila_cruda = _row()
    del fila_cruda["Precio Neto"]
    fila_cruda["Precio SIN IVA"] = 70653.636
    resultado = _adapter([fila_cruda]).procesar("x.xlsx", Decimal(1500))
    assert resultado.lineas[0].precio_sin_iva == Decimal("70653.636")


def test_tc_es_el_mismo_para_todas_las_lineas_del_periodo():
    resultado = _adapter([_row(), _row(**{"Número Orden": 999.0})]).procesar("x.xlsx", Decimal("1510.5"))
    assert all(f.tc == Decimal("1510.5") for f in resultado.lineas)
