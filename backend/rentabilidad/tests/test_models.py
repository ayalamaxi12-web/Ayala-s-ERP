"""Etapa 1 — verifica el esquema y la carga paramétrica, no el motor de
cálculo (eso es Etapa 4/5/6/7). Ninguna tasa/prefijo/régimen se hardcodea acá:
solo se comprueba que lo que quedó en la base coincide con RENTABILIDAD_FUNCIONAL.md.
"""
from datetime import date
from decimal import Decimal

from rentabilidad.models import (
    ParametroTasa,
    PrefijoPerdidaDefinitiva,
    Regimen,
    RegimenComprobante,
    SkuAuxiliar,
    SkuExcluido,
    VentaEcom,
    VentaTactica,
)


def test_tasas_seedeadas_segun_funcional_5_3(db_session):
    tasas = {t.nombre: t for t in db_session.query(ParametroTasa).all()}
    assert tasas["imp_cheque"].valor == Decimal("0.012")
    assert tasas["imp_cheque"].motor == "AMBOS"
    assert tasas["iibb"].valor == Decimal("0.05")
    assert tasas["iibb"].motor == "AMBOS"
    assert tasas["cf1"].valor == Decimal("0.03")
    assert tasas["cf1"].motor == "TACTICA"
    assert tasas["cf2"].valor == Decimal("0.03")
    assert tasas["cf2"].motor == "TACTICA"
    assert tasas["agin_1"].valor == Decimal("0.009")
    assert tasas["agin_2"].valor == Decimal("0.004")


def test_prefijos_perdida_definitiva_segun_funcional_6_1(db_session):
    prefijos = {p.prefijo for p in db_session.query(PrefijoPerdidaDefinitiva).all()}
    assert prefijos == {"00007", "05007"}


def test_regimen_comprobante_segun_funcional_6_1(db_session):
    mapa = {r.comprobante: r.regimen for r in db_session.query(RegimenComprobante).all()}
    assert mapa["FEA"] == Regimen.CUENTA_1
    assert mapa["FEB"] == Regimen.CUENTA_1
    assert mapa["FEE"] == Regimen.CUENTA_1
    assert mapa["CEA"] == Regimen.CUENTA_1
    assert mapa["CEB"] == Regimen.CUENTA_1
    assert mapa["CEE"] == Regimen.CUENTA_1
    assert mapa["FAE"] == Regimen.CUENTA_2
    assert mapa["CVE"] == Regimen.CUENTA_2
    assert mapa["MLA"] == Regimen.NO_DETERMINADO


def test_sku_excluido_vacia_pendiente_p05(db_session):
    assert db_session.query(SkuExcluido).count() == 0


def test_sku_auxiliar_promos(db_session):
    patrones = {s.patron for s in db_session.query(SkuAuxiliar).all()}
    assert "PROMOS-*" in patrones


def test_venta_tactica_preserva_precision_decimal(db_session):
    """Caso T-1 de §13.1 como smoke test de persistencia — no del cálculo:
    solo confirma que los importes viajan y vuelven exactos, sin corrupción
    de float (prohibición técnica #2)."""
    fila = VentaTactica(
        periodo="Junio-Julio",
        fecha=date(2026, 6, 15),
        empresa="Cliente Demo",
        codigo="CF217ACOMP",
        tipo_factura="FEA",
        nro_factura="00003-00127071",
        cantidad=Decimal("6"),
        precio_venta=Decimal("31153.50"),
        tc=Decimal("1500"),
        costo_lista=Decimal("2.65"),
    )
    db_session.add(fila)
    db_session.commit()

    recuperada = db_session.query(VentaTactica).filter_by(codigo="CF217ACOMP").one()
    assert recuperada.precio_venta == Decimal("31153.50")
    assert recuperada.tc == Decimal("1500")
    assert recuperada.costo_lista == Decimal("2.65")
    assert isinstance(recuperada.precio_venta, Decimal)


def test_venta_ecom_acepta_multiples_skus_sin_normalizar(db_session):
    fila = VentaEcom(
        periodo="Julio-Agosto",
        numero_orden="1405031",
        skus_vendidos="SKU-A, SKU-B",
        costo_sin_iva=Decimal("130.27"),
        comision_venta=Decimal("98898.56"),
        comision_cobro=Decimal("0"),
        costo_envio=Decimal("7821"),
        precio_sin_iva=Decimal("620053.636"),
        precio_final=Decimal("682059"),
        tc=Decimal("1500"),
    )
    db_session.add(fila)
    db_session.commit()

    recuperada = db_session.query(VentaEcom).filter_by(numero_orden="1405031").one()
    assert recuperada.skus_vendidos == "SKU-A, SKU-B"
    assert recuperada.vinculacion == "OK"  # default (§8.4), no se invierte
    assert recuperada.comision_cobro == Decimal("0")
