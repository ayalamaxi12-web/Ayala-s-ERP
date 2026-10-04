"""Reporte diario de Rentabilidad ECOM, para mandar por mail (n8n).

**Solo lectura**: lee lo que la corrida diaria (`cierre_ecom_diario`) ya
guardó en `venta_ecom` para el ciclo en curso (23 → 22) y lo resume. No
recalcula ni consulta ninguna fuente externa.

Definiciones (las mismas del informe de rentabilidad y de la pantalla):
- facturación = Σ Precio Final (con IVA); también se informa sin IVA.
- rentabilidad % = rentabilidad $ / facturación sin IVA.
- "ayer" = órdenes con fecha de CREACIÓN ese día (hora Argentina).
- SKU = cada SKU de la orden con SU parte del importe (`desglose_sku`): un
  kit / carrito de varios SKU ya no cuenta como una "combinación" ni suma el
  total de la orden a cada SKU — cada SKU toma el importe de su línea. Los
  totales por orden (ayer, ciclo, canales) no cambian. Las órdenes viejas
  importadas de la planilla que nunca tuvieron líneas se reparten por precio
  de lista y quedan marcadas `prorrateado`.
- PM = el de cada SKU (no el del primer SKU de la orden).
- Las órdenes con costo 0 (sin calcular) suman facturación pero no
  rentabilidad, y se listan en alertas.
"""
from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from .cierre_ecom_diario import ayer_en_argentina, ciclo_de
from .desglose_sku import LineaSku, con_lineas, desglosar
from .ingesta_ecom import ORIGEN_COMISION_ESTIMADO_FRAVEGA, ORIGEN_COMISION_ESTIMADO_ONCITY
from .models import CierreRentabilidad, VentaEcom
from .regimen import periodo_de_rango

# Marketplaces del bloque de Maxi Inglese → valor de `canal_de_venta`.
# Frávega llega por integración (ChFravega); OnCity es un canal manual de Ecom
# (owner "OnCity"); Megatone: la cuenta "Global Megatone" existe en Ecom pero
# sin órdenes todavía (verificado 2026-09-29) — cuando empiece a vender, su
# etiqueta de canal se confirma contra la API y se ajusta acá.
MARKETPLACES = {"fravega": "Fravega", "oncity": "OnCity", "megatone": "Megatone"}


def _n(v) -> float:
    return float(round(Decimal(v or 0), 2))


def _pct(rent: Decimal, sin_iva: Decimal) -> float | None:
    return float(round(rent / sin_iva * 100, 2)) if sin_iva else None


def _totales(ventas: list[VentaEcom]) -> dict:
    fact = sum((v.precio_final or 0 for v in ventas), Decimal(0))
    sin_iva = sum((v.precio_sin_iva or 0 for v in ventas), Decimal(0))
    rent = sum((v.rentabilidad or 0 for v in ventas), Decimal(0))
    return {
        "facturacion": _n(fact), "facturacion_sin_iva": _n(sin_iva),
        "rentabilidad": _n(rent), "rentabilidad_pct": _pct(rent, sin_iva),
        "ordenes": len(ventas),
    }


def _por_sku(lineas: list[LineaSku]) -> list[dict]:
    grupos: dict[str, list] = defaultdict(lambda: [Decimal(0), Decimal(0), Decimal(0), set(), False])
    for l in lineas:
        g = grupos[l.sku]
        g[0] += l.precio_final or 0
        g[1] += l.precio_sin_iva or 0
        g[2] += l.rentabilidad or 0
        g[3].add(l.venta.numero_orden)
        g[4] = g[4] or l.prorrateado
    return [
        {"sku": sku, "facturacion": _n(f), "rentabilidad": _n(r), "rentabilidad_pct": _pct(r, s),
         "ordenes": len(ordenes), "prorrateado": prorr}
        for sku, (f, s, r, ordenes, prorr) in grupos.items()
    ]


def _mas_facturaron(lineas: list[LineaSku], top: int) -> list[dict]:
    return sorted(_por_sku(lineas), key=lambda x: -x["facturacion"])[:top]


def _en_perdida(lineas: list[LineaSku], top: int) -> list[dict]:
    """SKU con rentabilidad negativa, de la mayor pérdida a la menor."""
    return sorted((x for x in _por_sku(lineas) if x["rentabilidad"] < 0), key=lambda x: x["rentabilidad"])[:top]


def _lineas_de(lineas: list[LineaSku], ventas: list[VentaEcom]) -> list[LineaSku]:
    ids = {id(v) for v in ventas}
    return [l for l in lineas if id(l.venta) in ids]


def _bloque(ventas_ciclo: list[VentaEcom], lineas: list[LineaSku], dia: date, top: int) -> dict:
    lineas_ciclo = _lineas_de(lineas, ventas_ciclo)
    return {
        "ayer": _totales([v for v in ventas_ciclo if v.fecha_creacion_venta == dia]),
        "ciclo": _totales(ventas_ciclo),
        "mas_facturaron": _mas_facturaron(lineas_ciclo, top),
        "en_perdida": _en_perdida(lineas_ciclo, top),
    }


def _totales_lineas(lineas: list[LineaSku]) -> dict:
    fact = sum((l.precio_final or 0 for l in lineas), Decimal(0))
    sin_iva = sum((l.precio_sin_iva or 0 for l in lineas), Decimal(0))
    rent = sum((l.rentabilidad or 0 for l in lineas), Decimal(0))
    return {
        "facturacion": _n(fact), "facturacion_sin_iva": _n(sin_iva),
        "rentabilidad": _n(rent), "rentabilidad_pct": _pct(rent, sin_iva),
        "ordenes": len({l.venta.numero_orden for l in lineas}),
    }


def _por_pm(lineas: list[LineaSku], top_skus: int) -> list[dict]:
    """Por el PM de cada SKU: una orden de un combo con SKU de dos PM suma a
    cada uno SU parte (la suma de los PM sigue dando el total)."""
    grupos: dict[str, list[LineaSku]] = defaultdict(list)
    for l in lineas:
        grupos[l.pm or "(sin PM)"].append(l)
    filas = [
        {"pm": pm, **_totales_lineas(ls), "top_skus": [
            {"sku": x["sku"], "facturacion": x["facturacion"]} for x in _mas_facturaron(ls, top_skus)
        ]}
        for pm, ls in grupos.items()
    ]
    return sorted(filas, key=lambda x: -x["facturacion"])


def reporte_diario(db: Session, dia: date | None = None, top: int = 5) -> dict:
    dia = dia or ayer_en_argentina()
    inicio, fin = ciclo_de(dia)
    periodo = periodo_de_rango(inicio, fin)
    ventas = (
        con_lineas(db.query(VentaEcom))
        .filter(VentaEcom.periodo == periodo, VentaEcom.excluido.is_(False))
        .all()
    )
    ventas = [v for v in ventas if v.fecha_creacion_venta is None or v.fecha_creacion_venta <= dia]
    del_dia = [v for v in ventas if v.fecha_creacion_venta == dia]
    lineas = desglosar(db, ventas)
    lineas_del_dia = _lineas_de(lineas, del_dia)
    prorrateadas = sorted({l.venta.numero_orden for l in lineas if l.prorrateado})
    cierre = db.get(CierreRentabilidad, periodo)

    datos_hasta = cierre.hasta if cierre else None
    avisos = []
    if cierre is None:
        avisos.append(f"No hay nada guardado para el ciclo {periodo}: la corrida diaria no corrió todavía.")
    elif datos_hasta < dia:
        avisos.append(f"Los datos guardados llegan hasta {datos_hasta}, no hasta {dia}: la corrida diaria de hoy no terminó.")

    costo_cero = [v for v in ventas if v.rentabilidad is None]
    fravega_est = [v for v in ventas if v.origen_comision == ORIGEN_COMISION_ESTIMADO_FRAVEGA]
    full = [v for v in ventas if v.es_full]
    if ventas and all(v.es_full is None for v in ventas):
        avisos.append("El dato de Full todavía no está guardado para este ciclo: aparece desde la próxima corrida diaria.")

    marketplaces = {}
    for clave, canal in MARKETPLACES.items():
        vs = [v for v in ventas if (v.canal_de_venta or "") == canal]
        bloque = _bloque(vs, lineas, dia, top)
        if clave == "fravega":
            bloque["comision_estimada_ordenes"] = sum(1 for v in vs if v.origen_comision == ORIGEN_COMISION_ESTIMADO_FRAVEGA)
            bloque["nota"] = "Comisión estimada (15% + IVA 21%) hasta cargar la liquidación quincenal; después pasa a la real (también + IVA)."
        elif clave == "oncity":
            bloque["comision_estimada_ordenes"] = sum(1 for v in vs if v.origen_comision == ORIGEN_COMISION_ESTIMADO_ONCITY)
            bloque["nota"] = "Canal manual en Ecom sin dato de comisión: se descuenta una comisión estimada (15% del Precio Final + IVA 21%)."
        elif clave == "megatone" and not vs:
            bloque["nota"] = "Sin órdenes de Megatone en Ecom en este ciclo."
        marketplaces[clave] = bloque

    return {
        "periodo": periodo,
        "ciclo": {"desde": inicio.isoformat(), "hasta": fin.isoformat()},
        "dia": dia.isoformat(),
        "datos_guardados_hasta": datos_hasta.isoformat() if datos_hasta else None,
        "generado_por_la_corrida_en": cierre.generado_en.isoformat() if cierre else None,
        "avisos": avisos,
        "definiciones": {
            "facturacion": "Precio Final con IVA",
            "rentabilidad_pct": "rentabilidad $ / facturación sin IVA × 100",
            "dia": "órdenes creadas ese día (hora Argentina)",
            "sku": "cada SKU con el importe de SU línea de la orden; los combos viejos sin detalle van prorrateados por precio de lista del PM (prorrateado=true)",
        },
        "general": {
            "ayer": _totales(del_dia),
            "acumulado_ciclo": _totales(ventas),
            "por_pm": {"ayer": _por_pm(lineas_del_dia, 2), "ciclo": _por_pm(lineas, 2)},
            "ayer_mas_facturaron": _mas_facturaron(lineas_del_dia, top),
            "ayer_en_perdida": _en_perdida(lineas_del_dia, top),
            "alertas": {
                "costo_cero": [
                    {"orden": v.numero_orden, "skus": v.skus_vendidos or "(sin SKU)", "fecha": v.fecha_creacion_venta.isoformat()
                     if v.fecha_creacion_venta else None, "canal": v.canal_de_venta, "facturacion": _n(v.precio_final)}
                    for v in costo_cero
                ],
                "combos_prorrateados": {
                    "ordenes": len(prorrateadas),
                    "nota": "Combos viejos importados de la planilla, sin detalle por línea: su importe se repartió entre los SKU por precio de lista del PM (prorrateado).",
                },
                "sin_sku": [v.numero_orden for v in ventas if not (v.skus_vendidos or "").strip()],
                "fravega_estimadas": {"ordenes": len(fravega_est), "facturacion": _n(sum((v.precio_final or 0 for v in fravega_est), Decimal(0)))},
                "observaciones": [{"orden": v.numero_orden, "observacion": v.observacion} for v in ventas if v.observacion],
                "tc": {"valor": _n(cierre.tc_ecom) if cierre and cierre.tc_ecom is not None else None,
                       "origen": cierre.tc_ecom_origen if cierre else None},
            },
        },
        "full_y_marketplaces": {
            "full": _bloque(full, lineas, dia, top),
            **marketplaces,
        },
    }
