"""Candidatos a Full: publicaciones activas que venden bien y todavía NO son de Full (solo lectura).

Igual que «Candidatos a oferta»: el usuario elige cuántos días mirar y cuántas ventas mínimas, por cuenta. Una publicación es candidata si
está activa, tiene stock propio, NO es `fulfillment` y vendió al menos `min_ventas` unidades (ventas pagadas, sea cual sea el envío) en los
últimos `dias_ventas` días. No chequea la elegibilidad de ML para Full (peso/tamaño/categoría): eso lo valida ML al armar el envío.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Callable

from ml_full import MLFullClient, _sku_de_item
from ml_ofertas import ventas_por_item

_jobs: dict[str, dict] = {}

TIPOS_ENVIO = {
    "cross_docking": "Colecta", "xd_drop_off": "Colecta + sucursal", "drop_off": "Sucursal", "self_service": "Flex",
    "default": "Acordar con el comprador", "custom": "Propio",
}


def estado_job(job_id: str) -> dict | None:
    return _jobs.get(job_id)


def detectar_candidatos_full(
    ml: MLFullClient, cuenta: str, dias_ventas: int = 30, min_ventas: int = 5, hoy: date | None = None,
    progreso_cb: Callable[[int, int, str], None] | None = None,
) -> list[dict]:
    hoy = hoy or date.today()
    desde = f"{(hoy - timedelta(days=dias_ventas)).isoformat()}T00:00:00.000-00:00"
    hasta = f"{hoy.isoformat()}T23:00:00.000-00:00"
    if progreso_cb:
        progreso_cb(0, 1, "ventas")
    ventas = ventas_por_item(ml, cuenta, desde, hasta)
    ids = [i for i in ml.items_activos(cuenta) if ventas.get(i, 0) >= min_ventas]
    out: list[dict] = []
    headers = {"Authorization": f"Bearer {ml._token(cuenta)}"}
    for i in range(0, len(ids), 20):
        if progreso_cb:
            progreso_cb(i, len(ids), "candidatos")
        d = ml._get("https://api.mercadolibre.com/items", {
            "ids": ",".join(ids[i:i + 20]),
            "attributes": "id,title,permalink,seller_custom_field,available_quantity,attributes,shipping,status"}, headers)
        for e in (d or []):
            it = e.get("body") if isinstance(e, dict) and "body" in e else e
            if not it:
                continue
            tipo = (it.get("shipping") or {}).get("logistic_type")
            stock = it.get("available_quantity") or 0
            if tipo == "fulfillment" or stock <= 0 or it.get("status") not in (None, "active"):
                continue
            v = ventas.get(it["id"], 0)
            out.append({"item_id": it["id"], "cuenta": cuenta, "sku": _sku_de_item(it), "titulo": it.get("title", ""), "permalink": it.get("permalink"),
                        "ventas_periodo": v, "por_dia": round(v / max(dias_ventas, 1), 2), "stock": stock, "envio": TIPOS_ENVIO.get(tipo, tipo or "")})
    if progreso_cb:
        progreso_cb(len(ids), max(len(ids), 1), "candidatos")
    return sorted(out, key=lambda c: -c["ventas_periodo"])


def iniciar_job(job_id: str, cuenta: str, dias_ventas: int = 30, min_ventas: int = 5, ml: MLFullClient | None = None) -> None:
    _jobs[job_id] = {"status": "running", "log": [f"Buscando candidatos a Full ({cuenta})..."], "result": None, "progress": None}

    def _prog(a, t, fase):
        _jobs[job_id]["progress"] = {"current": a, "total": t, "label": ("Trayendo ventas" if fase == "ventas" else "Mirando las publicaciones") + f" ({cuenta})"}

    try:
        c = detectar_candidatos_full(ml or MLFullClient(), cuenta, dias_ventas, min_ventas, progreso_cb=_prog)
        _jobs[job_id].update(status="done", result={"candidatos": c}, progress=None)
        _jobs[job_id]["log"].append(f"Listo: {len(c)} candidatos.")
    except Exception as e:  # noqa: BLE001
        _jobs[job_id].update(status="error", progress=None)
        _jobs[job_id]["log"].append(f"Error: {e}")
