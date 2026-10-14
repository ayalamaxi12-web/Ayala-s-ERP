"""Detección de la cuenta (IT/MT) de las publicaciones de un Excel de campaña, por ITEM_ID.

`GET /items?ids=…` es público: devuelve `seller_id` de cualquier ítem, así que alcanza con el
token de una cuenta. Se mapea con `ml_auth.SELLERS`. De paso trae el SKU del ítem
(`seller_custom_field` / atributo `SELLER_SKU`) para las filas del Excel que vienen sin SKU."""
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from ml_auth import SELLERS, token_de
from ml_full import _get_real, _sku_de_item

_CAMPOS = "id,seller_id,seller_custom_field,attributes,category_id,listing_type_id"
_POR_SELLER = {v: k for k, v in SELLERS.items()}


def _lote(ids: list[str], get_fn, headers: dict) -> dict[str, dict]:
    d = get_fn("https://api.mercadolibre.com/items", {"ids": ",".join(ids), "attributes": _CAMPOS}, headers)
    out = {}
    for entrada in d or []:
        cuerpo = entrada.get("body") if isinstance(entrada, dict) and "body" in entrada else entrada
        if not cuerpo or not cuerpo.get("id"):
            continue
        sid = str(cuerpo["seller_id"]) if cuerpo.get("seller_id") is not None else None
        out[cuerpo["id"]] = {"seller_id": sid, "cuenta": _POR_SELLER.get(sid), "sku_ml": _sku_de_item(cuerpo),
                             "category_id": cuerpo.get("category_id"), "listing_type_id": cuerpo.get("listing_type_id")}
    return out


# Lo que ML devuelve de cada publicación (cuenta, SKU, categoría, tipo) casi no cambia: se guarda 30 min para que volver a subir el
# mismo Excel (o uno parecido) no repita las ~100 llamadas.
_CACHE: dict[str, tuple[float, dict]] = {}
_TTL = 1800.0


def limpiar_cache() -> None:
    _CACHE.clear()


def detectar(item_ids: list[str], get_fn: Callable | None = None, token_fn: Callable[[str], str] | None = None,
             workers: int = 6) -> tuple[dict[str, dict], list[str]]:
    """Devuelve ({item_id: {seller_id, cuenta, sku_ml}}, avisos). Un lote que falla no tira el resto."""
    get_fn, token_fn = get_fn or _get_real, token_fn or token_de
    ids = list(dict.fromkeys(i for i in item_ids if i))
    headers = {"Authorization": f"Bearer {token_fn(next(iter(SELLERS)))}"}
    ahora = time.time()
    res, avisos = {}, []
    for i in ids:
        hit = _CACHE.get(i)
        if hit and ahora - hit[0] < _TTL:
            res[i] = hit[1]
    pendientes = [i for i in ids if i not in res]
    lotes = [pendientes[i:i + 20] for i in range(0, len(pendientes), 20)]

    def uno(lote):
        try:
            return _lote(lote, get_fn, headers), None
        except Exception as e:  # noqa: BLE001 -- un lote caído no debe tirar el análisis
            return {}, f"{type(e).__name__}: {e}"

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for parcial, error in ex.map(uno, lotes):
            res.update(parcial)
            if error:
                avisos.append(f"Un lote de ítems no se pudo consultar a ML ({error})")
    for i, info in res.items():
        _CACHE.setdefault(i, (ahora, info))
    faltan = [i for i in ids if i not in res]
    if faltan and not avisos:
        avisos.append(f"{len(faltan)} publicaciones no respondió ML (borradas o sin acceso): sin cuenta.")
    return res, avisos


def resumen_cuentas(detectado: dict[str, dict], item_ids: list[str]) -> dict:
    """Cuenta de la campaña = la de la mayoría de sus ítems (un Excel sale de UNA cuenta)."""
    c = Counter((detectado.get(i) or {}).get("cuenta") or "?" for i in item_ids)
    reales = {k: v for k, v in c.items() if k != "?"}
    sugerida = max(reales, key=reales.get) if reales else None
    return {"conteo": dict(c), "sugerida": sugerida,
            "mixta": len(reales) > 1, "cuentas": list(SELLERS)}
