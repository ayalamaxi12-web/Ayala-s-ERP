"""Etapa 3 — casos de §6.1, incluida la prioridad absoluta del prefijo de
pérdida definitiva sobre el tipo de comprobante."""
from rentabilidad.models import Regimen
from rentabilidad.regimen import resolver_regimen


def test_cuenta_1_fea(db_session):
    assert resolver_regimen(db_session, "FEA", "00003-00127071") == Regimen.CUENTA_1


def test_cuenta_1_notas_credito_reverso(db_session):
    for comp in ("CEA", "CEB", "CEE"):
        assert resolver_regimen(db_session, comp, "00003-00009750") == Regimen.CUENTA_1


def test_cuenta_2_fae(db_session):
    assert resolver_regimen(db_session, "FAE", "05001-02057831") == Regimen.CUENTA_2


def test_cuenta_2_cve_reverso(db_session):
    assert resolver_regimen(db_session, "CVE", "05001-19036008") == Regimen.CUENTA_2


def test_prefijo_00007_gana_sobre_comprobante_cuenta_1(db_session):
    assert resolver_regimen(db_session, "FEA", "00007-00000014") == Regimen.PERDIDA_DEFINITIVA


def test_prefijo_05007_gana_sobre_comprobante_cuenta_2(db_session):
    assert resolver_regimen(db_session, "FAE", "05007-00000008") == Regimen.PERDIDA_DEFINITIVA


def test_prefijo_perdida_definitiva_sobre_cva(db_session):
    # CVA está seedeado como NO_RECONOCIDO fuera del caso de pérdida
    # definitiva (§6.1) — con el prefijo, el prefijo gana igual.
    assert resolver_regimen(db_session, "CVA", "00007-00000014") == Regimen.PERDIDA_DEFINITIVA


def test_mla_no_determinado_pendiente_p01(db_session):
    assert resolver_regimen(db_session, "MLA", "00001-00000001") == Regimen.NO_DETERMINADO


def test_comprobante_no_reconocido(db_session):
    assert resolver_regimen(db_session, "XYZ", "00001-00000001") == Regimen.NO_RECONOCIDO


def test_cva_sin_prefijo_perdida_definitiva_no_reconocido(db_session):
    assert resolver_regimen(db_session, "CVA", "00001-00000001") == Regimen.NO_RECONOCIDO
