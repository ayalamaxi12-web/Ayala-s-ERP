"""SKU -> NUESTRAS publicaciones de ML (cuentas IT y MT), para que la pantalla de competencia pueda actuar (oferta, precio) sobre la publicación correcta.

Las acciones de escritura de ML (Ofertas, aplicar precio) son por publicación (MLA + cuenta), no por SKU. Acá se busca con la API de ML de NUESTRAS cuentas
(`users/{seller}/items/search?seller_sku=`; las publicaciones propias sí se pueden leer, a diferencia de las ajenas que dan 403) y se confirma el SKU exacto
leyendo cada ítem (`seller_custom_field` o atributo `SELLER_SKU`, igual que Ofertas), para no devolver ítems de SKU parecido.
Un error en una cuenta no corta la otra: vuelve en `errores`. Solo lectura."""
from ml_auth import SELLERS
from ml_full import MLFullClient, _sku_de_item

CAMPOS = ("id,title,price,original_price,permalink,status,seller_custom_field,attributes,catalog_listing,catalog_product_id,"
          "available_quantity,shipping,variations")
MAX_ITEMS = 50


def _norm(s):
    return str(s or "").strip().lower()


def publicaciones_por_sku(sku, cliente=None, cuentas=None):
    """-> {'sku', 'publicaciones': [{item_id, cuenta, titulo, precio, precio_original, estado, permalink, catalogo, stock}], 'errores': [{cuenta, error}]}"""
    sku = str(sku or "").strip()
    if not sku:
        raise ValueError("Falta el SKU.")
    cliente = cliente or MLFullClient()
    out, errores = [], []
    for cuenta in (cuentas or list(SELLERS)):
        try:
            headers = {"Authorization": f"Bearer {cliente._token(cuenta)}"}
            d = cliente._get(f"https://api.mercadolibre.com/users/{SELLERS[cuenta]}/items/search",
                             {"seller_sku": sku, "limit": MAX_ITEMS}, headers)
            ids = [i for i in (d.get("results") or []) if i][:MAX_ITEMS]
            for i in range(0, len(ids), 20):
                lote = cliente._get("https://api.mercadolibre.com/items", {"ids": ",".join(ids[i:i + 20]), "attributes": CAMPOS}, headers)
                for entrada in lote:
                    it = entrada.get("body") if isinstance(entrada, dict) and "body" in entrada else entrada
                    if not it or not it.get("id") or _norm(_sku_de_item(it)) != _norm(sku):
                        continue
                    out.append({"item_id": it["id"], "cuenta": cuenta, "titulo": it.get("title", ""), "precio": it.get("price"),
                                "precio_original": it.get("original_price"), "estado": it.get("status", ""), "permalink": it.get("permalink", ""),
                                "catalogo": bool(it.get("catalog_listing")), "stock": it.get("available_quantity")})
        except Exception as e:  # noqa: BLE001  una cuenta caída no corta la otra
            errores.append({"cuenta": cuenta, "error": f"{type(e).__name__}: {str(e)[:160]}"})
    out.sort(key=lambda x: (x["estado"] != "active", x["cuenta"], x["item_id"]))
    return {"sku": sku, "publicaciones": out, "errores": errores}


# ── Precio real en ML por SKU (E2 de "contexto por SKU" en Análisis de Competencia) ──
# `price` de /items es el TACHADO cuando hay promoción activa; lo que paga el comprador es el precio de la promoción "started" (igual criterio que
# `ayala_core.resolver_precio_real`). Cuesta ~1 llamada por publicación activa (+1 por cuenta para los nombres de campaña), por eso se pide por SKU
# al abrirlo y se cachea unos minutos; traer todo el catálogo de una vez no es viable.
import threading
import time
from decimal import Decimal

TTL_PRECIO_SEG = 300
_cache_precio: dict = {}
_cache_lock = threading.Lock()


def _num(x):
    return float(Decimal(str(x))) if x not in (None, "") else None


def precio_real_por_sku(sku, cliente=None, cuentas=None, ahora=time.time):
    """-> {'sku', 'publicaciones': [{item_id, cuenta, titulo, estado, stock, permalink, catalogo, precio_real, precio_tachado, precio_lista,
    campana:{nombre, tipo}|None}], 'errores', 'leido_en'}. `precio_lista` es lo que dice /items (price); `precio_real` el que rige (promoción
    activa de menor precio, o precio_lista si no hay). Las pausadas/cerradas se devuelven sin consultar promociones."""
    from ml_ofertas import MLOfertasClient
    cliente = cliente or MLOfertasClient()
    base = publicaciones_por_sku(sku, cliente, cuentas)
    errores = list(base["errores"])
    nombres = {}
    out = []
    for p in base["publicaciones"]:
        r = {"item_id": p["item_id"], "cuenta": p["cuenta"], "titulo": p["titulo"], "estado": p["estado"], "stock": p["stock"],
             "permalink": p["permalink"], "catalogo": p["catalogo"], "precio_lista": _num(p["precio"]), "precio_real": _num(p["precio"]),
             "precio_tachado": _num(p["precio_original"]), "campana": None}
        if p["estado"] == "active":
            try:
                promos = cliente.promociones_item(p["item_id"], p["cuenta"]) or []
                activas = [x for x in promos if x.get("status") == "started" and x.get("price")]
                if activas:
                    m = min(activas, key=lambda x: Decimal(str(x["price"])))
                    if p["cuenta"] not in nombres:
                        try:
                            nombres[p["cuenta"]] = {c.get("id"): c.get("name") for c in cliente.promociones_seller(p["cuenta"]) if c.get("id")}
                        except Exception:  # noqa: BLE001  sin nombres igual se muestra el precio
                            nombres[p["cuenta"]] = {}
                    tipo = m.get("type")
                    nombre = nombres[p["cuenta"]].get(m.get("promotion_id") or m.get("id")) or ("Descuento propio" if tipo == "PRICE_DISCOUNT" else tipo)
                    r["precio_real"] = _num(m["price"])
                    r["precio_tachado"] = _num(m.get("original_price")) or r["precio_tachado"] or r["precio_lista"]
                    r["campana"] = {"nombre": nombre, "tipo": tipo}
            except Exception as e:  # noqa: BLE001  si falla, queda el precio de lista y se avisa
                errores.append({"cuenta": p["cuenta"], "error": f"{p['item_id']}: promociones no leídas ({type(e).__name__}: {str(e)[:120]})"})
        out.append(r)
    return {"sku": base["sku"], "publicaciones": out, "errores": errores, "leido_en": ahora()}


def precio_real_cacheado(sku, refrescar=False, ttl=TTL_PRECIO_SEG, ahora=time.time, **kw):
    k = str(sku or "").strip().lower()
    with _cache_lock:
        c = _cache_precio.get(k)
        if c and not refrescar and ahora() - c["leido_en"] < ttl:
            return c
    r = precio_real_por_sku(sku, ahora=ahora, **kw)
    if not r["errores"]:                       # un resultado con errores no se cachea: el próximo clic reintenta
        with _cache_lock:
            _cache_precio[k] = r
            if len(_cache_precio) > 500:
                _cache_precio.pop(next(iter(_cache_precio)))
    return r
