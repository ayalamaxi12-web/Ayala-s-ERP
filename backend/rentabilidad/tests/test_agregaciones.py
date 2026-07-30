"""Etapa 9 — agregaciones puras (§11): sin reglas de negocio adicionales,
% siempre sobre totales agregados, exclusión lógica respetada, bloque AGIN
excluye líneas sin responsable a propósito (O-06)."""
from datetime import date
from decimal import Decimal

from rentabilidad.agregaciones import agregar_ecom, agregar_tactica, agregar_tactica_con_agin_por_responsable
from rentabilidad.models import MotivoExclusion, Regimen, VentaEcom, VentaTactica
from rentabilidad.validador import excluir_linea


def _linea_tactica(**overrides) -> VentaTactica:
    base = dict(
        periodo="P1", fecha=date(2026, 6, 1), empresa="E", codigo="SKU1",
        tipo_factura="FEA", nro_factura="00003-1", cantidad=Decimal(1),
        precio_venta=Decimal(100), tc=Decimal(1500), regimen=Regimen.CUENTA_1,
        canal_tactica="Canal Tactica", responsable="Juan",
        precio_venta_iva=Decimal(121), costo_total_pesos=Decimal(-50), margen_real=Decimal(30),
    )
    base.update(overrides)
    return VentaTactica(**base)


def _linea_ecom(**overrides) -> VentaEcom:
    base = dict(
        periodo="P1", numero_orden="1", skus_vendidos="SKU1", costo_sin_iva=Decimal(1),
        comision_venta=Decimal(0), comision_cobro=Decimal(0), costo_envio=Decimal(0),
        precio_sin_iva=Decimal(100), precio_final=Decimal(120), tc=Decimal(1500),
        canal_de_venta="Mercadolibre", costo_total=Decimal(40), rentabilidad=Decimal(20),
    )
    base.update(overrides)
    return VentaEcom(**base)


def test_agregar_tactica_por_canal_suma_y_pct(db_session):
    db_session.add_all([
        _linea_tactica(nro_factura="1", precio_venta=Decimal(100), margen_real=Decimal(30)),
        _linea_tactica(nro_factura="2", precio_venta=Decimal(200), margen_real=Decimal(50)),
    ])
    db_session.commit()

    filas = agregar_tactica(db_session, "P1", "canal")
    assert len(filas) == 1
    fila = filas[0]
    assert fila.suma_precio_venta == Decimal(300)
    assert fila.suma_margen_real == Decimal(80)
    assert fila.pct == Decimal(80) / Decimal(300)  # nunca promedio de %, sobre el total
    assert fila.cantidad_lineas == 2


def test_agregar_tactica_excluye_lineas_excluidas_por_defecto(db_session):
    l1 = _linea_tactica(nro_factura="1", precio_venta=Decimal(100), margen_real=Decimal(30))
    l2 = _linea_tactica(nro_factura="2", precio_venta=Decimal(9999), margen_real=Decimal(9999))
    db_session.add_all([l1, l2])
    db_session.commit()
    excluir_linea(l2, MotivoExclusion.FIXTURE)
    db_session.commit()

    filas = agregar_tactica(db_session, "P1", "canal")
    assert filas[0].suma_precio_venta == Decimal(100)
    assert filas[0].cantidad_lineas == 1


def test_agregar_tactica_incluir_excluidos_true_los_trae_igual(db_session):
    l1 = _linea_tactica(nro_factura="1", precio_venta=Decimal(100))
    l2 = _linea_tactica(nro_factura="2", precio_venta=Decimal(50))
    db_session.add_all([l1, l2])
    db_session.commit()
    excluir_linea(l2, MotivoExclusion.FIXTURE)
    db_session.commit()

    filas = agregar_tactica(db_session, "P1", "canal", incluir_excluidos=True)
    assert filas[0].cantidad_lineas == 2
    assert filas[0].suma_precio_venta == Decimal(150)


def test_agregar_ecom_por_canal(db_session):
    db_session.add_all([
        _linea_ecom(numero_orden="1", precio_sin_iva=Decimal(100), rentabilidad=Decimal(20)),
        _linea_ecom(numero_orden="2", precio_sin_iva=Decimal(300), rentabilidad=Decimal(60)),
    ])
    db_session.commit()

    filas = agregar_ecom(db_session, "P1", "canal")
    assert len(filas) == 1
    fila = filas[0]
    assert fila.suma_precio_sin_iva == Decimal(400)
    assert fila.suma_rentabilidad == Decimal(80)
    assert fila.pct == Decimal(80) / Decimal(400)


def test_agin_excluye_lineas_sin_responsable(db_session):
    db_session.add_all([
        _linea_tactica(nro_factura="1", precio_venta=Decimal(1000), responsable="Juan"),
        _linea_tactica(nro_factura="2", precio_venta=Decimal(500), responsable=None),
    ])
    db_session.commit()

    filas = agregar_tactica_con_agin_por_responsable(db_session, "P1")
    assert len(filas) == 1
    assert filas[0].responsable == "Juan"
    assert filas[0].suma_precio_venta == Decimal(1000)
    assert filas[0].agin_1 == Decimal(1000) * Decimal("0.009")
    assert filas[0].agin_2 == Decimal(1000) * Decimal("0.004")
