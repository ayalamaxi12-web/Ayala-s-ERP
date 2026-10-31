"""Insumo del Cyber 2026 (`cyber_2026_input.csv`): una fila por SKU con stock disponible, solo Mercado Libre (cuentas GROUP = IT y ARG = MT).

Solo lectura: no escribe en ML, Ecom ni Sheets. El CSV lo consume después el motor de precios del Cyber; las reglas de precio van aparte (`REGLAS`)
como parámetros, no están "cocinadas" acá.

Fuentes:
  - publicaciones activas, precio y título: API de ML (por cuenta);
  - ventas (YTD y últimos 90 días): `venta_ecom` del ERP (unidades por orden, cuenta por `usuario_integracion` GROUP / ARG);
  - stock disponible: Ecom por depósito. Se toma el depósito NO Full que más tiene; si ahí no hay y Full sí, se usa Full (`stock_origen` = "full": SKU
    que hay que empujar fuerte porque solo queda stock en Full);
  - costo y margen: costo vigente de Ecom × TC, margen de la cuenta de ML a ese precio (contado: comisión real de la publicación, cargos, envío real si
    se conoce); renta % sobre el precio sin IVA, como en el resto del ERP;
  - grupo `liquidar`: alerta «LIQUIDAR» (REVENTAR) de la última foto de Proyección 2027; grupo `rey`: clase REY de esa misma foto (Pareto del margen anual);
  - links de competidores: `Referencias_Mercado` (Rol_Competidor Rey / Media / Barato).
"""
from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from decimal import Decimal

CUENTA_NOMBRE = {"IT": "GROUP", "MT": "ARG"}
UMBRAL_TICKET_ALTO = 150000

# Reglas que va a aplicar el motor DESPUÉS (parámetros; Maxx, 2026-10-31). Sin estos números el motor no decide nada.
REGLAS = {
    "ticket_alto_desde": UMBRAL_TICKET_ALTO,
    "margen": "neto de comisión, cargos, envío y costo de cuotas",
    "grupos": {
        "liquidar": {"piso_margen_pct": None, "puede_ir_bajo_el_costo": True},
        "medio": {"piso_margen_pct": 10, "piso_margen_si_hace_falta_pct": 8, "piso_margen_si_ticket_alto_pct": 5},
        "rey": {"piso_margen_pct": 20, "piso_margen_si_muy_necesario_pct": 18, "debajo_del_piso_requiere_ok_de": "Maxx"},
    },
    "como_se_clasifica": "liquidar si la proyección de aging lo marca LIQUIDAR; rey si es clase REY en Proyección 2027 (los SKU que concentran ~80 % del margen anual de 12 meses: lo define lo que vendió, no el precio); medio todo lo demás. El precio solo marca ticket_alto.",
}

COLUMNAS = ["sku", "titulo", "cuenta", "mla_id", "grupo", "costo", "precio_actual", "margen_actual_pct", "stock_disponible", "ventas_ytd_unid",
            "ventas_ult_90d_unid", "ticket_alto", "link_rey", "link_media", "link_barato", "stock_origen"]
ORDEN_GRUPO = {"liquidar": 0, "rey": 1, "medio": 2}


def cuenta_de_usuario(usuario_integracion: str | None) -> str | None:
    """`GLOBALELECTRONICSGROUP` → IT (GROUP); `GLOBALELECTRONICSARG` → MT (ARG); cualquier otra (Global WEB, Frávega...) no es de ML."""
    u = (usuario_integracion or "").upper()
    if "GROUP" in u:
        return "IT"
    if "ARG" in u:
        return "MT"
    return None


def ventas_por_sku_y_cuenta(db, hoy: date) -> dict[tuple[str, str], dict]:
    """Unidades vendidas en el año y en los últimos 90 días por (SKU normalizado, cuenta) con las órdenes de ML ya guardadas. Las órdenes con varios SKU no se
    cuentan (como en el resto de los reportes por SKU) y se informan en `omitidas`."""
    from rentabilidad.models import VentaEcom
    from rentabilidad.pricing_pm import norm_sku

    inicio = date(hoy.year, 1, 1)
    d90 = hoy - timedelta(days=90)
    out: dict[tuple[str, str], dict] = {}
    q = db.query(VentaEcom).filter(VentaEcom.excluido.is_(False), VentaEcom.fecha_creacion_venta >= inicio)
    for v in q.all():
        cuenta = cuenta_de_usuario(v.usuario_integracion)
        if not cuenta or not v.skus_vendidos or "," in v.skus_vendidos:
            continue
        acum = out.setdefault((norm_sku(v.skus_vendidos), cuenta), {"ytd": 0, "d90": 0})
        u = int(v.unidades or 1)
        acum["ytd"] += u
        if v.fecha_creacion_venta >= d90:
            acum["d90"] += u
    return out


def stock_de_ecom(ecom, sku: str) -> tuple[int | None, int | None]:
    """(stock propio, stock Full) de un SKU en Ecom. Propio = el depósito NO Full que más tiene (no la suma). Un pack o kit («X2 A», «A B») se resuelve por sus
    componentes: alcanza para tantas unidades como el componente más escaso permita. (None, None) = el SKU no está en Ecom."""
    from rentabilidad.campanas_ml import descomponer_sku

    def uno(s: str) -> tuple[int | None, int | None]:
        p = ecom._producto_por_sku(s)
        if not p:
            return None, None
        full_id = ecom.warehouse_full_id()
        por_deposito: dict[str, int] = {}
        for var in p.get("variants") or []:
            for wh in var.get("variantWarehouses") or []:
                por_deposito[wh.get("warehouse_id")] = por_deposito.get(wh.get("warehouse_id"), 0) + (wh.get("warehouse_qty") or 0)
        full = por_deposito.pop(full_id, 0)
        return (max(por_deposito.values()) if por_deposito else 0), full

    propio, full = uno(sku)
    if propio is not None:
        return propio, full
    comps = descomponer_sku(sku)
    if not comps or comps == [(sku, 1)]:
        return None, None
    partes = [(uno(c), n) for c, n in comps]
    if any(p[0] is None for p, _ in partes):
        return None, None
    return min(p[0] // n for p, n in partes), min(p[1] // n for p, n in partes)


def clasificar(es_liquidar: bool, es_rey: bool) -> str:
    """liquidar manda sobre rey (un REY nunca está en LIQUIDAR en Proyección, pero por las dudas); todo lo demás es medio."""
    return "liquidar" if es_liquidar else ("rey" if es_rey else "medio")


def elegir_publicaciones(candidatas: list[dict]) -> list[dict]:
    """Una fila por SKU: entre sus publicaciones (de las dos cuentas), la que más vendió en los últimos 90 días; si empatan, quedan todas las empatadas."""
    por_sku: dict[str, list[dict]] = {}
    for c in candidatas:
        por_sku.setdefault(c["sku_norm"], []).append(c)
    out = []
    for lista in por_sku.values():
        mejor = max(c["ventas_ult_90d_unid"] for c in lista)
        out.extend(c for c in lista if c["ventas_ult_90d_unid"] == mejor)
    return out


def ordenar(filas: list[dict]) -> list[dict]:
    """Por grupo (liquidar, rey, medio) y, dentro de cada grupo, por plata en stock (costo × stock disponible) de mayor a menor."""
    return sorted(filas, key=lambda f: (ORDEN_GRUPO[f["grupo"]], -float(f["costo"] or 0) * f["stock_disponible"], f["sku"]))


def resumen(filas: list[dict]) -> dict:
    out = {g: {"skus": 0, "plata_en_stock": 0.0, "stock_solo_full": 0} for g in ORDEN_GRUPO}
    for f in filas:
        r = out[f["grupo"]]
        r["skus"] += 1
        r["plata_en_stock"] = round(r["plata_en_stock"] + float(f["costo"] or 0) * f["stock_disponible"], 2)
        r["stock_solo_full"] += f["stock_origen"] == "full"
    out["total"] = {"skus": sum(r["skus"] for r in out.values()), "plata_en_stock": round(sum(r["plata_en_stock"] for r in out.values()), 2)}
    return out


def a_csv(filas: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(COLUMNAS)
    for f in filas:
        w.writerow([("" if f.get(c) is None else f[c]) for c in COLUMNAS])
    return buf.getvalue()


def links_de_competidores(filas_refs: list[list[str]]) -> dict[str, dict[str, str]]:
    """SKU normalizado → {'Rey': link, 'Media': link, 'Barato': link} de `Referencias_Mercado` (Tipo = Competencia, activas). Con varias del mismo rol queda la primera."""
    from rentabilidad.pricing_pm import norm_sku

    if not filas_refs:
        return {}
    cab = [str(c).strip() for c in filas_refs[0]]
    idx = {c: i for i, c in enumerate(cab)}
    out: dict[str, dict[str, str]] = {}
    for r in filas_refs[1:]:
        g = lambda c: (r[idx[c]].strip() if c in idx and idx[c] < len(r) else "")
        if g("Tipo").lower() != "competencia" or g("Activo").lower() not in ("si", "sí", "true", "1", "s", "x"):
            continue
        rol = g("Rol_Competidor").capitalize()
        link = g("Link_Publicacion")
        if rol in ("Rey", "Media", "Barato") and link and g("SKU"):
            out.setdefault(norm_sku(g("SKU")), {}).setdefault(rol, link)
    return out


def costo_y_iva(sku: str, datos_fn, tc: Decimal) -> tuple[Decimal | None, Decimal | None]:
    """Costo en pesos (sin IVA) e IVA del SKU; un pack o kit suma el costo de sus componentes (igual que Campañas ML). (None, None) si falta el dato."""
    from rentabilidad.campanas_ml import descomponer_sku
    from rentabilidad.pricing_pm import norm_sku

    d = datos_fn(norm_sku(sku))
    if d.costo_usd and d.iva_factor:
        return d.costo_usd * tc, d.iva_factor
    total, iva = Decimal(0), None
    comps = descomponer_sku(sku)
    if not comps:
        return None, None
    for c, n in comps:
        dc = datos_fn(norm_sku(c))
        if not (dc.costo_usd and dc.iva_factor):
            return None, None
        total += dc.costo_usd * tc * n
        iva = iva or dc.iva_factor
    return total, iva


def generar(ml, ecom, db, datos_fn, tc: Decimal, par, hoy: date, alertas: dict[str, dict], links: dict[str, dict[str, str]],
            reglas: dict = REGLAS, progreso=None) -> dict:
    """Arma el insumo completo: {filas, resumen, reglas, avisos, conteos}. `alertas`: SKU → {clase, alerta} de la foto de Proyección; `links`: de
    `links_de_competidores`."""
    import campanas_ml_comision
    from rentabilidad import campanas_ml
    from rentabilidad.pricing_pm import norm_sku

    avisos: list[str] = []
    prog = progreso or (lambda *a: None)
    ventas = ventas_por_sku_y_cuenta(db, hoy)
    candidatas: list[dict] = []
    sin_sku = 0
    for cuenta in CUENTA_NOMBRE:
        ids = ml.items_activos(cuenta)
        headers = {"Authorization": f"Bearer {ml._token(cuenta)}"}
        for i in range(0, len(ids), 20):
            prog(i, len(ids), f"Publicaciones de ML ({CUENTA_NOMBRE[cuenta]})")
            d = ml._get("https://api.mercadolibre.com/items", {
                "ids": ",".join(ids[i:i + 20]),
                "attributes": "id,title,price,available_quantity,seller_custom_field,attributes,status,category_id,listing_type_id"}, headers)
            for e in (d or []):
                it = e.get("body") if isinstance(e, dict) and "body" in e else e
                if not it or it.get("status") not in (None, "active"):
                    continue
                from ml_full import _sku_de_item
                sku = _sku_de_item(it)
                if not sku:
                    sin_sku += 1
                    continue
                v = ventas.get((norm_sku(sku), cuenta), {"ytd": 0, "d90": 0})
                candidatas.append({"sku": sku, "sku_norm": norm_sku(sku), "titulo": it.get("title", ""), "cuenta": cuenta, "mla_id": it["id"],
                                   "precio_actual": float(it.get("price") or 0), "categoria_ml": it.get("category_id"), "tipo_ml": it.get("listing_type_id"),
                                   "ventas_ytd_unid": v["ytd"], "ventas_ult_90d_unid": v["d90"]})
    if sin_sku:
        avisos.append(f"{sin_sku} publicaciones activas sin SKU: no entran al insumo.")
    elegidas = elegir_publicaciones(candidatas)
    cache_stock: dict[str, tuple[int | None, int | None]] = {}
    filas, sin_ecom, sin_costo = [], 0, 0
    skus = sorted({c["sku"] for c in elegidas})
    for k, sku in enumerate(skus):
        prog(k, len(skus), "Stock en Ecom")
        try:
            cache_stock[sku] = stock_de_ecom(ecom, sku)
        except Exception as e:  # noqa: BLE001
            cache_stock[sku] = (None, None)
            avisos.append(f"No se pudo leer el stock de {sku} en Ecom ({type(e).__name__}).")
    con_stock = []
    for c in elegidas:
        propio, full = cache_stock.get(c["sku"], (None, None))
        if propio is None:
            sin_ecom += 1
            continue
        if propio > 0:
            c["stock_disponible"], c["stock_origen"] = propio, "ecom"
        elif full and full > 0:
            c["stock_disponible"], c["stock_origen"] = full, "full"
        else:
            continue
        con_stock.append(c)
    if sin_ecom:
        avisos.append(f"{sin_ecom} publicaciones con un SKU que no se encontró en Ecom: no se pudo saber su stock y quedaron afuera.")
    prog(0, 1, "Comisiones reales de ML")
    try:
        coms, av = campanas_ml_comision.comisiones({c["mla_id"]: {"category_id": c["categoria_ml"], "listing_type_id": c["tipo_ml"], "precio": c["precio_actual"]} for c in con_stock})
        avisos += av
    except Exception as e:  # noqa: BLE001
        coms = {}
        avisos.append(f"No se pudo leer la comisión real de ML ({type(e).__name__}): se usa la general.")
    umbral_envio = par.valor("ML", "umbral_envio_gratis")
    sin_envio_real = 0
    for c in con_stock:
        costo, iva = costo_y_iva(c["sku"], datos_fn, tc)
        precio = Decimal(str(c["precio_actual"]))
        margen = None
        if costo is not None and precio > 0:
            real = (coms.get(c["mla_id"]) or {}).get("pct")
            comision, _ = campanas_ml.comision_de(par, None, real)
            try:
                margen = round(float(campanas_ml.margen_oferta(precio, precio, "contado", costo, iva, par, Decimal(0), precio, comision).margen) * 100, 1)
            except Exception:  # noqa: BLE001
                margen = None
            if precio >= umbral_envio:
                sin_envio_real += 1
        else:
            sin_costo += 1
        al = alertas.get(c["sku_norm"]) or {}
        liquidar = (al.get("alerta") or "").upper() == "LIQUIDAR" or (al.get("clase") or "").upper() == "REVENTAR"
        es_rey = (al.get("clase") or "").upper() == "REY"
        l = links.get(c["sku_norm"], {})
        filas.append({
            "sku": c["sku"], "titulo": c["titulo"], "cuenta": CUENTA_NOMBRE[c["cuenta"]], "mla_id": c["mla_id"],
            "grupo": clasificar(liquidar, es_rey),
            "costo": None if costo is None else round(float(costo), 2), "precio_actual": round(c["precio_actual"], 2), "margen_actual_pct": margen,
            "stock_disponible": c["stock_disponible"], "ventas_ytd_unid": c["ventas_ytd_unid"], "ventas_ult_90d_unid": c["ventas_ult_90d_unid"],
            "ticket_alto": "si" if c["precio_actual"] >= reglas["ticket_alto_desde"] else "no",
            "link_rey": l.get("Rey", ""), "link_media": l.get("Media", ""), "link_barato": l.get("Barato", ""), "stock_origen": c["stock_origen"],
        })
    if sin_costo:
        avisos.append(f"{sin_costo} SKU sin costo vigente en Ecom: costo y margen quedan vacíos.")
    if sin_envio_real:
        avisos.append(f"{sin_envio_real} publicaciones de $33.000 o más: el margen actual NO descuenta el envío real (usa 0).")
    if not alertas:
        avisos.append("No hay foto de Proyección 2027 cargada: los grupos «liquidar» y «rey» quedan vacíos (todo sale como «medio»).")
    filas = ordenar(filas)
    return {"filas": filas, "resumen": resumen(filas), "reglas": reglas, "avisos": avisos,
            "conteos": {"publicaciones_activas": len(candidatas), "con_stock": len(filas), "hoy": hoy.isoformat()}}
