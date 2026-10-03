"""Reportes del motor de precios para n8n (2026-10-03) — solo lectura.

**Desvío de precios (Maca)** — `desvio_precios`: por cada SKU vendido en el
ciclo, en Web y ML (sin Frávega/OnCity ni Full, que esperan peso y medidas
del depósito), el margen real de las ventas contra el que el motor proyecta
para ESAS MISMAS ventas a precio del PM:

- mismas unidades, mismo costo y TC con que se calculó la venta real (así
  el desvío es de precio o de cargos, no de una diferencia de costo);
- mismas cuotas: si la venta pagó cargo por cuotas sin interés, el motor
  proyecta con ese mismo cargo. Una venta en cuotas no aparece como desvío
  solo por haber pagado cuotas (pedido de Maxx);
- ML sin envío: al real se le devuelve el envío (el motor todavía no tiene
  el costo de envío por publicación);
- solo órdenes de un SKU (la corrida no guarda el importe por línea).

Se marcan para revisar los que quedan por DEBAJO del proyectado más de
`umbral_pts`. Prioridad 1 = el precio cobrado está por debajo del precio
del PM (vendiendo barato); 2 = el precio está bien pero los cargos
comieron margen. Un precio por ENCIMA del PM en una venta en cuotas
("inflado por cuotas") nunca se marca.

**Control de ofertas (Natalia)** — `control_ofertas`: cada oferta activa de
ML (módulo Ofertas ML) contra el precio ML del PM (precio web × % ML, con el
redondeo de la planilla). Si el precio con la oferta aplicada no coincide
con el del PM, la oferta está mal cargada. Prioridad 1 = por debajo del
precio del PM; 2 = por encima (salvo publicaciones con cuotas, que no se
marcan por estar arriba).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from . import motor_precios as motor
from .models import ParametroTasa, PricingSku, VentaEcom
from .pricing_pm import _canal_de_venta, norm_sku, precio_ml, vigentes

CANALES_DESVIO = ("ML", "WEB")
_TOLERANCIA_PRECIO = Decimal("0.01")  # 1%: el redondeo a "terminado en 9" no es un desvío


def _n(v, q="0.01") -> float | None:
    return None if v is None else float(Decimal(v).quantize(Decimal(q))) + 0.0  # sin "-0.0"


def _pct(v) -> float | None:
    return None if v is None else float((Decimal(v) * 100).quantize(Decimal("0.01")))


def _precio_pm(p: PricingSku, canal: str) -> Decimal | None:
    return precio_ml(p.precio_web, p.pct_ml) if canal == "ML" else p.precio_web


def _plan_pm(p: PricingSku, canal: str) -> str | None:
    return p.condicion_ml if canal == "ML" else p.forma_pago_web


def _pm_de(p: PricingSku) -> str | None:
    """El PM sale de quién cargó el precio ("Sheet Verónica" → Verónica)."""
    quien = (p.cargado_por or "").replace("(navegador)", "").strip()
    return quien[6:].strip() if quien.startswith("Sheet ") else None


class _VigentesPorFecha:
    def __init__(self, db: Session):
        self.db, self.cache = db, {}

    def __call__(self, fecha: date) -> dict[str, PricingSku]:
        if fecha not in self.cache:
            self.cache[fecha] = vigentes(self.db, fecha)
        return self.cache[fecha]


# ── Desvío de precios (Maca) ──

def desvio_precios(
    db: Session, periodo: str, hoy: date, umbral_pts: Decimal = Decimal(5), solo_revisar: bool = False,
    dia: date | None = None,
) -> dict:
    """`dia`: solo las ventas CREADAS ese día (lo que usa Maca: ayer, para
    revisar ventas recientes cuyo precio todavía no corrigió). None = todo
    el período."""
    par = motor.cargar_parametros(db, hoy)
    tasa_op = db.get(ParametroTasa, "costo_operacion_ecom")
    costo_operacion = tasa_op.valor if tasa_op else Decimal(0)
    precios = _VigentesPorFecha(db)

    grupos: dict[tuple[str, str], dict] = {}
    sin_precio_pm, sin_datos = set(), set()
    excluidas = {"full": 0, "kits_o_carritos": 0}

    q = db.query(VentaEcom).filter(VentaEcom.periodo == periodo, VentaEcom.excluido.is_(False))
    if dia is not None:
        q = q.filter(VentaEcom.fecha_creacion_venta == dia)
    ventas = q.all()
    for v in ventas:
        canal = _canal_de_venta(v.canal_de_venta)
        if canal not in CANALES_DESVIO or v.rentabilidad is None or not v.precio_sin_iva or not v.precio_final:
            continue
        skus = (v.skus_vendidos or "").strip()
        if not skus or "," in skus:
            excluidas["kits_o_carritos"] += 1
            continue
        if v.es_full:
            excluidas["full"] += 1
            continue
        sku = norm_sku(skus)
        if not v.unidades:
            sin_datos.add(v.numero_orden)
            continue
        p = precios(v.fecha_creacion_venta or hoy).get(sku)
        precio_pm = _precio_pm(p, canal) if p else None
        if not precio_pm:
            sin_precio_pm.add(sku)
            continue

        unidades = Decimal(v.unidades)
        cuotas_pct = (v.cargo_cuotas / v.precio_final) if v.cargo_cuotas is not None else None
        entrada = motor.EntradaMotor(
            canal=canal, costo=v.costo_sin_iva * v.tc / unidades, iva_factor=v.iva or Decimal("1.21"),
            categoria=v.categoria, plan=_plan_pm(p, canal), cuotas_pct_final=cuotas_pct,
        )
        try:
            proy = motor.precio_a_margen(precio_pm, entrada, par)
        except (motor.ParametroFaltante, ValueError):
            sin_datos.add(v.numero_orden)
            continue

        g = grupos.setdefault((sku, canal), {
            "sku": sku, "canal": canal, "pm": v.pm or _pm_de(p), "categoria": v.categoria,
            "precio_pm": precio_pm, "plan_pm": _plan_pm(p, canal), "ordenes": [], "ordenes_en_cuotas": 0,
            "unidades": Decimal(0), "facturado": Decimal(0), "proy_rent": Decimal(0), "proy_venta": Decimal(0),
            "real_rent": Decimal(0), "real_venta": Decimal(0),
        })
        g["precio_pm"] = precio_pm  # el de la venta más reciente procesada
        g["ordenes"].append(v.numero_orden)
        g["ordenes_en_cuotas"] += 1 if (v.cargo_cuotas or 0) > 0 or (v.cuotas or 1) > 1 else 0
        g["unidades"] += unidades
        g["facturado"] += v.precio_final
        g["proy_rent"] += proy.rentabilidad * unidades - costo_operacion
        g["proy_venta"] += proy.venta_sin_iva * unidades
        # ML sin envío: el motor todavía no proyecta el envío por publicación.
        g["real_rent"] += v.rentabilidad + ((v.costo_envio or 0) if canal == "ML" else 0)
        g["real_venta"] += v.precio_sin_iva

    filas = []
    for g in grupos.values():
        proy = g["proy_rent"] / g["proy_venta"]
        real = g["real_rent"] / g["real_venta"]
        dif_pts = (real - proy) * 100
        precio_real = g["facturado"] / g["unidades"]
        dif_precio = (precio_real - g["precio_pm"]) / g["precio_pm"]
        precio_bajo = dif_precio < -_TOLERANCIA_PRECIO
        inflado_cuotas = dif_precio > _TOLERANCIA_PRECIO and g["ordenes_en_cuotas"] > 0
        revisar = dif_pts < -umbral_pts and not inflado_cuotas
        if revisar:
            prioridad, motivo = (1, "precio_por_debajo_del_pm") if precio_bajo else (2, "cargos_o_costo_mayores_al_proyectado")
        else:
            prioridad, motivo = 3, ("precio_inflado_por_cuotas" if inflado_cuotas else None)
        if solo_revisar and not revisar:
            continue
        filas.append({
            "sku": g["sku"], "pm": g["pm"], "canal": g["canal"], "categoria": g["categoria"],
            "margen_proyectado_pct": _pct(proy), "margen_real_pct": _pct(real),
            "diferencia_pts": _n(dif_pts), "revisar": revisar, "prioridad": prioridad, "motivo": motivo,
            "precio_pm": _n(g["precio_pm"]), "precio_real_promedio": _n(precio_real),
            "diferencia_precio_pct": _pct(dif_precio), "plan_pm": g["plan_pm"],
            "ordenes": len(g["ordenes"]), "ordenes_en_cuotas": g["ordenes_en_cuotas"],
            "unidades": int(g["unidades"]), "facturacion": _n(g["facturado"]),
            "ejemplos_orden": g["ordenes"][:5],
        })
    filas.sort(key=lambda f: (not f["revisar"], f["prioridad"], f["diferencia_pts"]))

    avisos = []
    if sin_datos:
        avisos.append(f"{len(sin_datos)} órdenes sin unidades/cuotas guardadas: se completan en la próxima corrida diaria.")
    return {
        "periodo": periodo,
        "dia": dia.isoformat() if dia else None,
        "alcance": f"ventas creadas el {dia.isoformat()}" if dia else "todo el período",
        "umbral_pts": float(umbral_pts),
        "canales": list(CANALES_DESVIO),
        "definiciones": {
            "margen": "rentabilidad / venta sin IVA, igual que la rentabilidad real",
            "margen_proyectado_pct": "el del motor para las mismas ventas a precio del PM: mismas unidades, costo, TC y cargo por cuotas",
            "margen_real_pct": "el de las ventas del ciclo; en ML sin el costo de envío (el motor todavía no lo proyecta)",
            "diferencia_pts": "real − proyectado, en puntos",
            "revisar": f"real por debajo del proyectado más de {umbral_pts} pts, salvo precio inflado por cuotas",
            "prioridad": "1 = precio cobrado por debajo del precio del PM · 2 = precio OK, cargos o costo mayores · 3 = no revisar",
            "fuera_del_reporte": "Frávega, OnCity y Full (esperan peso y medidas), kits y carritos de varios SKU",
        },
        "resumen": {
            "skus": len(filas), "a_revisar": sum(f["revisar"] for f in filas),
            "prioridad_1": sum(f["prioridad"] == 1 for f in filas),
            "prioridad_2": sum(f["prioridad"] == 2 for f in filas),
            "inflados_por_cuotas": sum(f["motivo"] == "precio_inflado_por_cuotas" for f in filas),
            "excluidas_full": excluidas["full"], "excluidas_kits_o_carritos": excluidas["kits_o_carritos"],
        },
        "avisos": avisos,
        "filas": filas,
        "sin_precio_pm": sorted(sin_precio_pm),
    }


# ── Control de ofertas (Natalia) ──

def control_ofertas(
    db: Session, ofertas: list[dict], hoy: date, tolerancia_pct: Decimal = Decimal(1), solo_revisar: bool = False,
) -> dict:
    """`ofertas`: filas del módulo Ofertas ML (`ml_ofertas._fila_a_dict`)."""
    precios = vigentes(db, hoy)
    tol = tolerancia_pct / 100
    filas, sin_precio_pm, sin_sku = [], set(), 0
    for o in ofertas:
        if not o.get("sku"):
            sin_sku += 1
            continue
        sku = norm_sku(o["sku"])
        p = precios.get(sku)
        base = _precio_pm(p, "ML") if p else None
        if not base:
            sin_precio_pm.add(sku)
            continue
        oferta = Decimal(str(o["precio_oferta"]))
        normal = Decimal(str(o["precio_normal"])) if o.get("precio_normal") else None
        dif = oferta - base
        dif_pct = dif / base
        cuotas = o.get("cuotas_ofrecidas")
        if abs(dif_pct) <= tol:
            estado, prioridad = "ok", 3
        elif dif < 0:
            estado, prioridad = "por_debajo", 1
        else:
            estado, prioridad = ("por_encima_con_cuotas", 3) if cuotas else ("por_encima", 2)
        revisar = prioridad < 3
        if solo_revisar and not revisar:
            continue
        filas.append({
            "sku": sku, "pm": _pm_de(p), "cuenta": o.get("cuenta"), "item_id": o.get("item_id"),
            "titulo": o.get("titulo"), "permalink": o.get("permalink"),
            "tipo_oferta": o.get("tipo_oferta"), "nombre_campana": o.get("nombre_campana"),
            "precio_base_pm": _n(base), "precio_oferta": _n(oferta), "precio_normal": _n(normal),
            "diferencia": _n(dif), "diferencia_pct": _pct(dif_pct),
            "descuento_actual_pct": _n(o.get("descuento_pct")),
            "descuento_que_cuadra_pct": _pct((normal - base) / normal) if normal else None,
            "cuotas_ofrecidas": cuotas, "estado": estado, "revisar": revisar, "prioridad": prioridad,
        })
    filas.sort(key=lambda f: (not f["revisar"], f["prioridad"], f["diferencia_pct"]))
    return {
        "fecha": hoy.isoformat(),
        "tolerancia_pct": float(tolerancia_pct),
        "definiciones": {
            "precio_base_pm": "precio ML del PM: precio web × % ML, redondeado como la planilla (decena, terminado en 9)",
            "diferencia": "precio de la oferta − precio base del PM",
            "estado": "ok (dentro de la tolerancia) · por_debajo · por_encima · por_encima_con_cuotas (no se marca)",
            "prioridad": "1 = por debajo del precio del PM · 2 = por encima · 3 = no revisar",
            "descuento_que_cuadra_pct": "el % de descuento sobre el precio normal que deja la oferta en el precio del PM",
        },
        "resumen": {
            "ofertas": len(filas), "a_revisar": sum(f["revisar"] for f in filas),
            "por_debajo": sum(f["estado"] == "por_debajo" for f in filas),
            "por_encima": sum(f["estado"] == "por_encima" for f in filas),
            "sin_precio_pm": len(sin_precio_pm), "sin_sku": sin_sku,
        },
        "filas": filas,
        "sin_precio_pm": sorted(sin_precio_pm),
    }
