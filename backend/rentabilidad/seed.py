"""Carga inicial de las tablas paramétricas.

Ninguna tasa, prefijo o régimen vive en el código de los calculadores
(prohibición técnica #1) — este módulo es la única fuente que los escribe en
la base, tomándolos literalmente de RENTABILIDAD_FUNCIONAL.md §5.3 y §6.1.

GAP DOCUMENTAL (no resuelto, no inventado — ver feedback_rentabilidad-workflow):
el funcional lista "Notas de débito" como comprobante excluido (§6.1, §10),
pero no da el/los código(s) de comprobante reales para ese tipo (a diferencia
de FEA/FEB/FEE/etc., que sí tienen código explícito). No se seedea ninguna fila
para "nota de débito" por no tener un valor real que mapear — cualquier
comprobante no listado en `regimen_comprobante` ya cae en NO_RECONOCIDO por
default en `resolver_regimen`, que es el mismo efecto práctico ("la línea no
se calcula"), pero esto debe confirmarse contra los códigos reales de
comprobante de nota de débito antes de dar el motor por completo.
"""
from sqlalchemy.orm import Session

from .models import (
    MotivoExclusion,
    ParametroTasa,
    PrefijoPerdidaDefinitiva,
    Regimen,
    RegimenComprobante,
    SkuAuxiliar,
    SkuExcluido,
)

# §5.3 — tasas, todas paramétricas
TASAS = [
    dict(nombre="imp_cheque", valor="0.012", motor="AMBOS", descripcion="Impuesto al cheque — 1,2%"),
    dict(nombre="iibb", valor="0.05", motor="AMBOS", descripcion="Retenciones IIBB — 5%"),
    dict(nombre="cf1", valor="0.03", motor="TACTICA", descripcion="Costo financiero 1 — 3%, base bruta"),
    dict(nombre="cf2", valor="0.03", motor="TACTICA", descripcion="Costo financiero 2 — 3%, base neta"),
    dict(nombre="agin_1", valor="0.009", motor="TACTICA", descripcion="Tasa AGIN 1 — 0,90% (§11.3, reportes)"),
    dict(nombre="agin_2", valor="0.004", motor="TACTICA", descripcion="Tasa AGIN 2 — 0,40% (§11.3, reportes)"),
]

# §6.1 — prefijos de pérdida definitiva, prioridad absoluta sobre el comprobante
PREFIJOS_PERDIDA_DEFINITIVA = ["00007", "05007"]

# §6.1 — mapeo comprobante → régimen
REGIMEN_COMPROBANTE = [
    dict(comprobante="FEA", regimen=Regimen.CUENTA_1, descripcion="Factura de Venta A – Electrónica"),
    dict(comprobante="FEB", regimen=Regimen.CUENTA_1, descripcion="Factura de Venta B – Electrónica"),
    dict(comprobante="FEE", regimen=Regimen.CUENTA_1, descripcion="Factura de Venta E – Electrónica"),
    dict(comprobante="CEA", regimen=Regimen.CUENTA_1, descripcion="Nota de crédito electrónica A (reverso Cuenta 1)"),
    dict(comprobante="CEB", regimen=Regimen.CUENTA_1, descripcion="Nota de crédito electrónica B (reverso Cuenta 1)"),
    dict(comprobante="CEE", regimen=Regimen.CUENTA_1, descripcion="Nota de crédito electrónica E (reverso Cuenta 1)"),
    dict(comprobante="FAE", regimen=Regimen.CUENTA_2, descripcion="Factura de Venta E (no electrónica)"),
    dict(comprobante="CVE", regimen=Regimen.CUENTA_2, descripcion="Nota de crédito E no electrónica (reverso Cuenta 2)"),
    dict(comprobante="MLA", regimen=Regimen.NO_DETERMINADO, descripcion="Multipropósito — régimen no determinado, pendiente P-01"),
    # CVA/CVB: en el período relevado solo aparecen con prefijo de pérdida
    # definitiva (que tiene prioridad absoluta sobre esta tabla). Fuera de ese
    # caso el funcional dice explícitamente que su régimen "no es observable
    # en la evidencia disponible" (§6.1) — se mapean como NO_RECONOCIDO para
    # ese escenario no observado, sin inventar un régimen real para él.
    dict(comprobante="CVA", regimen=Regimen.NO_RECONOCIDO, descripcion="Sin evidencia fuera del caso de pérdida definitiva"),
    dict(comprobante="CVB", regimen=Regimen.NO_RECONOCIDO, descripcion="Sin evidencia fuera del caso de pérdida definitiva"),
]

# §7.6 — patrón de SKU promocional, no altera el cálculo
SKU_AUXILIAR = [
    dict(patron="PROMOS-*", descripcion="Aportes Promociones 21% — cae en pérdida definitiva vía prefijo 00007"),
]

# SKUs de flete/envío — encontrados y confirmados 2026-08-14 al validar
# Rentabilidad Táctica contra la base real: Táctica factura el flete como una
# línea de comprobante más, pero el "costo vigente" cargado para esos SKUs en
# `productosprecios.Costo` es el propio precio de venta en pesos, no un costo
# unitario real en USD. El motor, al tratarlo como costo USD y multiplicarlo
# por el TC (§5.6), calculaba pérdidas de millones de pesos por línea (ej.
# `ENVIOS-BSAS-C1+18KG`: precio $5.609, costo cargado "5609" → margen de
# -$8.520.636,50 en una sola línea). Decisión de Maxx (2026-08-14): son
# cargos de flete, no ventas de producto con margen — se excluyen del
# cálculo, no se corrige la fórmula ni se reinterpreta el costo.
# Lista relevada contra `productos` en vivo (`Codigo LIKE '%ENVIO%' OR
# '%FLETE%'`), no solo los 5 SKUs que aparecieron en la muestra de un día.
SKU_EXCLUIDO = [
    dict(sku=sku, motivo=MotivoExclusion.ENVIO, activo=True)
    for sku in (
        "ENVIOS-BSAS-C1", "ENVIOS-BSAS-C1+18KG", "ENVIOS-BSAS-C1-ESPECIAL",
        "ENVIOS-BSAS-C2", "ENVIOS-BSAS-C2+18KG", "ENVIOS-BSAS-C2-ESPECIAL",
        "ENVIOS-BSAS-C3", "ENVIOS-BSAS-C3+18KG", "ENVIOS-BSAS-C3-ESPECIAL",
        "ENVIOS-BSAS-C4", "ENVIOS-BSAS-C4+18KG", "ENVIOS-BSAS-C4-ESPECIAL",
        "ENVIOS-BSAS-C5", "ENVIOS-BSAS-C5+18KG", "ENVIOS-BSAS-C5-ESPECIAL",
        "ENVIOS-CABA", "ENVIOS-CABA+18KG", "ENVIOS-CABA-ESPECIAL",
        "FLETE", "FLETECLIENTE", "FLETEI", "FLETES", "FLETES A COBRAR",
    )
]


def seed(db: Session) -> None:
    """Idempotente: no duplica filas si ya existen (por PK)."""
    for tabla, filas, modelo in (
        ("tasas", TASAS, ParametroTasa),
        ("prefijos", [dict(prefijo=p) for p in PREFIJOS_PERDIDA_DEFINITIVA], PrefijoPerdidaDefinitiva),
        ("regimenes", REGIMEN_COMPROBANTE, RegimenComprobante),
        ("sku_auxiliar", SKU_AUXILIAR, SkuAuxiliar),
        ("sku_excluido", SKU_EXCLUIDO, SkuExcluido),
    ):
        for fila in filas:
            pk_col = list(modelo.__table__.primary_key.columns)[0].name
            existente = db.get(modelo, fila[pk_col])
            if existente is None:
                db.add(modelo(**fila))
