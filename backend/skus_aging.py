"""Listado de SKUs de AGING (stock a liquidar): se definen en «Criterios de precio» y cada PM carga los suyos.

«Aging» no es la antigüedad de una venta: es una lista de SKUs que se venden a pérdida a propósito (se estaba esperando) y por eso su pérdida está contemplada.
Ventas y Rentabilidad usa esta lista para mostrar la rentabilidad general con y sin esos SKUs.
Se guarda como la configuración de Criterios (una «foto» JSON en la base propia, sin tabla nueva): cada cambio pide operador y queda en un historial.
Sin FastAPI ni red: recibe una sesión de SQLAlchemy.
"""
from __future__ import annotations

import re
import threading
from datetime import datetime, timezone

import ml_foto

MODULO_FOTO = "skus_aging"
CUENTA_FOTO = "global"
MAX_HISTORIAL = 1000
MAX_SKU = 80
_LOCK = threading.Lock()


class SkuAgingInvalido(ValueError):
    """Error que se le muestra a quien edita el listado (mensaje en castellano)."""


def clave(sku: str) -> str:
    """Misma idea que `normSku` del front: sin espacios y sin distinguir mayúsculas."""
    return re.sub(r"\s+", "", sku or "").lower()


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


def separar(texto) -> list[str]:
    """Acepta una lista o un texto con SKUs separados por salto de línea, coma, punto y coma o tabulación (el espacio NO separa: hay SKUs con espacio)."""
    partes = texto if isinstance(texto, list) else re.split(r"[\n\r,;\t]+", str(texto or ""))
    return [p.strip() for p in partes if p and p.strip()]


def leer(sesion_fn) -> dict:
    """{"skus": [{sku, pm, motivo, operador, cuando}], "historial": [...]}. Sin nada guardado: listas vacías."""
    try:
        with sesion_fn() as db:
            f = ml_foto.leer(db, MODULO_FOTO, CUENTA_FOTO, "")
            v = ml_foto.vista_foto(f)
    except Exception:  # noqa: BLE001 -- base caída: la pantalla sigue sin el listado
        return {"skus": [], "historial": [], "error": "No se pudo leer el listado"}
    p = (v.get("payload") or {}) if v.get("existe") else {}
    return {"skus": list(p.get("skus", [])), "historial": list(p.get("historial", []))}


def _guardar(sesion_fn, skus: list[dict], historial: list[dict]) -> None:
    payload = {"skus": skus, "historial": historial[-MAX_HISTORIAL:]}
    with sesion_fn() as db:
        ml_foto.guardar_exito(db, MODULO_FOTO, CUENTA_FOTO, "", payload, "completa", 0, 0, [])


def _operador(operador: str) -> str:
    op = (operador or "").strip()
    if not op:
        raise SkuAgingInvalido("Falta el operador: elegí quién hace el cambio.")
    return op[:40]


def agregar(sesion_fn, skus, pm: str, motivo: str, operador: str) -> dict:
    """Suma SKUs al listado de un PM. Un SKU ya cargado no se duplica (se informa de quién es). Devuelve {agregados, ya_estaban}."""
    op = _operador(operador)
    pm = (pm or "").strip()
    if not pm:
        raise SkuAgingInvalido("Falta el PM dueño de esos SKUs.")
    lista = separar(skus)
    if not lista:
        raise SkuAgingInvalido("Pegá al menos un SKU.")
    largos = [s for s in lista if len(s) > MAX_SKU]
    if largos:
        raise SkuAgingInvalido(f"SKU demasiado largo (máximo {MAX_SKU} caracteres): {largos[0][:30]}…")
    motivo = (motivo or "").strip()[:200]
    with _LOCK:
        actual = leer(sesion_fn)
        if actual.get("error"):
            raise SkuAgingInvalido(actual["error"])
        existentes = {clave(x["sku"]): x for x in actual["skus"]}
        agregados, ya = [], []
        ahora = _ahora()
        for s in lista:
            k = clave(s)
            if k in existentes:
                ya.append({"sku": existentes[k]["sku"], "pm": existentes[k]["pm"]})
                continue
            fila = {"sku": s, "pm": pm, "motivo": motivo, "operador": op, "cuando": ahora}
            actual["skus"].append(fila)
            existentes[k] = fila
            agregados.append(s)
            actual["historial"].append({"cuando": ahora, "operador": op, "accion": "agregar", "sku": s, "pm": pm, "motivo": motivo})
        if agregados:
            _guardar(sesion_fn, actual["skus"], actual["historial"])
    return {"agregados": agregados, "ya_estaban": ya}


def quitar(sesion_fn, sku: str, operador: str) -> dict:
    op = _operador(operador)
    k = clave(sku)
    if not k:
        raise SkuAgingInvalido("Falta el SKU a quitar.")
    with _LOCK:
        actual = leer(sesion_fn)
        if actual.get("error"):
            raise SkuAgingInvalido(actual["error"])
        quitado = next((x for x in actual["skus"] if clave(x["sku"]) == k), None)
        if quitado is None:
            raise SkuAgingInvalido("Ese SKU no está en el listado.")
        actual["skus"] = [x for x in actual["skus"] if clave(x["sku"]) != k]
        actual["historial"].append({"cuando": _ahora(), "operador": op, "accion": "quitar", "sku": quitado["sku"], "pm": quitado["pm"], "motivo": quitado.get("motivo", "")})
        _guardar(sesion_fn, actual["skus"], actual["historial"])
    return {"quitado": quitado["sku"], "pm": quitado["pm"]}
