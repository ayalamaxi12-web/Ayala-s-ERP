"""Motor de precios — fija los ejemplos del documento de diseño
("Motor de Pricing Ayala — Diseño detallado", 2026-09-29) y las reglas
aprobadas por Maxx, sobre los parámetros sembrados (`seed.seed_pricing`)."""
import os
import tempfile
from datetime import date

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from rentabilidad import motor_precios as m
from rentabilidad.db import Base
from rentabilidad.models import PricingCuotas, PricingParametro, PricingTramo
from rentabilidad.tests.test_migrations import RENTABILIDAD_DIR

from .conftest import d

HOY = date(2026, 9, 29)


@pytest.fixture()
def par(db_session):
    return m.cargar_parametros(db_session, HOY)


def _plancha(**k):
    """PLANCHA-SUB-26X26-PORT, ejemplo 3.5 del documento."""
    base = dict(canal="ML", costo=d("56105.10"), iva_factor=d("1.105"), categoria="Gráfica y Estampado", envio=d("29410"))
    return m.EntradaMotor(**{**base, **k})


# ── Ejemplo 3.5: los dos modos en ML ──

def test_ml_precio_a_margen_contado_desglosa_cada_cargo(par):
    r = m.precio_a_margen(d("201258"), _plancha(), par)
    assert r.venta_sin_iva == d("182133.94")
    assert r.cargos == {
        "comision": d("31194.99"), "cuotas": d("0.00"), "costo_fijo": d("0.00"), "envio": d("29410.00"),
        "imp_cheque": d("2415.10"), "iibb": d("9106.70"), "costo": d("56105.10"),
    }
    assert r.rentabilidad == d("53902.05")
    assert r.margen == d("0.2959")


def test_ml_tres_cuotas_descuenta_el_cargo_por_cuotas(par):
    r = m.precio_a_margen(d("239645"), _plancha(plan="3"), par)
    assert r.cargos["cuotas"] == d("21328.41")  # 8,9%
    assert r.margen == d("0.2728")


@pytest.mark.parametrize("plan,precio", [("contado", "203019"), ("3", "257399"), ("6", "297719")])
def test_ml_margen_a_precio_cumple_el_margen_pedido(par, plan, precio):
    r = m.margen_a_precio(d("0.30"), _plancha(plan=plan), par)
    assert r.precio == d(precio)
    assert r.margen == d("0.3000")


def test_ida_y_vuelta_sin_redondeo_devuelve_el_mismo_margen(par):
    r = m.margen_a_precio(d("0.2537"), _plancha(plan="6"), par, redondear=False)
    assert r.margen == d("0.2537")


def test_redondeo_como_las_planillas():
    assert m.redondear_precio(d("200635.4")) == d("200639")
    assert m.redondear_precio(d("200629.9")) == d("200629")


# ── ML: costo fijo, envío gratis, comisión por categoría ──

def test_ml_barato_lleva_costo_fijo_actual_y_no_envio(par):
    r = m.precio_a_margen(d("10159"), _plancha(costo=d("3000"), envio=d("9999")), par)
    assert r.cargos["costo_fijo"] == d("1330.00")
    assert r.cargos["envio"] == d("0.00")  # < $33.000: el envío lo paga el comprador


def test_ml_costo_fijo_de_la_publicacion_tiene_prioridad_sobre_la_tabla(par):
    r = m.precio_a_margen(d("20000"), _plancha(costo=d("3000"), costo_fijo_ml=d("2910")), par)
    assert r.cargos["costo_fijo"] == d("2910.00")


def test_ml_margen_a_precio_recalcula_si_el_precio_cae_en_un_tramo_de_costo_fijo(par):
    r = m.margen_a_precio(d("0.30"), _plancha(costo=d("3000"), envio=d("0")), par)
    assert r.precio == d("10279")
    assert r.cargos["costo_fijo"] == d("1330.00")
    assert r.margen == d("0.3000")


def test_ml_categoria_sin_fila_usa_la_comision_general(par):
    r = m.precio_a_margen(d("100000"), _plancha(categoria="Impresión 3D"), par)
    assert r.cargos["comision"] == d("15500.00")


def test_ml_comision_unica_15_5_aunque_la_categoria_tenga_fila_propia(par):
    # Criterio de margen §2: 15,5% único. La tabla por categoría sigue cargada
    # (futuro) pero el motor no la usa.
    assert par.comision_categoria[("ML", "audio y video")] == d("0.16")
    for cat in ("Audio y Video", "Electrodomesticos", "Gráfica y Estampado"):
        r = m.precio_a_margen(d("100000"), _plancha(categoria=cat), par)
        assert r.cargos["comision"] == d("15500.00")


# ── Web (Mercado Pago): tarifa del panel + IVA ──

def test_web_mp_suma_el_iva_a_comision_y_cuotas(par):
    e = m.EntradaMotor(canal="WEB", costo=d("50000"), iva_factor=d("1.21"), plan="3")
    r = m.precio_a_margen(d("120000"), e, par)
    assert r.cargos["comision"] == d("7260.00")  # 5,00% × 1,21 = 6,05%, igual a lo cobrado en Woo
    assert r.cargos["cuotas"] == d("4936.80")  # 3,40% × 1,21 = 4,11%
    assert r.margen == d("0.3083")


def test_web_debito_usa_la_tarifa_al_instante(par):
    e = m.EntradaMotor(canal="WEB", costo=d("50000"), iva_factor=d("1.21"), medio_pago="otros")
    assert m.precio_a_margen(d("100000"), e, par).cargos["comision"] == d("7610.90")  # 6,29% × 1,21


def test_ml_y_mp_no_comparten_tabla_de_cuotas(par):
    assert par.cuota("ML", "3") == d("0.089")
    assert par.cuota("WEB", "3") == d("0.034")


# ── Frávega: comisión + financiera + fee, todo + IVA ──

def _fravega(**k):
    return m.EntradaMotor(**{**dict(canal="FRAVEGA", costo=d("50000"), iva_factor=d("1.21")), **k})


def test_fravega_por_kilo_aforado_sin_colecta(par):
    r = m.precio_a_margen(d("120000"), _fravega(plan="6", kg_aforado=d("0.9")), par)
    assert r.cargos["comision"] == d("21780.00")  # 15% × 1,21
    assert r.cargos["financiera"] == d("15391.20")  # 10,6% × 1,21
    assert r.cargos["fee_logistico"] == d("3350.49")  # 2.769 × 1,21 (0–1,5 kg, orden ≥ $35.000)
    assert r.origen_fee == "kg_aforado"


def test_fravega_orden_chica_usa_la_escala_baja(par):
    r = m.precio_a_margen(d("30000"), _fravega(costo=d("5000"), kg_aforado=d("3")), par)
    assert r.cargos["fee_logistico"] == d("1996.50")  # 1.650 × 1,21 (1,5–5 kg, orden < $35.000)


def test_fravega_limite_de_escala_de_peso_es_inclusivo(par):
    assert m.precio_a_margen(d("50000"), _fravega(kg_aforado=d("1.5")), par).cargos["fee_logistico"] == d("3350.49")


def test_fravega_fee_historico_primero_despues_kilo_despues_promedio(par):
    assert m.precio_a_margen(d("50000"), _fravega(fee_logistico=d("1016"), kg_aforado=d("9")), par).origen_fee == "historico"
    promedio = m.precio_a_margen(d("50000"), _fravega(), par)
    assert promedio.origen_fee == "promedio"
    assert promedio.cargos["fee_logistico"] == d("10285.00")  # 8.500 × 1,21


def test_fravega_con_colecta_usa_su_tabla(par):
    r = m.precio_a_margen(d("50000"), _fravega(kg_aforado=d("1"), colecta=True), par)
    assert r.cargos["fee_logistico"] == d("5576.89")  # 4.609 × 1,21


# ── Errores claros ──

def test_margen_inalcanzable(par):
    with pytest.raises(ValueError, match="inalcanzable"):
        m.margen_a_precio(d("0.80"), _plancha(), par)


def test_plan_sin_costo_cargado(par):
    with pytest.raises(m.ParametroFaltante):
        m.precio_a_margen(d("50000"), _plancha(plan="18"), par)


def test_megatone_sin_tarifario_avisa(par):
    with pytest.raises(m.ParametroFaltante, match="MEGATONE"):
        m.precio_a_margen(d("50000"), m.EntradaMotor(canal="MEGATONE", costo=d("1"), iva_factor=d("1.21")), par)


# ── Vigencia: nada se pisa, rige la última fila a la fecha ──

def test_un_cambio_con_vigencia_futura_no_afecta_hoy(db_session):
    db_session.add(PricingParametro(canal="*", clave="iibb", valor=d("0.065"), vigente_desde=date(2026, 10, 1), cargado_por="test"))
    db_session.add(PricingCuotas(canal="ML", plan="3", pct=d("0.095"), vigente_desde=date(2026, 10, 1), cargado_por="test"))
    db_session.flush()
    hoy, despues = m.cargar_parametros(db_session, HOY), m.cargar_parametros(db_session, date(2026, 10, 1))
    assert hoy.valor("ML", "iibb") == d("0.05") and despues.valor("ML", "iibb") == d("0.065")
    assert hoy.cuota("ML", "3") == d("0.089") and despues.cuota("ML", "3") == d("0.095")


def test_una_tabla_de_tramos_nueva_reemplaza_entera_a_la_anterior(db_session):
    db_session.add(PricingTramo(tabla="ml_costo_fijo", unidad="precio", desde=d("0"), hasta=d("20000"), valor=d("1500"),
                                vigente_desde=date(2026, 10, 1), cargado_por="test"))
    db_session.flush()
    despues = m.cargar_parametros(db_session, date(2026, 10, 1))
    assert despues.tramo("ml_costo_fijo", d("18000")) == d("1500")
    assert despues.tramo("ml_costo_fijo", d("25000")) is None  # la tabla vieja ya no rige
    assert m.cargar_parametros(db_session, HOY).tramo("ml_costo_fijo", d("18000")) == d("2740")


def test_la_tabla_de_fee_de_fravega_rige_desde_el_7_de_septiembre(db_session):
    assert "fravega_fee_sin_colecta_alto" not in m.cargar_parametros(db_session, date(2026, 9, 6)).tramos


# ── Esquema: la migración Alembic crea exactamente lo que dicen los modelos ──

def test_migracion_del_motor_coincide_con_los_modelos():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        url = f"sqlite:///{os.path.join(tmp, 'motor.sqlite3')}"
        cfg = Config(str(RENTABILIDAD_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(RENTABILIDAD_DIR / "migrations"))
        cfg.set_main_option("sqlalchemy.url", url)
        command.upgrade(cfg, "head")
        engine = create_engine(url, future=True)
        try:
            with engine.connect() as conn:
                diferencias = compare_metadata(MigrationContext.configure(conn), Base.metadata)
        finally:
            engine.dispose()
    del_motor = [x for x in diferencias if "pricing_" in repr(x)]
    assert del_motor == []
