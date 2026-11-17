"""Métricas de respuesta de Mercado Libre desde la API (solo lectura): PREGUNTAS de compradores y MENSAJES de posventa, agrupadas por mes.

Preguntas: `questions/search` (fecha de la pregunta, fecha de la respuesta, estado). Mensajes: por cada venta del rango, la conversación
`messages/packs/{pack}/sellers/{seller}`; el tiempo de respuesta es desde el primer mensaje del comprador hasta la primera respuesta del vendedor.
Los tiempos son corridos (24 h/7 días), no horario laboral. Un mes parcial al borde del rango se rotula igual: comparar meses completos.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from statistics import median
from typing import Callable

from ml_auth import SELLERS
from ml_full import MLFullClient, _sku_de_item
from ml_posventa import traer_ordenes

_jobs: dict[str, dict] = {}
MAX_PAGINAS = 200
MAX_CONVERSACIONES = 6000
HILOS = 6
MAX_DETALLE = 1500
TRAMOS_H = [(0.25, "Hasta 15 min"), (1, "15 min a 1 h"), (4, "1 a 4 h"), (24, "4 a 24 h"), (None, "Más de 24 h")]
DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
SIN_RESPUESTA = ("UNANSWERED", "CLOSED_UNANSWERED")


def estado_job(job_id: str) -> dict | None:
    return _jobs.get(job_id)


def _dt(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


def _horas(a: datetime | None, b: datetime | None) -> float | None:
    if not a or not b:
        return None
    return max((b - a).total_seconds() / 3600, 0.0)


def traer_preguntas(ml: MLFullClient, cuenta: str, desde: str, hasta: str) -> list[dict]:
    h = {"Authorization": f"Bearer {ml._token(cuenta)}"}
    out, offset = [], 0
    for _ in range(MAX_PAGINAS):
        d = ml._get("https://api.mercadolibre.com/questions/search", {
            "seller_id": SELLERS[cuenta], "sort_fields": "date_created", "sort_types": "DESC", "api_version": "4", "limit": 50, "offset": offset}, h) or {}
        filas = d.get("questions") or []
        out.extend(filas)
        offset += len(filas)
        if not filas or offset >= (d.get("total") or 0) or all((f.get("date_created") or "")[:10] < desde for f in filas):
            break
    return [q for q in out if desde <= (q.get("date_created") or "")[:10] <= hasta]


def _fecha_msg(m: dict) -> datetime | None:
    return _dt((m.get("message_date") or {}).get("created") or m.get("date_created"))


def conversacion(ml: MLFullClient, cuenta: str, pack_id: str) -> dict | None:
    """Resume una conversación de posventa: cuándo escribió el comprador por primera vez y cuándo respondió el vendedor."""
    h = {"Authorization": f"Bearer {ml._token(cuenta)}"}
    seller = SELLERS[cuenta]
    d = ml._get(f"https://api.mercadolibre.com/messages/packs/{pack_id}/sellers/{seller}", {"tag": "post_sale", "limit": 100}, h) or {}
    msgs = sorted((m for m in d.get("messages") or [] if _fecha_msg(m)), key=_fecha_msg)
    comp = [m for m in msgs if str((m.get("from") or {}).get("user_id")) != seller]
    if not comp:
        return None
    primero = _fecha_msg(comp[0])
    resp = next((m for m in msgs if str((m.get("from") or {}).get("user_id")) == seller and _fecha_msg(m) > primero), None)
    t = comp[0].get("text")
    texto = (t.get("plain") if isinstance(t, dict) else t) or ""
    return {"pack": str(pack_id), "inicio": primero.isoformat(), "mensajes_comprador": len(comp), "texto": texto[:240],
            "respuesta_h": _horas(primero, _fecha_msg(resp)) if resp else None}


def _texto(x) -> str:
    return ((x.get("plain") if isinstance(x, dict) else x) or "").strip()


def tramos(tiempos: list[float], sin_responder: int) -> list[dict]:
    """Cuántas se respondieron en cada franja de tiempo, más las que siguen sin respuesta."""
    cont = [0] * len(TRAMOS_H)
    for t in tiempos:
        for i, (tope, _) in enumerate(TRAMOS_H):
            if tope is None or t <= tope:
                cont[i] += 1
                break
    return [{"tramo": TRAMOS_H[i][1], "cantidad": cont[i]} for i in range(len(TRAMOS_H))] + [{"tramo": "Sin responder", "cantidad": sin_responder}]


def series(eventos: list[tuple[str, float | None]]) -> dict:
    """Series de (fecha-hora local, tiempo de respuesta en h o None): por día, por hora del día y por día de la semana."""
    def agrupar(clave):
        g: dict = {}
        for f, t in eventos:
            g.setdefault(clave(f), []).append(t)
        return g

    def fila(k, ts):
        v = [t for t in ts if t is not None]
        return {"clave": k, "cantidad": len(ts), "sin_responder": len(ts) - len(v), "mediana_h": round(median(v), 2) if v else None}
    por_dia = [fila(k, v) | {"fecha": k} for k, v in sorted(agrupar(lambda f: f[:10]).items())]
    por_hora = [fila(f"{h:02d}", agrupar(lambda f: f[11:13]).get(f"{h:02d}", [])) for h in range(24)]
    sem = agrupar(lambda f: date.fromisoformat(f[:10]).weekday())
    por_semana = [fila(DIAS[i], sem.get(i, [])) for i in range(7)]
    return {"por_dia": por_dia, "por_hora": por_hora, "por_dia_semana": por_semana}


def _resumen_tiempos(tiempos: list[float]) -> dict:
    return {"mediana_h": round(median(tiempos), 1) if tiempos else None, "promedio_h": round(sum(tiempos) / len(tiempos), 1) if tiempos else None,
            "pct_1h": round(sum(t <= 1 for t in tiempos) / len(tiempos) * 100, 1) if tiempos else None,
            "pct_24h": round(sum(t <= 24 for t in tiempos) / len(tiempos) * 100, 1) if tiempos else None}


def por_mes_preguntas(preguntas: list[dict]) -> list[dict]:
    meses: dict[str, list[dict]] = {}
    for q in preguntas:
        meses.setdefault((q.get("date_created") or "")[:7], []).append(q)
    out = []
    for mes in sorted(meses):
        qs = meses[mes]
        resp = [q for q in qs if q.get("answer") and (q["answer"].get("text") or q["answer"].get("date_created"))]
        tiempos = [t for q in resp if (t := _horas(_dt(q.get("date_created")), _dt(q["answer"].get("date_created")))) is not None]
        out.append({"mes": mes, "preguntas": len(qs), "respondidas": len(resp), "sin_responder": sum(1 for q in qs if q.get("status") in SIN_RESPUESTA),
                    "pct_respondidas": round(len(resp) / len(qs) * 100, 1), **_resumen_tiempos(tiempos)})
    return out


def por_mes_mensajes(convs: list[dict]) -> list[dict]:
    meses: dict[str, list[dict]] = {}
    for c in convs:
        meses.setdefault(c["inicio"][:7], []).append(c)
    out = []
    for mes in sorted(meses):
        cs = meses[mes]
        tiempos = [c["respuesta_h"] for c in cs if c["respuesta_h"] is not None]
        out.append({"mes": mes, "conversaciones": len(cs), "respondidas": len(tiempos), "sin_responder": len(cs) - len(tiempos),
                    "pct_respondidas": round(len(tiempos) / len(cs) * 100, 1), **_resumen_tiempos(tiempos)})
    return out


def detalle_preguntas(preguntas: list[dict], info_items: dict[str, dict]) -> list[dict]:
    out = []
    for q in sorted(preguntas, key=lambda x: x.get("date_created") or "", reverse=True)[:MAX_DETALLE]:
        a = q.get("answer") or {}
        resp = bool(a and (a.get("text") or a.get("date_created")))
        it = info_items.get(q.get("item_id") or "", {})
        out.append({"id": q.get("id"), "fecha": (q.get("date_created") or "")[:16].replace("T", " "), "item_id": q.get("item_id"), "titulo": it.get("titulo", ""), "sku": it.get("sku"),
                    "pregunta": _texto(q.get("text")), "respuesta": _texto(a.get("text")) if resp else "", "estado": q.get("status"),
                    "respuesta_h": round(_horas(_dt(q.get("date_created")), _dt(a.get("date_created"))), 2) if resp and _horas(_dt(q.get("date_created")), _dt(a.get("date_created"))) is not None else None})
    return out


def top_items(preguntas: list[dict], info_items: dict[str, dict], n: int = 30) -> list[dict]:
    g: dict[str, list[dict]] = {}
    for q in preguntas:
        if q.get("item_id"):
            g.setdefault(q["item_id"], []).append(q)
    out = []
    for i, qs in g.items():
        ts = [t for q in qs if q.get("answer") and (t := _horas(_dt(q.get("date_created")), _dt(q["answer"].get("date_created")))) is not None]
        it = info_items.get(i, {})
        out.append({"item_id": i, "titulo": it.get("titulo", ""), "sku": it.get("sku"), "preguntas": len(qs), "sin_responder": sum(1 for q in qs if q.get("status") in SIN_RESPUESTA),
                    "mediana_h": round(median(ts), 2) if ts else None})
    return sorted(out, key=lambda r: (-r["preguntas"], r["item_id"]))[:n]


def top_sin_responder(preguntas: list[dict], n: int = 20) -> list[dict]:
    cont: dict[str, int] = {}
    for q in preguntas:
        if q.get("status") in SIN_RESPUESTA and q.get("item_id"):
            cont[q["item_id"]] = cont.get(q["item_id"], 0) + 1
    return [{"item_id": k, "sin_responder": v} for k, v in sorted(cont.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]


def metricas_respuestas(ml: MLFullClient, cuenta: str, desde: str, hasta: str, con_mensajes: bool = True,
                        progreso_cb: Callable[[str], None] | None = None) -> dict:
    p = progreso_cb or (lambda t: None)
    p("Trayendo preguntas")
    preguntas = traer_preguntas(ml, cuenta, desde, hasta)
    p("Identificando publicaciones")
    ids = list(dict.fromkeys(q["item_id"] for q in preguntas if q.get("item_id")))[:800]
    info: dict[str, dict] = {}
    try:
        for b in ml.detalle_items(ids, cuenta):
            info[b.get("id")] = {"titulo": b.get("title", ""), "sku": _sku_de_item(b)}
    except Exception:  # noqa: BLE001  (sin títulos igual se muestra todo lo demás)
        pass
    tp = [t for q in preguntas if q.get("answer") and (t := _horas(_dt(q.get("date_created")), _dt(q["answer"].get("date_created")))) is not None]
    sin = sum(1 for q in preguntas if q.get("status") in SIN_RESPUESTA)
    ev = [((q.get("date_created") or "")[:19], _horas(_dt(q.get("date_created")), _dt((q.get("answer") or {}).get("date_created"))) if q.get("answer") else None) for q in preguntas if q.get("date_created")]
    r = {"cuenta": cuenta, "desde": desde, "hasta": hasta, "preguntas_por_mes": por_mes_preguntas(preguntas), "top_sin_responder": top_sin_responder(preguntas),
         "preguntas_total": {"preguntas": len(preguntas), "sin_responder": sin, "pct_respondidas": round((len(preguntas) - sin) / len(preguntas) * 100, 1) if preguntas else None, **_resumen_tiempos(tp)},
         "preguntas_tramos": tramos(tp, sin), "preguntas_series": series(ev), "preguntas_items": top_items(preguntas, info), "preguntas_detalle": detalle_preguntas(preguntas, info),
         "mensajes_por_mes": [], "mensajes_truncado": False}
    if con_mensajes:
        p("Trayendo ventas")
        packs: dict[str, str] = {}
        for o in traer_ordenes(ml, cuenta, desde, hasta):
            packs.setdefault(str(o.get("pack_id") or o.get("id")), str(o.get("id")))
        lista = list(packs)
        r["mensajes_truncado"] = len(lista) > MAX_CONVERSACIONES
        lista = lista[:MAX_CONVERSACIONES]
        hechas = [0]

        def leer(pk):
            try:
                c = conversacion(ml, cuenta, pk)
            except Exception:  # noqa: BLE001  (una conversación que falla no tira el resto)
                c = None
            hechas[0] += 1
            if hechas[0] % 50 == 0:
                p(f"Leyendo conversaciones {hechas[0]}/{len(lista)}")
            return c
        with ThreadPoolExecutor(HILOS) as ex:
            convs = [c for c in ex.map(leer, lista) if c]
        for c in convs:
            c["orden"] = packs.get(c["pack"])
        tm = [c["respuesta_h"] for c in convs if c["respuesta_h"] is not None]
        r["mensajes_por_mes"] = por_mes_mensajes(convs)
        r["mensajes_total"] = {"conversaciones": len(convs), "sin_responder": len(convs) - len(tm), "pct_respondidas": round(len(tm) / len(convs) * 100, 1) if convs else None, **_resumen_tiempos(tm)}
        r["mensajes_tramos"] = tramos(tm, len(convs) - len(tm))
        r["mensajes_series"] = series([(c["inicio"][:19], c["respuesta_h"]) for c in convs])
        r["mensajes_detalle"] = [{"fecha": c["inicio"][:16].replace("T", " "), "orden": c.get("orden"), "pack": c["pack"], "texto": c["texto"], "mensajes": c["mensajes_comprador"], "respuesta_h": None if c["respuesta_h"] is None else round(c["respuesta_h"], 2)}
                                 for c in sorted(convs, key=lambda c: c["inicio"], reverse=True)[:MAX_DETALLE]]
    return r


def iniciar_job(job_id: str, cuenta: str, desde: str, hasta: str, con_mensajes: bool = True, ml: MLFullClient | None = None) -> None:
    _jobs[job_id] = {"status": "running", "log": [f"Respuestas {cuenta} {desde} → {hasta}"], "result": None, "progress": None}
    try:
        res = metricas_respuestas(ml or MLFullClient(), cuenta, desde, hasta, con_mensajes,
                                  lambda t: _jobs[job_id].update(progress={"current": 0, "total": 1, "label": f"{t} ({cuenta})"}))
        _jobs[job_id].update(status="done", result=res, progress=None)
        _jobs[job_id]["log"].append("Listo.")
    except Exception as e:  # noqa: BLE001
        _jobs[job_id].update(status="error", progress=None)
        _jobs[job_id]["log"].append(f"Error: {e}")
