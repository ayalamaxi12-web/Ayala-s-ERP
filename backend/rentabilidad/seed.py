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
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from .models import (
    MotivoExclusion,
    ParametroTasa,
    PricingComisionCategoria,
    PricingCuotas,
    PricingParametro,
    PricingTramo,
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
    dict(nombre="costo_operacion_ecom", valor="149.12", motor="ECOM", descripcion="Costo por Operación Ecom — monto fijo en pesos por orden (§7.7, OP), vigente desde 23/08/2026"),
    dict(nombre="oncity_comision_estimada", valor="0.15", motor="ECOM", descripcion="Comisión estimada OnCity — 15% sobre Precio Final (canal manual en Ecom, sin dato real de comisión; 2026-09-29)"),
    dict(nombre="fravega_comision_base", valor="0.15", motor="ECOM", descripcion="Comisión base Frávega — 15% sobre Precio Final, estimado hasta cargar la liquidación quincenal (2026-09-27)"),
    dict(nombre="oncity_iva_cargos", valor="0.21", motor="ECOM", descripcion="IVA sobre la comisión estimada de OnCity — se suma al costo, mismo criterio que Frávega (Maxx, 2026-09-29)"),
    dict(nombre="fravega_iva_cargos", valor="0.21", motor="ECOM", descripcion="IVA que Frávega factura aparte sobre comisión y fee logístico — se suma al costo (Maxx, 2026-09-29: mismo criterio que ML/MP, comisión completa)"),
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


# ── Motor de precios — valores iniciales del documento de diseño (2026-09-29).
# Fuente de cada número: cargos reales medidos (ML: ciclo 23/08 → 22/09; MP:
# 438 órdenes Woo jul–sep, iguales al panel de MP × 1,21), tarifario de
# Frávega vigente desde 07/09/2026 y decisiones de Maxx. Porcentajes como
# fracción. `iva_cargos` = IVA que el canal factura aparte sobre sus cargos y
# que se suma al costo (comisión completa, decisión 7.1): ML ya cobra con IVA
# (0); MP y Frávega publican tarifas sin IVA (0,21).
_PRICING_ALTA = dict(vigente_desde=date(2026, 9, 29), cargado_por="seed — documento de diseño del motor")
_ORIGEN_ML = "cargos reales ML, ciclo 23/08 → 22/09/2026"

PRICING_PARAMETROS = [
    ("*", "iibb", "0.05", "IIBB sobre la venta sin IVA (Laura 2.0)"),
    ("*", "imp_cheque", "0.012", "Impuesto al cheque sobre el precio con IVA"),
    ("ML", "iva_cargos", "0", "ML cobra sus cargos con el IVA incluido"),
    ("ML", "comision_general", "0.155", "Comisión ML para categorías sin fila propia"),
    ("ML", "umbral_envio_gratis", "33000", "Desde este precio el envío lo paga el vendedor"),
    ("WEB", "iva_cargos", "0.21", "Tarifas del panel de MP son sin IVA"),
    ("WEB", "comision_mp_credito", "0.05", "MP tarjeta de crédito (acredita a 4 días), sin IVA"),
    ("WEB", "comision_mp_otros", "0.0629", "MP débito / dinero en cuenta / prepaga / efectivo (al instante), sin IVA"),
    ("FRAVEGA", "iva_cargos", "0.21", "Frávega factura comisión y fee sin IVA"),
    ("FRAVEGA", "comision_base", "0.15", "Comisión base Frávega"),
    ("FRAVEGA", "umbral_escala_fee", "35000", "Órdenes menores usan la escala baja del fee logístico"),
    ("FRAVEGA", "fee_logistico_default", "8500", "Fee promedio sin peso/medidas ni histórico del SKU (Maxx, 2026-09-29)"),
    ("ONCITY", "iva_cargos", "0.21", "Mismo modelo que Frávega hasta tener su tarifario"),
    ("ONCITY", "comision_base", "0.15", "Estimado, igual que la rentabilidad (2026-09-29)"),
]

PRICING_COMISION_ML = [
    ("Audio y Video", "0.16"), ("Insumo De Impresion", "0.155"), ("Perifericos", "0.155"),
    ("Conectores", "0.155"), ("Gráfica y Estampado", "0.15"), ("Comercial y Oficinas", "0.15"),
    ("Equipamiento Automotor", "0.145"), ("Construcción y Hogar", "0.144"),
    ("Electrodomesticos", "0.14"), ("Seguridad", "0.14"),
]

PRICING_CUOTAS = [
    ("ML", "reducida", "0.05"), ("ML", "3", "0.089"), ("ML", "6", "0.134"), ("ML", "9", "0.178"), ("ML", "12", "0.216"),
    ("WEB", "2", "0.03"), ("WEB", "3", "0.034"), ("WEB", "6", "0.079"), ("WEB", "9", "0.126"),
    ("WEB", "12", "0.152"), ("WEB", "18", "0.221"), ("WEB", "24", "0.276"),
    ("FRAVEGA", "3", "0.068"), ("FRAVEGA", "6", "0.106"), ("FRAVEGA", "9", "0.137"), ("FRAVEGA", "12", "0.166"),
]

_KG = ["0", "1.5", "5", "10", "15", "20", "25", "35", "50", "81", "100", "250", "5000"]
_FEE_FRAVEGA = {
    "fravega_fee_sin_colecta_alto": [2769, 3299, 5259, 6139, 7849, 9329, 12759, 14539, 16999, 25169, 31639, 47279],
    "fravega_fee_sin_colecta_bajo": [1019, 1650, 2630, 3070, 3925, 4665, 6380, 7270, 8500, 12585, 15820, 23640],
    "fravega_fee_con_colecta_alto": [4609, 6159, 8759, 10239, 13079, 15539, 21259, 24239, 28339, 41949, 52729, 79129],
    "fravega_fee_con_colecta_bajo": [1220, 3080, 4380, 5120, 6540, 7770, 10630, 12120, 14170, 20975, 26365, 39565],
}
PRICING_TRAMOS = [
    # Costo fijo ML actual (≈ lo cobrado hoy); el motor prefiere el de la
    # API por publicación — esta tabla es el respaldo.
    dict(tabla="ml_costo_fijo", unidad="precio", desde="0", hasta="16000", valor="1330"),
    dict(tabla="ml_costo_fijo", unidad="precio", desde="16000", hasta="24000", valor="2740"),
    dict(tabla="ml_costo_fijo", unidad="precio", desde="24000", hasta="33000", valor="3320"),
] + [
    dict(tabla=tabla, unidad="kg", desde=_KG[i], hasta=_KG[i + 1], valor=str(v), vigente_desde=date(2026, 9, 7))
    for tabla, valores in _FEE_FRAVEGA.items() for i, v in enumerate(valores)
]


def seed_pricing(db: Session) -> None:
    """Idempotente por tabla: solo carga los valores iniciales si la tabla
    está vacía — después, los cambios son filas nuevas con vigencia."""
    if db.query(PricingParametro).first() is None:
        for canal, clave, valor, desc in PRICING_PARAMETROS:
            db.add(PricingParametro(canal=canal, clave=clave, valor=Decimal(valor), descripcion=desc, **_PRICING_ALTA))
    if db.query(PricingComisionCategoria).first() is None:
        for categoria, pct in PRICING_COMISION_ML:
            db.add(PricingComisionCategoria(canal="ML", categoria=categoria, pct=Decimal(pct), origen=_ORIGEN_ML, **_PRICING_ALTA))
    if db.query(PricingCuotas).first() is None:
        for canal, plan, pct in PRICING_CUOTAS:
            db.add(PricingCuotas(canal=canal, plan=plan, pct=Decimal(pct), **_PRICING_ALTA))
    if db.query(PricingTramo).first() is None:
        for fila in PRICING_TRAMOS:
            numeros = {k: Decimal(fila[k]) for k in ("desde", "hasta", "valor")}
            db.add(PricingTramo(**{**_PRICING_ALTA, **fila, **numeros}))


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
    seed_pricing(db)
