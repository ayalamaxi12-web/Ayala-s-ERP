"""Comisión REAL de ML por publicación (el "Cargo por vender"), en vez de una tabla por categoría.

La comisión depende de la categoría de ML y del tipo de publicación (clásica / premium), no de las categorías internas de
GRAL CATEGORIAS: SEW-MINI es "Textil" en la planilla y "Electrodomésticos y Aires Ac." en ML, y cobra 15%. Se pide a
`GET /sites/MLA/listing_prices` (público) una vez por cada par (category_id, listing_type_id) distinto -- decenas por
Excel, no una por publicación -- usando el precio de lista de una publicación de ese par.

`sale_fee_details` trae `meli_percentage_fee` (la comisión base) y `financing_add_on_fee` (el recargo por cuotas, que acá
se modela aparte); `percentage_fee` es la suma de ambas. Se toma `meli_percentage_fee`; si falta, `percentage_fee` menos el
recargo de financiación; si tampoco, (sale_fee_amount − fixed_fee) / precio. Cualquier valor fuera de 1–40% se descarta.
NOTA: el formato de la respuesta se programó según la documentación de ML y se probó con respuestas simuladas, no contra la API
real (sin acceso desde donde se desarrolló): por eso cada par devuelve también la respuesta cruda (`raw`) para auditarla."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import Callable

from ml_auth import SELLERS, token_de
from ml_full import _get_real

URL = "https://api.mercadolibre.com/sites/MLA/listing_prices"


def _num(v):
    try:
        return None if v is None else Decimal(str(v))
    except Exception:  # noqa: BLE001
        return None


def parsear(resp, listing_type_id: str, precio) -> tuple[Decimal | None, dict]:
    """(fracción 0.15 | None, detalle crudo). `resp` es un dict o la lista de tipos de publicación."""
    if isinstance(resp, list):
        resp = next((r for r in resp if isinstance(r, dict) and r.get("listing_type_id") == listing_type_id), None)
    if not isinstance(resp, dict):
        return None, {}
    det = resp.get("sale_fee_details") or {}
    financ = _num(det.get("financing_add_on_fee")) or Decimal(0)
    pct = _num(det.get("meli_percentage_fee"))
    if pct is None:
        pf = _num(det.get("percentage_fee"))
        pct = None if pf is None else pf - financ
    if pct is None:
        monto, fijo, p = _num(resp.get("sale_fee_amount")), _num(det.get("fixed_fee")) or Decimal(0), _num(precio)
        if monto is not None and p:
            pct = (monto - fijo) / p * 100
    raw = {k: resp.get(k) for k in ("listing_type_id", "sale_fee_amount")} | {"sale_fee_details": det}
    if pct is None:
        return None, raw
    frac = pct / 100 if pct >= 1 else pct       # ML manda 15 o 15.0 (por ciento); por si viniera 0.15
    return (frac if Decimal("0.01") <= frac <= Decimal("0.40") else None), raw


def comisiones(items: dict[str, dict], get_fn: Callable | None = None, token_fn: Callable[[str], str] | None = None,
               workers: int = 6) -> tuple[dict, list[str]]:
    """`items`: {item_id: {category_id, listing_type_id, precio}}. Devuelve
    ({item_id: {pct, categoria, tipo, raw}}, avisos). Un par que falla no tira el resto: esas publicaciones quedan sin dato."""
    get_fn, token_fn = get_fn or _get_real, token_fn or token_de
    headers = {"Authorization": f"Bearer {token_fn(next(iter(SELLERS)))}"}
    pares: dict[tuple, list] = {}
    for iid, d in items.items():
        cat, lt, precio = d.get("category_id"), d.get("listing_type_id"), d.get("precio")
        if cat and lt and precio:
            pares.setdefault((cat, lt), []).append((iid, precio))
    avisos: list[str] = []

    def uno(par):
        (cat, lt), lista = par
        precio = sorted(p for _, p in lista)[len(lista) // 2]          # el precio de lista mediano del par
        try:
            resp = get_fn(URL, {"price": precio, "listing_type_id": lt, "category_id": cat}, headers)
        except Exception as e:  # noqa: BLE001
            return par, None, {}, f"{cat}/{lt}: {type(e).__name__}: {e}"
        pct, raw = parsear(resp, lt, precio)
        return par, pct, raw, (None if pct is not None else f"{cat}/{lt}: respuesta de ML sin comisión válida")

    out: dict = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for par, pct, raw, error in ex.map(uno, list(pares.items())):
            if error:
                avisos.append(f"Comisión real de ML no disponible para {error}")
                continue
            (cat, lt), lista = par
            for iid, _ in lista:
                out[iid] = {"pct": pct, "categoria": cat, "tipo": lt, "raw": raw}
    sin = [i for i, d in items.items() if i not in out]
    if sin and not avisos:
        avisos.append(f"{len(sin)} publicaciones sin categoría/tipo de ML: sin comisión real")
    return out, avisos
