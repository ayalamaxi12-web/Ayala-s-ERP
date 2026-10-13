"""Campañas de ML (Central de Promociones): cruce de cada fila del Excel con el
precio PM y el costo de Ecom, y margen real a precio de oferta, por cuota.

Regla del aporte de ML (Maxx, 2026-10-13): el descuento total se reparte entre el
vendedor (SELLER_*) y ML (MELI_*). Ej.: lista $10.000, 10% total → el cliente
paga $9.000; el vendedor pone 9,5% ($950) y ML 0,5% ($50).
  · precio del vendedor = lista − su descuento = $9.050 (cliente + crédito de ML):
    es la venta sobre la que se calcula el margen (IVA, IIBB, cheque).
  · comisión, cuotas, costo fijo y envío salen del precio que paga el cliente
    ($9.000) — `EntradaMotor.precio_cliente`. (Por confirmar con una venta real.)
Solo cálculo: no escribe nada ni llama a ML."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from . import motor_precios as motor
from .pricing_pm import DatosSku, norm_sku, precio_ml, vigentes
from .reportes_pricing import _n, _pct, _pm_de

PLANES = ("contado", "3", "6", "9", "12")
PCT_MIN, PCT_MAX = 5, 80  # ML: enteros entre 5% y 80%
_D = lambda x: Decimal(str(x))


def precios_oferta(original, seller_pct=None, seller_monto=None, meli_pct=None, meli_monto=None) -> dict:
    """Montos de la oferta. Si ML informa el monto, manda sobre el %. Todo en pesos."""
    orig = _D(original)
    s = _D(seller_monto) if seller_monto is not None else orig * _D(seller_pct) / 100 if seller_pct is not None else None
    if s is None:
        return {"precio_vendedor": None, "precio_cliente": None, "seller_monto": None, "meli_monto": None}
    m = _D(meli_monto) if meli_monto is not None else orig * _D(meli_pct) / 100 if meli_pct is not None else Decimal(0)
    return {"seller_monto": s, "meli_monto": m, "precio_vendedor": orig - s, "precio_cliente": orig - s - m}


def margen_oferta(
    precio_vendedor, precio_cliente, plan: str, costo: Decimal, iva: Decimal, par: motor.ParametrosMotor,
    envio: Decimal = Decimal(0),
) -> motor.Desglose:
    pv, pc = _D(precio_vendedor), _D(precio_cliente)
    e = motor.EntradaMotor(
        canal="ML", costo=costo, iva_factor=iva, plan=plan, envio=envio,
        precio_cliente=pc if pc != pv else None,
    )
    return motor.precio_a_margen(pv, e, par)


def pct_max_para_margen(
    original, meli_pct, objetivo, plan: str, costo: Decimal, iva: Decimal, par: motor.ParametrosMotor,
    envio: Decimal = Decimal(0),
) -> int | None:
    """Mayor % ENTERO de descuento del vendedor (5–80) que deja el margen ≥ `objetivo`
    (fracción). Supone que ML mantiene su %. Recorre todos los enteros: el margen no es
    monótono (el costo fijo y el envío cambian por tramo de precio). None si ni el 5% alcanza."""
    orig, mejor = _D(original), None
    for pct in range(PCT_MIN, PCT_MAX + 1):
        o = precios_oferta(orig, seller_pct=pct, meli_pct=meli_pct)
        if o["precio_cliente"] <= 0:
            break
        try:
            r = margen_oferta(o["precio_vendedor"], o["precio_cliente"], plan, costo, iva, par, envio)
        except (motor.ParametroFaltante, ValueError):
            continue
        if r.margen >= _D(objetivo):
            mejor = pct
    return mejor


def analizar(
    db: Session, filas: list[dict], fecha: date, tc: Decimal, datos_fn, par: motor.ParametrosMotor,
    envios: dict[str, Decimal] | None = None, margen_objetivo: Decimal | None = None,
) -> dict:
    """`filas`: las de `campanas_ml_xlsx.leer_promociones`. `datos_fn(sku) -> DatosSku`."""
    precios = vigentes(db, fecha)
    envios = envios or {}
    umbral = par.valor("ML", "umbral_envio_gratis")
    out = []
    for f in filas:
        av, sku = [], norm_sku(f.get("SKU") or "")
        o = precios_oferta(f["ORIGINAL_PRICE"], f.get("SELLER_PERCENTAGE"), f.get("SELLER_AMOUNT"),
                           f.get("MELI_PERCENTAGE"), f.get("MELI_AMOUNT"))  # montos de ML mandan: el % viene redondeado
        orig = _D(f["ORIGINAL_PRICE"]) if f.get("ORIGINAL_PRICE") else None
        r = {
            "fila": f["fila"], "item_id": f["ITEM_ID"], "sku": sku or None, "titulo": f.get("TITLE"),
            "editable": f.get("editable"), "estado": f.get("STATUS"), "accion": f.get("ACTION"),
            "precio_original": _n(orig), "seller_pct": f.get("SELLER_PERCENTAGE"), "meli_pct": f.get("MELI_PERCENTAGE"),
            "seller_monto": _n(o["seller_monto"]), "meli_monto": _n(o["meli_monto"]),
            "precio_vendedor": _n(o["precio_vendedor"]), "precio_cliente": _n(o["precio_cliente"]),
            "descuento_total_pct": f.get("DISCOUNT_PERCENTAGE"), "precio_final_ml": f.get("FINAL_PRICE"),
            "recibis_ml": f.get("NEW_RECEIVES"),
            "pm": None, "precio_pm": None, "costo": None, "margenes": {}, "avisos": av,
        }
        sp = f.get("SELLER_PERCENTAGE")
        if sp is not None and not (float(sp).is_integer() and PCT_MIN <= sp <= PCT_MAX):
            av.append(f"ML pide % entero entre {PCT_MIN} y {PCT_MAX}: {sp}")
        if not f.get("editable"):
            av.append("Celda no editable en ML (ya participa)")
        if not sku:
            av.append("Sin SKU: no se puede cruzar con el PM ni el costo")
            out.append(r)
            continue
        p = precios.get(sku)
        base = precio_ml(p.precio_web, p.pct_ml) if p else None
        if p:
            r["pm"], r["precio_pm"] = _pm_de(p), _n(base)
        else:
            av.append("Sin precio en el PM")
        datos: DatosSku = datos_fn(sku)
        if r["pm"] is None and datos.pm:
            r["pm"] = datos.pm
        r["categoria"] = datos.categoria
        if not datos.costo_usd:
            av.append("Sin costo vigente en Ecom")
        elif not datos.iva_factor:
            av.append("Sin alícuota de IVA")
        if base and orig:
            r["descuento_que_cuadra_pct"] = _pct((orig - base) / orig)
            if o["precio_cliente"] is not None:
                r["dif_vs_pm_pct"] = _pct((o["precio_cliente"] - base) / base)
        if o["precio_vendedor"] is None:
            av.append("Sin descuento cargado: no hay margen de oferta")
        elif datos.costo_usd and datos.iva_factor:
            costo = datos.costo_usd * tc
            r["costo"] = _n(costo)
            envio = _D(envios[f["ITEM_ID"]]) if f["ITEM_ID"] in envios else Decimal(0)
            if f["ITEM_ID"] not in envios and o["precio_cliente"] >= umbral:
                av.append("Sin envío: el margen de esta oferta no descuenta el costo de envío")
            try:
                for plan in PLANES:
                    d = margen_oferta(o["precio_vendedor"], o["precio_cliente"], plan, costo, datos.iva_factor, par, envio)
                    r["margenes"][plan] = {"margen": _pct(d.margen), "rentabilidad": _n(d.rentabilidad)}
                if o["meli_monto"]:
                    sin = margen_oferta(o["precio_cliente"], o["precio_cliente"], "contado", costo, datos.iva_factor, par, envio)
                    r["margen_contado_sin_aporte_ml"] = _pct(sin.margen)
                if margen_objetivo is not None:
                    r["pct_max_para_margen"] = pct_max_para_margen(
                        orig, f.get("MELI_PERCENTAGE") or 0, margen_objetivo, "contado", costo, datos.iva_factor, par, envio)
                if base:
                    r["margen_a_precio_pm_contado"] = _pct(margen_oferta(base, base, "contado", costo, datos.iva_factor, par, envio).margen)
            except (motor.ParametroFaltante, ValueError) as e:
                av.append(str(e))
        out.append(r)
    con_margen = [x for x in out if x["margenes"]]
    return {
        "fecha": fecha.isoformat(), "tc": float(tc), "planes": list(PLANES),
        "resumen": {
            "filas": len(out), "con_margen": len(con_margen),
            "sin_sku": sum(1 for x in out if not x["sku"]),
            "sin_precio_pm": sum(1 for x in out if x["sku"] and x["precio_pm"] is None),
            "sin_costo": sum(1 for x in out if any("Sin costo" in a for a in x["avisos"])),
            "margen_contado_negativo": sum(1 for x in con_margen if x["margenes"]["contado"]["margen"] < 0),
        },
        "filas": out,
    }
