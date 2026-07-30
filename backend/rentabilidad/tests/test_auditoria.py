"""Etapa 10 — auditoría de costo (§4). No interviene en el resultado del
motor: se prueba de forma aislada, sin tocar los calculadores existentes."""
from decimal import Decimal

from rentabilidad.adapters import CostoVigenteProvider
from rentabilidad.auditoria import construir_auditoria_costo
from rentabilidad.models import AuditoriaCosto


def _fila_global(sku: str, valor_s: str = "", valor_r: str = ""):
    fila = [""] * 30
    fila[0] = sku
    fila[18] = valor_s
    fila[17] = valor_r
    return fila


def test_costo_vigente_provider_informa_columna_origen_s():
    filas = [_fila_global("SKU1", valor_s="2.65")]
    prov = CostoVigenteProvider(sheet_id="x", fetch_fn=lambda sid, tab: filas)
    costo, columna = prov.obtener_con_origen("SKU1")
    assert costo == Decimal("2.65")
    assert columna == "S"


def test_costo_vigente_provider_informa_columna_origen_r_si_s_es_cero():
    filas = [_fila_global("SKU1", valor_s="0", valor_r="1.50")]
    prov = CostoVigenteProvider(sheet_id="x", fetch_fn=lambda sid, tab: filas)
    costo, columna = prov.obtener_con_origen("SKU1")
    assert costo == Decimal("1.50")
    assert columna == "R"


def test_obtener_sigue_funcionando_igual_que_antes():
    """La API existente (Etapa 2/4/5) no debe romperse por este cambio."""
    filas = [_fila_global("SKU1", valor_s="2.65")]
    prov = CostoVigenteProvider(sheet_id="x", fetch_fn=lambda sid, tab: filas)
    assert prov.obtener("SKU1") == Decimal("2.65")


def test_construir_auditoria_costo_no_persiste_por_si_sola(db_session):
    filas = [_fila_global("SKU1", valor_s="2.65")]
    prov = CostoVigenteProvider(sheet_id="x", fetch_fn=lambda sid, tab: filas)

    registro = construir_auditoria_costo(prov, linea_id="linea-1", sku="SKU1", calculo_id="calc-2026-07")

    assert registro.costo_usd_usado == Decimal("2.65")
    assert registro.columna_origen == "S"
    assert registro.linea_id == "linea-1"
    assert registro.calculo_id == "calc-2026-07"
    assert registro.leido_en is not None

    # Recién al agregarlo explícitamente a la sesión queda persistido —
    # confirma que "no interviene en el resultado" del calculador.
    assert db_session.query(AuditoriaCosto).count() == 0
    db_session.add(registro)
    db_session.commit()
    assert db_session.query(AuditoriaCosto).count() == 1


def test_auditoria_costo_no_resuelto_queda_registrada_igual(db_session):
    prov = CostoVigenteProvider(sheet_id="x", fetch_fn=lambda sid, tab: [])
    registro = construir_auditoria_costo(prov, linea_id="linea-2", sku="SKUX", calculo_id="calc-1")
    assert registro.costo_usd_usado is None
    assert registro.columna_origen is None
