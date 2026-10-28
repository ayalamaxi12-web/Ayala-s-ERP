"""Participar en una campaña de ML (ej. «Sumate al Cyber Monday») DESDE el ERP, sin subir otro Excel.

Dos pasos, los dos contra la API de promociones de ML (`/seller-promotions`):

1. `diagnosticar` — SOLO LECTURA. Busca la campaña en las promociones de la cuenta y, para unas pocas publicaciones, lee cómo la ve ML (estado, tipo,
   rangos de precio). Sirve para confirmar el tipo REAL de promoción que hay que mandar y que cada publicación sea candidata, antes de escribir.
2. `participar` — ESCRIBE en Mercado Libre: `POST /seller-promotions/items/{item}?app_version=v2` con `{promotion_id, promotion_type}` (+ `deal_price` solo si
   el precio se cambió respecto de la propuesta de ML). Una por una, con el resultado de cada fila; corta si fallan varias seguidas. El tipo que se manda es
   el que ML informa para esa campaña, nunca uno supuesto.

Contrato verificado solo parcialmente: ML no documenta públicamente el tipo «TIERS» del Excel; por eso el primer uso es una prueba de UNA publicación.
"""
from __future__ import annotations

import random
import threading
from datetime import date
from decimal import Decimal
from typing import Callable

from ml_ofertas import MLOfertasClient, MLOfertasEscritura

_jobs: dict[str, dict] = {}
CORTE_ERRORES_SEGUIDOS = 5
ESTADOS_ADENTRO = ("started", "pending", "active", "candidate_accepted")
# Tipos de promoción donde EL VENDEDOR fija el precio: ML exige `deal_price` en el alta (campañas tradicionales). En SMART / MARKETPLACE_CAMPAIGN (co-fondeadas)
# ML define el precio y `deal_price` no va, salvo que el usuario lo haya cambiado a propósito. Verificado en vivo (28/10/2026): el «TIERS» del Excel del Cyber
# es un DEAL en la API y la campaña «Ofertas compartidas» es SMART.
TIPOS_CON_PRECIO = ("DEAL", "SELLER_CAMPAIGN", "DOD", "LIGHTNING", "PRICE_DISCOUNT")


def estado_job(job_id: str) -> dict | None:
    return _jobs.get(job_id)


def _id_promo(p: dict):
    return p.get("promotion_id") or p.get("id")


def diagnosticar(ml: MLOfertasClient, cuenta: str, promos: dict[str, list[str]]) -> dict:
    """`promos`: `{promotion_id: [item_id de muestra, ...]}`. Solo lectura."""
    del_vendedor = {c.get("id"): c for c in ml.promociones_seller(cuenta) if c.get("id")}
    salida = []
    for pid, muestra in promos.items():
        c = del_vendedor.get(pid)
        info = {"promotion_id": pid, "listada_por_ml": c is not None, "tipo_api": (c or {}).get("type"), "nombre": (c or {}).get("name"),
                "estado": (c or {}).get("status"), "desde": (c or {}).get("start_date") or (c or {}).get("date_from"),
                "hasta": (c or {}).get("finish_date") or (c or {}).get("date_to") or (c or {}).get("end_date"), "muestras": [], "avisos": []}
        if c is None:
            info["avisos"].append("ML no lista esta campaña entre las promociones de la cuenta: no se puede participar desde acá (usá el Excel).")
        for item_id in muestra[:3]:
            try:
                entradas = [p for p in ml.promociones_item(item_id, cuenta) if _id_promo(p) == pid]
            except Exception as e:  # noqa: BLE001
                info["muestras"].append({"item_id": item_id, "error": str(e)})
                continue
            if not entradas:
                info["muestras"].append({"item_id": item_id, "candidata": False, "detalle": "ML no la muestra como candidata de esta campaña en esta cuenta"})
                info["avisos"].append(f"{item_id} no figura en la campaña para esta cuenta (¿es de la otra cuenta?).")
                continue
            e = entradas[0]
            info["muestras"].append({"item_id": item_id, "candidata": True, "estado": e.get("status"), "tipo": e.get("type"),
                                     "precio": e.get("price"), "precio_original": e.get("original_price"), "min": e.get("min_discounted_price"),
                                     "max": e.get("max_discounted_price"), "sugerido": e.get("suggested_discounted_price"), "campos": sorted(e.keys())})
            if c and e.get("type") and e.get("type") != c.get("type"):
                info["avisos"].append(f"El tipo de la publicación ({e.get('type')}) no coincide con el de la campaña ({c.get('type')}).")
        salida.append(info)
    return {"campanas": salida}


def _es_error(d: dict) -> str | None:
    if not isinstance(d, dict):
        return "Respuesta inesperada de ML"
    if d.get("error") or (isinstance(d.get("status"), int) and d["status"] >= 400):
        causas = "; ".join(str(c.get("message") or c) for c in (d.get("cause") or []) if c)
        return (d.get("message") or str(d.get("error"))) + (f" ({causas})" if causas else "")
    return None


def participar_una(ml: MLOfertasEscritura, cuenta: str, promotion_id: str, tipo: str, item_id: str, deal_price: float | None = None) -> dict:
    body = {"promotion_id": promotion_id, "promotion_type": tipo}
    if deal_price is not None:
        body["deal_price"] = float(Decimal(str(deal_price)).quantize(Decimal("0.01")))
    elif tipo in TIPOS_CON_PRECIO:
        return {"ok": False, "error": f"Esta campaña es de tipo {tipo}: ML exige el precio final y la fila no lo trae."}
    headers = {"Authorization": f"Bearer {ml._token(cuenta)}", "Content-Type": "application/json"}
    d = ml._post(f"https://api.mercadolibre.com/seller-promotions/items/{item_id}?app_version=v2", headers, body)
    err = _es_error(d)
    return {"ok": False, "error": err, "respuesta": d} if err else {"ok": True, "respuesta": d}


def _verificar(ml: MLOfertasClient, cuenta: str, promotion_id: str, item_id: str) -> str | None:
    """Estado de la publicación en la campaña según ML (lectura), o None si no aparece."""
    for p in ml.promociones_item(item_id, cuenta):
        if _id_promo(p) == promotion_id:
            return p.get("status")
    return None


def participar(ml: MLOfertasEscritura, cuenta: str, promotion_id: str, filas: list[dict], solo_probar: bool = False,
               progreso_cb: Callable[[int, int, str], None] | None = None, historial_cb: Callable[[list[dict]], None] | None = None,
               operador: str = "") -> dict:
    """`filas`: `[{item_id, sku?, deal_price?, cambiado?}]`. `deal_price` = precio final de la fila (el que propone ML o el que editó el usuario) y `cambiado` = lo editó el
    usuario. Primero resuelve el tipo real de la campaña: en tipos donde el vendedor fija el precio (DEAL…) el precio va siempre; en los demás (SMART…) solo si se cambió."""
    campana = next((c for c in ml.promociones_seller(cuenta) if c.get("id") == promotion_id), None)
    if not campana or not campana.get("type"):
        return {"resultados": [], "error": "ML no lista esta campaña entre las promociones de la cuenta: no se puede participar desde el ERP. Usá el Excel."}
    tipo, nombre = campana["type"], campana.get("name") or promotion_id
    lote = filas[:1] if solo_probar else filas
    resultados, historial, seguidos = [], [], 0
    for i, f in enumerate(lote, start=1):
        if progreso_cb:
            progreso_cb(i - 1, len(lote), f"Participando {f['item_id']}")
        if seguidos >= CORTE_ERRORES_SEGUIDOS:
            resultados.append({"item_id": f["item_id"], "estado": "pendiente", "mensaje": f"No se intentó: fallaron {CORTE_ERRORES_SEGUIDOS} seguidas, se cortó para no insistir."})
            continue
        try:
            precio = f.get("deal_price") if (tipo in TIPOS_CON_PRECIO or f.get("cambiado")) else None
            r = participar_una(ml, cuenta, promotion_id, tipo, f["item_id"], precio)
        except Exception as e:  # noqa: BLE001
            r = {"ok": False, "error": f"Error de red: {e}"}
        if r["ok"]:
            seguidos = 0
            res = {"item_id": f["item_id"], "estado": "ok", "mensaje": "Participa en la campaña."}
            if solo_probar:
                est = _verificar(ml, cuenta, promotion_id, f["item_id"])
                res["verificado"] = est
                res["mensaje"] = f"Participa en la campaña (ML la muestra como «{est}»)." if est else "ML respondió bien pero no la muestra en la campaña: revisá en ML antes de seguir."
                res["estado"] = "ok" if est else "dudosa"
            resultados.append(res)
            historial.append({"Fecha": date.today().isoformat(), "Cuenta": cuenta, "Item ID": f["item_id"], "SKU": f.get("sku", ""), "Accion": "Participar en campaña ML",
                              "Tipo/Promocion": f"{tipo} ({nombre})", "Precio Anterior": "", "Precio Nuevo": (f.get("deal_price") if (tipo in TIPOS_CON_PRECIO or f.get("cambiado")) else None) or "propuesta de ML",
                              "Operador": operador, "Origen": "Campañas ML"})
        else:
            seguidos += 1
            resultados.append({"item_id": f["item_id"], "estado": "error", "mensaje": r["error"]})
    ok = [x for x in resultados if x["estado"] == "ok"]
    if not solo_probar and ok:     # control por muestreo: ML muestra adentro a unas cuantas de las que dijo OK
        for x in random.sample(ok, min(5, len(ok))):
            try:
                x["verificado"] = _verificar(ml, cuenta, promotion_id, x["item_id"])
            except Exception:  # noqa: BLE001
                x["verificado"] = None
    if progreso_cb:
        progreso_cb(len(lote), len(lote), "Listo")
    aviso_h = None
    if historial and historial_cb:
        try:
            historial_cb(historial)
        except Exception as e:  # noqa: BLE001
            aviso_h = str(e)
    return {"resultados": resultados, "tipo_api": tipo, "campana": nombre, "solo_probar": solo_probar, "aviso_historial": aviso_h,
            "verificadas_por_muestreo": [{"item_id": x["item_id"], "estado_en_ml": x.get("verificado")} for x in ok if "verificado" in x] if not solo_probar else []}


def _job(job_id: str, fn: Callable[[Callable], dict]) -> None:
    _jobs[job_id] = {"status": "running", "progress": None, "result": None, "log": []}

    def _prog(a, t, label):
        _jobs[job_id]["progress"] = {"current": a, "total": t, "label": label}

    try:
        _jobs[job_id]["result"] = fn(_prog)
        _jobs[job_id]["status"] = "done"
    except Exception as e:  # noqa: BLE001
        _jobs[job_id]["status"] = "error"
        _jobs[job_id]["log"].append(f"Error: {e}")
    _jobs[job_id]["progress"] = None


def lanzar(job_id: str, fn: Callable[[Callable], dict]) -> None:
    threading.Thread(target=_job, args=(job_id, fn), daemon=True).start()
