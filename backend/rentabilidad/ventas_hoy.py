"""«Ventas de hoy»: lo cobrado en el día, en vivo, por canal. **Solo lectura**: no guarda nada.

Mismo criterio que la rentabilidad y el reporte diario (`reporte_diario`):
- Órdenes **cobradas** (estado de pago Cobrado o Cobro Parcial: lo filtra la ingesta de Ecom), con fecha de CREACIÓN hoy (hora Argentina, desde las 00:00).
- Se excluyen las filas marcadas `excluido` (notas de débito, fixture, envíos, SKU auxiliares).
- facturación = Σ Precio Final (con IVA); también sin IVA. Rentabilidad % = rentabilidad $ / facturación sin IVA.
- SKU = los SKU de la orden tal como están en `skus_vendidos`: una orden de un solo SKU cuenta para ese SKU; un kit o carrito cuenta como esa combinación
  (no hay importe por línea).
- Las órdenes con costo 0 (sin calcular) suman facturación pero no rentabilidad; se cuentan en `sin_costo`.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from .models import VentaEcom
from .reporte_diario import _n, _por_sku, _totales

_ZONA_ARGENTINA = timezone(timedelta(hours=-3))
TOP_DEFAULT = 5

# (clave, etiqueta, prefijos del `canal_de_venta` en minúsculas). El orden es el de las tarjetas.
CANALES = (
    ("ml", "Mercado Libre", ("mercadolibre", "mercado libre")),
    ("web", "Web", ("woocommerce", "web")),
    ("fravega", "Frávega", ("fravega", "frávega")),
    ("oncity", "OnCity", ("oncity",)),
    ("megatone", "Megatone", ("megatone",)),
)
SIEMPRE = ("ml", "web", "fravega")      # estas tarjetas se muestran aunque todavía no haya ventas


def hoy_en_argentina(ahora: datetime | None = None) -> date:
    ahora = ahora or datetime.now(timezone.utc)
    return ahora.astimezone(_ZONA_ARGENTINA).date()


def canal_de(canal_de_venta: str | None) -> str:
    c = (canal_de_venta or "").strip().lower()
    for clave, _etq, prefijos in CANALES:
        if any(c.startswith(p) for p in prefijos):
            return clave
    return "otros"


def _tarjeta(clave: str, etiqueta: str, ventas: list[VentaEcom], top: int) -> dict:
    t = _totales(ventas)
    top_skus = sorted(_por_sku(ventas), key=lambda x: -x["facturacion"])[:top]
    sin_iva_por_sku: dict[str, Decimal] = {}
    for v in ventas:
        k = (v.skus_vendidos or "").strip() or "(sin SKU)"
        sin_iva_por_sku[k] = sin_iva_por_sku.get(k, Decimal(0)) + (v.precio_sin_iva or 0)
    for x in top_skus:
        x["facturacion_sin_iva"] = _n(sin_iva_por_sku.get(x["sku"], 0))
    return {"clave": clave, "etiqueta": etiqueta, **t, "sin_costo": sum(1 for v in ventas if not v.costo_sin_iva), "top_skus": top_skus}


def armar_ventas_hoy(ventas: list[VentaEcom], dia: date, top: int = TOP_DEFAULT) -> dict:
    """`ventas`: las filas ya calculadas por el motor (cobradas). Devuelve el total y una tarjeta por canal."""
    del_dia = [v for v in ventas if not v.excluido and v.fecha_creacion_venta == dia]
    grupos: dict[str, list[VentaEcom]] = {}
    for v in del_dia:
        grupos.setdefault(canal_de(v.canal_de_venta), []).append(v)
    tarjetas = [_tarjeta("total", "Total", del_dia, top)]
    for clave, etiqueta, _p in CANALES:
        if clave in grupos or clave in SIEMPRE:
            tarjetas.append(_tarjeta(clave, etiqueta, grupos.get(clave, []), top))
    if "otros" in grupos:
        tarjetas.append(_tarjeta("otros", "Otros canales", grupos["otros"], top))
    return {"fecha": dia.isoformat(), "tarjetas": tarjetas}
