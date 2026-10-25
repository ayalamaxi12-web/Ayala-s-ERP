"""Catálogo de costos de Ecom por SKU — FUENTE PRIMARIA de costo del ERP.

Decisión de Maxx (2026-10, ajuste a CRITERIOS_MARGEN.md §7): el costo del
producto sale de Ecom (módulo Artículos / Editar Artículos, donde se crean los
SKU y se les pone el costo), no de Táctica — Táctica vive en el servidor de la
oficina y se cae con la VPN. Táctica queda para CRUZAR (`cruzar_costos`): cuando
hay diferencia entre las dos fuentes, se informa.

Origen: GraphQL de Ecom, `products.find` paginado (30 por página, ~115 páginas
y ~80 s para los ~3.400 artículos), `Variant.cost` en USD — el mismo campo que
ya usa la ingesta de ventas (`ingesta_ecom_api`). Como bajar todo cuesta
~80 s, se baja UNA vez por día (cron de las 06:00), o a mano, y la foto se
guarda en la base (`costo_ecom_snapshot`): un request solo la lee, nunca baja
nada de Ecom (ver "Foto guardada en la base + caché de proceso"). Si el
refresco falla se sigue con la última foto buena.

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


# ── Foto guardada en la base + caché de proceso ──
#
# El catálogo se baja de Ecom (~80 s) UNA vez por día (cron de las 06:00, `scripts/ecom_diario.py`), en el arranque si no hay una foto reciente, o
# a mano (`refrescar`, botón del front). Cada foto queda guardada en la base (`costo_ecom_snapshot`); un request SOLO lee la más reciente
# (memoria → base, milisegundos) y nunca baja nada de Ecom. Si Ecom falla se sigue con la última foto buena. La única excepción: la primera vez
# que no existe ninguna foto, `obtener_catalogo` la baja en el momento (una sola vez en la vida del sistema).

import json

_REFRESCO_MEMORIA_SEG = 300      # cada cuánto se vuelve a mirar la base (toma la foto que dejó el cron)
_MAX_EDAD_SEG = 24 * 3600        # una foto más vieja dispara un refresco en segundo plano (mientras se sigue sirviendo la vieja)
_CONSERVAR = 7

_lock = threading.Lock()            # protege la memoria
_refresco_lock = threading.Lock()   # un solo refresco a la vez
_cache: CatalogoCostos | None = None
_meta: dict = {}                    # origen / duracion_seg / cantidad de la foto en memoria
_leido_en = 0.0
_estado = {"en_curso": False, "ultimo_error": None, "ultimo_intento": None}


def _sesion_default():
    from .db import sesion
    return sesion()


def catalogo_a_json(cat: CatalogoCostos) -> str:
    return json.dumps({
        "costos": {k: str(v) for k, v in cat.costos.items()}, "iva": {k: str(v) for k, v in cat.iva.items()},
        "ambiguos": {k: [str(x) for x in v] for k, v in cat.ambiguos.items()}, "sin_costo": sorted(cat.sin_costo),
    }, separators=(",", ":"))


def _armar(d: dict, obtenido_en: float) -> CatalogoCostos:
    return CatalogoCostos(
        costos={k: Decimal(v) for k, v in d["costos"].items()}, iva={k: Decimal(v) for k, v in d["iva"].items()},
        ambiguos={k: [Decimal(x) for x in v] for k, v in d["ambiguos"].items()}, sin_costo=set(d["sin_costo"]), obtenido_en=obtenido_en)


def guardar_snapshot(cat: CatalogoCostos, origen: str, duracion_seg: float, db_factory: Callable = _sesion_default) -> None:
    """Escribe la foto y poda las más viejas (deja las últimas `_CONSERVAR`)."""
    from datetime import datetime, timezone
    from .models import CostoEcomSnapshot
    with db_factory() as db:
        db.add(CostoEcomSnapshot(obtenido_en=datetime.fromtimestamp(cat.obtenido_en, timezone.utc).replace(tzinfo=None), origen=origen,
                                 duracion_seg=Decimal(str(round(duracion_seg, 2))), cantidad=len(cat.costos), payload=catalogo_a_json(cat)))
        db.flush()
        viejas = db.query(CostoEcomSnapshot).order_by(CostoEcomSnapshot.obtenido_en.desc()).offset(_CONSERVAR).all()
        for f in viejas:
            db.delete(f)


def leer_snapshot(db_factory: Callable = _sesion_default) -> tuple[CatalogoCostos, dict] | None:
    """La foto más reciente de la base, o None si no hay."""
    from datetime import timezone
    from .models import CostoEcomSnapshot
    with db_factory() as db:
        f = db.query(CostoEcomSnapshot).order_by(CostoEcomSnapshot.obtenido_en.desc()).first()
        if f is None:
            return None
        t = f.obtenido_en.replace(tzinfo=timezone.utc).timestamp()
        return _armar(json.loads(f.payload), t), {"origen": f.origen, "duracion_seg": float(f.duracion_seg), "cantidad": f.cantidad}


def _poner_en_memoria(cat: CatalogoCostos, meta: dict, ahora: float) -> None:
    global _cache, _meta, _leido_en
    _cache, _meta, _leido_en = cat, meta, ahora


def refrescar(origen: str = "manual", descargar: Callable[[], CatalogoCostos] | None = None, db_factory: Callable = _sesion_default,
              ahora: Callable[[], float] = time.time, log: Callable[[str], None] | None = None) -> dict:
    """Baja el catálogo de Ecom, lo guarda en la base y lo pone en memoria. UN solo refresco a la vez (si ya hay uno corriendo devuelve el estado
    sin esperar). Si Ecom falla se conserva la foto anterior, se anota el error y se propaga la excepción (el que llama decide: el cron/arranque la
    registran, el botón la muestra)."""
    if not _refresco_lock.acquire(blocking=False):
        return {**estado(ahora), "ya_en_curso": True}
    try:
        _estado.update(en_curso=True, ultimo_intento=ahora())
        t0 = time.monotonic()
        try:
            cat = (descargar or descargar_catalogo)()
            cat.obtenido_en = ahora()
            dur = time.monotonic() - t0
            meta = {"origen": origen, "duracion_seg": round(dur, 1), "cantidad": len(cat.costos)}
            try:
                guardar_snapshot(cat, origen, dur, db_factory)
            except Exception as e:  # la base no escribió: se sirve igual desde memoria, pero se avisa
                _estado["ultimo_error"] = f"No se pudo guardar la foto en la base: {type(e).__name__}: {str(e)[:150]}"
            else:
                _estado["ultimo_error"] = None
            with _lock:
                _poner_en_memoria(cat, meta, ahora())
            if log:
                log(f"Catálogo de costos de Ecom: {meta['cantidad']} SKU con costo, {meta['duracion_seg']} s, origen {origen}")
        except Exception as e:
            _estado["ultimo_error"] = f"{type(e).__name__}: {str(e)[:180]}"
            raise
    finally:
        _estado["en_curso"] = False
        _refresco_lock.release()
    return estado(ahora)


def refrescar_en_segundo_plano(origen: str = "manual", **kw) -> bool:
    """Lanza `refrescar` en un hilo y vuelve en seguida. False si ya hay uno corriendo. Con origen manual/auto también vuelve a leer el IVA de Táctica
    (la otra única lectura en vivo de los cálculos), en su propio hilo."""
    if origen != "arranque":
        refrescar_iva_tactica_en_segundo_plano()
    if _refresco_lock.locked():
        return False

    def _correr():
        try:
            refrescar(origen, **kw)
        except Exception:
            pass  # el error ya quedó en `estado()["ultimo_error"]`
    threading.Thread(target=_correr, daemon=True).start()
    return True


def estado(ahora: Callable[[], float] = time.time) -> dict:
    with _lock:
        cat, meta = _cache, dict(_meta)
    return {"hay_catalogo": cat is not None, "obtenido_en": cat.obtenido_en if cat else None,
            "antiguedad_seg": round(ahora() - cat.obtenido_en) if cat else None, "origen": meta.get("origen"),
            "duracion_seg": meta.get("duracion_seg"), "cantidad": meta.get("cantidad"), "en_curso": _estado["en_curso"],
            "ultimo_error": _estado["ultimo_error"], "ultimo_intento": _estado["ultimo_intento"], "iva_tactica": estado_iva_tactica(ahora)}


def obtener_catalogo(ahora: Callable[[], float] = time.time, db_factory: Callable = _sesion_default,
                     descargar: Callable[[], CatalogoCostos] | None = None) -> CatalogoCostos:
    """El catálogo vigente, SIN bajar nada de Ecom (salvo la primera vez de la historia, cuando no existe ninguna foto). Memoria → base (cada 5 min)."""
    with _lock:
        fresco = _cache is not None and ahora() - _leido_en < _REFRESCO_MEMORIA_SEG
        if not fresco:
            try:
                f = leer_snapshot(db_factory)
            except Exception:
                f = None  # la base no responde: se sigue con lo que haya en memoria
            if f is not None and (_cache is None or f[0].obtenido_en >= _cache.obtenido_en):
                _poner_en_memoria(f[0], f[1], ahora())
            elif _cache is not None:
                _poner_en_memoria(_cache, _meta, ahora())
        cat = _cache
    if cat is None:
        refrescar("primer-uso", descargar=descargar, db_factory=db_factory, ahora=ahora)  # única bajada dentro de un request
        with _lock:
            cat = _cache
        if cat is None:   # otro refresco estaba corriendo: se espera a que termine
            with _refresco_lock:
                pass
            with _lock:
                cat = _cache
        if cat is None:
            raise CatalogoEcomError("El catálogo de costos todavía no está disponible.")
    elif ahora() - cat.obtenido_en > _MAX_EDAD_SEG:
        refrescar_en_segundo_plano("auto", descargar=descargar, db_factory=db_factory, ahora=ahora)
    return cat


def limpiar_cache() -> None:
    global _cache, _meta, _leido_en
    with _lock:
        _cache, _meta, _leido_en = None, {}, 0.0
        _estado.update(en_curso=False, ultimo_error=None, ultimo_intento=None)


def cargar_de_base(db_factory: Callable = _sesion_default) -> bool:
    """Pone en memoria la foto más reciente de la base SIN bajar nada de Ecom. False si no hay (o la base no responde)."""
    try:
        with _lock:
            f = leer_snapshot(db_factory)
            if f is None:
                return False
            _poner_en_memoria(f[0], f[1], time.time())
            return True
    except Exception:
        return False


def precalentar(db_factory: Callable = _sesion_default) -> None:
    """Para el arranque del backend (hilo aparte): carga la foto de la base a memoria (milisegundos) y, si no hay o tiene más de 24 h, baja una nueva
    en este mismo hilo (el resto del ERP sigue sirviendo la foto vieja mientras tanto)."""
    cargar_de_base(db_factory)
    try:
        if _cache is None or time.time() - _cache.obtenido_en > _MAX_EDAD_SEG:
            refrescar("arranque", db_factory=db_factory)
    except Exception:
        pass  # sin credenciales / sin red: el error queda en estado(); se reintenta con el cron o a mano
    refrescar_iva_tactica()   # una sola consulta a Táctica por arranque; si falla queda el error en estado_iva_tactica() y el IVA sale de Ecom


# ── Foto del IVA de Táctica ──
# El IVA por SKU sale de la base de Táctica (SQL, por el túnel). Antes cada cálculo (Motor de Precios, Ofertas, simulador) armaba su propio proveedor y
# volvía a consultar TODO el catálogo de Táctica: con 9 SKU piloto eran 9 consultas SQL seguidas. Ahora la consulta se hace una vez (arranque,
# botón «Refrescar costos» o pasadas 24 h, siempre en un hilo aparte) y los cálculos leen esta foto de memoria. Si todavía no hay foto o Táctica
# no respondió, el IVA sale de Ecom (`IvaConRespaldoEcom`) y la pantalla lo avisa en texto.
_IVA_MAX_EDAD_SEG = 24 * 3600
_iva_tactica: dict | None = None   # {"factores": {sku: Decimal}, "obtenido_en": float}
_iva_estado: dict = {"en_curso": False, "ultimo_error": None, "ultimo_intento": None}
_iva_lock = threading.Lock()
_iva_refresco_lock = threading.Lock()


class TacticaSinFoto(RuntimeError):
    """Todavía no hay una lectura del IVA de Táctica en memoria (se pide en el arranque o con «Refrescar costos»)."""


def refrescar_iva_tactica(consultar: Callable[[], list[dict]] | None = None, ahora: Callable[[], float] = time.time) -> bool:
    """Lee el catálogo de Táctica (puede tardar hasta ~30 s con reintentos si el túnel está caído) y deja la foto en memoria. Si falla se conserva la
    foto anterior y se anota el error. Un solo refresco a la vez (False si ya hay uno)."""
    global _iva_tactica
    from .adapters import IvaProvider, _consultar_catalogo_tactica_real

    if not _iva_refresco_lock.acquire(blocking=False):
        return False
    try:
        _iva_estado.update(en_curso=True, ultimo_intento=ahora())
        try:
            p = IvaProvider(consultar=consultar or _consultar_catalogo_tactica_real)
            p.precargar()
            factores = {sku: f for sku in p._catalogo if (f := p.factor(sku)) is not None}
            with _iva_lock:
                _iva_tactica = {"factores": factores, "obtenido_en": ahora()}
            _iva_estado["ultimo_error"] = None
        except Exception as e:
            _iva_estado["ultimo_error"] = causa_error_tactica(e)
        return True
    finally:
        _iva_estado["en_curso"] = False
        _iva_refresco_lock.release()


def refrescar_iva_tactica_en_segundo_plano(**kw) -> bool:
    if _iva_refresco_lock.locked():
        return False
    threading.Thread(target=refrescar_iva_tactica, kwargs=kw, daemon=True).start()
    return True


def causa_error_tactica(exc: BaseException) -> str:
    """Por qué no respondió Táctica, en palabras y sin datos de conexión. Es una clasificación por el texto/tipo del error del driver, no un diagnóstico
    de red: sin conexión no se distingue túnel caído de VPN apagada de tiempo de espera (por eso se dicen juntos)."""
    from .config import ConfiguracionFaltante

    if isinstance(exc, ConfiguracionFaltante):
        return "falta configurar la conexión a Táctica"
    txt = f"{type(exc).__name__}: {exc}".lower()
    if any(k in txt for k in ("20009", "20002", "unable to connect", "connection failed", "socks", "refused", "unreachable", "no route", "timeout", "timed out", "20003")):
        return "no se pudo conectar (¿VPN apagada o túnel caído?)"
    if "20017" in txt or "eof" in txt:
        return "la conexión se cortó a mitad de la consulta"
    return f"error al consultar ({type(exc).__name__})"


def estado_iva_tactica(ahora: Callable[[], float] = time.time) -> dict:
    with _iva_lock:
        f = _iva_tactica
    return {"hay_foto": f is not None, "obtenido_en": f["obtenido_en"] if f else None, "antiguedad_seg": round(ahora() - f["obtenido_en"]) if f else None,
            "cantidad": len(f["factores"]) if f else 0, "en_curso": _iva_estado["en_curso"], "ultimo_error": _iva_estado["ultimo_error"]}


def limpiar_iva_tactica() -> None:
    global _iva_tactica
    with _iva_lock:
        _iva_tactica = None
    _iva_estado.update(en_curso=False, ultimo_error=None, ultimo_intento=None)


class IvaTacticaFoto:
    """Misma interfaz que `adapters.IvaProvider` (`precargar`, `factor`) pero lee la foto en memoria: nunca consulta Táctica dentro de un cálculo."""

    def precargar(self) -> None:
        with _iva_lock:
            f = _iva_tactica
        if f is None:
            raise TacticaSinFoto(_iva_estado["ultimo_error"] or "todavía no hay una lectura de Táctica en memoria")
        if time.time() - f["obtenido_en"] > _IVA_MAX_EDAD_SEG:
            refrescar_iva_tactica_en_segundo_plano()   # se sigue sirviendo la foto vieja mientras tanto

    def factor(self, sku: str) -> Decimal | None:
        with _iva_lock:
            f = _iva_tactica
        if f is None:
            raise TacticaSinFoto("todavía no hay una lectura de Táctica en memoria")
        return f["factores"].get(sku)


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
        self._tactica = tactica or IvaTacticaFoto()
        self._catalogo_fn = catalogo or obtener_catalogo
        self.tactica_caida = False

    def precargar(self) -> None:
        try:
            self._tactica.precargar()
        except Exception:
            self.tactica_caida = True
        self._catalogo_fn()

    def factor_con_origen(self, sku: str) -> tuple[Decimal | None, str | None]:
        """(factor, origen): `TACTICA`, `ECOM` (respaldo) o None si no hay IVA en ninguna. Mismo orden de búsqueda que `factor`."""
        if not self.tactica_caida:
            try:
                f = self._tactica.factor(sku)
                if f is not None:
                    return f, "TACTICA"
            except Exception:
                self.tactica_caida = True
        f = self._catalogo_fn().factor_iva(sku)
        return (f, "ECOM") if f is not None else (None, None)

    def factor(self, sku: str) -> Decimal | None:
        return self.factor_con_origen(sku)[0]


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
