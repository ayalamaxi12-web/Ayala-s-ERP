"""Etapa 4 — cobertura de mecánica del calculador (ramas de régimen,
incidencias). La paridad numérica exacta contra el libro es Etapa 5
(test_tactica_regresion.py, la puerta real)."""
from decimal import Decimal

from rentabilidad.adapters import CostoVigenteProvider, IvaProvider
from rentabilidad.calculators import LineaTacticaInput, RentabilidadTacticaCalculator
from rentabilidad.models import Regimen


def _calc(db_session, catalogo=None):
    consultar = lambda: catalogo or []
    costo_provider = CostoVigenteProvider(consultar=consultar)
    iva_provider = IvaProvider(consultar=consultar)
    return RentabilidadTacticaCalculator(db_session, costo_provider, iva_provider)


def test_comprobante_no_reconocido_no_se_calcula(db_session):
    calc = _calc(db_session)
    linea = LineaTacticaInput("SKU1", "XYZ", "00001-1", Decimal(1), Decimal(100), Decimal(1500))
    r = calc.calcular(linea)
    assert r.regimen == Regimen.NO_RECONOCIDO
    assert r.margen_real is None
    assert r.incidencia == "LINEA_NO_CALCULADA"


def test_mla_no_determinado_no_se_calcula(db_session):
    calc = _calc(db_session)
    linea = LineaTacticaInput("SKU1", "MLA", "00001-1", Decimal(1), Decimal(100), Decimal(1500))
    r = calc.calcular(linea)
    assert r.regimen == Regimen.NO_DETERMINADO
    assert r.margen_real is None


def test_perdida_definitiva_anula_todo_menos_aa(db_session):
    calc = _calc(db_session)
    linea = LineaTacticaInput("SKU1", "CVA", "00007-1", Decimal(-1), Decimal(-100), Decimal(1500))
    r = calc.calcular(linea)
    assert r.regimen == Regimen.PERDIDA_DEFINITIVA
    assert r.margen_real == Decimal(-100)
    assert r.costo_total_pesos is None
    assert r.iva is None


def test_costo_no_resuelto_es_incidencia_bloqueante(db_session):
    calc = _calc(db_session, catalogo=[])  # SKU no aparece en el catálogo -> None
    linea = LineaTacticaInput("SKU1", "FEA", "00003-1", Decimal(1), Decimal(100), Decimal(1500))
    r = calc.calcular(linea)
    assert r.incidencia == "COSTO_NO_RESUELTO"
    assert r.margen_real is None


def test_iva_no_resuelto_en_cuenta_1_es_incidencia_bloqueante(db_session):
    catalogo = [{"sku": "SKU1", "costo": "2.65", "iva_descripcion": "valor rarísimo"}]
    calc = _calc(db_session, catalogo=catalogo)
    linea = LineaTacticaInput("SKU1", "FEA", "00003-1", Decimal(6), Decimal(31153.50), Decimal(1500))
    r = calc.calcular(linea)
    assert r.incidencia == "IVA_NO_RESUELTO"
    assert r.margen_real is None
    assert r.costo_lista == Decimal("2.65")  # ya se había resuelto antes de fallar Q


def test_cuenta_2_no_requiere_iva(db_session):
    catalogo = [{"sku": "SKU1", "costo": "63.3", "iva_descripcion": None}]
    calc = _calc(db_session, catalogo=catalogo)  # Q no resuelve, es irrelevante en Cuenta 2
    linea = LineaTacticaInput("SKU1", "FAE", "05001-1", Decimal(3), Decimal(363439.95), Decimal(1500))
    r = calc.calcular(linea)
    assert r.regimen == Regimen.CUENTA_2
    assert r.incidencia is None
    assert r.iva is None and r.imp_cheque is None and r.iibb is None
    assert r.costo_financiero_2 is not None
