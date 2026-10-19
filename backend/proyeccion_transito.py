"""GET /proyeccion-2027/transito -- requerimientos abiertos de Táctica (mercadería pedida y en tránsito) por SKU. SOLO LECTURA.

Alimenta el tablero Proyección 2027 con lo que hoy el modelo no ve (pedidos abiertos). Solo SELECT contra Táctica: nada se escribe allá.

Lógica (decodificada con el diagnóstico y confirmada con Maxx):
  requerimientos r + requerimientositems ri (ri.IDRequerimiento = r.RecID) + fiscal (proveedor, por r.IDFiscal).
  ABIERTO      = requerimientos.Estado = 0. Se EXCLUYEN Estado 1 (cerrado) y Estado 2 (sin decodificar: no se sabe qué significa, no se cuenta).
  pendiente    = pedido (requerimientositems.Cantidad). El recibido por comprasitems y el comprometido a clientes son INFORMATIVOS: Táctica casi no
                 registra recepciones contra el requerimiento, así que no se restan.
  recibido     = SUM(comprasitems.Cantidad) por IDReqProd = ri.RecID (comprasitems -> compras por IDCompra)      [informativo]
  comprometido = SUM(requerimientositemsclientes.Cantidad) por IDReqProd = ri.RecID                              [informativo]
  fecha        = la del ítem (requerimientositems.FechaEntrega); si es nula, 2001-01-01 o anterior a 2020, la de cabecera
                 (requerimientos.FechaEntrega); si las dos son inválidas, "sin fecha"
  antigüedad   = días desde requerimientos.FechaCreacion (es de la cabecera: todos los ítems de un requerimiento tienen la misma)
                 más de 180 días -> `revisar`; más de 365 -> `excluido`: sigue listado pero NO entra al cálculo (por SKU ni por requerimiento).
                 Sin FechaCreacion válida no se puede medir la antigüedad: el requerimiento queda en el cálculo y se cuenta en la calidad.
  SKU          = ri.Codigo (sin el padding de Táctica), con respaldo por `productos` si el ítem no trae código

Modos:
  GET /proyeccion-2027/transito                  ítems abiertos + resumen por requerimiento + resumen por SKU + informe de calidad (con proveedor)
  GET /proyeccion-2027/transito?diagnostico=1    para decodificar los estados de Táctica: NO devuelve proveedores ni costos.
      [&reqs=9001,9002,...]                      números de requerimiento a contrastar (si coinciden con r.ID o con r.Numero)
      Incluye: estados, FechaDespacho por estado de requerimiento, recibido / cantidad de compras por compras.Estado y, por requerimiento,
      cuántos `pedidos` (de clientes) tienen IDRequerimiento igual a su RecID (¿ahí está la reserva de clientes?).

Garantías: X-ERP-Key obligatoria (falla cerrado: 503 sin ERP_API_KEY), solo SELECT de texto fijo (lo único que viene del usuario es `reqs`,
validado como enteros y mandado como parámetro, nunca concatenado), lecturas sin bloqueos (WITH (NOLOCK)), timeout de login y de consulta, tope de filas.
Un error de conexión no devuelve el texto de la excepción (podría traer servidor o usuario); los errores de esquema ("Invalid column name ...") sí, filtrados.

ESQUEMA: cada columna de cada SELECT se verificó contra el esquema real de Táctica (INFORMATION_SCHEMA). `fiscal` y `productos` no estaban en ese listado:
sus columnas (RecID, RazonSocial, Codigo) son las de las consultas que ya corren en producción (ingesta_tactica / adapters). En `requerimientos` no existe
`Fecha`: la fecha de cabecera es `FechaEntrega`. Si el esquema cambia, el endpoint responde 502 con "Invalid column name 'X'".
"""
import os
import re
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from erp_auth import HEADER_CLAVE, clave_valida
from rentabilidad import config

router = APIRouter(prefix="/proyeccion-2027", tags=["proyeccion-2027"])

LOGIN_TIMEOUT_SEG = 20
QUERY_TIMEOUT_SEG = 30
TOPE_FILAS = 5000
MAX_REQS = 500
ESTADO_ABIERTO = 0      # requerimientos.Estado: 0 = abierto; 1 = cerrado; 2 = sin decodificar (1 y 2 se excluyen)
REVISAR_MAS_DE_DIAS = 180
EXCLUIR_MAS_DE_DIAS = 365
FECHA_PLACEHOLDER = date(2001, 1, 1)
FECHA_MINIMA_VALIDA = date(2020, 1, 1)

# Columnas reales de Táctica (verificadas contra el esquema). Solo identificadores de código, nunca texto del usuario.
C_PEDIDO = "Cantidad"          # requerimientositems: unidades pedidas
C_FECHA_ITEM = "FechaEntrega"  # requerimientositems: fecha estimada del ítem
C_FECHA_CAB = "FechaEntrega"   # requerimientos: fecha de cabecera (no existe `Fecha`)
C_CREACION = "FechaCreacion"   # requerimientos: de acá sale la antigüedad
C_PRODUCTO = "IDProducto"      # requerimientositems -> productos.RecID (respaldo del SKU)

_FMT = dict(n=TOPE_FILAS + 1, pedido=C_PEDIDO, fecha_item=C_FECHA_ITEM, fecha_cab=C_FECHA_CAB, creacion=C_CREACION, producto=C_PRODUCTO, abierto=ESTADO_ABIERTO)

# Subconsultas por ítem (una fila por IDReqProd): evitan multiplicar filas al unir varias compras / clientes.
_RECIBIDO = """(SELECT ci.IDReqProd, SUM(ci.Cantidad) AS recibido
         FROM comprasitems ci WITH (NOLOCK) JOIN compras c WITH (NOLOCK) ON c.RecID = ci.IDCompra
         GROUP BY ci.IDReqProd)"""
_COMPROMETIDO = """(SELECT rc.IDReqProd, SUM(rc.Cantidad) AS comprometido
         FROM requerimientositemsclientes rc WITH (NOLOCK) GROUP BY rc.IDReqProd)"""
# Pedidos (de clientes) cuyo IDRequerimiento apunta al requerimiento: una fila por requerimiento.
_PEDIDOS_POR_REQ = """(SELECT pd.IDRequerimiento, COUNT(*) AS pedidos
         FROM pedidos pd WITH (NOLOCK) GROUP BY pd.IDRequerimiento)"""

def _invalida(col):
    """Fragmento SQL: fecha nula, 2001-01-01 o anterior a 2020 (mismo criterio que `_motivo`)."""
    return "({c} IS NULL OR CAST({c} AS date) = '20010101' OR CAST({c} AS date) < '20200101')".format(c=col)


_ITEM_INVALIDA = _invalida("ri.{fecha_item}".format(**_FMT))
_CAB_INVALIDA = _invalida("r.{fecha_cab}".format(**_FMT))

_SQL_ITEMS = """
SELECT TOP ({n})
    r.RecID AS req_recid, r.ID AS req_id, r.Estado AS estado, fis.RazonSocial AS proveedor,
    ri.RecID AS item_recid, ri.Codigo AS codigo_item, pm.Codigo AS en_maestro, pf.Codigo AS codigo_respaldo,
    ri.{pedido} AS pedido, ISNULL(rec.recibido, 0) AS recibido, ISNULL(com.comprometido, 0) AS comprometido,
    ri.{fecha_item} AS fecha_item, r.{fecha_cab} AS fecha_cab, r.{creacion} AS fecha_creacion
FROM requerimientos r WITH (NOLOCK)
JOIN requerimientositems ri WITH (NOLOCK) ON ri.IDRequerimiento = r.RecID
LEFT JOIN fiscal fis WITH (NOLOCK) ON fis.RecID = r.IDFiscal
OUTER APPLY (SELECT TOP 1 p.Codigo FROM productos p WITH (NOLOCK) WHERE p.Codigo = ri.Codigo) pm
OUTER APPLY (SELECT TOP 1 p.Codigo FROM productos p WITH (NOLOCK) WHERE p.RecID = ri.{producto}) pf
LEFT JOIN {recibido} rec ON rec.IDReqProd = ri.RecID
LEFT JOIN {comprometido} com ON com.IDReqProd = ri.RecID
WHERE r.Estado = {abierto} AND ri.{pedido} > 0
ORDER BY r.ID, ri.RecID
""".format(recibido=_RECIBIDO, comprometido=_COMPROMETIDO, **_FMT)

# Diagnóstico 1: requerimientos e ítems por Estado y cuántos ítems tienen fecha inválida. Sin proveedores ni costos.
_SQL_DIAG_ESTADOS = """
SELECT TOP ({n}) r.Estado AS estado, COUNT(DISTINCT r.RecID) AS requerimientos, COUNT(ri.RecID) AS items,
    SUM(CASE WHEN ri.RecID IS NOT NULL AND {item_invalida} THEN 1 ELSE 0 END) AS items_fecha_propia_invalida,
    SUM(CASE WHEN ri.RecID IS NOT NULL AND {item_invalida} AND {cab_invalida} THEN 1 ELSE 0 END) AS items_sin_fecha
FROM requerimientos r WITH (NOLOCK)
LEFT JOIN requerimientositems ri WITH (NOLOCK) ON ri.IDRequerimiento = r.RecID
GROUP BY r.Estado
ORDER BY r.Estado
""".format(item_invalida=_ITEM_INVALIDA, cab_invalida=_CAB_INVALIDA, **_FMT)

# Diagnóstico 2: por cada número recibido, ¿coincide con r.ID o con r.Numero? (se compara como texto: no se asume el tipo de la columna).
_SQL_DIAG_REQS = """
SELECT TOP ({n}) r.RecID AS req_recid, r.ID AS req_id, r.Numero AS req_numero, r.Estado AS estado,
    CASE WHEN CAST(r.ID AS varchar(40)) IN %(reqs)s THEN 1 ELSE 0 END AS coincide_id,
    CASE WHEN CAST(r.Numero AS varchar(40)) IN %(reqs)s THEN 1 ELSE 0 END AS coincide_numero,
    COUNT(ri.RecID) AS items,
    SUM(ISNULL(ri.{pedido}, 0)) AS pedido,
    SUM(ISNULL(rec.recibido, 0)) AS recibido,
    SUM(CASE WHEN ri.{pedido} - ISNULL(rec.recibido, 0) > 0 THEN ri.{pedido} - ISNULL(rec.recibido, 0) ELSE 0 END) AS pendiente,
    SUM(ISNULL(com.comprometido, 0)) AS comprometido,
    MAX(ISNULL(ped.pedidos, 0)) AS pedidos_vinculados
FROM requerimientos r WITH (NOLOCK)
LEFT JOIN requerimientositems ri WITH (NOLOCK) ON ri.IDRequerimiento = r.RecID
LEFT JOIN {recibido} rec ON rec.IDReqProd = ri.RecID
LEFT JOIN {comprometido} com ON com.IDReqProd = ri.RecID
LEFT JOIN {pedidos} ped ON ped.IDRequerimiento = r.RecID
WHERE CAST(r.ID AS varchar(40)) IN %(reqs)s OR CAST(r.Numero AS varchar(40)) IN %(reqs)s
GROUP BY r.RecID, r.ID, r.Numero, r.Estado
ORDER BY r.RecID
""".format(recibido=_RECIBIDO, comprometido=_COMPROMETIDO, pedidos=_PEDIDOS_POR_REQ, **_FMT)

# Diagnóstico 3: requerimientos con compra que tienen compras.FechaDespacho cargada (válida / inválida), por Estado.
_SQL_DIAG_DESPACHO = """
SELECT TOP ({n}) r.Estado AS estado,
    COUNT(DISTINCT r.RecID) AS requerimientos_con_compra,
    COUNT(DISTINCT CASE WHEN c.FechaDespacho IS NOT NULL AND CAST(c.FechaDespacho AS date) >= '20200101' THEN r.RecID END) AS con_fecha_despacho,
    COUNT(DISTINCT CASE WHEN c.FechaDespacho IS NOT NULL AND CAST(c.FechaDespacho AS date) < '20200101' THEN r.RecID END) AS con_fecha_despacho_invalida
FROM requerimientos r WITH (NOLOCK)
JOIN requerimientositems ri WITH (NOLOCK) ON ri.IDRequerimiento = r.RecID
JOIN comprasitems ci WITH (NOLOCK) ON ci.IDReqProd = ri.RecID
JOIN compras c WITH (NOLOCK) ON c.RecID = ci.IDCompra
GROUP BY r.Estado
ORDER BY r.Estado
""".format(**_FMT)

# Diagnóstico 4: recibido y cantidad de compras por compras.Estado (solo compras con ítems ligados a un ítem de requerimiento).
_SQL_DIAG_COMPRAS = """
SELECT TOP ({n}) c.Estado AS estado, COUNT(DISTINCT c.RecID) AS compras, COUNT(ci.RecID) AS items_recibidos,
    SUM(ISNULL(ci.Cantidad, 0)) AS recibido
FROM compras c WITH (NOLOCK)
JOIN comprasitems ci WITH (NOLOCK) ON ci.IDCompra = c.RecID
JOIN requerimientositems ri WITH (NOLOCK) ON ri.RecID = ci.IDReqProd
GROUP BY c.Estado
ORDER BY c.Estado
""".format(**_FMT)


# ── Acceso ───────────────────────────────────────────────────────────────

def _exigir_clave(request: Request):
    esperada = os.environ.get("ERP_API_KEY", "").strip()
    if not esperada:
        raise HTTPException(status_code=503, detail="ERP_API_KEY no está definida en el servidor: este endpoint no responde sin clave.")
    if not clave_valida(esperada, request.headers.get(HEADER_CLAVE)):
        raise HTTPException(status_code=401, detail="X-ERP-Key inválida o ausente")


def _conectar():
    """Import perezoso de pymssql (igual que ingesta_tactica / adapters) y mismas variables RENT_TACTICA_SQL_*."""
    import pymssql

    return pymssql.connect(
        server=config.requerido("RENT_TACTICA_SQL_SERVER"),
        user=config.requerido("RENT_TACTICA_SQL_USER"),
        password=config.requerido("RENT_TACTICA_SQL_PASSWORD"),
        database=config.requerido("RENT_TACTICA_SQL_DATABASE"),
        login_timeout=LOGIN_TIMEOUT_SEG,
        timeout=QUERY_TIMEOUT_SEG,
        as_dict=True,
    )


def _consultar(consultas):
    """consultas: [(sql, params|None)] -> [filas de cada una] en UNA conexión. Cada una trae hasta TOPE_FILAS + 1 filas (la de más marca el truncado)."""
    conn = _conectar()
    try:
        cur = conn.cursor()
        out = []
        for sql, params in consultas:
            if params is None:
                cur.execute(sql)
            else:
                cur.execute(sql, params)
            out.append(list(cur.fetchmany(TOPE_FILAS + 1)))
        return out
    finally:
        conn.close()


_ERRORES_DE_ESQUEMA = re.compile(r"^(Invalid (column|object) name|Ambiguous column name|The multi-part identifier|Incorrect syntax)[^\r\n]*", re.I)


def _detalle_error(e: Exception) -> str:
    """Solo la clase del error, salvo errores de esquema/sintaxis de SQL Server (nombran columnas u objetos, nunca servidor ni usuario)."""
    if type(e).__name__ == "ProgrammingError":
        a = e.args[-1] if e.args else ""
        txt = a.decode("utf-8", "replace") if isinstance(a, bytes) else str(a)
        txt = re.split(r"DB-Lib|Net-Lib", txt)[0].strip()
        m = _ERRORES_DE_ESQUEMA.match(txt)
        if m:
            return f"{type(e).__name__}: {m.group(0)[:200]}"
    return type(e).__name__


# ── Lógica pura ──────────────────────────────────────────────────────────

def _dia(v):
    if isinstance(v, datetime):
        return v.date()
    return v if isinstance(v, date) else None


def _motivo(v):
    """None si la fecha es válida; si no, por qué no: nula, placeholder_2001 (2001-01-01) o anterior_2020."""
    f = _dia(v)
    if f is None:
        return "nula"
    if f == FECHA_PLACEHOLDER:
        return "placeholder_2001"
    if f < FECHA_MINIMA_VALIDA:
        return "anterior_2020"
    return None


def clasificar_fecha(fecha_item, fecha_cab):
    """-> (fecha | None, origen | None, motivo por el que la fecha del ítem no sirvió | None).
    Ítem si es válida; si no (nula, 2001-01-01 o anterior a 2020), cabecera; si las dos son inválidas, (None, None, motivo): "sin fecha"."""
    mi = _motivo(fecha_item)
    if mi is None:
        return _dia(fecha_item), "item", None
    if _motivo(fecha_cab) is None:
        return _dia(fecha_cab), "cabecera", mi
    return None, None, mi


def _num(v):
    if v is None:
        return 0
    if isinstance(v, Decimal):
        v = float(v)
    return int(v) if float(v).is_integer() else float(v)


def _sku(codigo_item, codigo_respaldo):
    for c in (codigo_item, codigo_respaldo):
        c = (str(c).strip() if c is not None else "")
        if c:
            return c
    return None


def armar_respuesta(filas, hoy: date):
    """Filas crudas de `_SQL_ITEMS` (solo requerimientos abiertos) -> (ítems, resumen por requerimiento, resumen por SKU, calidad). Sin acceso a la base."""
    items, motivos, usaron_cabecera, sin_fecha = [], defaultdict(int), 0, 0
    vistos, duplicados, sin_maestro = defaultdict(int), set(), set()
    for f in filas:
        sku = _sku(f.get("codigo_item"), f.get("codigo_respaldo"))
        pedido = _num(f.get("pedido"))
        fecha, origen, motivo = clasificar_fecha(f.get("fecha_item"), f.get("fecha_cab"))
        creacion = _dia(f.get("fecha_creacion"))
        antig = (hoy - creacion).days if _motivo(creacion) is None else None
        en_maestro = f.get("en_maestro") is not None
        it = {"requerimiento": f.get("req_id"), "estado": f.get("estado"), "proveedor": (f.get("proveedor") or "").strip() or None,
              "sku": sku, "sku_en_maestro": en_maestro, "pendiente": pedido,
              "fecha_estimada": fecha.isoformat() if fecha else None,
              "fecha_estado": {"item": "del ítem", "cabecera": "de cabecera"}.get(origen, "sin fecha"), "fecha_item_invalida": motivo,
              "antiguedad_dias": antig, "revisar": antig is not None and antig > REVISAR_MAS_DE_DIAS, "excluido": antig is not None and antig > EXCLUIR_MAS_DE_DIAS,
              "recibido_informativo": _num(f.get("recibido")), "comprometido_informativo": _num(f.get("comprometido"))}
        items.append(it)
        if motivo:
            motivos[motivo] += 1
        usaron_cabecera += origen == "cabecera"
        sin_fecha += origen is None
        clave = (it["requerimiento"], sku)
        vistos[clave] += 1
        if vistos[clave] == 2:
            duplicados.add(clave)
        if not en_maestro and sku:
            sin_maestro.add(sku)
    # Por requerimiento (para cruzar con el Excel de Marcelo): todos los ítems abiertos, también los excluidos por antigüedad (con su marca).
    reqs = {}
    for it in items:
        r = reqs.setdefault(it["requerimiento"], {"requerimiento": it["requerimiento"], "estado": it["estado"], "proveedor": it["proveedor"], "items": 0, "unidades": 0,
                                                    "antiguedad_dias": it["antiguedad_dias"], "revisar": it["revisar"], "excluido": it["excluido"], "items_sin_fecha": 0, "_fechas": []})
        r["items"] += 1
        r["unidades"] += it["pendiente"]
        r["items_sin_fecha"] += it["fecha_estado"] == "sin fecha"
        if it["fecha_estimada"]:
            r["_fechas"].append(it["fecha_estimada"])
    por_requerimiento = []
    for _, r in sorted(reqs.items(), key=lambda kv: (kv[0] is None, kv[0] if isinstance(kv[0], (int, float)) else str(kv[0]))):
        fechas = r.pop("_fechas")
        por_requerimiento.append({**r, "proxima_fecha": min(fechas) if fechas else None})
    # Por SKU: solo lo que entra al cálculo (sin los excluidos por antigüedad); lo marcado `revisar` entra pero se informa aparte.
    por_sku = defaultdict(lambda: {"pendiente": 0, "a_revisar": 0, "fechas": [], "requerimientos": set(), "proveedores": set()})
    for it in items:
        if not it["sku"] or it["excluido"]:
            continue
        s = por_sku[it["sku"]]
        s["pendiente"] += it["pendiente"]
        if it["revisar"]:
            s["a_revisar"] += it["pendiente"]
        if it["fecha_estimada"]:
            s["fechas"].append(it["fecha_estimada"])
        s["requerimientos"].add(str(it["requerimiento"]))
        if it["proveedor"]:
            s["proveedores"].add(it["proveedor"])
    resumen_sku = [{"sku": k, "pendiente": v["pendiente"], "de_los_cuales_a_revisar": v["a_revisar"], "proxima_fecha": min(v["fechas"]) if v["fechas"] else None,
                    "requerimientos": sorted(v["requerimientos"]), "proveedores": sorted(v["proveedores"])} for k, v in sorted(por_sku.items())]
    revisar = [r for r in por_requerimiento if r["revisar"]]
    excluidos = [r for r in por_requerimiento if r["excluido"]]
    calidad = {
        "antiguedad": {"revisar_mas_de_dias": REVISAR_MAS_DE_DIAS, "excluir_mas_de_dias": EXCLUIR_MAS_DE_DIAS,
                       "requerimientos_a_revisar": len(revisar), "requerimientos_excluidos": len(excluidos),
                       "unidades_excluidas": sum(r["unidades"] for r in excluidos), "requerimientos_sin_antiguedad": sum(1 for r in por_requerimiento if r["antiguedad_dias"] is None)},
        "fechas": {"item_invalida": {"total": sum(motivos.values()), "nula": motivos["nula"], "placeholder_2001": motivos["placeholder_2001"], "anterior_2020": motivos["anterior_2020"]},
                   "usaron_cabecera": usaron_cabecera, "sin_fecha": sin_fecha},
        "duplicados": {"total": len(duplicados), "muestra": [{"requerimiento": k[0], "sku": k[1], "veces": vistos[k]} for k in sorted(duplicados, key=str)[:50]]},
        "sku_fuera_del_maestro": {"total": len(sin_maestro), "muestra": sorted(sin_maestro)[:50]},
        "items_sin_sku": sum(1 for i in items if not i["sku"]),
    }
    return items, por_requerimiento, resumen_sku, calidad


def _limpiar(fila):
    return {k: (v.isoformat() if isinstance(v, (date, datetime)) else _num(v) if isinstance(v, (Decimal, float)) else v) for k, v in fila.items()}


def _recortar(filas):
    return filas[:TOPE_FILAS], len(filas) > TOPE_FILAS


def _parsear_reqs(reqs: str | None) -> tuple[str, ...]:
    if reqs is None:
        return ()
    partes = [p.strip() for p in reqs.split(",") if p.strip()]
    if not partes or len(partes) > MAX_REQS or any(not re.fullmatch(r"\d{1,12}", p) for p in partes):
        raise HTTPException(status_code=422, detail=f"'reqs' debe ser una lista de 1 a {MAX_REQS} números enteros separados por coma.")
    return tuple(dict.fromkeys(partes))


# ── Endpoint ─────────────────────────────────────────────────────────────

@router.get("/transito")
def transito(request: Request, diagnostico: int = Query(0, ge=0, le=1), reqs: str | None = None):
    _exigir_clave(request)
    pedidos = _parsear_reqs(reqs)
    if pedidos and not diagnostico:
        raise HTTPException(status_code=422, detail="'reqs' solo se usa con diagnostico=1.")
    try:
        if diagnostico:
            consultas = [(_SQL_DIAG_ESTADOS, None), (_SQL_DIAG_DESPACHO, None), (_SQL_DIAG_COMPRAS, None)] + ([(_SQL_DIAG_REQS, {"reqs": pedidos})] if pedidos else [])
            res = _consultar(consultas)
        else:
            res = _consultar([(_SQL_ITEMS, None)])
    except config.ConfiguracionFaltante:
        raise  # main.py lo convierte en 503 con el nombre de la variable que falta (no el valor)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"No se pudo consultar Táctica ({_detalle_error(e)}).")
    cab = {"generado": datetime.now(timezone.utc).isoformat(timespec="seconds"), "tope": TOPE_FILAS}
    if not diagnostico:
        filas, trunc = _recortar(res[0])
        items, por_req, por_sku, calidad = armar_respuesta(filas, date.today())
        criterio = {"abierto": f"requerimientos.Estado = {ESTADO_ABIERTO} (1 = cerrado y 2 = sin decodificar quedan excluidos)",
                    "pendiente": "= unidades pedidas; recibido y comprometido son solo informativos",
                    "revisar_mas_de_dias": REVISAR_MAS_DE_DIAS, "excluido_del_calculo_mas_de_dias": EXCLUIR_MAS_DE_DIAS, "antiguedad": "desde requerimientos.FechaCreacion"}
        return JSONResponse({**cab, "criterio": criterio, "truncado": trunc, "total_items": len(items), "items": items, "por_requerimiento": por_req, "por_sku": por_sku, "calidad": calidad},
                            headers={"Cache-Control": "no-store"})
    estados, t1 = _recortar(res[0])
    despacho, t3 = _recortar(res[1])
    compras, t4 = _recortar(res[2])
    out = {**cab, "modo": "diagnostico",
           "nota": "No incluye proveedores ni costos. 'estado' es el valor crudo de requerimientos.Estado.",
           "por_estado": [_limpiar(f) for f in estados], "despacho_por_estado": [_limpiar(f) for f in despacho],
           "compras_por_estado": [_limpiar(f) for f in compras], "truncado": t1 or t3 or t4}
    if pedidos:
        reqf, t2 = _recortar(res[3])
        por_req = [_limpiar(f) for f in reqf]
        hay_id = {str(f["req_id"]) for f in por_req if f["coincide_id"]}
        hay_num = {str(f["req_numero"]) for f in por_req if f["coincide_numero"]}
        out["pedidos"] = {"recibidos": len(pedidos), "coinciden_por_id": sum(1 for p in pedidos if p in hay_id), "coinciden_por_numero": sum(1 for p in pedidos if p in hay_num),
                          "sin_coincidencia": [p for p in pedidos if p not in hay_id and p not in hay_num]}
        out["por_requerimiento"] = por_req
        out["truncado"] = out["truncado"] or t2
    return JSONResponse(out, headers={"Cache-Control": "no-store"})
