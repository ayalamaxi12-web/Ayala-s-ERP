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
