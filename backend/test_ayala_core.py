from decimal import Decimal

import ayala_core
from ayala_core import (
    calcular_precio_condicion,
    calcular_precios_todas_condiciones,
    detectar_condicion_pago,
)


# ── Ejemplo congelado, AYALA_CORE.md A.3.1 (PLANCHA-SUB-26X26-PORT,
# tomado de la planilla 2026-09-02) -- valida el motor al peso exacto.
# Usa las tasas de cuotas VIEJAS (8,4/12,3/15,7/19,2%) a propósito: son
# las que estaban en la planilla cuando se congeló el ejemplo, antes de
# la corrección del mismo día (ver Decisiones tomadas en el .md) -- por
# eso se pasan explícitas acá y no se lee `CUOTAS_PCT_DEFAULT` (que ya
# tiene las nuevas, 8,9/13,4/17,8/21,6%). ──
_COSTO = Decimal("56105.10")
_IVA_FACTOR = Decimal("1.105")
_ENVIO = Decimal("29410")


def test_congelado_contado():
    p = calcular_precio_condicion(
        costo_sin_iva=_COSTO, iva_factor=_IVA_FACTOR, envio_real=_ENVIO,
        financiero_pct=Decimal("0"), renta_pct=Decimal("32"),
    )
    assert p == Decimal("201258")


def test_congelado_reducida():
    p = calcular_precio_condicion(
        costo_sin_iva=_COSTO, iva_factor=_IVA_FACTOR, envio_real=_ENVIO,
        financiero_pct=Decimal("5"), renta_pct=Decimal("32"),
    )
    assert p == Decimal("230046")


def test_congelado_3_cuotas_tasa_vieja():
    p = calcular_precio_condicion(
        costo_sin_iva=_COSTO, iva_factor=_IVA_FACTOR, envio_real=_ENVIO,
        financiero_pct=Decimal("8.4"), renta_pct=Decimal("30"),
    )
    assert p == Decimal("239645")


def test_congelado_6_cuotas_tasa_vieja():
    p = calcular_precio_condicion(
        costo_sin_iva=_COSTO, iva_factor=_IVA_FACTOR, envio_real=_ENVIO,
        financiero_pct=Decimal("12.3"), renta_pct=Decimal("28"),
    )
    assert p == Decimal("254029")


def test_congelado_9_cuotas_tasa_vieja():
    p = calcular_precio_condicion(
        costo_sin_iva=_COSTO, iva_factor=_IVA_FACTOR, envio_real=_ENVIO,
        financiero_pct=Decimal("15.7"), renta_pct=Decimal("26"),
    )
    assert p == Decimal("265784")


def test_congelado_12_cuotas_tasa_vieja():
    p = calcular_precio_condicion(
        costo_sin_iva=_COSTO, iva_factor=_IVA_FACTOR, envio_real=_ENVIO,
        financiero_pct=Decimal("19.2"), renta_pct=Decimal("24"),
    )
    assert p == Decimal("279649")


def test_congelado_las_6_condiciones_juntas_con_tasas_vigentes():
    # Mismo ejemplo, pero llamando al motor completo con las tasas
    # ACTUALES de CUOTAS_PCT_DEFAULT (8,9/13,4/17,8/21,6%) -- no debe dar
    # lo mismo que el ejemplo congelado en las 4 columnas de cuotas
    # (la Reducida y el Contado sí, porque no dependen de esa tabla).
    precios = calcular_precios_todas_condiciones(
        costo_sin_iva=_COSTO, iva_factor=_IVA_FACTOR, envio_real=_ENVIO,
    )
    assert precios["contado"] == Decimal("201258")
    assert precios["reducida"] == Decimal("230046")
    assert precios["3"] != Decimal("239645")  # tasa vigente subió -> precio distinto
    assert set(precios) == {"contado", "reducida", "3", "6", "9", "12"}


def test_renta_baja_2_puntos_por_escalon_de_cuotas():
    # Motor!D31:G31 real: cada escalón resta 2 puntos sobre el anterior,
    # arrancando desde Reducida (no desde Contado directo -- Reducida
    # "hereda" la renta de Contado sin cambio).
    precios_altos = calcular_precios_todas_condiciones(
        costo_sin_iva=_COSTO, iva_factor=_IVA_FACTOR, envio_real=_ENVIO,
        renta_contado_pct=Decimal("40"), diferencial_cuotas_pct=Decimal("2"),
    )
    # A mayor renta objetivo, el precio de cada condición debe subir vs.
    # el default (32%) -- prueba de sanidad, no un valor congelado.
    default = calcular_precios_todas_condiciones(
        costo_sin_iva=_COSTO, iva_factor=_IVA_FACTOR, envio_real=_ENVIO,
    )
    for cond in ayala_core.CONDICIONES:
        assert precios_altos[str(cond)] > default[str(cond)]


def test_envio_full_suma_un_medio_pct_solo_si_se_pide():
    sin_full = calcular_precio_condicion(
        costo_sin_iva=_COSTO, iva_factor=_IVA_FACTOR, envio_real=_ENVIO,
        financiero_pct=Decimal("0"), renta_pct=Decimal("32"), envio_full=False,
    )
    con_full = calcular_precio_condicion(
        costo_sin_iva=_COSTO, iva_factor=_IVA_FACTOR, envio_real=_ENVIO,
        financiero_pct=Decimal("0"), renta_pct=Decimal("32"), envio_full=True,
    )
    assert con_full > sin_full


def test_financiero_pct_condicion_no_soportada_explota():
    import pytest
    with pytest.raises(ValueError):
        calcular_precio_condicion(
            costo_sin_iva=_COSTO, iva_factor=_IVA_FACTOR, envio_real=_ENVIO,
            financiero_pct=ayala_core._financiero_pct(18), renta_pct=Decimal("32"),
        )


# ── Detección de condición de pago, A.4 ──

def test_detectar_condicion_reducida_por_tag():
    assert detectar_condicion_pago({"tags": ["pcj-co-funded", "immediate_payment"]}) == "reducida"


def test_detectar_condicion_cuotas_sin_interes_por_tag():
    assert detectar_condicion_pago({"tags": ["3x_campaign", "immediate_payment"]}) == 3


def test_detectar_condicion_contado_default():
    assert detectar_condicion_pago({"tags": ["immediate_payment"]}) == "contado"
    assert detectar_condicion_pago({}) == "contado"


def test_reducida_tiene_prioridad_si_por_algun_motivo_conviven_los_dos_tags():
    # No debería pasar en la práctica (son mutuamente excluyentes en ML,
    # confirmado en vivo), pero si convivieran, Reducida gana -- es la
    # que ML mostró priorizada al alternar campañas en el mismo item.
    assert detectar_condicion_pago({"tags": ["pcj-co-funded", "3x_campaign"]}) == "reducida"


# ── SKUs piloto ──

def test_skus_piloto_son_los_5_confirmados():
    assert ayala_core.SKUS_PILOTO == [
        "PLANCHA-SUB-26X26-PORT", "PLANCHA-SUB-30X38-10EN1", "PLANCHA-SUB-30X38-5EN1",
        "PLANCHA-SUB-GORRA", "PLANCHA-SUB-TERMO",
    ]
