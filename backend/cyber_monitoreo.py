"""Monitoreo diario del Cyber 2026 (solo lectura de las órdenes ya guardadas; las únicas escrituras son filas en planillas, ver `publicar_*`).

Qué mira, por publicación de la lista oficial (`Cyber_Precios`):
- cuánto vendió el día y a qué precio REAL cobró (precio final de la orden ÷ unidades; nunca el tachado), y si coincide con el precio definido para el Cyber;
- el margen real de esas órdenes contra el proyectado (en 3 cuotas);
- su ritmo contra el histórico (promedio diario de los 90 días ANTERIORES al Cyber);
- los días de stock que quedan al ritmo del Cyber.
Y, aparte, las publicaciones que venden durante el Cyber y NO están en la lista (candidatas a sumar).

Las alertas salen en el mismo formato que los «precios desfasados» que revisa Maca (pestaña «Maca» de «Historial Automatizaciones»).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

CANAL_ALERTA = "ML Cyber"
COLS_ALERTA = ["Fecha", "SKU", "PM", "Canal", "Se_Vende", "Deberia", "Margen_Real", "Margen_Proyect", "Prioridad", "Link"]
TOL_PRECIO_PCT = 2.0            # el precio cobrado se aparta del del Cyber en más de esto → prioridad 1
TOL_MARGEN_PTS = 3.0            # el margen real está esto o más por debajo del proyectado → prioridad 2
PISO_POR_GRUPO = {"rey": 18.0, "medio": 8.0}      # margen real por debajo de esto → prioridad 1 (el piso más bajo que se acepta por grupo; liquidar no tiene)
RITMO_BAJO = 0.5                # vende menos de la mitad de su ritmo histórico → aviso
DIAS_STOCK_URGENTE = 3
UNIDADES_CANDIDATA = 2          # mínimo de unidades en el día para proponer una publicación que no está en el Cyber
DIAS_BASE = 90


def _f(x) -> float | None:
    try:
        if x in (None, ""):
            return None
        return float(str(x).replace(",", "."))
    except ValueError:
        return None


def link_ml(mla: str) -> str:
    digitos = "".join(c for c in str(mla) if c.isdigit())
    return f"https://articulo.mercadolibre.com.ar/MLA-{digitos}" if digitos else ""


def ventas_del_periodo(db, desde: date, hasta: date) -> list[dict]:
    """Órdenes de ML (de un solo SKU, no excluidas) creadas entre `desde` y `hasta`, ya con la cuenta."""
    from cyber_input import cuenta_de_usuario
    from rentabilidad.models import VentaEcom
    from rentabilidad.pricing_pm import norm_sku

    out = []
    q = db.query(VentaEcom).filter(VentaEcom.excluido.is_(False), VentaEcom.fecha_creacion_venta >= desde, VentaEcom.fecha_creacion_venta <= hasta)
    for v in q.all():
        cuenta = cuenta_de_usuario(v.usuario_integracion)
        if not cuenta or not v.skus_vendidos or "," in v.skus_vendidos:
            continue
        out.append({"fecha": v.fecha_creacion_venta, "sku": norm_sku(v.skus_vendidos), "sku_orig": v.skus_vendidos, "cuenta": cuenta, "mla": v.item_ml or "", "unidades": int(v.unidades or 1),
                    "precio_final": float(v.precio_final or 0), "precio_sin_iva": float(v.precio_sin_iva or 0), "rentabilidad": None if v.rentabilidad is None else float(v.rentabilidad),
                    "costo": float(v.costo_sin_iva or 0), "pm": v.pm or ""})
    return out


def ritmo_base(ventas_previas: list[dict], dias: int = DIAS_BASE) -> dict[tuple, float]:
    """Unidades por día en los `dias` previos al Cyber, por ("MLA", mla) y por (sku, cuenta)."""
    acum: dict[tuple, int] = defaultdict(int)
    for v in ventas_previas:
        for k in ((("MLA", v["mla"]) if v["mla"] else None), (v["sku"], v["cuenta"])):
            if k:
                acum[k] += v["unidades"]
    return {k: u / dias for k, u in acum.items()}


def _agrupar(ventas: list[dict]) -> dict[tuple, dict]:
    """Por publicación (cuenta, MLA): unidades, facturación, rentabilidad y precio promedio cobrado."""
    out: dict[tuple, dict] = {}
    for v in ventas:
        a = out.setdefault((v["cuenta"], v["mla"]), {"cuenta": v["cuenta"], "mla": v["mla"], "sku": v["sku"], "sku_orig": v["sku_orig"], "pm": v["pm"], "unidades": 0, "facturacion": 0.0,
                                                    "sin_iva": 0.0, "rent": 0.0, "sin_iva_con_rent": 0.0, "sin_costo": 0})
        a["unidades"] += v["unidades"]
        a["facturacion"] += v["precio_final"]
        a["sin_iva"] += v["precio_sin_iva"]
        if v["rentabilidad"] is not None and v["costo"] > 0:
            a["rent"] += v["rentabilidad"]
            a["sin_iva_con_rent"] += v["precio_sin_iva"]
        else:
            a["sin_costo"] += 1
    for a in out.values():
        a["precio_cobrado"] = a["facturacion"] / a["unidades"] if a["unidades"] else None
        a["margen_real"] = round(a["rent"] / a["sin_iva_con_rent"] * 100, 2) if a["sin_iva_con_rent"] > 0 else None
    return out


def analizar_dia(fecha: date, inicio: date, fin: date, lista: list[dict], ventas_dia: list[dict], ventas_cyber: list[dict], base: dict[tuple, float],
                 stock_fn=None) -> dict:
    """`lista`: filas de `Cyber_Precios`. `ventas_dia`: órdenes del `fecha`. `ventas_cyber`: todas las del Cyber hasta `fecha` (acumulado y ritmo). `base`: `ritmo_base`.
    `stock_fn(sku) -> (propio, full) | (None, None)` es opcional."""
    en_lista = {}
    for r in lista:
        if str(r.get("Estado")) == "no_participa":
            continue
        mla = str(r.get("MLA") or "")
        en_lista[(str(r.get("Cuenta")), mla)] = r
    dia = _agrupar(ventas_dia)
    acum = _agrupar(ventas_cyber)
    dias_cyber = max((fecha - inicio).days + 1, 1)
    filas, alertas, candidatas = [], [], []
    for clave, a in dia.items():
        r = en_lista.get(clave)
        if r is None:
            if a["unidades"] >= UNIDADES_CANDIDATA:
                b = base.get(("MLA", a["mla"]), base.get((a["sku"], a["cuenta"]), 0.0))
                candidatas.append({"cuenta": a["cuenta"], "mla": a["mla"], "sku": a["sku_orig"], "pm": a["pm"], "unidades": a["unidades"], "precio_cobrado": round(a["precio_cobrado"], 2),
                                   "margen_real": a["margen_real"], "ritmo_historico_dia": round(b, 2), "link": link_ml(a["mla"])})
            continue
        cyber = _f(r.get("Precio_Cyber"))
        proy = _f(r.get("Margen_3_cuotas_pct"))
        grupo = str(r.get("Grupo") or "")
        pc = a["precio_cobrado"]
        dif = None if not cyber or pc is None else round((pc / cyber - 1) * 100, 2)
        coincide = dif is not None and abs(dif) <= TOL_PRECIO_PCT
        b = base.get(("MLA", a["mla"]), base.get((a["sku"], a["cuenta"]), 0.0))
        ratio = None if b <= 0 else round(a["unidades"] / b, 2)
        ac = acum.get(clave)
        vel = (ac["unidades"] / dias_cyber) if ac else 0
        dias_stock = None
        if stock_fn and vel > 0:
            try:
                p, fu = stock_fn(a["sku_orig"])
                if p is not None or fu is not None:
                    dias_stock = round(((p or 0) + (fu or 0)) / vel, 1)
            except Exception:  # noqa: BLE001
                dias_stock = None
        motivos, prioridad = [], 0
        if dif is not None and not coincide:
            motivos.append(f"vendió a ${pc:,.0f} y el Cyber es ${cyber:,.0f} ({dif:+.1f} %)")
            prioridad = 1
        piso = PISO_POR_GRUPO.get(grupo)
        if a["margen_real"] is not None and piso is not None and a["margen_real"] < piso:
            motivos.append(f"margen real {a['margen_real']:.1f} % bajo el piso del grupo ({piso:.0f} %)")
            prioridad = 1
        elif a["margen_real"] is not None and proy is not None and a["margen_real"] <= proy - TOL_MARGEN_PTS:
            motivos.append(f"margen real {a['margen_real']:.1f} % contra {proy:.1f} % proyectado")
            prioridad = prioridad or 2
        if dias_stock is not None and dias_stock < DIAS_STOCK_URGENTE:
            motivos.append(f"quedan {dias_stock} días de stock")
            prioridad = 1
        if ratio is not None and ratio < RITMO_BAJO:
            motivos.append(f"vende {ratio:.0%} de su ritmo histórico")
            prioridad = prioridad or 2
        fila = {"cuenta": a["cuenta"], "mla": a["mla"], "sku": a["sku_orig"], "pm": a["pm"], "grupo": grupo, "unidades": a["unidades"], "precio_cobrado": round(pc, 2) if pc else None,
                "precio_cyber": cyber, "dif_precio_pct": dif, "coincide": coincide, "margen_real": a["margen_real"], "margen_proyectado": proy, "facturacion": round(a["facturacion"], 2),
                "rentabilidad": round(a["rent"], 2), "ritmo_historico_dia": round(b, 2), "ratio_vs_historico": ratio, "dias_stock": dias_stock, "prioridad": prioridad, "motivos": motivos,
                "sin_costo": a["sin_costo"]}
        filas.append(fila)
        if prioridad:
            alertas.append({"Fecha": fecha.isoformat(), "SKU": a["sku_orig"], "PM": a["pm"], "Canal": CANAL_ALERTA, "Se_Vende": round(pc, 2) if pc else "", "Deberia": cyber if cyber else "",
                            "Margen_Real": a["margen_real"] if a["margen_real"] is not None else "", "Margen_Proyect": proy if proy is not None else "", "Prioridad": prioridad,
                            "Link": link_ml(a["mla"]), "_motivo": "; ".join(motivos), "_mla": a["mla"], "_cuenta": a["cuenta"]})
    sin_ventas = [r for k, r in en_lista.items() if k not in dia]
    fact = sum(a["facturacion"] for a in dia.values())
    sin_iva = sum(a["sin_iva_con_rent"] for a in dia.values())
    rent = sum(a["rent"] for a in dia.values())
    fact_ac = sum(a["facturacion"] for a in acum.values())
    sin_iva_ac = sum(a["sin_iva_con_rent"] for a in acum.values())
    rent_ac = sum(a["rent"] for a in acum.values())
    filas.sort(key=lambda x: (-(x["prioridad"] or 0), -x["unidades"]))
    alertas.sort(key=lambda x: (x["Prioridad"], x["SKU"]))
    candidatas.sort(key=lambda x: -x["unidades"])
    return {"fecha": fecha.isoformat(), "dia_del_cyber": dias_cyber, "dias_totales": (fin - inicio).days + 1,
            "totales": {"publicaciones_con_ventas": len(filas), "publicaciones_en_lista": len(en_lista), "publicaciones_sin_ventas": len(sin_ventas), "unidades": sum(a["unidades"] for a in dia.values()),
                        "facturacion": round(fact, 2), "rentabilidad": round(rent, 2), "rentabilidad_pct": round(rent / sin_iva * 100, 2) if sin_iva else None,
                        "acumulado_facturacion": round(fact_ac, 2), "acumulado_rentabilidad": round(rent_ac, 2),
                        "acumulado_rentabilidad_pct": round(rent_ac / sin_iva_ac * 100, 2) if sin_iva_ac else None,
                        "alertas_prioridad_1": sum(1 for x in alertas if x["Prioridad"] == 1), "alertas_prioridad_2": sum(1 for x in alertas if x["Prioridad"] == 2)},
            "filas": filas, "alertas": alertas, "candidatas": candidatas}


def texto_mail(r: dict) -> tuple[str, str]:
    """(asunto, cuerpo en texto) del mail diario; el detalle va en la planilla."""
    t = r["totales"]
    asunto = f"Cyber día {r['dia_del_cyber']}/{r['dias_totales']} · {t['alertas_prioridad_1']} para revisar urgente · {r['fecha']}"
    l = [f"Cyber 2026 · día {r['dia_del_cyber']} de {r['dias_totales']} ({r['fecha']})", "",
         f"Facturación del día: ${t['facturacion']:,.0f} · rentabilidad {t['rentabilidad_pct'] if t['rentabilidad_pct'] is not None else '—'} %",
         f"Acumulado del Cyber: ${t['acumulado_facturacion']:,.0f} · rentabilidad {t['acumulado_rentabilidad_pct'] if t['acumulado_rentabilidad_pct'] is not None else '—'} %",
         f"Publicaciones con ventas: {t['publicaciones_con_ventas']} de {t['publicaciones_en_lista']} en la lista ({t['publicaciones_sin_ventas']} sin ventas)", "",
         f"Para revisar: {t['alertas_prioridad_1']} urgentes (prioridad 1) y {t['alertas_prioridad_2']} (prioridad 2)."]
    for x in r["alertas"][:15]:
        l.append(f"  P{x['Prioridad']} · {x['SKU']} ({x['PM'] or 'sin PM'}) · {x['_motivo']}")
    if len(r["alertas"]) > 15:
        l.append(f"  … y {len(r['alertas']) - 15} más en la pestaña «Maca».")
    if r["candidatas"]:
        l += ["", f"Venden en el Cyber y no están en la lista ({len(r['candidatas'])}): las 5 con más ventas"]
        for c in r["candidatas"][:5]:
            l.append(f"  {c['sku']} · {c['unidades']} u. a ${c['precio_cobrado']:,.0f} · {c['link']}")
    return asunto, "\n".join(l)


# ── Planillas (única escritura de este módulo: agrega filas, nunca borra ni pisa las existentes) ──
HISTORIAL_AUTOMATIZACIONES_ID = "1Ps4vx3dhsNZTMYCYXxXnTyLo0XOw65SpAn7QerCltx4"
TAB_MACA = "Maca"
TAB_MONITOREO = "Monitoreo Cyber"
TAB_CANDIDATAS = "Cyber_Candidatas"
COLS_MONITOREO = ["Fecha", "Cuenta", "MLA", "SKU", "PM", "Grupo", "Unidades", "Precio_Cobrado", "Precio_Cyber", "Dif_Precio_pct", "Margen_Real", "Margen_Proyect", "Facturacion", "Rentabilidad",
                  "Ritmo_Historico_Dia", "Ratio_vs_Historico", "Dias_Stock", "Prioridad", "Motivo"]
COLS_CANDIDATAS = ["Fecha", "Cuenta", "MLA", "SKU", "PM", "Unidades", "Precio_Cobrado", "Margen_Real", "Ritmo_Historico_Dia", "Link"]


def _hoja(ss, titulo: str, cols: list[str]):
    try:
        return ss.worksheet(titulo)
    except Exception:  # noqa: BLE001
        ws = ss.add_worksheet(title=titulo, rows=2000, cols=len(cols))
        ws.update(values=[cols], range_name="A1")
        return ws


def _agregar_sin_duplicar(ws, cols: list[str], filas: list[list], clave_idx: list[int]) -> int:
    """Agrega al final las filas cuya clave (columnas `clave_idx`, como texto) no esté ya en la hoja. No modifica ni borra nada."""
    existentes = ws.get_all_values()
    claves = {tuple(str(r[i]).strip() if i < len(r) else "" for i in clave_idx) for r in existentes[1:]}
    nuevas = [f for f in filas if tuple(str(f[i]).strip() for i in clave_idx) not in claves]
    if nuevas:
        ws.append_rows(nuevas, value_input_option="USER_ENTERED")
    return len(nuevas)


def publicar_alertas_maca(gc, alertas: list[dict]) -> dict:
    """Agrega las alertas a la pestaña «Maca» de «Historial Automatizaciones», con las MISMAS columnas que los precios desfasados. Si los encabezados no coinciden, no escribe."""
    ss = gc.open_by_key(HISTORIAL_AUTOMATIZACIONES_ID)
    ws = ss.worksheet(TAB_MACA)
    cab = [str(c).strip() for c in (ws.row_values(1) or [])][: len(COLS_ALERTA)]
    if cab != COLS_ALERTA:
        raise ValueError(f"Los encabezados de la pestaña «{TAB_MACA}» cambiaron ({cab}): no se escribió nada.")
    filas = [[a[c] for c in COLS_ALERTA] for a in alertas]
    return {"agregadas": _agregar_sin_duplicar(ws, COLS_ALERTA, filas, [0, 1, 3, 9]), "recibidas": len(filas)}      # clave: fecha + SKU + canal + link


def publicar_monitoreo(ss, resultado: dict) -> dict:
    """Agrega el detalle del día a «Monitoreo Cyber» y las candidatas a «Cyber_Candidatas» (hojas del Sheet del ERP)."""
    f = resultado["fecha"]
    det = [[f, x["cuenta"], x["mla"], x["sku"], x["pm"], x["grupo"], x["unidades"], x["precio_cobrado"] or "", x["precio_cyber"] or "", x["dif_precio_pct"] if x["dif_precio_pct"] is not None else "",
            x["margen_real"] if x["margen_real"] is not None else "", x["margen_proyectado"] if x["margen_proyectado"] is not None else "", x["facturacion"], x["rentabilidad"],
            x["ritmo_historico_dia"], x["ratio_vs_historico"] if x["ratio_vs_historico"] is not None else "", x["dias_stock"] if x["dias_stock"] is not None else "", x["prioridad"],
            "; ".join(x["motivos"])] for x in resultado["filas"]]
    cand = [[f, c["cuenta"], c["mla"], c["sku"], c["pm"], c["unidades"], c["precio_cobrado"], c["margen_real"] if c["margen_real"] is not None else "", c["ritmo_historico_dia"], c["link"]]
            for c in resultado["candidatas"]]
    return {"detalle": _agregar_sin_duplicar(_hoja(ss, TAB_MONITOREO, COLS_MONITOREO), COLS_MONITOREO, det, [0, 1, 2]),
            "candidatas": _agregar_sin_duplicar(_hoja(ss, TAB_CANDIDATAS, COLS_CANDIDATAS), COLS_CANDIDATAS, cand, [0, 1, 2])}
