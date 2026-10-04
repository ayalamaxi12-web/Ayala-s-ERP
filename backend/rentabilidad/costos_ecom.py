"""Catálogo de costos de Ecom por SKU — FUENTE PRIMARIA de costo del ERP.

Decisión de Maxx (2026-10, ajuste a CRITERIOS_MARGEN.md §7): el costo del
producto sale de Ecom (módulo Artículos / Editar Artículos, donde se crean los
SKU y se les pone el costo), no de Táctica — Táctica vive en el servidor de la
oficina y se cae con la VPN. Táctica queda para CRUZAR (`cruzar_costos`): cuando
hay diferencia entre las dos fuentes, se informa.

Origen: GraphQL de Ecom, `products.find` paginado (30 por página, ~115 páginas
y ~80 s para los ~3.400 artículos), `Variant.cost` en USD — el mismo campo que
ya usa la ingesta de ventas (`ingesta_ecom_api`). Como bajar todo cuesta
~80 s, el catálogo se cachea en el proceso (`obtener_catalogo`, TTL 1 h) y si
el refresco falla se sigue con el último catálogo bueno.

Producto con varias variantes: el SKU es del producto y cada variante trae su
propio costo. Si todas valen lo mismo, ese es el costo; si difieren y la
variante no tiene SKU propio, el costo del SKU es AMBIGUO — no se elige uno al
azar (queda en `ambiguos`, `obtener` devuelve None). Costo 0 = sin costo, igual
que en Táctica.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable

from .ingesta_ecom_api import EcomApiClient

_QUERY_CATALOGO = """
query CatalogoCostos($page: Int) {
  products {
    find(page: $page) {
      pageInfo { page pageCount }
      data { sku tax variants { sku cost } }
    }
  }
}
"""

_TTL_SEGUNDOS = 3600
_REINTENTOS_PAGINA = 3
_MAX_PAGINAS = 1000  # tope de seguridad contra un paginado que no termina


class CatalogoEcomError(RuntimeError):
    pass


@dataclass
class CatalogoCostos:
    costos: dict[str, Decimal] = field(default_factory=dict)  # SKU → costo USD (> 0)
    ambiguos: dict[str, list[Decimal]] = field(default_factory=dict)  # SKU con variantes de costo distinto
    sin_costo: set[str] = field(default_factory=set)  # SKU en Ecom sin costo cargado (0 / vacío)
    iva: dict[str, Decimal] = field(default_factory=dict)  # SKU → factor de IVA (1,21 / 1,105)
    obtenido_en: float = 0.0

    def costo(self, sku: str) -> Decimal | None:
        return self.costos.get((sku or "").strip())

    def factor_iva(self, sku: str) -> Decimal | None:
        return self.iva.get((sku or "").strip())


def _dec(v) -> Decimal:
    try:
        return Decimal(str(v)) if v is not None else Decimal(0)
    except Exception:
        return Decimal(0)


def _factor_iva_de_tax(tax) -> Decimal | None:
    """`Product.tax` viene como porcentaje (21 / 10.5). Solo se aceptan las dos
    alícuotas que usa el ERP; cualquier otra cosa → None (no se inventa)."""
    t = _dec(tax)
    if t == Decimal("21"):
        return Decimal("1.21")
    if t == Decimal("10.5"):
        return Decimal("1.105")
    return None


def armar_catalogo(productos: list[dict]) -> CatalogoCostos:
    """Pura (sin red): lista de productos de `products.find` → catálogo."""
    cat = CatalogoCostos()
    for p in productos:
        sku = (p.get("sku") or "").strip()
        variantes = p.get("variants") or []
        propias = []
        sin_sku_propio = []
        for v in variantes:
            vsku = (v.get("sku") or "").strip()
            if vsku and vsku != sku:
                propias.append((vsku, _dec(v.get("cost"))))
            else:
                sin_sku_propio.append(_dec(v.get("cost")))
        for vsku, costo in propias:
            if costo > 0:
                cat.costos[vsku] = costo
            else:
                cat.sin_costo.add(vsku)
        if not sku:
            continue
        factor = _factor_iva_de_tax(p.get("tax"))
        if factor is not None:
            cat.iva[sku] = factor
        if not sin_sku_propio and propias:
            continue  # todas las variantes con SKU propio: el SKU de producto no tiene costo propio
        distintos = sorted({c for c in sin_sku_propio if c > 0})
        if len(distintos) == 1:
            cat.costos[sku] = distintos[0]
        elif len(distintos) > 1:
            cat.ambiguos[sku] = distintos
        else:
            cat.sin_costo.add(sku)
    return cat


def descargar_catalogo(cliente: EcomApiClient | None = None, log: Callable[[str], None] | None = None,
                       dormir: Callable[[float], None] = time.sleep) -> CatalogoCostos:
    """Baja TODO el catálogo de artículos de Ecom (paginado) y arma el índice."""
    cliente = cliente or EcomApiClient()
    productos: list[dict] = []
    pagina = 1
    while pagina <= _MAX_PAGINAS:
        ultimo_error: Exception | None = None
        data = None
        for intento in range(_REINTENTOS_PAGINA):
            try:
                data = cliente.graphql(_QUERY_CATALOGO, {"page": pagina})["products"]["find"]
                break
            except Exception as e:  # el servidor de Ecom a veces devuelve errores internos sueltos
                ultimo_error = e
                dormir(2 ** (intento + 1))
        if data is None:
            raise CatalogoEcomError(f"Ecom no devolvió la página {pagina} del catálogo: {ultimo_error}")
        filas = data.get("data") or []
        if not filas:
            break
        productos.extend(filas)
        if pagina >= int((data.get("pageInfo") or {}).get("pageCount") or 0):
            break
        pagina += 1
    if log:
        log(f"Catálogo de Ecom: {len(productos)} artículos en {pagina} páginas")
    if not productos:
        raise CatalogoEcomError("El catálogo de artículos de Ecom vino vacío.")
    cat = armar_catalogo(productos)
    cat.obtenido_en = time.time()
    return cat


# ── Cache de proceso ──

_lock = threading.Lock()
_cache: CatalogoCostos | None = None


def obtener_catalogo(descargar: Callable[[], CatalogoCostos] | None = None, ttl: float = _TTL_SEGUNDOS,
                     ahora: Callable[[], float] = time.time) -> CatalogoCostos:
    """Catálogo cacheado (TTL 1 h). Si el refresco falla y hay uno anterior, se
    sigue con ese (más vale un costo de hace unas horas que cortar todo)."""
    global _cache
    with _lock:
        if _cache is not None and ahora() - _cache.obtenido_en < ttl:
            return _cache
        try:
            nuevo = (descargar or descargar_catalogo)()
            nuevo.obtenido_en = ahora()
            _cache = nuevo
        except Exception:
            if _cache is None:
                raise
        return _cache


def limpiar_cache() -> None:
    global _cache
    with _lock:
        _cache = None


def precalentar() -> None:
    """Para el arranque del backend (hilo aparte): la primera descarga tarda ~80 s."""
    try:
        obtener_catalogo()
    except Exception:
        pass  # sin credenciales / sin red: se reintenta en el primer uso


# ── Proveedores con la misma interfaz que los de Táctica (adapters.py) ──

class CostoEcomProvider:
    """Reemplazo de `CostoVigenteProvider` (misma interfaz: `obtener`,
    `obtener_con_origen`, `precargar`) con el costo del catálogo de Ecom."""

    def __init__(self, catalogo: Callable[[], CatalogoCostos] | None = None):
        self._catalogo_fn = catalogo or obtener_catalogo

    def precargar(self) -> None:
        self._catalogo_fn()

    def obtener(self, sku: str) -> Decimal | None:
        return self.obtener_con_origen(sku)[0]

    def obtener_con_origen(self, sku: str) -> tuple[Decimal | None, str | None]:
        costo = self._catalogo_fn().costo(sku)
        return (costo, "ECOM") if costo is not None else (None, None)


class IvaConRespaldoEcom:
    """IVA del SKU: Táctica primero (como siempre); si Táctica no responde o no
    tiene el SKU, el IVA del artículo en Ecom. Sin esto, con Táctica caída el
    motor calcularía todo al 21% sin avisar."""

    def __init__(self, tactica=None, catalogo: Callable[[], CatalogoCostos] | None = None):
        from .adapters import IvaProvider

        self._tactica = tactica or IvaProvider()
        self._catalogo_fn = catalogo or obtener_catalogo
        self.tactica_caida = False

    def precargar(self) -> None:
        try:
            self._tactica.precargar()
        except Exception:
            self.tactica_caida = True
        self._catalogo_fn()

    def factor(self, sku: str) -> Decimal | None:
        if not self.tactica_caida:
            try:
                f = self._tactica.factor(sku)
                if f is not None:
                    return f
            except Exception:
                self.tactica_caida = True
        return self._catalogo_fn().factor_iva(sku)


def proveedores_de_costo_e_iva() -> tuple[CostoEcomProvider, IvaConRespaldoEcom]:
    """Los dos proveedores que usan Ofertas ML, Ayala Core, el simulador y el
    motor de precios: costo de Ecom, IVA de Táctica con respaldo de Ecom."""
    return CostoEcomProvider(), IvaConRespaldoEcom()


# ── Cruce con Táctica (a futuro) ──

def cruzar_costos(ecom: dict[str, Decimal], tactica: dict[str, Decimal],
                  tolerancia_pct: Decimal = Decimal("1")) -> list[dict]:
    """Alerta de diferencias de costo Ecom vs Táctica, por SKU presente en
    ambas. `tolerancia_pct`: diferencia relativa (sobre Ecom) que se ignora.
    Ordenada de mayor a menor diferencia."""
    out = []
    for sku, c_ecom in ecom.items():
        c_tac = tactica.get(sku)
        if c_tac is None or c_ecom <= 0:
            continue
        dif_pct = (c_tac - c_ecom) / c_ecom * 100
        if abs(dif_pct) > tolerancia_pct:
            out.append({"sku": sku, "ecom": c_ecom, "tactica": c_tac, "dif_pct": dif_pct.quantize(Decimal("0.01"))})
    return sorted(out, key=lambda r: abs(r["dif_pct"]), reverse=True)
