"""Wiring HTTP hacia el ERP (`api.py`) — traducción CSV -> motor, sin tocar
el cálculo en sí (ya cubierto por test_tactica_regresion.py). Mismo patrón
que el resto de `rentabilidad/`: proveedores con `fetch_fn` de fixture, sin
red ni credenciales reales."""
from decimal import Decimal

from rentabilidad.adapters import CostoVigenteProvider, IvaProvider
from rentabilidad.api import LineaTacticaIn, calcular_lineas, extraer_comprobante
from rentabilidad.config import ConfiguracionFaltante
from rentabilidad.models import Regimen

TOLERANCIA = Decimal("0.01")


def _cerca(actual, esperado):
    if esperado is None or actual is None:
        return actual == esperado
    return abs(Decimal(actual) - Decimal(esperado)) <= TOLERANCIA


# ── extraer_comprobante — traducción de formato §6.1, no una regla nueva ──

def test_extrae_codigo_embebido_en_texto_descriptivo():
    assert extraer_comprobante("Factura A - FEA") == "FEA"
    assert extraer_comprobante("factura e electronica fee") == "FEE"
    assert extraer_comprobante("Nota de Credito CEA") == "CEA"


def test_extrae_mla_de_multiproposito():
    assert extraer_comprobante("Multipropósito Factura MLA") == "MLA"


def test_sin_codigo_reconocido_devuelve_texto_tal_cual():
    # Cae a NO_RECONOCIDO en resolver_regimen — mismo efecto que "no se
    # calcula" que ya tenía la nota de débito en el JS viejo.
    assert extraer_comprobante("Nota de Débito") == "Nota de Débito"


def test_extraccion_no_confunde_fea_con_fae():
    assert extraer_comprobante("Factura E no electronica FAE") == "FAE"
    assert extraer_comprobante("Factura Venta A Electronica FEA") == "FEA"


# ── calcular_lineas — traducción de tipos + orquestación, motor ya probado ──

def _fila_global(sku: str, costo_s: str):
    fila = [""] * 30
    fila[0] = sku
    fila[18] = costo_s
    return fila


def _providers(costo_s: str, iva_texto: str | None, sku="CF217ACOMP"):
    filas_costo = [_fila_global(sku, costo_s)]
    filas_iva = [["SKU", "IVA"], [sku, iva_texto]] if iva_texto else []
    costo = CostoVigenteProvider(sheet_id="x", fetch_fn=lambda sid, tab: filas_costo)
    iva = IvaProvider(sheet_id="x", fetch_fn=lambda sid, tab: filas_iva)
    return costo, iva


def test_t1_via_endpoint_reproduce_el_caso_de_aceptacion(db_session):
    # T-1 de RENTABILIDAD_FUNCIONAL.md §13.1, pero entrando por el mismo
    # camino que usará el frontend: texto crudo de "Tipo de Factura", no el
    # código corto ya resuelto.
    costo, iva = _providers("2.65", "IVA Debito 21%")
    linea = LineaTacticaIn(
        codigo="CF217ACOMP", tipo_factura="Factura de Venta A - FEA",
        nro_factura="00003-00127071", cantidad="6", precio_venta="31153.50", tc="1500",
    )
    [r] = calcular_lineas([linea], db_session, costo, iva)
    assert r.regimen == Regimen.CUENTA_1.value
    assert _cerca(r.iva, "6542.235")
    assert _cerca(r.imp_cheque, "-452.35")
    assert _cerca(r.iibb, "-1557.675")
    assert _cerca(r.costo_total_pesos, "-23850.00")
    assert _cerca(r.costo_financiero_1, "-1130.87")
    assert _cerca(r.margen_real, "4162.60")


def test_mla_no_calculado_pendiente_p01(db_session):
    costo, iva = _providers("2.65", "IVA Debito 21%")
    linea = LineaTacticaIn(
        codigo="CF217ACOMP", tipo_factura="Multipropósito Factura MLA",
        nro_factura="00003-00000001", cantidad="1", precio_venta="1000", tc="1500",
    )
    [r] = calcular_lineas([linea], db_session, costo, iva)
    assert r.regimen == Regimen.NO_DETERMINADO.value
    assert r.margen_real is None


def test_costo_no_resuelto_es_incidencia_no_numero(db_session):
    costo, iva = _providers("2.65", "IVA Debito 21%", sku="OTRO-SKU")
    linea = LineaTacticaIn(
        codigo="CF217ACOMP", tipo_factura="FEA",
        nro_factura="00003-00000001", cantidad="1", precio_venta="1000", tc="1500",
    )
    [r] = calcular_lineas([linea], db_session, costo, iva)
    assert r.incidencia == "COSTO_NO_RESUELTO"
    assert r.margen_real is None


def test_sheet_id_faltante_no_rompe_el_lote_completo(db_session):
    # Sin sheet_id configurado, el proveedor levanta ConfiguracionFaltante —
    # el endpoint lo captura como incidencia en vez de tirar abajo el request.
    costo = CostoVigenteProvider(sheet_id=None)
    iva = IvaProvider(sheet_id=None)
    linea = LineaTacticaIn(
        codigo="CF217ACOMP", tipo_factura="FEA",
        nro_factura="00003-00000001", cantidad="1", precio_venta="1000", tc="1500",
    )
    [r] = calcular_lineas([linea], db_session, costo, iva)
    assert r.incidencia.startswith("CONFIG_FALTANTE")
    assert r.margen_real is None
