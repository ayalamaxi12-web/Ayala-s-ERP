"""Etapa 10 — auditoría de costo (§4). No interviene en el resultado del
motor: se prueba de forma aislada, sin tocar los calculadores existentes."""
from decimal import Decimal

from rentabilidad.adapters import CostoVigenteProvider
from rentabilidad.auditoria import construir_auditoria_costo
from rentabilidad.models import AuditoriaCosto


def _catalogo(sku: str, costo=None):
    return [{"sku": sku, "costo": costo, "iva_descripcion": None}]


def test_costo_vigente_provider_informa_origen_sql():
    prov = CostoVigenteProvider(consultar=lambda: _catalogo("SKU1", costo="2.65"))
    costo, origen = prov.obtener_con_origen("SKU1")
    assert costo == Decimal("2.65")
    assert origen == "SQL"


def test_costo_vigente_provider_cero_se_trata_como_sin_costo():
    prov = CostoVigenteProvider(consultar=lambda: _catalogo("SKU1", costo="0"))
    costo, origen = prov.obtener_con_origen("SKU1")
    assert costo is None
    assert origen is None


def test_obtener_sigue_funcionando_igual_que_antes():
    """La API existente (Etapa 2/4/5) no debe romperse por este cambio."""
    prov = CostoVigenteProvider(consultar=lambda: _catalogo("SKU1", costo="2.65"))
    assert prov.obtener("SKU1") == Decimal("2.65")


def test_construir_auditoria_costo_no_persiste_por_si_sola(db_session):
    prov = CostoVigenteProvider(consultar=lambda: _catalogo("SKU1", costo="2.65"))

    registro = construir_auditoria_costo(prov, linea_id="linea-1", sku="SKU1", calculo_id="calc-2026-07")

    assert registro.costo_usd_usado == Decimal("2.65")
    assert registro.columna_origen == "SQL"
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
    prov = CostoVigenteProvider(consultar=lambda: [])
    registro = construir_auditoria_costo(prov, linea_id="linea-2", sku="SKUX", calculo_id="calc-1")
    assert registro.costo_usd_usado is None
    assert registro.columna_origen is None
