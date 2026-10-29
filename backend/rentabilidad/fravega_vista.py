"""Vista «Frávega»: cada publicación del Seller Center con su margen, su stock y sus ventas.

El margen sale del MISMO motor que Motor de Precios (`motor_precios.precio_a_margen`, canal FRAVEGA, planes 3/6/9/12): no hay fórmula nueva.
Las ventas salen de las órdenes de Frávega ya guardadas (`venta_ecom` con comisión de Frávega); `venta_ecom` guarda una fila por orden y
no la cantidad, así que se cuentan ÓRDENES.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from . import motor_precios as motor
from .models import VentaEcom
from .pricing_pm import DatosSku, fee_historico_fravega, norm_sku, vigentes
from .reportes_pricing import _n, _pct, _pm_de

ORIGENES_FRAVEGA = ("ESTIMADO_FRAVEGA", "LIQUIDACION_FRAVEGA")
PLANES = ("3", "6", "9", "12")
VENTANAS = (30, 60, 90)


def margen_fravega(precio: Decimal, datos: DatosSku, tc: Decimal, par: motor.ParametrosMotor, cuotas: str | None,
                   fee: Decimal | None) -> tuple[dict | None, list[str]]:
    """(`{margen, rentabilidad, cargos}`, avisos) a ese precio y plan; None si falta costo/IVA o el plan."""
    if not datos.costo_usd:
        return None, ["Sin costo vigente en Ecom"]
    if not datos.iva_factor:
        return None, ["Sin alícuota de IVA"]
    if cuotas not in PLANES:
        return None, ["Sin plan de cuotas conocido (3, 6, 9 o 12)"]
    e = motor.EntradaMotor(canal="FRAVEGA", costo=datos.costo_usd * tc, iva_factor=datos.iva_factor, plan=cuotas, fee_logistico=fee)
    try:
        d = motor.precio_a_margen(Decimal(precio), e, par)
    except (motor.ParametroFaltante, ValueError) as ex:
        return None, [str(ex)]
    return {"margen": _pct(d.margen), "rentabilidad": _n(d.rentabilidad), "cargos": {k: float(v) for k, v in d.cargos.items()}}, []


def ventas_por_sku(db: Session, hoy: date) -> dict[str, dict]:
    desde = hoy - timedelta(days=max(VENTANAS))
    acum: dict[str, dict] = {}
    q = db.query(VentaEcom).filter(VentaEcom.origen_comision.in_(ORIGENES_FRAVEGA), VentaEcom.excluido.is_(False),
                                   VentaEcom.fecha_creacion_venta >= desde)
    for v in q.all():
        if not v.skus_vendidos or "," in v.skus_vendidos or not v.fecha_creacion_venta:
            continue
        a = acum.setdefault(norm_sku(v.skus_vendidos), {"fechas": [], "ordenes": {w: 0 for w in VENTANAS}})
        dias = (hoy - v.fecha_creacion_venta).days
        for w in VENTANAS:
            if dias <= w:
                a["ordenes"][w] += 1
        a["fechas"].append(v.fecha_creacion_venta)
    out = {}
    for sku, a in acum.items():
        f60 = {f for f in a["fechas"] if (hoy - f).days <= 60}
        out[sku] = {"ordenes_30": a["ordenes"][30], "ordenes_60": a["ordenes"][60], "ordenes_90": a["ordenes"][90],
                    "dias_con_venta_60": len(f60), "ultima_venta": max(a["fechas"]).isoformat()}
    return out


def construir_vista(db: Session, items: list[dict], datos_fn, tc: Decimal, par: motor.ParametrosMotor, hoy: date) -> list[dict]:
    precios_pm = vigentes(db, hoy)
    fees = fee_historico_fravega(db)
    ventas = ventas_por_sku(db, hoy)
    filas = []
    for it in items:
        sku = norm_sku(it["ref_id"])
        datos = datos_fn(sku) if sku else DatosSku(None, None, None, None, None)
        pm_sku = precios_pm.get(sku)
        cuotas = (it.get("plan") or {}).get("cuotas")
        m, av = (margen_fravega(it["venta"], datos, tc, par, cuotas, fees.get(sku)) if it.get("venta") else (None, []))
        v = ventas.get(sku) or {"ordenes_30": 0, "ordenes_60": 0, "ordenes_90": 0, "dias_con_venta_60": 0, "ultima_venta": None}
        por_dia = v["ordenes_60"] / 60
        filas.append({
            **{k: (float(x) if isinstance(x, Decimal) else x) for k, x in it.items() if k != "_plan_completo"},
            "sku": sku, "pm": (_pm_de(pm_sku) if pm_sku else None) or datos.pm, "categoria": datos.categoria,
            "precio_pm": _n(pm_sku.precio_fravega) if pm_sku and pm_sku.precio_fravega else None,
            "costo": _n(datos.costo_usd * tc) if datos.costo_usd else None,
            "margen": m and m["margen"], "rentabilidad": m and m["rentabilidad"], "avisos": av + ([] if sku else ["Sin código de referencia"]),
            "fee_hist": _n(fees[sku]) if sku in fees else None,
            **v, "dias_cobertura": round(it["stock"] / por_dia) if por_dia and it["stock"] else None,
            "descuento_pct": round(float((1 - it["venta"] / it["lista"]) * 100), 1) if it.get("lista") and it.get("venta") else None,
        })
    return filas
