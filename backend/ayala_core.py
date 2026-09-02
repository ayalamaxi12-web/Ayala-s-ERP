"""Ayala Core -- motor de precios propio (reverse-markup) para los SKU
piloto que dejan de depender del sistema de precios de Ecom, escribiendo
directo a MercadoLibre. Ver la constitución del módulo:
docs/business/COMERCIAL/canales/mercadolibre/AYALA_CORE.md -- toda regla
de negocio de acá sale de ese documento y del motor real de la planilla
de Maxx ("VENTAS POR CANALES MATIAS", pestañas Calculadora/Motor/Tasas),
NO se inventa nada acá.

La fórmula de `calcular_precio_condicion` es una transcripción exacta de
`Motor!B32:G32` de esa planilla (leída en modo solo-lectura vía la API
pública de Sheets, 2026-09-02) -- reproduce el ejemplo congelado de
AYALA_CORE.md A.3.1 al peso exacto (ver test_ayala_core.py).
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from ml_ofertas import CUOTAS_PCT_DEFAULT, _cuotas_sin_interes

# Los 5 SKU piloto (AYALA_CORE.md A.1) -- lista extensible, NO un límite
# estructural: no hardcodear "5" en ningún lado que dependa de esto.
SKUS_PILOTO: list[str] = [
    "PLANCHA-SUB-26X26-PORT",
    "PLANCHA-SUB-30X38-10EN1",
    "PLANCHA-SUB-30X38-5EN1",
    "PLANCHA-SUB-GORRA",
    "PLANCHA-SUB-TERMO",
]

# Tasas del motor -- Tasas!B6:D7 de la planilla real (misma para las dos
# alícuotas hoy, 10,5% y 21%). Se mantienen a mano por Maxx (no vienen de
# la API de ML por dominio, a diferencia de Ofertas ML -- ver AYALA_CORE.md
# A.2/A.3, decisión explícita de Maxx de replicar la planilla tal cual).
COMISION_ML_DEFAULT = Decimal("15.32")
IIBB_PCT_DEFAULT = Decimal("6.50")
ENVIO_FULL_PCT_DEFAULT = Decimal("0.50")  # solo si envío a Bodega (Full), Tasas!D6:D7

# Financiero por condición -- Tasas!C13:C18. Reducida es un 5% FIJO (no
# escala con la cantidad de cuotas -- distinto de cuotas sin interés,
# donde el % sube con la cantidad). Cuotas sin interés reutiliza
# `CUOTAS_PCT_DEFAULT` de `ml_ofertas` -- MISMA tabla, un solo lugar para
# corregir si ML cambia la tasa (ver AYALA_CORE.md, Decisiones tomadas
# 2026-09-02).
REDUCIDA_PCT_DEFAULT = Decimal("5.00")

# Renta objetivo -- Calculadora!B11 (Contado) + B12 ("Diferencial en
# cuotas"). Motor!D31:G31 confirma la cascada real: cada escalón de
# cuotas resta EXACTAMENTE el mismo diferencial sobre el escalón
# anterior (Contado -> Reducida: sin cambio; Reducida -> 3c -> 6c -> 9c
# -> 12c: -2 puntos cada paso). Default 32%/2 puntos reproduce el
# ejemplo de AYALA_CORE.md A.3.1 (32/32/30/28/26/24) -- ambos valores son
# editables por SKU (A.3 punto 7).
RENTA_CONTADO_DEFAULT = Decimal("32.00")
RENTA_DIFERENCIAL_CUOTAS_DEFAULT = Decimal("2.00")

# Cuántos "escalones" de -diferencial% aplican por condición, contados
# desde Contado/Reducida (escalón 0) hasta 12 cuotas (escalón 4).
_ESCALON_POR_CONDICION: dict[str | int, int] = {
    "contado": 0, "reducida": 0, 3: 1, 6: 2, 9: 3, 12: 4,
}

CONDICIONES: tuple[str | int, ...] = ("contado", "reducida", 3, 6, 9, 12)

_IVA_SERVICIOS_ML = Decimal("1.21")  # IVA del servicio/comisión de ML -- SIEMPRE 21%,
# sin importar la alícuota del producto (confirmado en la fórmula real).


def _financiero_pct(condicion: str | int) -> Decimal:
    if condicion == "contado":
        return Decimal("0")
    if condicion == "reducida":
        return REDUCIDA_PCT_DEFAULT
    pct = CUOTAS_PCT_DEFAULT.get(condicion)
    if pct is None:
        raise ValueError(f"condición de pago no soportada: {condicion!r}")
    return pct


def calcular_precio_condicion(
    *,
    costo_sin_iva: Decimal,
    iva_factor: Decimal,
    envio_real: Decimal,
    financiero_pct: Decimal,
    renta_pct: Decimal,
    comision_pct: Decimal = COMISION_ML_DEFAULT,
    iibb_pct: Decimal = IIBB_PCT_DEFAULT,
    envio_full: bool = False,
    envio_full_pct: Decimal = ENVIO_FULL_PCT_DEFAULT,
) -> Decimal:
    """Reverse-markup: resuelve el precio de venta (con IVA) tal que,
    descontando comisión ML, IIBB, el costo financiero de la condición
    de pago, el envío y la renta objetivo, cubre EXACTAMENTE el costo
    del producto. `iva_factor` es 1+alícuota (1,105 o 1,21), igual que
    devuelve `IvaProvider.factor()` en `rentabilidad/adapters.py` --
    pensado para no tener que reconvertir nada al llamar desde ahí.

    Nota real de la planilla: la comisión de ML y el % de Envío Full se
    descuentan siempre sobre 1,21 (el servicio de ML factura IVA 21%
    sin importar la alícuota del producto vendido); el IIBB se descuenta
    sobre la alícuota propia del producto (`iva_factor`)."""
    numerador = costo_sin_iva + envio_real / _IVA_SERVICIOS_ML
    full = (envio_full_pct / 100) if envio_full else Decimal("0")
    denominador = (
        (1 / iva_factor)
        - (comision_pct / 100) / _IVA_SERVICIOS_ML
        - (iibb_pct / 100) / iva_factor
        - (financiero_pct / 100)
        - (renta_pct / 100)
        - full
    )
    return (numerador / denominador).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def calcular_precios_todas_condiciones(
    *,
    costo_sin_iva: Decimal,
    iva_factor: Decimal,
    envio_real: Decimal,
    renta_contado_pct: Decimal = RENTA_CONTADO_DEFAULT,
    diferencial_cuotas_pct: Decimal = RENTA_DIFERENCIAL_CUOTAS_DEFAULT,
    envio_full: bool = False,
    comision_pct: Decimal = COMISION_ML_DEFAULT,
    iibb_pct: Decimal = IIBB_PCT_DEFAULT,
) -> dict[str, Decimal]:
    """El motor completo, las 6 condiciones de una (A.8 punto 2 de
    AYALA_CORE.md: "tabla ... precio calculado por el motor para cada
    condición"). Devuelve un dict con claves 'contado'/'reducida'/'3'/
    '6'/'9'/'12' -- strings, para que sea JSON-friendly tal cual en el
    endpoint."""
    return {
        str(condicion): calcular_precio_condicion(
            costo_sin_iva=costo_sin_iva,
            iva_factor=iva_factor,
            envio_real=envio_real,
            financiero_pct=_financiero_pct(condicion),
            renta_pct=renta_contado_pct - diferencial_cuotas_pct * _ESCALON_POR_CONDICION[condicion],
            comision_pct=comision_pct,
            iibb_pct=iibb_pct,
            envio_full=envio_full,
        )
        for condicion in CONDICIONES
    }


def detectar_condicion_pago(detalle: dict) -> str | int:
    """A.4 de AYALA_CORE.md: la condición de pago se lee en vivo de los
    `tags` reales de la publicación, nunca se carga a mano. `pcj-co-
    funded` = Reducida (ML "3 a 12 cuotas con interés bajo", 5% fijo sin
    importar cuántas cuotas elija el comprador dentro del rango) --
    confirmado en vivo 2026-09-02 (MLA3655836976, cuenta IT) que este tag
    reemplaza a los de cuotas sin interés, son mutuamente excluyentes.
    Si no hay ninguno de los dos, cae a Contado por default."""
    tags = detalle.get("tags") or []
    if "pcj-co-funded" in tags:
        return "reducida"
    cuotas = _cuotas_sin_interes(detalle)
    return cuotas if cuotas else "contado"
