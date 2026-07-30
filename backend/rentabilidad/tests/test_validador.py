"""Etapa 8 — un caso por cada uno de los 16 controles de §12, más exclusión
lógica (§10) y cuadre de período (§15/V-15)."""
from datetime import date
from decimal import Decimal

from rentabilidad.models import MotivoExclusion, Regimen, VentaEcom, VentaTactica
from rentabilidad.validador import BLOQUEANTE, INFORMATIVO, ValidadorRentabilidad, excluir_linea


def _linea_tactica(**overrides) -> VentaTactica:
    base = dict(
        periodo="P1", fecha=date(2026, 6, 1), empresa="E", codigo="SKU1",
        tipo_factura="FEA", nro_factura="00003-1", cantidad=Decimal(1),
        precio_venta=Decimal(100), tc=Decimal(1500), regimen=Regimen.CUENTA_1,
        costo_lista=Decimal(1), iva_producto=Decimal("1.21"),
        costo_financiero_2=Decimal(0), pm="Matias",
    )
    base.update(overrides)
    return VentaTactica(**base)


def _linea_ecom(**overrides) -> VentaEcom:
    base = dict(
        periodo="P1", numero_orden="1", skus_vendidos="SKU1", costo_sin_iva=Decimal(1),
        comision_venta=Decimal(0), comision_cobro=Decimal(0), costo_envio=Decimal(0),
        precio_sin_iva=Decimal(100), precio_final=Decimal(120), tc=Decimal(1500),
        iva=Decimal("1.21"), pm="Matias", vinculacion="OK",
    )
    base.update(overrides)
    return VentaEcom(**base)


def _codigos(incidencias):
    return {i.codigo for i in incidencias}


# ── TACTICA ──

def test_v1_comprobante_no_reconocido(db_session):
    v = ValidadorRentabilidad(db_session)
    r = v.validar_linea_tactica(_linea_tactica(regimen=Regimen.NO_RECONOCIDO, tipo_factura="MLA"))
    assert "V-1" in _codigos(r)
    assert next(i for i in r if i.codigo == "V-1").severidad == BLOQUEANTE


def test_v2_nota_de_debito(db_session):
    v = ValidadorRentabilidad(db_session)
    r = v.validar_linea_tactica(_linea_tactica(motivo_exclusion=MotivoExclusion.NOTA_DEBITO))
    assert "V-2" in _codigos(r)


def test_v3_iva_no_resuelto_cuenta1(db_session):
    v = ValidadorRentabilidad(db_session)
    r = v.validar_linea_tactica(_linea_tactica(iva_producto=None))
    assert "V-3" in _codigos(r)


def test_v3_no_aplica_en_cuenta2(db_session):
    v = ValidadorRentabilidad(db_session)
    r = v.validar_linea_tactica(_linea_tactica(regimen=Regimen.CUENTA_2, iva_producto=None, costo_financiero_1=None))
    assert "V-3" not in _codigos(r)


def test_v5_costo_no_resuelto(db_session):
    v = ValidadorRentabilidad(db_session)
    r = v.validar_linea_tactica(_linea_tactica(costo_lista=None))
    assert "V-5" in _codigos(r)


def test_v6_tc_ausente_tactica(db_session):
    v = ValidadorRentabilidad(db_session)
    r = v.validar_linea_tactica(_linea_tactica(tc=Decimal(0)))
    assert "V-6" in _codigos(r)


def test_v7_precio_vacio_tactica(db_session):
    v = ValidadorRentabilidad(db_session)
    r = v.validar_linea_tactica(_linea_tactica(precio_venta=Decimal(0)))
    assert "V-7" in _codigos(r)


def test_v8_cuenta1_con_z_distinto_de_cero(db_session):
    v = ValidadorRentabilidad(db_session)
    r = v.validar_linea_tactica(_linea_tactica(costo_financiero_2=Decimal(5)))
    assert "V-8" in _codigos(r)


def test_v8_cuenta2_con_s_poblado(db_session):
    v = ValidadorRentabilidad(db_session)
    r = v.validar_linea_tactica(_linea_tactica(
        regimen=Regimen.CUENTA_2, iva=Decimal(5), iva_producto=None, costo_financiero_1=Decimal(0),
    ))
    assert "V-8" in _codigos(r)


def test_v9_perdida_definitiva_no_aplicada(db_session):
    v = ValidadorRentabilidad(db_session)
    r = v.validar_linea_tactica(_linea_tactica(
        regimen=Regimen.PERDIDA_DEFINITIVA, margen_real=Decimal(999), precio_venta=Decimal(100),
    ))
    assert "V-9" in _codigos(r)


def test_v10_nota_credito_signo_invertido(db_session):
    v = ValidadorRentabilidad(db_session)
    r = v.validar_linea_tactica(_linea_tactica(tipo_factura="CEA", cantidad=Decimal(2), precio_venta=Decimal(100)))
    assert "V-10" in _codigos(r)


def test_v13_sin_pm_tactica(db_session):
    v = ValidadorRentabilidad(db_session)
    r = v.validar_linea_tactica(_linea_tactica(pm="SIN PM"))
    assert "V-13" in _codigos(r)


def test_v16_duplicados_tactica(db_session):
    db_session.add_all([
        _linea_tactica(nro_factura="00003-1", codigo="SKU1"),
        _linea_tactica(nro_factura="00003-1", codigo="SKU1"),
    ])
    db_session.commit()
    v = ValidadorRentabilidad(db_session)
    incidencias = v.detectar_duplicados_tactica("P1")
    assert len(incidencias) == 1
    assert incidencias[0].codigo == "V-16" and incidencias[0].severidad == INFORMATIVO


# ── ECOM ──

def test_v4_iva_no_resuelto_ecom_es_informativo(db_session):
    v = ValidadorRentabilidad(db_session)
    r = v.validar_linea_ecom(_linea_ecom(iva=None))
    assert "V-4" in _codigos(r)
    assert next(i for i in r if i.codigo == "V-4").severidad == INFORMATIVO


def test_v6_tc_ausente_ecom(db_session):
    v = ValidadorRentabilidad(db_session)
    r = v.validar_linea_ecom(_linea_ecom(tc=Decimal(-1)))
    assert "V-6" in _codigos(r)


def test_v7_precio_vacio_ecom(db_session):
    v = ValidadorRentabilidad(db_session)
    r = v.validar_linea_ecom(_linea_ecom(precio_sin_iva=Decimal(0)))
    assert "V-7" in _codigos(r)


def test_v11_comision_cobro_informativa(db_session):
    v = ValidadorRentabilidad(db_session)
    r = v.validar_linea_ecom(_linea_ecom(comision_cobro=Decimal(50)))
    assert "V-11" in _codigos(r)


def test_v12_retenciones_informadas(db_session):
    v = ValidadorRentabilidad(db_session)
    r = v.validar_linea_ecom(_linea_ecom(impuestos_informados=Decimal(20)))
    assert "V-12" in _codigos(r)


def test_v13_sin_pm_ecom(db_session):
    v = ValidadorRentabilidad(db_session)
    r = v.validar_linea_ecom(_linea_ecom(pm=None))
    assert "V-13" in _codigos(r)


def test_v14_vinculacion_distinta_de_ok(db_session):
    v = ValidadorRentabilidad(db_session)
    r = v.validar_linea_ecom(_linea_ecom(vinculacion="REVISAR"))
    assert "V-14" in _codigos(r)


def test_v16_duplicados_ecom(db_session):
    db_session.add_all([_linea_ecom(numero_orden="1"), _linea_ecom(numero_orden="1")])
    db_session.commit()
    v = ValidadorRentabilidad(db_session)
    incidencias = v.detectar_duplicados_ecom("P1")
    assert len(incidencias) == 1


# ── Exclusión lógica (§10) ──

def test_exclusion_logica_no_borra_la_fila(db_session):
    linea = _linea_tactica()
    db_session.add(linea)
    db_session.commit()
    excluir_linea(linea, MotivoExclusion.FIXTURE)
    db_session.commit()

    recuperada = db_session.get(VentaTactica, linea.id)
    assert recuperada is not None  # sigue existiendo
    assert recuperada.excluido is True
    assert recuperada.motivo_exclusion == MotivoExclusion.FIXTURE


# ── Cuadre de período (V-15) ──

def test_v15_cuadre_periodo_detecta_diferencia(db_session):
    db_session.add(_linea_tactica(margen_real=Decimal(100)))
    db_session.add(_linea_ecom(rentabilidad=Decimal(50)))
    db_session.commit()

    v = ValidadorRentabilidad(db_session)
    incidencias = v.validar_cuadre_periodo("P1", suma_aa_tactica_esperada=Decimal(999), suma_ab_ecom_esperada=Decimal(999))
    assert any(i.codigo == "V-15" and i.entidad == "TACTICA" for i in incidencias)
    assert any(i.codigo == "V-15" and i.entidad == "ECOM" for i in incidencias)


def test_v15_cuadre_periodo_sin_diferencia_no_incidencia(db_session):
    db_session.add(_linea_tactica(margen_real=Decimal(100)))
    db_session.add(_linea_ecom(rentabilidad=Decimal(50)))
    db_session.commit()

    v = ValidadorRentabilidad(db_session)
    incidencias = v.validar_cuadre_periodo("P1", suma_aa_tactica_esperada=Decimal(100), suma_ab_ecom_esperada=Decimal(50))
    assert incidencias == []


def test_v15_excluye_lineas_excluidas_de_la_suma(db_session):
    l1 = _linea_tactica(margen_real=Decimal(100))
    l2 = _linea_tactica(margen_real=Decimal(9999))
    db_session.add_all([l1, l2])
    db_session.commit()
    excluir_linea(l2, MotivoExclusion.FIXTURE)
    db_session.commit()

    v = ValidadorRentabilidad(db_session)
    incidencias = v.validar_cuadre_periodo("P1", suma_aa_tactica_esperada=Decimal(100), suma_ab_ecom_esperada=Decimal(0))
    assert not any(i.entidad == "TACTICA" for i in incidencias)
