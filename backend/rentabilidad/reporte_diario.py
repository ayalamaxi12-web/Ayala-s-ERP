"""Reporte diario de Rentabilidad ECOM, para mandar por mail (n8n).

**Solo lectura**: lee lo que la corrida diaria (`cierre_ecom_diario`) ya
guardó en `venta_ecom` para el ciclo en curso (23 → 22) y lo resume. No
recalcula ni consulta ninguna fuente externa.

Definiciones (las mismas del informe de rentabilidad y de la pantalla):
- facturación = Σ Precio Final (con IVA); también se informa sin IVA.
- rentabilidad % = rentabilidad $ / facturación sin IVA.
- "ayer" = órdenes con fecha de CREACIÓN ese día (hora Argentina).
- SKU = los SKU de la orden tal como los guarda la corrida (`skus_vendidos`):
  una orden de un solo SKU cuenta para ese SKU; un kit / carrito de varios
  SKU cuenta como esa combinación — mismo criterio que las filas de la
  planilla (una fila = una orden). La corrida no guarda el importe por línea.
- Las órdenes con costo 0 (sin calcular) suman facturación pero no
  rentabilidad, y se listan en alertas.
"""
from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from .cierre_ecom_diario import ayer_en_argentina, ciclo_de
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


def _por_sku(ventas: list[VentaEcom]) -> list[dict]:
    grupos: dict[str, list] = defaultdict(lambda: [Decimal(0), Decimal(0), Decimal(0), 0])
    for v in ventas:
        g = grupos[(v.skus_vendidos or "").strip() or "(sin SKU)"]
        g[0] += v.precio_final or 0
        g[1] += v.precio_sin_iva or 0
        g[2] += v.rentabilidad or 0
        g[3] += 1
    return [
        {"sku": sku, "facturacion": _n(f), "rentabilidad": _n(r), "rentabilidad_pct": _pct(r, s), "ordenes": n}
        for sku, (f, s, r, n) in grupos.items()
    ]


def _mas_facturaron(ventas: list[VentaEcom], top: int) -> list[dict]:
    return sorted(_por_sku(ventas), key=lambda x: -x["facturacion"])[:top]


def _en_perdida(ventas: list[VentaEcom], top: int) -> list[dict]:
    """SKU con rentabilidad negativa, de la mayor pérdida a la menor."""
    return sorted((x for x in _por_sku(ventas) if x["rentabilidad"] < 0), key=lambda x: x["rentabilidad"])[:top]


def _bloque(ventas_ciclo: list[VentaEcom], dia: date, top: int) -> dict:
    return {
        "ayer": _totales([v for v in ventas_ciclo if v.fecha_creacion_venta == dia]),
        "ciclo": _totales(ventas_ciclo),
        "mas_facturaron": _mas_facturaron(ventas_ciclo, top),
        "en_perdida": _en_perdida(ventas_ciclo, top),
    }


def _por_pm(ventas: list[VentaEcom], top_skus: int) -> list[dict]:
    grupos: dict[str, list[VentaEcom]] = defaultdict(list)
    for v in ventas:
        grupos[v.pm or "(sin PM)"].append(v)
    filas = [
        {"pm": pm, **_totales(vs), "top_skus": [
            {"sku": x["sku"], "facturacion": x["facturacion"]} for x in _mas_facturaron(vs, top_skus)
        ]}
        for pm, vs in grupos.items()
    ]
    return sorted(filas, key=lambda x: -x["facturacion"])


def reporte_diario(db: Session, dia: date | None = None, top: int = 5) -> dict:
    dia = dia or ayer_en_argentina()
    inicio, fin = ciclo_de(dia)
    periodo = periodo_de_rango(inicio, fin)
    ventas = (
        db.query(VentaEcom)
        .filter(VentaEcom.periodo == periodo, VentaEcom.excluido.is_(False))
        .all()
    )
    ventas = [v for v in ventas if v.fecha_creacion_venta is None or v.fecha_creacion_venta <= dia]
    del_dia = [v for v in ventas if v.fecha_creacion_venta == dia]
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
        bloque = _bloque(vs, dia, top)
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
            "sku": "SKU de la orden; un kit o carrito de varios SKU cuenta como esa combinación",
        },
        "general": {
            "ayer": _totales(del_dia),
            "acumulado_ciclo": _totales(ventas),
            "por_pm": {"ayer": _por_pm(del_dia, 2), "ciclo": _por_pm(ventas, 2)},
            "ayer_mas_facturaron": _mas_facturaron(del_dia, top),
            "ayer_en_perdida": _en_perdida(del_dia, top),
            "alertas": {
                "costo_cero": [
                    {"orden": v.numero_orden, "skus": v.skus_vendidos or "(sin SKU)", "fecha": v.fecha_creacion_venta.isoformat()
                     if v.fecha_creacion_venta else None, "canal": v.canal_de_venta, "facturacion": _n(v.precio_final)}
                    for v in costo_cero
                ],
                "sin_sku": [v.numero_orden for v in ventas if not (v.skus_vendidos or "").strip()],
                "fravega_estimadas": {"ordenes": len(fravega_est), "facturacion": _n(sum((v.precio_final or 0 for v in fravega_est), Decimal(0)))},
                "observaciones": [{"orden": v.numero_orden, "observacion": v.observacion} for v in ventas if v.observacion],
                "tc": {"valor": _n(cierre.tc_ecom) if cierre and cierre.tc_ecom is not None else None,
                       "origen": cierre.tc_ecom_origen if cierre else None},
            },
        },
        "full_y_marketplaces": {
            "full": _bloque(full, dia, top),
            **marketplaces,
        },
    }
