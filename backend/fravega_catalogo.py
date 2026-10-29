"""Catálogo de Frávega (Seller Center): leer publicaciones con precio de lista/venta, stock y plan de cuotas, y cambiar precio y plan.

Ficha: `docs/markets/FRAVEGA.md` §7. Es la API INTERNA del portal (la que usa su front, con la sesión del navegador): puede cambiar sin aviso.
La API oficial (developers.fravega.io) todavía no se leyó. Las llamadas de escritura salen del código del front y NO se probaron en vivo:
por eso están apagadas salvo `FRAVEGA_ESCRITURA=1` en Railway y el alta se prueba primero con UNA publicación y se verifica releyéndola.

Autenticación: las mismas cookies de `rentabilidad.fravega_seller` (`FRAVEGA_SELLER_*`). Primero se pide solo con cookies; si Frávega responde
401/403 se reintenta mandando también el header `authorization` con el valor de `X-SELLER-AUTH`.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable

from rentabilidad.fravega_seller import SesionFravegaVencida, cookies_desde_env

URL_BASE = "https://seller-center.fravega.com/api/v1/seller-center-service/api"
POR_PAGINA = 25      # el portal pide de a 10; 100 hacía fallar a Frávega con un 500 de su base (mongo.CommandError)
MAX_PAGINAS = 100


class EscrituraApagada(RuntimeError):
    """`FRAVEGA_ESCRITURA` no está en 1: el módulo lee pero no escribe en Frávega."""


class FravegaRechazo(RuntimeError):
    """Frávega respondió pero rechazó el cambio (409 parcial, validación, etc.). `campos` trae lo que informó."""

    def __init__(self, mensaje: str, campos: dict | None = None):
        super().__init__(mensaje)
        self.campos = campos or {}


def escritura_habilitada(env: dict | None = None) -> bool:
    return (os.environ if env is None else env).get("FRAVEGA_ESCRITURA") == "1"


def _headers(cookies: dict[str, str], con_authorization: bool) -> dict[str, str]:
    h = {"Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items()), "Accept": "application/json", "Content-Type": "application/json"}
    if cookies.get("X-FVG-SELLER-ID"):
        h["x-fvg-seller-id"] = cookies["X-FVG-SELLER-ID"]
    if con_authorization and cookies.get("X-SELLER-AUTH"):
        a = cookies["X-SELLER-AUTH"]
        h["authorization"] = a if a.lower().startswith("bearer ") else "Bearer " + a
    return h


def _pedir_real(metodo: str, url: str, params: dict | None, cuerpo: dict | None, headers: dict):
    import requests

    return requests.request(metodo, url, params=params, json=cuerpo, headers=headers, timeout=60, allow_redirects=False)


def _pedir(metodo: str, ruta: str, cookies: dict[str, str], params: dict | None = None, cuerpo: dict | None = None,
           request_fn: Callable | None = None):
    """Devuelve la respuesta (`.status_code`, `.json()`); levanta `SesionFravegaVencida` si Frávega no acepta la sesión."""
    pedir = request_fn or _pedir_real
    estados = []
    for con_auth in (False, True):
        r = pedir(metodo, URL_BASE + ruta, params, cuerpo, _headers(cookies, con_auth))
        if r.status_code not in (301, 302, 303, 307, 308, 401, 403, 503):
            return r
        estados.append(f"{'con' if con_auth else 'sin'} authorization: {r.status_code}")
    raise SesionFravegaVencida("Frávega no aceptó la sesión del Seller Center (vencida o mal cargada): renová las cookies FRAVEGA_SELLER_* en Railway "
                               f"({'; '.join(estados)}).")


def _num(v) -> Decimal | None:
    try:
        return Decimal(str(v)) if v not in (None, "") else None
    except Exception:  # noqa: BLE001
        return None


def cuotas_de_plan(nombre: str | None) -> str | None:
    """«IMPORTADOS: 6 cuotas sin interés v6» → '6' (la clave de los planes de `pricing_cuotas` para FRAVEGA)."""
    m = re.search(r"(\d+)\s*cuotas", nombre or "", re.I)
    return m.group(1) if m else None


def normalizar_item(it: dict) -> dict:
    precio, stock = it.get("price") or {}, it.get("stock") or {}
    asoc = it.get("associatedPlan") or {}
    plan = asoc.get("plan") or {}
    return {
        "id": it.get("id"), "sku_fravega": it.get("sku"), "ref_id": (it.get("refId") or "").strip(), "titulo": it.get("title"),
        "activo": bool(it.get("active")), "estado": it.get("itemState"), "estado_msg": (it.get("status") or {}).get("message"),
        "lista": _num(precio.get("list")), "venta": _num(precio.get("sale")), "neto": _num(precio.get("net")),
        "stock": int(stock.get("quantity") or 0), "origen": it.get("origin"),
        "plan": {"id": plan.get("_id"), "nombre": plan.get("name"), "comision": _num(plan.get("commission")), "cuotas": cuotas_de_plan(plan.get("name")),
                 "desde": asoc.get("from"), "hasta": asoc.get("to")} if plan else None,
        "_plan_completo": plan or None,
    }


def _detalle(r) -> str:
    t = (getattr(r, "text", "") or "")[:200].replace("\n", " ")
    return f": {t}" if t else ""


def traer_items(cookies: dict[str, str] | None = None, request_fn: Callable | None = None) -> list[dict]:
    cookies = cookies if cookies is not None else cookies_desde_env()
    out: list[dict] = []
    tamanos = [POR_PAGINA, 10]                # si Frávega rechaza un tamaño de página (400/422/500), se reintenta con el que usa el portal
    pagina = 1
    while pagina <= MAX_PAGINAS:
        r = _pedir("GET", "/v2/item", cookies, {"page": pagina, "size": tamanos[0]}, None, request_fn)
        if r.status_code in (400, 422, 500) and len(tamanos) > 1 and pagina == 1:
            tamanos.pop(0)
            continue
        if r.status_code != 200:
            raise RuntimeError(f"Frávega respondió {r.status_code} al pedir el listado de productos (página {pagina}){_detalle(r)}")
        try:
            d = r.json()
        except ValueError:
            raise SesionFravegaVencida("Frávega devolvió una página en vez de datos (la sesión probablemente venció).")
        lote = d.get("items") or []
        out.extend(normalizar_item(i) for i in lote)
        if not lote or pagina >= int(d.get("totalPages") or 1):
            break
        pagina += 1
    return out


def planes_en_uso(items: list[dict]) -> list[dict]:
    """Planes que hoy tienen publicaciones (con el objeto completo que Frávega pide para asignar uno)."""
    vistos: dict[str, dict] = {}
    for i in items:
        p = i.get("_plan_completo")
        if p and p.get("_id") and p["_id"] not in vistos:
            vistos[p["_id"]] = p
    return sorted(vistos.values(), key=lambda p: int(cuotas_de_plan(p.get("name")) or 0))


def _exigir_escritura():
    if not escritura_habilitada():
        raise EscrituraApagada("La escritura en Frávega está apagada: poné FRAVEGA_ESCRITURA=1 en Railway para activarla.")


def validar_precios(lista: Decimal, venta: Decimal) -> None:
    if lista <= 0 or venta <= 0:
        raise ValueError("El precio de lista y el de venta tienen que ser mayores a 0.")
    if venta > lista:
        raise ValueError("El precio de venta no puede superar al de lista (tachado).")


def poner_precio(item_id: str, lista: Decimal, venta: Decimal, neto: Decimal, cookies: dict[str, str] | None = None,
                 request_fn: Callable | None = None) -> None:
    """`PUT /v1/item/{id}/partial` con `{price:{list,sale,net}}` (botón «Editar valores» del portal). 409 = rechazo parcial."""
    _exigir_escritura()
    validar_precios(lista, venta)
    cookies = cookies if cookies is not None else cookies_desde_env()
    cuerpo = {"price": {"list": float(lista), "sale": float(venta), "net": float(neto)}}
    r = _pedir("PUT", f"/v1/item/{item_id}/partial", cookies, None, cuerpo, request_fn)
    _revisar_escritura(r, cuerpo)


def poner_plan(item_id: str, plan: dict, desde: datetime | None = None, cookies: dict[str, str] | None = None,
               request_fn: Callable | None = None) -> None:
    """`POST /v1/item/{id}/plan` con el plan completo y su vigencia (paso «Financiación» de Editar producto)."""
    _exigir_escritura()
    if not plan or not plan.get("_id"):
        raise ValueError("Falta el plan (objeto completo de Frávega).")
    cookies = cookies if cookies is not None else cookies_desde_env()
    desde = desde or datetime.now(timezone.utc)
    hasta = (plan.get("validity") or {}).get("expiration")
    cuerpo = {"plan": plan, "from": desde.strftime("%Y-%m-%dT%H:%M:%SZ"), "to": hasta}
    r = _pedir("POST", f"/v1/item/{item_id}/plan", cookies, None, cuerpo, request_fn)
    _revisar_escritura(r, {"plan": {"_id": plan.get("_id"), "name": plan.get("name")}, "from": cuerpo["from"], "to": cuerpo["to"]})


def _revisar_escritura(r, enviado: dict | None = None) -> None:
    if r.status_code in (200, 201, 204):
        return
    try:
        d = r.json()
    except ValueError:
        d = {}
    d = d if isinstance(d, dict) else {}
    campos = ((d.get("error") or {}).get("fields")) if isinstance(d.get("error"), dict) else None
    texto = d.get("message") or d.get("error") or (getattr(r, "text", "") or "")[:300].replace("\n", " ") or "sin detalle"
    raise FravegaRechazo(f"Frávega rechazó el cambio ({r.status_code}): {texto}" + (f" · enviado: {json.dumps(enviado, default=str)[:300]}" if enviado else ""), campos or {})


def releer_item(item_id: str, cookies: dict[str, str] | None = None, request_fn: Callable | None = None) -> dict | None:
    cookies = cookies if cookies is not None else cookies_desde_env()
    r = _pedir("GET", f"/v2/item/{item_id}", cookies, None, None, request_fn)
    if r.status_code != 200:
        return None
    try:
        return normalizar_item(r.json())
    except ValueError:
        return None
