"""Verificar Ecom BR — ETAPA 1 (solo lectura): bajar la base de stock del Ecom de Brasil y simular un Excel de cantidades nuevas, sin escribir nada.

Otra instancia del mismo sistema (EcomExperts / EcomGestión): mismo host y mismas llamadas, otras claves (`ECOM_BR_EMAIL` / `ECOM_BR_PASSWORD`, separadas de las de Argentina).
Se reutiliza `EcomApiClient` (login `users/users/doLogin.json`, ÚLTIMA cookie `CAKEPHP`, vence 00:06 UTC, relogueo ante 401/403 o error de sesión).

Reglas (las que pasó Maxx, validadas en producción manual con `stock_masivo_ecom.py`; ese script NO está en el repo: ver docs/business/ECOM_BR_STOCK.md):
- Catálogo: `products.find(page: N, filters: [{filter:"status", values:["1"]}])`, de a 30, hasta que una página no trae IDs nuevos.
- La API NO resta lo reservado (`availableQty` = stock del depósito); la pantalla de Ecom sí: Disponible = Stock total − Reservado (`commited`). En el depósito configurable
  («depósito con disponible», por defecto «Good Storage Jaguaré») la cantidad del Excel es DISPONIBLE y se escribe `cantidad + commited`; en los demás, el valor tal cual.
- Excel: SKU como texto (sin ".0" residual); cantidades enteras y no negativas; «1.000» / «1,000» son ambiguas y se rechazan; SKU duplicados con cantidades distintas, SKU inexistentes
  (con sugerencia si difiere en mayúsculas), SKU ambiguos y depósitos inexistentes se rechazan; aviso si el stock nuevo queda menor al reservado. Cantidad vacía = no se toca; 0 = poner en cero.

Esta etapa NO escribe en Ecom: la escritura (etapa 2) está bloqueada por la compuerta de escritura de docs/business/COMERCIAL/00_LEEME.md §5 hasta que se la habilite expresamente.
"""
from __future__ import annotations

import io
import os
import re
import threading
import time
import unicodedata
from datetime import datetime, timezone
from typing import Callable

DEPOSITO_DISPONIBLE_DEFECTO = "Good Storage Jaguaré"
MODULO_CONFIG = "ecom_br_config"
MAX_PAGINAS = 400
REINTENTOS_PAGINA = 3
VIGENCIA_CATALOGO_SEG = 15 * 60       # una simulación reutiliza el catálogo si tiene menos de esto; si no, lo vuelve a bajar
MAX_FILAS_EXCEL = 60000

QUERY_CATALOGO = """
query CatalogoStockBR($page: Int) {
  products {
    find(page: $page, filters: [{filter: "status", values: ["1"]}]) {
      pageInfo { page pageCount count }
      data {
        id sku title active
        variants { id sku qty cost availableQty commited variantPrices { title price } variantWarehouses { warehouse_title warehouse_qty } }
      }
    }
  }
}
"""

_lock = threading.Lock()
_catalogo: dict | None = None            # {"obtenido_en", "variantes", "depositos", "productos"}
_jobs: dict[str, dict] = {}
_archivos: dict[str, tuple[float, bytes]] = {}      # job_id -> (cuándo, xlsx): descargas pendientes
_simulaciones: dict[str, dict] = {}                 # job_id -> simulación completa (la usará la etapa 2)


class EcomBRNoConfigurado(RuntimeError):
    pass


class EcomBRError(RuntimeError):
    pass


def estado_job(job_id: str) -> dict | None:
    return _jobs.get(job_id)


# ── Configuración ──

def credenciales_configuradas(env: dict | None = None) -> bool:
    env = os.environ if env is None else env
    return bool(env.get("ECOM_BR_EMAIL") and env.get("ECOM_BR_PASSWORD"))


def deposito_disponible(sesion_fn=None) -> str:
    """Depósito en el que la cantidad del Excel es DISPONIBLE (se le suma lo reservado al escribir). Es configuración, no está fijo en el código: lo guardado en la base
    (pantalla) → variable `ECOM_BR_DEPOSITO_DISPONIBLE` → valor por defecto."""
    try:
        import ml_foto
        if sesion_fn is None:
            from rentabilidad.db import sesion as sesion_fn
        with sesion_fn() as db:
            f = ml_foto.leer(db, MODULO_CONFIG, "BR", "")
            v = ((f.payload or {}).get("deposito_disponible") if f is not None else None)
            if v:
                return str(v)
    except Exception:  # noqa: BLE001  (sin base se usa la variable o el defecto)
        pass
    return os.environ.get("ECOM_BR_DEPOSITO_DISPONIBLE") or DEPOSITO_DISPONIBLE_DEFECTO


def guardar_deposito_disponible(valor: str, sesion_fn=None) -> str:
    valor = (valor or "").strip()
    if not valor:
        raise ValueError("El nombre del depósito no puede estar vacío.")
    import ml_foto
    if sesion_fn is None:
        from rentabilidad.db import sesion as sesion_fn
    with sesion_fn() as db:
        ml_foto.guardar_exito(db, MODULO_CONFIG, "BR", "", {"deposito_disponible": valor}, "ok", 0, 0.0, [])
    return valor


def cliente_br():
    """Cliente del Ecom de Brasil con SUS credenciales (nunca las de Argentina)."""
    email, password = os.environ.get("ECOM_BR_EMAIL"), os.environ.get("ECOM_BR_PASSWORD")
    if not (email and password):
        raise EcomBRNoConfigurado("Faltan las variables ECOM_BR_EMAIL y ECOM_BR_PASSWORD en Railway.")
    from rentabilidad.ingesta_ecom_api import EcomApiClient
    return EcomApiClient(email=email, password=password)


# ── Catálogo ──

def _num(v, defecto=0):
    try:
        if v is None or v == "":
            return defecto
        f = float(v)
        return int(f) if f == int(f) else f
    except (TypeError, ValueError):
        return defecto


def bajar_productos(cliente, progreso: Callable[[int, str], None] | None = None, dormir: Callable[[float], None] = time.sleep) -> list[dict]:
    """Todas las páginas de `products.find` (activos), de a 30, hasta que una página no trae IDs nuevos."""
    productos: list[dict] = []
    vistos: set = set()
    pagina = 1
    while pagina <= MAX_PAGINAS:
        data, ultimo = None, None
        for intento in range(REINTENTOS_PAGINA):
            try:
                data = cliente.graphql(QUERY_CATALOGO, {"page": pagina})["products"]["find"]
                break
            except Exception as e:  # noqa: BLE001  (el servidor de Ecom a veces devuelve errores sueltos)
                ultimo = e
                dormir(2 ** (intento + 1))
        if data is None:
            raise EcomBRError(f"Ecom Brasil no devolvió la página {pagina} del catálogo: {type(ultimo).__name__}")
        filas = data.get("data") or []
        nuevos = [p for p in filas if p.get("id") not in vistos]
        if not nuevos:
            break
        for p in nuevos:
            vistos.add(p.get("id"))
            productos.append(p)
        if progreso:
            progreso(len(productos), f"Leyendo el catálogo de Ecom Brasil: {len(productos)} productos")
        pagina += 1
    if not productos:
        raise EcomBRError("El catálogo de Ecom Brasil vino vacío.")
    return productos


def normalizar(productos: list[dict]) -> dict:
    """Una fila por variante (con sus depósitos) y el conjunto de depósitos conocidos."""
    variantes: list[dict] = []
    depositos: dict[str, str] = {}
    for p in productos:
        for v in p.get("variants") or []:
            almacenes: dict[str, int | float] = {}
            for w in v.get("variantWarehouses") or []:
                t = str(w.get("warehouse_title") or "").strip()
                if t:
                    almacenes[t] = _num(w.get("warehouse_qty"))
                    depositos[_clave_texto(t)] = t
            variantes.append({
                "variante_id": v.get("id"), "producto_id": p.get("id"), "sku": _sku_texto(v.get("sku")), "sku_producto": _sku_texto(p.get("sku")),
                "titulo": str(p.get("title") or ""), "activo": p.get("active"), "reservado": _num(v.get("commited")), "qty": _num(v.get("qty")),
                "disponible_api": _num(v.get("availableQty")), "costo": v.get("cost"), "precios": v.get("variantPrices") or [], "depositos": almacenes,
            })
    return {"variantes": variantes, "depositos": depositos, "productos": len(productos)}


def catalogo_en_memoria() -> dict | None:
    with _lock:
        return _catalogo


def asegurar_catalogo(progreso: Callable[[int, str], None] | None = None, forzar: bool = False, max_edad_seg: float = VIGENCIA_CATALOGO_SEG, cliente=None) -> dict:
    global _catalogo
    with _lock:
        actual = _catalogo
    if actual and not forzar and time.time() - actual["obtenido_en"] <= max_edad_seg:
        return actual
    productos = bajar_productos(cliente or cliente_br(), progreso)
    nuevo = {**normalizar(productos), "obtenido_en": time.time()}
    with _lock:
        _catalogo = nuevo
    return nuevo


def resumen_catalogo() -> dict | None:
    c = catalogo_en_memoria()
    if not c:
        return None
    return {"obtenido_en": datetime.fromtimestamp(c["obtenido_en"], timezone.utc).isoformat(), "productos": c["productos"], "variantes": len(c["variantes"]), "depositos": sorted(c["depositos"].values())}


# ── Textos ──

_INVISIBLES = dict.fromkeys(map(ord, "​‌‍⁠﻿"), None)


def _sku_texto(v) -> str:
    """SKU como texto: sin espacios raros / invisibles y sin el «.0» que deja Excel al leer un número."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return ""
    if isinstance(v, float) and v == int(v):
        v = int(v)
    t = str(v).replace("\xa0", " ").translate(_INVISIBLES).strip()
    return re.sub(r"^(\d+)\.0+$", r"\1", t)


def _clave_texto(t: str) -> str:
    return unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().casefold().strip()


# ── Cuentas ──

def es_deposito_disponible(titulo: str, deposito_disp: str) -> bool:
    return _clave_texto(titulo) == _clave_texto(deposito_disp)


def disponible_de(stock, reservado, titulo: str, deposito_disp: str):
    """Disponible tal como lo muestra Ecom en el depósito con disponible (stock − reservado); en los demás depósitos el valor se escribe tal cual: disponible = stock."""
    return stock - reservado if es_deposito_disponible(titulo, deposito_disp) else stock


def stock_a_escribir(cantidad: int, reservado, titulo: str, deposito_disp: str):
    """Valor que habría que escribir en `warehouse_qty`: en el depósito con disponible, cantidad + reservado; en los demás, la cantidad."""
    return cantidad + reservado if es_deposito_disponible(titulo, deposito_disp) else cantidad


# ── Excel: base ──

COLUMNAS_BASE = ["SKU variante", "SKU producto", "Título", "Depósito", "Stock depósito", "Reservado", "Disponible", "Cantidad nueva"]


def filas_base(catalogo: dict, deposito_disp: str) -> list[list]:
    filas = []
    for v in sorted(catalogo["variantes"], key=lambda x: (x["sku_producto"].casefold(), x["sku"].casefold())):
        for dep in sorted(v["depositos"], key=str.casefold):
            stock = v["depositos"][dep]
            filas.append([v["sku"], v["sku_producto"], v["titulo"], dep, stock, v["reservado"], disponible_de(stock, v["reservado"], dep, deposito_disp), None])
    return filas


def base_xlsx(catalogo: dict, deposito_disp: str) -> bytes:
    """Excel prolijo: pestañas «Base Stock» e «Instrucciones», sin cuadrícula, encabezado fijo, filtro y la columna «Cantidad nueva» resaltada para completar."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Base Stock"
    ws.sheet_view.showGridLines = False
    ws.append(COLUMNAS_BASE)
    for f in filas_base(catalogo, deposito_disp):
        ws.append(f)
    cab = PatternFill("solid", fgColor="D9EEF3")
    nueva = PatternFill("solid", fgColor="FFF6CC")
    for c in ws[1]:
        c.font = Font(bold=True, color="1F3A46")
        c.fill = cab
        c.alignment = Alignment(vertical="center", horizontal="center" if c.column >= 5 else "left", wrap_text=True)
    ws.row_dimensions[1].height = 30
    anchos = [24, 24, 52, 26, 15, 12, 12, 16]
    for i, a in enumerate(anchos, start=1):
        ws.column_dimensions[get_column_letter(i)].width = a
    for fila in ws.iter_rows(min_row=2):
        for c in fila:
            c.alignment = Alignment(vertical="center", horizontal="right" if c.column >= 5 else "left")
            if c.column >= 5:
                c.number_format = "#,##0"
            if c.column == 8:
                c.fill = nueva
    for c in ws["A"][1:] + ws["B"][1:]:
        c.number_format = "@"             # SKU como texto
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNAS_BASE))}{max(ws.max_row, 1)}"
    ws.sheet_properties.tabColor = "009DBC"

    ins = wb.create_sheet("Instrucciones")
    ins.sheet_view.showGridLines = False
    ins.column_dimensions["A"].width = 120
    texto = [
        ("Cómo usar esta planilla", True),
        ("1. Completá SOLO la columna «Cantidad nueva» (amarilla) de las filas que quieras cambiar. Las filas con la celda vacía NO se tocan; un 0 significa poner el stock en cero.", False),
        ("2. Las cantidades son números enteros y no negativos. No uses puntos ni comas de miles (1.000 / 1,000 se rechazan por ambiguas): escribí 1000.", False),
        (f"3. En el depósito «{deposito_disp}» la cantidad es DISPONIBLE (lo que muestra Ecom: stock total − reservado); al aplicar se le suma lo reservado. En los demás depósitos se escribe el valor tal cual.", False),
        ("4. Dejá el SKU variante y el Depósito como están: la carga identifica cada fila por esas dos columnas.", False),
        ("5. Subí el archivo en «Verificar Ecom BR → Subir Excel»: primero muestra una vista previa de qué cambiaría, sin escribir nada.", False),
        (f"Base generada el {datetime.now().strftime('%d/%m/%Y %H:%M')}.", False),
    ]
    for t, negrita in texto:
        ins.append([t])
        c = ins.cell(row=ins.max_row, column=1)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        c.font = Font(bold=negrita, size=13 if negrita else 11)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# ── Excel: lectura y validación ──

ENCABEZADOS = {"sku variante": "sku", "sku": "sku", "deposito": "deposito", "cantidad nueva": "cantidad", "cantidad": "cantidad"}
_RE_MILES = re.compile(r"^\d{1,3}([.,]\d{3})+$")
_RE_ENTERO = re.compile(r"^\d+$")
_RE_CERO_DECIMAL = re.compile(r"^(\d+)[.,]0{1,2}$")


def parsear_cantidad(v) -> tuple[str, int | None, str | None]:
    """(estado, valor, motivo): `vacia` | `ok` | `invalida` | `ambigua`."""
    if v is None:
        return "vacia", None, None
    if isinstance(v, bool):
        return "invalida", None, "La cantidad no es un número."
    if isinstance(v, (int, float)):
        if v != v:
            return "vacia", None, None
        if v < 0:
            return "invalida", None, "La cantidad no puede ser negativa."
        if float(v) != int(v):
            return "invalida", None, f"La cantidad tiene que ser un número entero (vino {v})."
        return "ok", int(v), None
    t = str(v).replace("\xa0", " ").translate(_INVISIBLES).strip()
    if t == "":
        return "vacia", None, None
    if t.startswith("-"):
        return "invalida", None, "La cantidad no puede ser negativa."
    if _RE_MILES.match(t):
        return "ambigua", None, f"«{t}» es ambigua (¿mil o uno con decimales?): escribí el número entero sin puntos ni comas."
    if _RE_ENTERO.match(t):
        return "ok", int(t), None
    m = _RE_CERO_DECIMAL.match(t)
    if m:
        return "ok", int(m.group(1)), None
    return "invalida", None, f"«{t}» no es un número entero."


def leer_excel(contenido: bytes) -> dict:
    """{"filas": [{"fila", "sku", "deposito", "cantidad_estado", "cantidad", "motivo"}], "errores": [...]}; solo lee, no toca nada."""
    from openpyxl import load_workbook
    try:
        wb = load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
    except Exception as e:  # noqa: BLE001
        return {"filas": [], "errores": [f"No se pudo leer el archivo como Excel (.xlsx): {type(e).__name__}"]}
    ws = next((w for w in wb.worksheets if _clave_texto(w.title) == "base stock"), wb.worksheets[0])
    rows = ws.iter_rows(values_only=True)
    cab = next(rows, None)
    if not cab:
        return {"filas": [], "errores": ["El Excel está vacío."]}
    cols: dict[str, int] = {}
    for i, h in enumerate(cab):
        k = ENCABEZADOS.get(_clave_texto(h or ""))
        if k and k not in cols:
            cols[k] = i
    faltan = [n for n, k in (("SKU variante", "sku"), ("Depósito", "deposito"), ("Cantidad nueva", "cantidad")) if k not in cols]
    if faltan:
        return {"filas": [], "errores": [f"Faltan columnas en la primera fila: {', '.join(faltan)}."]}
    filas = []
    for n, r in enumerate(rows, start=2):
        def cel(k):
            return r[cols[k]] if cols[k] < len(r) else None
        if all(x is None or str(x).strip() == "" for x in (cel("sku"), cel("deposito"), cel("cantidad"))):
            continue
        estado, valor, motivo = parsear_cantidad(cel("cantidad"))
        filas.append({"fila": n, "sku": _sku_texto(cel("sku")), "deposito": str(cel("deposito") or "").strip(), "cantidad_estado": estado, "cantidad": valor, "motivo": motivo})
        if len(filas) > MAX_FILAS_EXCEL:
            return {"filas": [], "errores": [f"El Excel tiene más de {MAX_FILAS_EXCEL} filas."]}
    if not filas:
        return {"filas": [], "errores": ["No hay filas con datos debajo de los encabezados."]}
    return {"filas": filas, "errores": []}


# ── Simulación ──

def simular(filas: list[dict], catalogo: dict, deposito_disp: str) -> dict:
    """Vista previa fila por fila. NO escribe nada: calcula qué pasaría. Las filas con cantidad vacía no se tocan (solo se cuentan)."""
    por_sku: dict[str, list[dict]] = {}
    for v in catalogo["variantes"]:
        por_sku.setdefault(v["sku"], []).append(v)
    por_sku_min = {k.casefold(): k for k in por_sku}
    depositos = catalogo["depositos"]

    # duplicados (mismo SKU y depósito)
    grupos: dict[tuple, list[dict]] = {}
    for f in filas:
        if f["cantidad_estado"] == "vacia":
            continue
        grupos.setdefault((f["sku"], _clave_texto(f["deposito"])), []).append(f)
    distintas = {k for k, g in grupos.items() if len({x["cantidad"] for x in g if x["cantidad_estado"] == "ok"}) > 1}
    vistos_dup: set = set()

    out, omitidas = [], 0
    for f in filas:
        if f["cantidad_estado"] == "vacia":
            omitidas += 1
            continue
        base = {"fila": f["fila"], "sku": f["sku"], "deposito": f["deposito"], "cantidad": f["cantidad"], "avisos": [], "estado": "error", "mensaje": "", "titulo": "", "variante_id": None, "producto_id": None,
                "stock_actual": None, "reservado": None, "disponible_actual": None, "disponible_pedido": None, "diferencia": None, "stock_a_escribir": None}

        def error(msg, **k):
            out.append({**base, "mensaje": msg, **k})
        if f["cantidad_estado"] in ("invalida", "ambigua"):
            error(f["motivo"], codigo="cantidad_" + f["cantidad_estado"])
            continue
        if not f["sku"]:
            error("Falta el SKU variante.", codigo="sin_sku")
            continue
        clave = (f["sku"], _clave_texto(f["deposito"]))
        if clave in distintas:
            error("El mismo SKU y depósito aparece varias veces con cantidades distintas: dejá una sola fila.", codigo="duplicado")
            continue
        if clave in vistos_dup:
            omitidas += 1
            out.append({**base, "estado": "aviso_omitida", "mensaje": "Fila repetida con la misma cantidad: se cuenta una sola vez.", "codigo": "repetida"})
            continue
        vistos_dup.add(clave)
        cands = por_sku.get(f["sku"])
        if not cands:
            sug = por_sku_min.get(f["sku"].casefold())
            error(f"El SKU no existe en Ecom Brasil." + (f" ¿Quisiste decir «{sug}»? (difiere en mayúsculas/minúsculas)" if sug else ""), codigo="sku_inexistente", sugerencia=sug)
            continue
        if len(cands) > 1:
            error(f"El SKU está en {len(cands)} variantes (ambiguo): no se puede saber cuál es.", codigo="sku_ambiguo")
            continue
        v = cands[0]
        canon = depositos.get(_clave_texto(f["deposito"]))
        if not canon:
            error("El depósito no existe en Ecom Brasil.", codigo="deposito_inexistente")
            continue
        base.update(titulo=v["titulo"], variante_id=v["variante_id"], producto_id=v["producto_id"], deposito=canon)
        avisos = []
        if canon != f["deposito"]:
            avisos.append(f"Depósito escrito «{f['deposito']}»: se toma «{canon}».")
        if canon not in v["depositos"]:
            avisos.append("La variante todavía no tiene registro en ese depósito: se toma su stock como 0.")
        stock = v["depositos"].get(canon, 0)
        reservado = v["reservado"]
        disp_act = disponible_de(stock, reservado, canon, deposito_disp)
        a_escribir = stock_a_escribir(f["cantidad"], reservado, canon, deposito_disp)
        disp_ped = f["cantidad"]
        if a_escribir < reservado:
            avisos.append(f"El stock nuevo ({a_escribir}) queda menor al reservado ({reservado}).")
        if disp_ped < 0:
            avisos.append("El disponible pedido es negativo.")
        estado = "sin_cambio" if a_escribir == stock else "cambia"
        out.append({**base, "estado": estado, "stock_actual": stock, "reservado": reservado, "disponible_actual": disp_act, "disponible_pedido": disp_ped, "diferencia": disp_ped - disp_act,
                    "stock_a_escribir": a_escribir, "avisos": avisos, "mensaje": "; ".join(avisos), "codigo": estado})
    errores = [x for x in out if x["estado"] == "error"]
    resumen = {
        "filas_excel": len(filas), "omitidas_sin_cantidad": omitidas, "a_cambiar": sum(1 for x in out if x["estado"] == "cambia"), "sin_cambio": sum(1 for x in out if x["estado"] == "sin_cambio"),
        "con_error": len(errores), "con_aviso": sum(1 for x in out if x["estado"] in ("cambia", "sin_cambio") and x["avisos"]),
        "variantes": len({x["variante_id"] for x in out if x["estado"] in ("cambia", "sin_cambio")}), "productos": len({x["producto_id"] for x in out if x["estado"] in ("cambia", "sin_cambio")}),
        "deposito_disponible": deposito_disp,
    }
    return {"resumen": resumen, "filas": [x for x in out if x["estado"] != "aviso_omitida"]}


# ── Jobs ──

def _nuevo_job(job_id: str, texto: str) -> None:
    _jobs[job_id] = {"status": "running", "log": [texto], "result": None, "progress": None}


def _progreso(job_id: str):
    def cb(n: int, texto: str) -> None:
        _jobs[job_id]["progress"] = {"current": n, "total": max(n, 1), "label": texto}
    return cb


def iniciar_base(job_id: str, cliente=None, sesion_fn=None) -> None:
    """Baja el catálogo fresco y arma el Excel «Base Stock» (queda para descargar). Solo lectura."""
    _nuevo_job(job_id, "Bajando la base de stock de Ecom Brasil...")
    try:
        cat = asegurar_catalogo(_progreso(job_id), forzar=True, cliente=cliente)
        dep = deposito_disponible(sesion_fn)
        datos = base_xlsx(cat, dep)
        _archivos[job_id] = (time.time(), datos)
        for k in [k for k, (t, _) in _archivos.items() if time.time() - t > 1800]:
            _archivos.pop(k, None)
        filas = len(filas_base(cat, dep))
        _jobs[job_id].update(status="done", progress=None, result={"filas": filas, "variantes": len(cat["variantes"]), "productos": cat["productos"], "deposito_disponible": dep, "bytes": len(datos)})
        _jobs[job_id]["log"].append(f"Listo: {filas} filas ({len(cat['variantes'])} variantes).")
    except Exception as e:  # noqa: BLE001
        _jobs[job_id].update(status="error", progress=None)
        _jobs[job_id]["log"].append(f"Error: {type(e).__name__}: {e}")


def archivo_base(job_id: str) -> bytes | None:
    x = _archivos.get(job_id)
    return x[1] if x else None


def iniciar_simulacion(job_id: str, contenido: bytes, cliente=None, sesion_fn=None) -> None:
    """Lee el Excel, valida y simula contra el stock actual de Ecom Brasil. NO escribe nada."""
    _nuevo_job(job_id, "Leyendo el Excel...")
    try:
        leido = leer_excel(contenido)
        if leido["errores"]:
            _jobs[job_id].update(status="done", result={"errores": leido["errores"], "resumen": None, "filas": []}, progress=None)
            _jobs[job_id]["log"].append(leido["errores"][0])
            return
        _jobs[job_id]["log"].append(f"{len(leido['filas'])} filas leídas. Mirando el stock actual en Ecom Brasil...")
        cat = asegurar_catalogo(_progreso(job_id), cliente=cliente)
        dep = deposito_disponible(sesion_fn)
        sim = simular(leido["filas"], cat, dep)
        sim["catalogo_obtenido_en"] = datetime.fromtimestamp(cat["obtenido_en"], timezone.utc).isoformat()
        sim["errores"] = []
        _simulaciones[job_id] = sim
        _jobs[job_id].update(status="done", result=sim, progress=None)
        r = sim["resumen"]
        _jobs[job_id]["log"].append(f"Listo: {r['a_cambiar']} cambiarían, {r['sin_cambio']} sin cambio, {r['con_error']} con error. No se escribió nada.")
    except Exception as e:  # noqa: BLE001
        _jobs[job_id].update(status="error", progress=None)
        _jobs[job_id]["log"].append(f"Error: {type(e).__name__}: {e}")
