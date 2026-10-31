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

import re
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from . import motor_precios as motor
from .pricing_pm import DatosSku, norm_sku, precio_ml, vigentes
from .reportes_pricing import _n, _pct, _pm_de

PLANES = ("contado", "3", "6", "9", "12")
PCT_MIN, PCT_MAX = 5, 80  # ML: enteros entre 5% y 80%
_D = lambda x: Decimal(str(x))

# Pendientes conocidos que la pantalla muestra siempre (Maxx, 2026-10-14).
AVISOS_GENERALES = [
    "Primer tramo de costo fijo (lista < $16.000): se usa $1.330 de la tabla. El Recibís del Excel sugiere ~$60 más (¿$1.390?); a confirmar con una venta real de ese tramo.",
    "Envío real desde $33.000 de lista: todavía no se trae de ML por ítem; esos márgenes NO descuentan el envío y salen más altos que los reales.",
]


# ── SKU de una publicación: simple, con cantidad («X2 CB435A…», «X10 AUTOR-80G-A4», «X2-CF230ACOMP») o combo («INKCARTHP74XL INKCARTHP75XL») ──
_SEP_SKU = re.compile(r"[\s,;+]+")


def descomponer_sku(texto) -> list[tuple[str, int]]:
    """`[(sku normalizado, cantidad)]`. «X2 A» o «X2-A» = 2 unidades de A; «A B» (o «A, B») = un combo de A y B; un SKU repetido suma cantidades."""
    comps: dict[str, int] = {}
    pendiente = 1
    for tok in _SEP_SKU.split(str(texto or "").strip()):
        if not tok or not re.search(r"[A-Za-z0-9]", tok):      # separadores sueltos como « - »
            continue
        m = re.fullmatch(r"[Xx](\d+)", tok)
        if m:
            pendiente = int(m.group(1)) or 1
            continue
        m = re.fullmatch(r"[Xx](\d+)[-_](.+)", tok)
        cant, sku = (int(m.group(1)) or 1, m.group(2)) if m else (pendiente, tok)
        pendiente = 1
        sku = norm_sku(sku)
        if sku:
            comps[sku] = comps.get(sku, 0) + cant
    return list(comps.items())


def _es_combo(comps) -> bool:
    return len(comps) > 1 or (len(comps) == 1 and comps[0][1] != 1)


def _cruzar_combo(comps, precios, datos_fn, av):
    """Precio PM, costo e IVA de un combo / una publicación con cantidad: la SUMA de sus componentes × cantidad. Si falta el precio o el costo de alguno, ese dato queda vacío
    y se dice cuál (no se inventa). El IVA es el ponderado por costo (si los componentes tienen IVA distinto, se avisa)."""
    ds = [(sku, cant, datos_fn(sku)) for sku, cant in comps]
    for sku, _, d in ds:
        if not d.costo_usd:
            av.append(f"Combo: sin costo vigente en Ecom de {sku}")
        elif not d.iva_factor:
            av.append(f"Combo: sin alícuota de IVA de {sku}")
    pms = [(sku, cant, precios.get(sku)) for sku, cant in comps]
    for sku, _, pp in pms:
        if pp is None:
            av.append(f"Combo: sin precio en el PM de {sku}")
    base = None if any(pp is None for _, _, pp in pms) else sum((precio_ml(pp.precio_web, pp.pct_ml) * cant for _, cant, pp in pms), Decimal(0))
    completo = all(d.costo_usd and d.iva_factor for _, _, d in ds)
    costo = sum((d.costo_usd * cant for _, cant, d in ds), Decimal(0)) if completo else None
    iva = (sum((d.costo_usd * cant * d.iva_factor for _, cant, d in ds), Decimal(0)) / costo) if completo and costo else None
    if completo and len({d.iva_factor for _, _, d in ds}) > 1:
        av.append("Combo con IVA distinto en sus componentes: se usa el promedio ponderado por costo")
    nombres = [(_pm_de(pp) if pp else None) or d.pm for (_, _, pp), (_, _, d) in zip(pms, ds)]
    pm = " + ".join(dict.fromkeys(n for n in nombres if n)) or None
    cat = next((d.categoria for _, _, d in ds if d.categoria), None)
    return DatosSku(costo, iva, pm, cat, None), base, pm


def comision_de(par: motor.ParametrosMotor, categoria: str | None, real=None, origen_real: str = "ml") -> tuple[Decimal, str]:
    """Comisión ML (fracción) de la publicación y de dónde sale, en este orden: la REAL leída de ML para esa publicación
    (`real`), la de su categoría en `pricing_comision_categoria` (las categorías internas no siempre coinciden con las de ML:
    es un respaldo), o la general."""
    if real is not None:
        return _D(real), origen_real
    # Comisión única de ML (criterio de precio, 15,5 %): la tabla por categoría queda cargada pero ya no se usa (dato viejo, decisión de Maxi 28/10).
    return par.valor("ML", "comision_general"), "general"


# "Impuestos" que ML descuenta aparte en el Recibís (retenciones): 0,904% del monto (240 s/ $26.599; 321 s/ $35.589 en ventas
# reales de SEW-MINI; idéntico en el Excel de Día de la Madre). No entra al margen (IIBB y cheque ya lo cubren): solo al Recibís.
IMPUESTOS_ML_PCT = Decimal("0.00904")


def dinero(v) -> float | None:
    """'$\xa06,947.91' (formato de ML) → 6947.91."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v).replace("\xa0", "").replace("$", "").replace(",", "").strip()
    try:
        return float(t)
    except ValueError:
        return None


def recibis(d: motor.Desglose, precio_vendedor) -> Decimal:
    """Lo que ML llama "Recibís": el precio del vendedor menos comisión, cuotas, costo fijo, envío e impuestos (0,904%)."""
    c = d.cargos
    return _D(precio_vendedor) - c["comision"] - c["cuotas"] - c["costo_fijo"] - c["envio"] - _D(precio_vendedor) * IMPUESTOS_ML_PCT


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
    envio: Decimal = Decimal(0), precio_lista=None, comision=None,
) -> motor.Desglose:
    """`precio_lista`: el de la publicación sin promo; define el tramo del costo fijo y
    el umbral de envío (validado contra el "Recibís" de ML)."""
    pv, pc = _D(precio_vendedor), _D(precio_cliente)
    pl = _D(precio_lista) if precio_lista is not None else None
    e = motor.EntradaMotor(
        canal="ML", costo=costo, iva_factor=iva, plan=plan, envio=envio,
        precio_cliente=pc if pc != pv else None, precio_lista=pl if pl is not None and pl != pc else None,
        comision_pct=None if comision is None else _D(comision),
    )
    return motor.precio_a_margen(pv, e, par)


def pct_max_para_margen(
    original, meli_pct, objetivo, plan: str, costo: Decimal, iva: Decimal, par: motor.ParametrosMotor,
    envio: Decimal = Decimal(0), comision=None,
) -> int | None:
    """Mayor % de descuento TOTAL entero (5–80, la regla de ML es sobre el total) que deja el margen ≥
    `objetivo` (fracción). El vendedor pone total − % de ML (supone que ML mantiene el suyo). Recorre todos los
    enteros: el margen no es monótono (el costo fijo y el envío cambian por tramo de precio). None si ni el 5% alcanza."""
    orig, mejor, meli = _D(original), None, _D(meli_pct or 0)
    for total in range(PCT_MIN, PCT_MAX + 1):
        if total < meli:  # ML ya cubre más que el total pedido
            continue
        o = precios_oferta(orig, seller_pct=_D(total) - meli, meli_pct=meli)
        try:
            r = margen_oferta(o["precio_vendedor"], o["precio_cliente"], plan, costo, iva, par, envio, orig, comision)
        except (motor.ParametroFaltante, ValueError):
            continue
        if r.margen >= _D(objetivo):
            mejor = total
    return mejor


def params_front(par: motor.ParametrosMotor) -> dict:
    """Los parámetros del motor para ML, para que la pantalla recalcule el margen al instante al jugar el
    descuento (misma cuenta que `margen_oferta`; la paridad la cubre test_front_campanas)."""
    return {
        "comision": float(par.valor("ML", "comision_general")), "iva_cargos": float(par.valor("ML", "iva_cargos")),
        "iibb": float(par.valor("ML", "iibb")), "cheque": float(par.valor("ML", "imp_cheque")),
        "umbral_envio": float(par.valor("ML", "umbral_envio_gratis")),
        "tramos_costo_fijo": [{"desde": float(t["desde"]), "hasta": None if t["hasta"] is None else float(t["hasta"]),
                               "valor": float(t["valor"])} for t in motor.tramos_costo_fijo_ml(par)],
        "cuotas": {pl: float(par.cuota("ML", pl)) for pl in PLANES},
    }


def analizar(
    db: Session, filas: list[dict], fecha: date, tc: Decimal, datos_fn, par: motor.ParametrosMotor,
    envios: dict[str, Decimal] | None = None, margen_objetivo: Decimal | None = None, plan_objetivo: str = "contado",
) -> dict:
    """`filas`: las de `campanas_ml_xlsx.leer_promociones`. `datos_fn(sku) -> DatosSku`."""
    precios = vigentes(db, fecha)
    envios = envios or {}
    umbral = par.valor("ML", "umbral_envio_gratis")
    out = []
    for f in filas:
        av, sku = [], norm_sku(f.get("SKU") or "")
        combo = None
        if sku and sku not in precios and not datos_fn(sku).costo_usd:     # un SKU con espacio propio («PV-AB 1») sigue siendo uno solo
            comps = descomponer_sku(f.get("SKU"))
            if _es_combo(comps) and any(c in precios or datos_fn(c).costo_usd for c, _ in comps):   # si no se conoce ninguno, es un SKU desconocido, no un combo
                combo = comps
                sku = " + ".join(s if c == 1 else f"{c}×{s}" for s, c in comps)
        o = precios_oferta(f["ORIGINAL_PRICE"], f.get("SELLER_PERCENTAGE"), f.get("SELLER_AMOUNT"),
                           f.get("MELI_PERCENTAGE"), f.get("MELI_AMOUNT"))  # montos de ML mandan: el % viene redondeado
        orig = _D(f["ORIGINAL_PRICE"]) if f.get("ORIGINAL_PRICE") else None
        r = {
            "fila": f["fila"], "item_id": f["ITEM_ID"], "sku": sku or None, "titulo": f.get("TITLE"),
            "editable": f.get("editable"), "estado": f.get("STATUS"), "accion": f.get("ACTION"),
            "precio_original": _n(orig), "seller_pct": f.get("SELLER_PERCENTAGE"), "meli_pct": f.get("MELI_PERCENTAGE"),
            "seller_monto": _n(o["seller_monto"]), "meli_monto": _n(o["meli_monto"]),
            "precio_vendedor": _n(o["precio_vendedor"]), "precio_cliente": _n(o["precio_cliente"]),
            "precio_final_ml": f.get("FINAL_PRICE"),
            "promo_id": f.get("PROMO_ID"), "promo_tipo": f.get("PROMO_TYPE"),
                        "cuenta": f.get("cuenta"), "sku_origen": f.get("sku_origen"),
            "pm": None, "precio_pm": None, "costo": None, "margenes": {}, "avisos": av,
        }
        sp, mp = f.get("SELLER_PERCENTAGE"), f.get("MELI_PERCENTAGE")
        total = f.get("DISCOUNT_PERCENTAGE") if f.get("DISCOUNT_PERCENTAGE") is not None else (None if sp is None else sp + (mp or 0))
        r["descuento_total_pct"] = None if total is None else round(float(total), 3)
        if total is not None and not (abs(total - round(total)) < 1e-6 and PCT_MIN <= total <= PCT_MAX):
            av.append(f"ML pide el descuento TOTAL entero entre {PCT_MIN} y {PCT_MAX}: {total}")
        if not f.get("editable"):
            av.append("Celda no editable en ML (ya participa)")
        if not sku:
            av.append("Sin SKU: no se puede cruzar con el PM ni el costo")
            out.append(r)
            continue
        if combo:
            datos, base, pm_combo = _cruzar_combo(combo, precios, datos_fn, av)
            r["sku"], r["combo"] = sku, [{"sku": s, "cantidad": c} for s, c in combo]
            r["pm"], r["precio_pm"] = pm_combo, _n(base)
        else:
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
        if combo:
            pass                       # los avisos de costo / IVA del combo ya salieron componente por componente
        elif not datos.costo_usd:
            av.append("Sin costo vigente en Ecom")
        elif not datos.iva_factor:
            av.append("Sin alícuota de IVA")
        if base and orig:
            r["descuento_que_cuadra_pct"] = _pct((orig - base) / orig)
            if o["precio_cliente"] is not None:
                r["dif_vs_pm_pct"] = _pct((o["precio_cliente"] - base) / base)
        comision, com_origen = comision_de(par, datos.categoria, f.get("comision_real"), f.get("comision_origen") or "ml")
        r["comision_pct"], r["comision_origen"] = round(float(comision) * 100, 3), com_origen
        if com_origen == "general":
            av.append("Comisión ML: no se pudo leer la real de la publicación y la categoría %s no está cargada: se usa la general (%s%%)" % (datos.categoria or "sin categoría", r["comision_pct"]))
        elif com_origen == "categoria":
            av.append("Comisión ML: no se pudo leer la real de la publicación; se usa la de la categoría de la tabla (%s%%), que puede no coincidir" % r["comision_pct"])
        tiene_costo = bool(datos.costo_usd and datos.iva_factor)
        envio = _D(envios[f["ITEM_ID"]]) if f["ITEM_ID"] in envios else Decimal(0)
        if tiene_costo:
            costo = datos.costo_usd * tc
            r["costo"] = _n(costo)
            r["calc"] = {"costo": float(costo), "costo_usd": float(datos.costo_usd), "iva": float(datos.iva_factor), "envio": float(envio), "comision": float(comision)}
        if o["precio_vendedor"] is None:
            av.append("Sin descuento cargado: no hay margen de oferta")
        elif tiene_costo:
            if f["ITEM_ID"] not in envios and orig and orig >= umbral:
                av.append("Envío no descontado: la publicación es de $33.000 o más y ML cobra el envío al vendedor; este margen NO lo descuenta (no hay una venta de los últimos 60 días de esta publicación para tomar el envío real: apretá «Traer envíos de 60 días» arriba), así que sale más alto que el real")
            try:
                for plan in PLANES:
                    d = margen_oferta(o["precio_vendedor"], o["precio_cliente"], plan, costo, datos.iva_factor, par, envio, orig, comision)
                    r["margenes"][plan] = {"margen": _pct(d.margen), "rentabilidad": _n(d.rentabilidad)}
                    if plan == "contado":
                        r["recibis_motor"] = _n(recibis(d, o["precio_vendedor"]))
                        rm = dinero(f.get("NEW_RECEIVES"))
                        r["recibis_ml"] = rm
                        r["recibis_dif"] = None if rm is None else round(r["recibis_motor"] - rm, 2)
                if o["meli_monto"]:
                    sin = margen_oferta(o["precio_cliente"], o["precio_cliente"], "contado", costo, datos.iva_factor, par, envio, orig, comision)
                    r["margen_contado_sin_aporte_ml"] = _pct(sin.margen)
                if margen_objetivo is not None:
                    r["pct_max_para_margen"] = pct_max_para_margen(
                        orig, float(o["meli_monto"] / orig * 100) if o["meli_monto"] else 0, margen_objetivo, plan_objetivo, costo, datos.iva_factor, par, envio, comision)
                if base:
                    r["margen_a_precio_pm_contado"] = _pct(margen_oferta(base, base, "contado", costo, datos.iva_factor, par, envio, comision=comision).margen)
            except (motor.ParametroFaltante, ValueError) as e:
                av.append(str(e))
        out.append(r)
    con_margen = [x for x in out if x["margenes"]]
    return {
        "fecha": fecha.isoformat(), "tc": float(tc), "planes": list(PLANES), "avisos_generales": AVISOS_GENERALES, "motor_ml": params_front(par),
        "resumen": {
            "filas": len(out), "con_margen": len(con_margen),
            "sin_sku": sum(1 for x in out if not x["sku"]),
            "sin_precio_pm": sum(1 for x in out if x["sku"] and x["precio_pm"] is None),
            "sin_costo": sum(1 for x in out if any("Sin costo" in a for a in x["avisos"])),
            "margen_contado_negativo": sum(1 for x in con_margen if x["margenes"]["contado"]["margen"] < 0),
        },
        "filas": out,
    }
