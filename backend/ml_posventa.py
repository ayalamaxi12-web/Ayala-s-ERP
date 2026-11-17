"""Métricas de posventa de Mercado Libre desde la API (solo lectura), por cuenta y rango de fechas.

Fuentes: `orders/search` (ventas, canceladas, unidades), `post-purchase/v1/claims/search` (reclamos, mediaciones, devoluciones) y
`users/{id}` (reputación oficial de 60 días). Los reclamos se cuentan por FECHA DEL RECLAMO y las ventas por fecha de la venta del mismo rango,
así que la tasa del período es una referencia, no la tasa oficial de ML (esa es la de reputación).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime
from typing import Callable

from ml_auth import SELLERS
from ml_full import MLFullClient, _sku_de_item

_jobs: dict[str, dict] = {}
MAX_PAGINAS = 200
MAX_ORDENES_SUELTAS = 400

TIPOS = {"mediations": "Mediación", "returns": "Devolución", "fulfillment": "Full", "ml_case": "Caso ML", "cancel_purchase": "Cancelación de compra",
         "change": "Cambio", "service": "Servicio"}
ETAPAS = {"claim": "Reclamo", "dispute": "Disputa (mediación ML)", "recontact": "Recontacto", "none": "Sin etapa"}
ESTADOS = {"opened": "Abierto", "closed": "Cerrado"}
MOTIVOS = {"PNR": "Producto no recibido", "PDD": "Producto defectuoso o distinto", "CS": "Compra cancelada"}


def estado_job(job_id: str) -> dict | None:
    return _jobs.get(job_id)


def _dia(iso: str | None) -> str:
    return (iso or "")[:10]


def motivo_de(reason_id: str | None) -> str:
    r = (reason_id or "").upper()
    for pref, txt in MOTIVOS.items():
        if r.startswith(pref):
            return f"{txt} ({r})"
    return r or "Sin motivo"


def _paginar(ml: MLFullClient, url: str, params: dict, headers: dict, clave: str, parar=None) -> list[dict]:
    out: list[dict] = []
    offset = 0
    for _ in range(MAX_PAGINAS):
        d = ml._get(url, {**params, "offset": offset}, headers) or {}
        filas = d.get(clave) or []
        out.extend(filas)
        offset += len(filas)
        total = (d.get("paging") or {}).get("total", 0)
        if not filas or offset >= total or (parar and parar(filas)):
            break
    return out


def traer_ordenes(ml: MLFullClient, cuenta: str, desde: str, hasta: str) -> list[dict]:
    h = {"Authorization": f"Bearer {ml._token(cuenta)}"}
    return _paginar(ml, "https://api.mercadolibre.com/orders/search", {
        "seller": SELLERS[cuenta], "order.date_created.from": f"{desde}T00:00:00.000-03:00", "order.date_created.to": f"{hasta}T23:59:59.999-03:00",
        "sort": "date_desc", "limit": 50}, h, "results")


def traer_reclamos(ml: MLFullClient, cuenta: str, desde: str, hasta: str) -> list[dict]:
    """Reclamos creados entre `desde` y `hasta` (inclusive). ML rechazó (400) la búsqueda con `sort` y filtros de jugador, así que se prueba de la más específica a la
    más simple: la sesión es la de la cuenta vendedora y la API ya devuelve solo SUS reclamos. Sin orden garantizado se pagina todo y se filtra por fecha."""
    h = {"Authorization": f"Bearer {ml._token(cuenta)}"}
    url = "https://api.mercadolibre.com/post-purchase/v1/claims/search"
    variantes = [({"players.role": "respondent", "players.user_id": SELLERS[cuenta], "sort": "date_created:desc"}, True),
                 ({"players.role": "respondent", "players.user_id": SELLERS[cuenta]}, False), ({}, False)]
    ultimo: Exception | None = None
    for extra, ordenado in variantes:
        try:
            todos = _paginar(ml, url, {**extra, "limit": 50}, h, "data",
                             parar=(lambda filas: all(_dia(f.get("date_created")) < desde for f in filas)) if ordenado else None)
        except Exception as e:  # noqa: BLE001  (400 por un filtro no aceptado: se prueba la variante siguiente)
            ultimo = e
            continue
        return [c for c in todos if desde <= _dia(c.get("date_created")) <= hasta]
    raise ultimo or RuntimeError("no se pudo leer reclamos")


def reputacion(ml: MLFullClient, cuenta: str) -> dict:
    h = {"Authorization": f"Bearer {ml._token(cuenta)}"}
    u = ml._get(f"https://api.mercadolibre.com/users/{SELLERS[cuenta]}", {}, h) or {}
    rep = u.get("seller_reputation") or {}
    m = rep.get("metrics") or {}

    def met(k):
        x = m.get(k) or {}
        return {"tasa": x.get("rate"), "valor": x.get("value"), "excluidas": x.get("excluded")}
    return {"nivel": rep.get("level_id"), "medalla": rep.get("power_seller_status"), "periodo": (m.get("sales") or {}).get("period"),
            "ventas_completadas": (m.get("sales") or {}).get("completed"), "reclamos": met("claims"), "demoras": met("delayed_handling_time"),
            "cancelaciones": met("cancellations")}


def _items_orden(o: dict) -> list[dict]:
    out = []
    for oi in o.get("order_items") or []:
        it = oi.get("item") or {}
        out.append({"item_id": it.get("id"), "titulo": it.get("title", ""), "sku": _sku_de_item({**it, "seller_custom_field": it.get("seller_custom_field"),
                    "attributes": [{"id": "SELLER_SKU", "value_name": it.get("seller_sku")}] if it.get("seller_sku") else []}) or it.get("seller_sku") or it.get("seller_custom_field"),
                    "cantidad": oi.get("quantity") or 0})
    return out


def calcular(ordenes: list[dict], reclamos: list[dict], orden_suelta: Callable[[str], dict | None] | None = None) -> dict:
    pagadas = [o for o in ordenes if o.get("status") == "paid"]
    canceladas = [o for o in ordenes if o.get("status") == "cancelled"]
    por_orden = {str(o.get("id")): _items_orden(o) for o in ordenes}
    unidades = sum(i["cantidad"] for o in pagadas for i in por_orden[str(o.get("id"))])
    sueltas = 0
    filas, por_sku = [], defaultdict(lambda: {"sku": None, "titulo": "", "reclamos": 0, "unidades_vendidas": 0})
    for o in pagadas:
        for i in por_orden[str(o.get("id"))]:
            r = por_sku[i["item_id"]]
            r["sku"], r["titulo"] = i["sku"], i["titulo"]
            r["unidades_vendidas"] += i["cantidad"]
    for c in reclamos:
        oid = str(c.get("resource_id")) if c.get("resource") in (None, "order") else None
        items = por_orden.get(oid) if oid else None
        if items is None and oid and orden_suelta and sueltas < MAX_ORDENES_SUELTAS:
            sueltas += 1
            o = orden_suelta(oid)
            items = _items_orden(o) if o else None
        items = items or []
        res = c.get("resolution") or {}
        filas.append({"id": c.get("id"), "fecha": _dia(c.get("date_created")), "cierre": _dia(res.get("date_created")), "orden": oid, "tipo": TIPOS.get(c.get("type"), c.get("type")),
                      "etapa": ETAPAS.get(c.get("stage"), c.get("stage")), "estado": ESTADOS.get(c.get("status"), c.get("status")),
                      "motivo": motivo_de(c.get("reason_id")), "resolucion": res.get("reason") or "", "beneficiado": res.get("benefited") or "",
                      "item_id": items[0]["item_id"] if items else None, "sku": items[0]["sku"] if items else None, "titulo": items[0]["titulo"] if items else ""})
        for i in items:
            r = por_sku[i["item_id"]]
            r["sku"], r["titulo"] = r["sku"] or i["sku"], r["titulo"] or i["titulo"]
            r["reclamos"] += 1
    cont = lambda k: [{"clave": a, "cantidad": b} for a, b in Counter(f[k] for f in filas).most_common()]
    ranking = sorted(({"item_id": k, **v, "tasa": round(v["reclamos"] / v["unidades_vendidas"] * 100, 1) if v["unidades_vendidas"] else None}
                      for k, v in por_sku.items() if v["reclamos"]), key=lambda r: (-r["reclamos"], r["item_id"] or ""))
    dias = Counter(f["fecha"] for f in filas)
    n = len(pagadas)
    return {"resumen": {"ordenes": len(ordenes), "ventas_pagadas": n, "unidades": unidades, "canceladas": len(canceladas),
                        "tasa_cancelacion": round(len(canceladas) / len(ordenes) * 100, 2) if ordenes else None,
                        "reclamos": len(filas), "abiertos": sum(1 for f in filas if f["estado"] == "Abierto"),
                        "mediaciones": sum(1 for f in filas if f["etapa"].startswith("Disputa")),
                        "devoluciones": sum(1 for f in filas if f["tipo"] == "Devolución"),
                        "tasa_reclamos": round(len(filas) / n * 100, 2) if n else None},
            "por_motivo": cont("motivo"), "por_tipo": cont("tipo"), "por_etapa": cont("etapa"), "por_estado": cont("estado"),
            "por_dia": [{"fecha": d, "reclamos": q} for d, q in sorted(dias.items())], "ranking_sku": ranking[:100], "reclamos": filas}


def metricas_posventa(ml: MLFullClient, cuenta: str, desde: str, hasta: str, progreso_cb: Callable[[str], None] | None = None) -> dict:
    p = progreso_cb or (lambda t: None)
    p("Trayendo ventas")
    ordenes = traer_ordenes(ml, cuenta, desde, hasta)
    p("Trayendo reclamos")
    reclamos = traer_reclamos(ml, cuenta, desde, hasta)
    h = {"Authorization": f"Bearer {ml._token(cuenta)}"}
    p("Identificando publicaciones")
    r = calcular(ordenes, reclamos, lambda oid: ml._get(f"https://api.mercadolibre.com/orders/{oid}", {}, h))
    p("Reputación")
    try:
        r["reputacion"] = reputacion(ml, cuenta)
    except Exception:  # noqa: BLE001
        r["reputacion"] = None
    r.update(cuenta=cuenta, desde=desde, hasta=hasta)
    return r


def iniciar_job(job_id: str, cuenta: str, desde: str, hasta: str, ml: MLFullClient | None = None) -> None:
    _jobs[job_id] = {"status": "running", "log": [f"Posventa {cuenta} {desde} → {hasta}"], "result": None, "progress": None}
    try:
        res = metricas_posventa(ml or MLFullClient(), cuenta, desde, hasta,
                                lambda t: _jobs[job_id].update(progress={"current": 0, "total": 1, "label": f"{t} ({cuenta})"}))
        _jobs[job_id].update(status="done", result=res, progress=None)
        _jobs[job_id]["log"].append(f"Listo: {res['resumen']['reclamos']} reclamos sobre {res['resumen']['ventas_pagadas']} ventas.")
    except Exception as e:  # noqa: BLE001
        _jobs[job_id].update(status="error", progress=None)
        _jobs[job_id]["log"].append(f"Error: {e}")
