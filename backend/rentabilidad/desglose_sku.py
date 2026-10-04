"""Desglose por SKU de las ventas de Ecom — lo que leen los reportes por SKU
(diario, desvío de precios de Maca, agregación por PM/subcategoría/categoría).

Una orden de un combo, kit o carrito trae varios SKU, cada uno con SU precio.
Antes todo el importe de la orden se atribuía a la combinación de SKU (y al PM
del primero). Acá cada SKU recibe solo lo que le corresponde. **El total de la
orden no cambia**: `venta_ecom` sigue siendo la fuente del total, y la suma de
las líneas de una orden da siempre ese total (facturación, rentabilidad,
costo, envío).

Tres casos, de más a menos exacto:

1. **La orden tiene líneas guardadas** (`venta_ecom_linea`, de la API de Ecom):
   cada SKU toma SU precio, SU costo y SU clasificación. Lo que es de la orden
   completa — comisión, envío, impuestos y costo por operación, o sea
   `precio_sin_iva − neto` — se reparte en proporción al `precio_sin_iva` de
   cada línea. Se calcula al leer, a partir del `neto` y `costo_total` de la
   orden, así si la orden se recalcula (liquidación de Frávega) las líneas
   siguen cerrando.
2. **Sin líneas y un solo SKU**: la orden es de ese SKU, importe exacto.
3. **Sin líneas y varios SKU** (solo las órdenes viejas importadas de la
   planilla, `origen="importado_sheet"`, que nunca tuvieron detalle): se
   reparte el total en proporción al precio de lista del PM de cada SKU
   (`PricingSku.precio_web`; si falta alguno, en partes iguales) y se marca
   `prorrateado=True` para no confundirlo con un importe real. Se asume
   cantidad 1 por SKU (no hay dato); el PM/subcategoría/categoría de estas
   filas es el de la orden, porque sin la API no hay clasificación por SKU.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Query, Session, selectinload

from .models import VentaEcom
from .pricing_pm import norm_sku, vigentes

SIN_SKU = "(sin SKU)"
METODO_PRECIO_LISTA = "precio_lista_pm"
METODO_PARTES_IGUALES = "partes_iguales"


@dataclass
class LineaSku:
    """La parte de una orden que le corresponde a un SKU."""

    venta: VentaEcom
    sku: str  # SIN_SKU si la orden no trae ninguno
    cantidad: int | None  # None = no se sabe (prorrateado)
    precio_final: Decimal
    precio_sin_iva: Decimal
    costo_usd: Decimal  # costo vigente de la línea, USD
    costo_total: Decimal | None  # pesos, = costo_usd × TC
    rentabilidad: Decimal | None  # None = orden sin calcular (costo 0)
    comision_venta: Decimal
    costo_envio: Decimal
    factor_iva: Decimal | None
    pm: str | None
    subcategoria: str | None
    categoria: str | None
    item_ml: str | None
    permalink_ml: str | None
    prorrateado: bool = False
    metodo_prorrateo: str | None = None


def con_lineas(q: Query) -> Query:
    """Carga las líneas de las ventas en una sola consulta (evita 1 por orden)."""
    return q.options(selectinload(VentaEcom.lineas))


def _partes(pesos: list[Decimal]) -> list[Decimal]:
    total = sum(pesos, Decimal(0))
    if total <= 0:
        return [Decimal(1) / len(pesos)] * len(pesos)
    return [p / total for p in pesos]


def _por_partes(v: VentaEcom, parte: Decimal, base: dict) -> dict:
    return dict(
        precio_final=(v.precio_final or 0) * parte, precio_sin_iva=(v.precio_sin_iva or 0) * parte,
        costo_usd=(v.costo_sin_iva or 0) * parte,
        costo_total=None if v.costo_total is None else v.costo_total * parte,
        rentabilidad=None if v.rentabilidad is None else v.rentabilidad * parte,
        comision_venta=(v.comision_venta or 0) * parte, costo_envio=(v.costo_envio or 0) * parte,
        **base,
    )


def _desde_lineas_guardadas(v: VentaEcom) -> list[LineaSku]:
    ls = v.lineas
    # Reparto de lo que es de la orden entera: por precio sin IVA de la línea;
    # sin precio (Postventa, todo en cero) por costo; sin nada, en partes iguales.
    w_precio = [l.precio_sin_iva or Decimal(0) for l in ls]
    w_costo = [l.costo_sin_iva or Decimal(0) for l in ls]
    parte = _partes(w_precio if sum(w_precio) > 0 else w_costo)
    parte_costo = _partes(w_costo)
    cargos = None if v.neto is None else (v.precio_sin_iva or 0) - v.neto  # comisión+envío+imp.cheque+IIBB+operación
    res = []
    for l, p, pc in zip(ls, parte, parte_costo):
        costo_total = None if v.costo_total is None else v.costo_total * pc
        res.append(LineaSku(
            venta=v, sku=l.sku or SIN_SKU, cantidad=l.cantidad,
            precio_final=l.precio_final or Decimal(0), precio_sin_iva=l.precio_sin_iva or Decimal(0),
            costo_usd=l.costo_sin_iva or Decimal(0), costo_total=costo_total,
            rentabilidad=None if (v.rentabilidad is None or cargos is None or costo_total is None)
            else (l.precio_sin_iva or 0) - cargos * p - costo_total,
            comision_venta=(v.comision_venta or 0) * p, costo_envio=(v.costo_envio or 0) * p,
            factor_iva=l.factor_iva or v.iva, pm=l.pm, subcategoria=l.subcategoria, categoria=l.categoria,
            item_ml=l.item_ml, permalink_ml=l.permalink_ml,
        ))
    return res


class _PreciosLista:
    """Precio de lista (web) del PM de cada SKU, vigente a la fecha de la venta."""

    def __init__(self, db: Session):
        self.db, self.cache = db, {}

    def __call__(self, sku: str, fecha: date | None) -> Decimal | None:
        if fecha not in self.cache:
            self.cache[fecha] = vigentes(self.db, fecha)
        p = self.cache[fecha].get(norm_sku(sku))
        return p.precio_web if p and p.precio_web else None


def _sin_lineas(v: VentaEcom, precios: _PreciosLista) -> list[LineaSku]:
    skus = [s.strip() for s in (v.skus_vendidos or "").split(",") if s.strip()]
    base = dict(
        factor_iva=v.iva, pm=v.pm, subcategoria=v.subcategoria, categoria=v.categoria,
        item_ml=v.item_ml, permalink_ml=v.permalink_ml,
    )
    if len(skus) <= 1:
        return [LineaSku(venta=v, sku=skus[0] if skus else SIN_SKU, cantidad=v.unidades,
                         **_por_partes(v, Decimal(1), base))]
    lista = [precios(s, v.fecha_creacion_venta) for s in skus]
    if all(lista):
        partes, metodo = _partes(lista), METODO_PRECIO_LISTA
    else:
        partes, metodo = _partes([Decimal(1)] * len(skus)), METODO_PARTES_IGUALES
    return [
        LineaSku(venta=v, sku=s, cantidad=None, prorrateado=True, metodo_prorrateo=metodo,
                 **_por_partes(v, p, base))
        for s, p in zip(skus, partes)
    ]


def desglosar(db: Session, ventas: list[VentaEcom]) -> list[LineaSku]:
    """Una `LineaSku` por SKU de cada venta (ver el docstring del módulo)."""
    precios = _PreciosLista(db)
    res = []
    for v in ventas:
        res.extend(_desde_lineas_guardadas(v) if v.lineas else _sin_lineas(v, precios))
    return res
