"""Métricas de respuesta de Mercado Libre desde la API (solo lectura): PREGUNTAS de compradores y MENSAJES de posventa, agrupadas por mes.

Preguntas: `questions/search` (fecha de la pregunta, fecha de la respuesta, estado). Mensajes: por cada venta del rango, la conversación
`messages/packs/{pack}/sellers/{seller}`; el tiempo de respuesta es desde el primer mensaje del comprador hasta la primera respuesta del vendedor.
Los tiempos son corridos (24 h/7 días), no horario laboral. Un mes parcial al borde del rango se rotula igual: comparar meses completos.
"""
from __future__ import annotations

from datetime import datetime
from statistics import median
from typing import Callable

from ml_auth import SELLERS
from ml_full import MLFullClient
from ml_posventa import traer_ordenes

_jobs: dict[str, dict] = {}
MAX_PAGINAS = 200
MAX_CONVERSACIONES = 2500
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
    return {"pack": str(pack_id), "inicio": primero.isoformat(), "mensajes_comprador": len(comp),
            "respuesta_h": _horas(primero, _fecha_msg(resp)) if resp else None}


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
    r = {"cuenta": cuenta, "desde": desde, "hasta": hasta, "preguntas_por_mes": por_mes_preguntas(preguntas), "top_sin_responder": top_sin_responder(preguntas),
         "mensajes_por_mes": [], "mensajes_truncado": False}
    if con_mensajes:
        p("Trayendo ventas")
        packs = list(dict.fromkeys(str(o.get("pack_id") or o.get("id")) for o in traer_ordenes(ml, cuenta, desde, hasta)))
        r["mensajes_truncado"] = len(packs) > MAX_CONVERSACIONES
        convs = []
        for i, pk in enumerate(packs[:MAX_CONVERSACIONES]):
            if i % 25 == 0:
                p(f"Leyendo conversaciones {i}/{min(len(packs), MAX_CONVERSACIONES)}")
            try:
                c = conversacion(ml, cuenta, pk)
            except Exception:  # noqa: BLE001  (una conversación que falla no tira el resto)
                c = None
            if c:
                convs.append(c)
        r["mensajes_por_mes"] = por_mes_mensajes(convs)
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
