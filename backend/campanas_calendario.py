"""Calendario de campañas/promociones de ML para el aviso diario (lo llama n8n: GET /campanas/calendario).

Consulta `seller-promotions/users/{id}` de las dos cuentas (IT y MT), separa EVENTOS ESPECIALES de CUPONES/OPERATIVAS, calcula
los días que faltan (al límite de adhesión si lo tiene, si no al inicio), cuenta en cuántos ítems es elegible la cuenta y marca las
que están a EXACTAMENTE `dias_aviso` días. La misma campaña en IT y MT sale UNA sola vez, con las dos cuentas marcadas.

Solo lectura. NOTA: los nombres de los campos de fecha de la respuesta de ML no estaban confirmados al escribirlo (el módulo de
Ofertas ML los lee con fallbacks): se aceptan las variantes conocidas y, si una campaña no trae fecha, sale con `sin_fecha: true`
y sus claves crudas en `diagnostico`, en vez de inventar un dato."""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

from ml_auth import SELLERS

DIAS_AVISO = 5

# Cupones y campañas operativas (no son un evento de venta): cupones, stock no saludable, descuentos propios, volumen.
OPERATIVAS = {"SELLER_COUPON_CAMPAIGN", "UNHEALTHY_STOCK", "PRICE_DISCOUNT", "VOLUME", "COUPON"}
# Eventos especiales conocidos. Un tipo que no está en ninguna lista va a ESPECIALES con `tipo_desconocido` (mejor avisar de más).
ESPECIALES = {"DEAL", "SMART", "SELLER_CAMPAIGN", "MARKETPLACE_CAMPAIGN", "LIGHTNING", "DOD", "PRE_NEGOTIATED", "TIERS",
              "SMART_CAMPAIGN", "PRICE_MATCHING", "EVENT", "FLEX"}

_CAMPOS_INICIO = ("start_date", "date_from", "start", "start_time")
_CAMPOS_FIN = ("finish_date", "date_to", "end_date", "end", "finish_time")
_CAMPOS_LIMITE = ("deadline_date", "deadline", "adhesion_deadline", "join_deadline", "date_deadline")


def clasificar(tipo: str | None) -> tuple[str, bool]:
    """('especial' | 'cupon_operativa', tipo_desconocido)."""
    t = (tipo or "").upper()
    if t in OPERATIVAS or "COUPON" in t or "STOCK" in t:
        return "cupon_operativa", False
    if t in ESPECIALES:
        return "especial", False
    return "especial", True


def fecha(v) -> date | None:
    """Fecha (sin hora) de lo que mande ML: ISO con o sin zona, 'AAAA-MM-DD', o epoch en segundos/milisegundos."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        try:
            return datetime.utcfromtimestamp(v / 1000 if v > 1e11 else v).date()
        except (OverflowError, OSError, ValueError):
            return None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(v).strip())
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def _primero(d: dict, campos) -> date | None:
    for c in campos:
        f = fecha(d.get(c))
        if f:
            return f
    return None


def normalizar(p: dict, cuenta: str) -> dict:
    inicio, fin, limite = _primero(p, _CAMPOS_INICIO), _primero(p, _CAMPOS_FIN), _primero(p, _CAMPOS_LIMITE)
    return {"id": p.get("id") or p.get("promotion_id"), "tipo": p.get("type") or p.get("promotion_type"), "nombre": (p.get("name") or "").strip(),
            "estado": p.get("status"), "inicio": inicio, "fin": fin, "limite_adhesion": limite, "cuenta": cuenta, "claves": sorted(p)}


def _clave_igual(c: dict):
    return (str(c["tipo"]).upper(), re.sub(r"\s+", " ", c["nombre"].lower()), c["inicio"], c["fin"])


def fusionar(por_cuenta: dict[str, list[dict]]) -> list[dict]:
    """Una fila por campaña: la misma campaña en IT y MT (mismo id, o mismo tipo + nombre + fechas) lleva las dos cuentas."""
    out: dict = {}
    por_id: dict = {}
    por_firma: dict = {}
    for cuenta, lista in por_cuenta.items():
        for c in lista:
            firma = _clave_igual(c) if c["nombre"] and (c["inicio"] or c["fin"]) else None
            k = por_id.get(c["id"]) if c["id"] else None
            k = k or (por_firma.get(firma) if firma else None)
            if k is None:
                k = len(out)
                out[k] = {**c, "cuentas": [], "ids_por_cuenta": {}, "claves": set()}
            f = out[k]
            if cuenta not in f["cuentas"]:
                f["cuentas"].append(cuenta)
            f["ids_por_cuenta"][cuenta] = c["id"]
            f["claves"].update(c["claves"])
            for campo in ("inicio", "fin", "limite_adhesion"):
                f[campo] = f[campo] or c[campo]
            f["estado"] = f["estado"] or c["estado"]
            if c["id"]:
                por_id[c["id"]] = k
            if firma:
                por_firma[firma] = k
    return list(out.values())


def enriquecer(c: dict, hoy: date, dias_aviso: int = DIAS_AVISO) -> dict:
    """Días que faltan (al límite de adhesión si tiene, si no al inicio) y marca de aviso destacado."""
    ref_nombre = "limite_adhesion" if c["limite_adhesion"] else "inicio" if c["inicio"] else None
    ref = c[ref_nombre] if ref_nombre else None
    dias = (ref - hoy).days if ref else None
    seccion, desconocido = clasificar(c["tipo"])
    d_inicio = (c["inicio"] - hoy).days if c["inicio"] else None
    d_limite = (c["limite_adhesion"] - hoy).days if c["limite_adhesion"] else None
    return {
        "id": c["id"], "ids_por_cuenta": c["ids_por_cuenta"], "nombre": c["nombre"] or c["tipo"], "tipo": c["tipo"], "seccion": seccion,
        "tipo_desconocido": desconocido, "estado": c["estado"], "cuentas": sorted(c["cuentas"]),
        "inicio": c["inicio"].isoformat() if c["inicio"] else None, "fin": c["fin"].isoformat() if c["fin"] else None,
        "limite_adhesion": c["limite_adhesion"].isoformat() if c["limite_adhesion"] else None,
        "dias_faltan": dias, "referencia_dias": ref_nombre, "dias_al_inicio": d_inicio, "dias_al_limite": d_limite,
        "a_dias_aviso": dias == dias_aviso, "sin_fecha": ref is None,
        "elegibles": c.get("elegibles", {}), "aceptados": c.get("aceptados", {}),
        "items_elegibles": sum(v for v in c.get("elegibles", {}).values() if isinstance(v, int)) if c.get("elegibles") else None,
    }


def _fmt(f: str | None) -> str:
    return f"{f[8:10]}/{f[5:7]}" if f else "—"


def linea(c: dict) -> str:
    """Una línea lista para pegar en el mail."""
    cuentas = "+".join(c["cuentas"])
    partes = [f"{c['nombre']} ({c['tipo']}) · {cuentas}"]
    if c["limite_adhesion"]:
        partes.append(f"límite de adhesión {_fmt(c['limite_adhesion'])}")
    partes.append(f"inicio {_fmt(c['inicio'])} · fin {_fmt(c['fin'])}")
    if c["dias_faltan"] is not None:
        d = c["dias_faltan"]
        ref = "al límite" if c["referencia_dias"] == "limite_adhesion" else "al inicio"
        partes.append(("en %d día%s %s" % (d, "" if d == 1 else "s", ref)) if d >= 0 else f"{ref} pasó hace {-d} d")
    if c["elegibles"]:
        partes.append("elegible en " + " + ".join(f"{n} ítems ({cu})" for cu, n in sorted(c["elegibles"].items()) if isinstance(n, int)))
    return " · ".join(partes)


def _orden(c: dict):
    return (c["dias_faltan"] is None, c["dias_faltan"] if c["dias_faltan"] is not None else 0, c["nombre"])


def calendario(ml, hoy: date, dias_aviso: int = DIAS_AVISO, con_elegibles: bool = True, cuentas=None, incluir_finalizadas: bool = False,
               workers: int = 6) -> dict:
    """`ml`: `MLOfertasClient` (inyectable). Una cuenta que falla no tira la otra: queda en `cuentas_consultadas` con su error."""
    cuentas = list(cuentas or SELLERS)
    por_cuenta, estado, avisos = {}, {}, []
    for cuenta in cuentas:
        try:
            crudas = ml.promociones_seller(cuenta)
            por_cuenta[cuenta] = [normalizar(p, cuenta) for p in crudas if isinstance(p, dict)]
            estado[cuenta] = {"ok": True, "campanas": len(por_cuenta[cuenta]), "error": None}
        except Exception as e:  # noqa: BLE001 -- 403 / token vencido / ML caído: se informa, no se corta
            por_cuenta[cuenta] = []
            estado[cuenta] = {"ok": False, "campanas": 0, "error": f"{type(e).__name__}: {e}"}
            avisos.append(f"No se pudo consultar la cuenta {cuenta} ({type(e).__name__}: {e}): el aviso sale sin sus campañas.")
    fusionadas = fusionar(por_cuenta)
    if not incluir_finalizadas:
        fusionadas = [c for c in fusionadas if c["estado"] != "finished" and not (c["fin"] and c["fin"] < hoy)]
    if con_elegibles:
        def contar(par):
            c, cuenta = par
            pid = c["ids_por_cuenta"][cuenta]
            try:
                return c, cuenta, ml.contar_items_promocion(pid, c["tipo"], cuenta, "candidate"), ml.contar_items_promocion(pid, c["tipo"], cuenta, "started"), None
            except Exception as e:  # noqa: BLE001
                return c, cuenta, None, None, f"{type(e).__name__}: {e}"
        tareas = [(c, cu) for c in fusionadas for cu in c["cuentas"] if c["id"] or c["ids_por_cuenta"].get(cu)]
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for c, cuenta, cand, ok, err in ex.map(contar, tareas):
                c.setdefault("elegibles", {})[cuenta] = cand if err is None else None
                c.setdefault("aceptados", {})[cuenta] = ok if err is None else None
                if err:
                    avisos.append(f"Elegibles de {c['nombre'] or c['id']} ({cuenta}): {err}")
    filas = sorted((enriquecer(c, hoy, dias_aviso) for c in fusionadas), key=_orden)
    for f in filas:
        f["texto"] = linea(f)
    especiales = [f for f in filas if f["seccion"] == "especial"]
    cupones = [f for f in filas if f["seccion"] == "cupon_operativa"]
    a_aviso = [f for f in filas if f["a_dias_aviso"]]
    sin_fecha = [f for f in filas if f["sin_fecha"]]
    if sin_fecha:
        avisos.append(f"{len(sin_fecha)} campaña(s) sin fecha de inicio ni límite en la respuesta de ML: no se pueden contar sus días "
                      "(ver `diagnostico.campanas_sin_fecha`).")
    desconocidos = sorted({f["tipo"] for f in filas if f["tipo_desconocido"]})
    if desconocidos:
        avisos.append(f"Tipos de campaña sin clasificar (van a especiales): {', '.join(map(str, desconocidos))}.")
    asunto = (f"⚠ {len(a_aviso)} campaña(s) de ML a {dias_aviso} días: " + ", ".join(f["nombre"] for f in a_aviso[:3]) + ("…" if len(a_aviso) > 3 else "")
              if a_aviso else f"Calendario de campañas de ML · {hoy.strftime('%d/%m/%Y')}")
    return {
        "fecha": hoy.isoformat(), "dias_aviso": dias_aviso, "asunto": asunto, "hay_aviso_destacado": bool(a_aviso),
        "cuentas_consultadas": estado,
        "resumen": {"campanas": len(filas), "especiales": len(especiales), "cupones_operativas": len(cupones), "a_dias_aviso": len(a_aviso),
                    "en_las_dos_cuentas": sum(1 for f in filas if len(f["cuentas"]) > 1)},
        "a_5_dias": a_aviso,          # las que están a `dias_aviso` días (5 por defecto): el aviso destacado
        "especiales": especiales, "cupones_operativas": cupones, "avisos": avisos,
        "diagnostico": {"campanas_sin_fecha": [{"id": f["id"], "nombre": f["nombre"], "tipo": f["tipo"], "cuentas": f["cuentas"]} for f in sin_fecha],
                        "claves_vistas": sorted({k for c in fusionadas for k in c["claves"]})},
    }
