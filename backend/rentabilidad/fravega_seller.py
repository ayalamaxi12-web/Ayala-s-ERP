"""Comisión y envío REALES de Frávega, orden por orden, desde el Seller Center («Estado de cuenta → Próxima liquidación»).

Ficha: `docs/markets/FRAVEGA.md`. Frávega muestra la comisión y el fee logístico de cada orden desde que se factura, sin esperar el
cierre de la quincena. Este módulo trae esa lista y la convierte al formato de `LiquidacionFravega`; la liquidación quincenal (Excel)
queda como conciliación final y SIEMPRE manda sobre estos valores (`persistencia.sincronizar_proxima_liquidacion`).

Autenticación: cookies de la sesión web (`X-SELLER-AUTH`, `X-FVG-SELLER-ID`, `X-SELLER-APP`) en variables de Railway
(`FRAVEGA_SELLER_AUTH`, `FRAVEGA_SELLER_ID`, `FRAVEGA_SELLER_APP`). Vencen: si Frávega responde 401/403 o redirige al login se avisa
(`SesionFravegaVencida`) y no se toca nada. Solo lectura del lado de Frávega.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Callable

URL_PROXIMA_LIQUIDACION = "https://seller-center.fravega.com/api/v1/seller-center-service/api/v1/settlement"
POR_PAGINA = 200
_COOKIES_ENV = {"X-SELLER-AUTH": "FRAVEGA_SELLER_AUTH", "X-FVG-SELLER-ID": "FRAVEGA_SELLER_ID", "X-SELLER-APP": "FRAVEGA_SELLER_APP"}
ESTADO_DEVUELTA = "Devuelta"


class SesionFravegaVencida(RuntimeError):
    """Frávega no aceptó la sesión (vencida o mal cargada): hay que renovar las cookies en Railway."""


class FravegaNoConfigurado(RuntimeError):
    """Faltan las variables FRAVEGA_SELLER_* en Railway."""


@dataclass(frozen=True)
class OrdenProximaLiquidacion:
    orden: str  # = venta_ecom.orden_externa (Ecom la guarda con el prefijo FVG-, ya quitado)
    estado: str
    fecha: date
    valor_sku: Decimal  # totalProductos
    comision: Decimal  # abs(totalComision), sin IVA
    fee_logistico: Decimal  # abs(totalFeeLogistico) + abs(totalEnvio): lo que Frávega cobra por el envío, sin IVA
    descuentos: Decimal
    neto: Decimal  # totalLiquidacion


def cookies_desde_env(env: dict | None = None) -> dict[str, str]:
    env = os.environ if env is None else env
    faltan = [v for v in _COOKIES_ENV.values() if not env.get(v)]
    if faltan:
        raise FravegaNoConfigurado("Faltan variables en Railway: " + ", ".join(faltan))
    return {cookie: env[var] for cookie, var in _COOKIES_ENV.items()}


def _get_real(url: str, params: dict, cookies: dict[str, str]):
    import requests

    return requests.get(url, params=params, headers={"Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items()), "Accept": "application/json"},
                        timeout=60, allow_redirects=False)


def _d(v) -> Decimal:
    return Decimal(str(v)) if v not in (None, "") else Decimal(0)


def _fecha(iso: str | None) -> date:
    # fechaVenta viene en UTC: la fecha de la venta es la de Argentina (UTC-3).
    from datetime import timedelta, timezone

    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(timezone(timedelta(hours=-3))).date()
    except ValueError:
        return date.today()


def traer_proxima_liquidacion(cookies: dict[str, str] | None = None, get_fn: Callable | None = None) -> list[OrdenProximaLiquidacion]:
    """Todas las órdenes de «Próxima liquidación» (el servidor ignora los filtros: se trae todo, 200 por página, y se pagina si hace falta)."""
    cookies = cookies if cookies is not None else cookies_desde_env()
    get = get_fn or _get_real
    items: list[dict] = []
    pagina = 1
    while True:
        r = get(URL_PROXIMA_LIQUIDACION, {"filter": json.dumps({"page": pagina, "perPage": POR_PAGINA, "sortField": "nroOrden", "sortOrder": "desc"}, separators=(",", ":"))}, cookies)
        if r.status_code in (301, 302, 303, 307, 308, 401, 403):
            raise SesionFravegaVencida("Frávega no aceptó la sesión del Seller Center (vencida): renová las cookies FRAVEGA_SELLER_* en Railway.")
        if r.status_code != 200:
            raise RuntimeError(f"Frávega respondió {r.status_code} al pedir la próxima liquidación.")
        try:
            d = r.json()
        except ValueError:
            raise SesionFravegaVencida("Frávega devolvió una página en vez de datos (la sesión probablemente venció).")
        lote = d.get("items") or []
        items.extend(lote)
        if not lote or len(items) >= int(d.get("totalCount") or 0):
            break
        pagina += 1
    ordenes: dict[str, OrdenProximaLiquidacion] = {}
    for it in items:
        nro = str(it.get("nroOrden") or "").strip()
        if not nro:
            continue
        ordenes[nro] = OrdenProximaLiquidacion(
            orden=nro, estado=str(it.get("estado") or ""), fecha=_fecha(it.get("fechaVenta")), valor_sku=_d(it.get("totalProductos")),
            comision=abs(_d(it.get("totalComision"))), fee_logistico=abs(_d(it.get("totalFeeLogistico"))) + abs(_d(it.get("totalEnvio"))),
            descuentos=abs(_d(it.get("totalDescuentos"))), neto=_d(it.get("totalLiquidacion")))
    return list(ordenes.values())
