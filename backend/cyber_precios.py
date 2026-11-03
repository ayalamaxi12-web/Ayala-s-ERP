"""Precios del Cyber 2026: rangos de precio que ML permite por publicación, envío histórico y la planilla `Cyber_Precios` (la lista oficial del Cyber).

El cálculo del precio (reglas por grupo, piso de margen, mismo precio en las dos cuentas) vive en `docs/index.html` (`cyberDecidirPrecio`), pegado al margen local de Campañas ML
que ya se usa para elegir precios; acá solo están los datos que ese cálculo necesita del servidor y la persistencia. Solo lectura de ML; escribe únicamente la pestaña de la planilla.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

TAB_PRECIOS = "Cyber_Precios"
COLS_PRECIOS = ["SKU", "Cuenta", "MLA", "Grupo", "Precio_Cyber", "Margen_3_cuotas_pct", "Estado", "Regla", "Precio_Actual", "Precio_PM", "Propuesta_ML", "ML_Min", "ML_Max", "Actualizado"]


def rangos_y_envios(ml, cuenta: str, items: list[dict], envios: dict, progreso=None, workers: int = 6) -> dict:
    """`items`: [{item_id, promo_id, sku, categoria}]. Para cada una, el rango de precio que ML permite en esa campaña (`min_discounted_price`, `max_discounted_price`, el sugerido)
    y el envío histórico del SKU. Una publicación que ML no muestra como candidata queda sin rango (el cálculo no la corta). Solo lectura."""
    import cyber_input
    from ml_campanas_participar import _id_promo
    from rentabilidad.pricing_pm import norm_sku

    prog = progreso or (lambda *a: None)
    hechos = [0]

    def uno(it):
        try:
            entradas = [p for p in ml.promociones_item(it["item_id"], cuenta) if _id_promo(p) == it["promo_id"]]
        except Exception as e:  # noqa: BLE001
            return it["item_id"], None, f"{type(e).__name__}"
        hechos[0] += 1
        prog(hechos[0], len(items), "Rangos de precio en ML")
        return it["item_id"], (entradas[0] if entradas else None), None

    rangos, sin_rango, errores = {}, 0, 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for item_id, e, err in ex.map(uno, items):
            if err:
                errores += 1
            if not e:
                sin_rango += 1
                continue
            rangos[item_id] = {"min": e.get("min_discounted_price"), "max": e.get("max_discounted_price"), "sugerido": e.get("suggested_discounted_price"),
                               "estado": e.get("status"), "precio": e.get("price")}
    envio = {}
    for it in items:
        c, origen = cyber_input.envio_de_publicacion(envios, it["item_id"], norm_sku(it.get("sku") or ""), cuenta, it.get("categoria"))
        envio[it["item_id"]] = {"envio": None if c is None else float(c), "origen": origen}
    avisos = []
    if sin_rango:
        avisos.append(f"{sin_rango} publicaciones sin rango de ML (no figuran como candidatas de esa campaña o falló la consulta): no se corta su precio contra el rango.")
    if errores:
        avisos.append(f"{errores} consultas a ML fallaron.")
    return {"rangos": rangos, "envios": envio, "avisos": avisos}


def _hoja(ss):
    try:
        return ss.worksheet(TAB_PRECIOS)
    except Exception:  # noqa: BLE001
        ws = ss.add_worksheet(title=TAB_PRECIOS, rows=5000, cols=len(COLS_PRECIOS))
        ws.update(values=[COLS_PRECIOS], range_name="A1")
        return ws


def leer_precios(ss) -> list[dict]:
    filas = _hoja(ss).get_all_values()
    if not filas:
        return []
    cab = [str(c).strip() for c in filas[0]]
    return [dict(zip(cab, f + [""] * (len(cab) - len(f)))) for f in filas[1:] if any(f)]


def precios_otra_cuenta(ss, cuenta: str) -> dict[str, float]:
    """SKU normalizado → precio del Cyber ya definido en la OTRA cuenta (para que el mismo SKU salga al mismo precio en las dos)."""
    from rentabilidad.pricing_pm import norm_sku
    out: dict[str, float] = {}
    for f in leer_precios(ss):
        if f.get("Cuenta") != cuenta and f.get("Estado") != "no_participa":
            try:
                out[norm_sku(f["SKU"])] = max(out.get(norm_sku(f["SKU"]), 0.0), float(str(f.get("Precio_Cyber")).replace(",", ".")))
            except ValueError:
                continue
    return out


def guardar_precios(ss, cuenta: str, filas: list[dict], ahora: datetime | None = None) -> dict:
    """Reemplaza en `Cyber_Precios` las filas de esa cuenta por las nuevas (las de la otra cuenta no se tocan)."""
    ahora = ahora or datetime.now(timezone(timedelta(hours=-3)))
    ws = _hoja(ss)
    previas = [f for f in leer_precios(ss) if f.get("Cuenta") != cuenta]
    nuevas = [[f.get("sku", ""), cuenta, f.get("mla", ""), f.get("grupo", ""), f.get("precio"), f.get("margen3"), f.get("estado", ""), f.get("regla", ""),
               f.get("precio_actual"), f.get("precio_pm"), f.get("propuesta_ml"), f.get("ml_min"), f.get("ml_max"), ahora.strftime("%d/%m/%Y %H:%M")] for f in filas]
    cuerpo = [[p.get(c, "") for c in COLS_PRECIOS] for p in previas] + nuevas
    ws.clear()
    ws.update(values=[COLS_PRECIOS] + cuerpo, range_name="A1")
    return {"guardadas": len(nuevas), "otras_cuentas": len(previas)}


def items_cyber_en_ml(ml, cuenta: str, promotion_id: str | None = None) -> dict:
    """SOLO LECTURA. Las publicaciones de esa cuenta que YA están dentro de la campaña del Cyber según ML (`started`), con su precio de oferta. Si no se pasa `promotion_id` se toma
    la campaña tipo DEAL cuyo nombre dice «CYBER MONDAY»."""
    campanas = ml.promociones_seller(cuenta)
    if promotion_id:
        camp = next((c for c in campanas if c.get("id") == promotion_id), None)
    else:
        camp = next((c for c in campanas if "CYBER MONDAY" in str(c.get("name", "")).upper() and c.get("type") == "DEAL"), None) \
            or next((c for c in campanas if "CYBER MONDAY" in str(c.get("name", "")).upper()), None)
    if not camp or not camp.get("type"):
        return {"campana": None, "items": [], "aviso": "ML no lista una campaña del Cyber para esa cuenta (revisá el identificador)."}
    filas = []
    for it in ml.items_de_promocion(camp["id"], camp["type"], cuenta):
        mla = str(it.get("id") or it.get("item_id") or "")
        if mla:
            filas.append({"mla": mla, "precio": it.get("price") if it.get("price") is not None else it.get("new_price"), "precio_original": it.get("original_price")})
    return {"campana": {"id": camp["id"], "nombre": camp.get("name"), "tipo": camp.get("type")}, "items": filas, "aviso": None}


def agregar_faltantes(ss, cuenta: str, filas: list[dict], ahora: datetime | None = None) -> dict:
    """Agrega a `Cyber_Precios` las publicaciones leídas de ML que todavía no figuran para esa cuenta. NO toca ni reemplaza las filas que ya están."""
    ahora = ahora or datetime.now(timezone(timedelta(hours=-3)))
    ws = _hoja(ss)
    ya = {(str(f.get("Cuenta")), str(f.get("MLA"))) for f in leer_precios(ss)}
    nuevas = []
    for f in filas:
        mla = str(f.get("mla") or "")
        if not mla or (cuenta, mla) in ya:
            continue
        ya.add((cuenta, mla))
        nuevas.append(["", cuenta, mla, "", f.get("precio"), "", "leido_de_ml", "Leída de ML: oferta activa en la campaña del Cyber", f.get("precio_original"), "", "", "", "", ahora.strftime("%d/%m/%Y %H:%M")])
    if nuevas:
        ws.append_rows(nuevas, value_input_option="USER_ENTERED")
    return {"agregadas": len(nuevas), "ya_estaban": len(filas) - len(nuevas)}
