"""Tablero "Proyección de compras e inversión 2027" -- Fase 1: SOLO LECTURA.

El ERP no calcula nada acá ni escribe en ningún canal: guarda versiones del JSON del contrato de datos v1.0
(generado por `export_dashboard_data.py`) y se las sirve al front. Son datos sensibles (márgenes y costos por SKU, capital):

  - GET  /proyeccion-2027/dashboard[?version=N]   último snapshot (o el N)
  - GET  /proyeccion-2027/versiones               metadata de las versiones guardadas
  - POST /proyeccion-2027/snapshot                sube una versión nueva (conserva las últimas CONSERVAR)

Todo exige X-ERP-Key y falla CERRADO: si `ERP_API_KEY` no está definida responde 503 en vez de servir los datos
(el middleware de erp_auth.py es permisivo en ese caso, por eso se vuelve a exigir acá). Los datos reales nunca van al repo.
"""
import json
import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from erp_auth import HEADER_CLAVE, clave_valida
from rentabilidad import db as _db
from rentabilidad.models import ProyeccionSnapshot

router = APIRouter(prefix="/proyeccion-2027", tags=["proyeccion-2027"])

CONSERVAR = 20
SCHEMA_VERSION = "1.0"
MAX_BYTES = 20 * 1024 * 1024
CLAVES_OBLIGATORIAS = ("meta", "kpis", "parametros", "clases", "categorias", "plata_liberada", "canales", "tactica", "capital", "alertas",
                       "demanda_historica", "estacionalidad", "tc_bna", "skus", "compras_sku", "pendientes")


def _exigir_clave(request: Request):
    esperada = os.environ.get("ERP_API_KEY", "").strip()
    if not esperada:
        raise HTTPException(status_code=503, detail="ERP_API_KEY no está definida en el servidor: los datos de la proyección no se sirven sin clave.")
    if not clave_valida(esperada, request.headers.get(HEADER_CLAVE)):
        raise HTTPException(status_code=401, detail="X-ERP-Key inválida o ausente")


def validar_payload(d) -> list[str]:
    """Errores de forma del contrato v1.0 (vacío = válido). No valida los números: eso lo hace quien genera el JSON."""
    if not isinstance(d, dict):
        return ["el cuerpo debe ser un objeto JSON"]
    errs = [f"falta la clave '{k}'" for k in CLAVES_OBLIGATORIAS if k not in d]
    meta = d.get("meta")
    if not isinstance(meta, dict):
        errs.append("'meta' debe ser un objeto")
    else:
        if meta.get("schema_version") != SCHEMA_VERSION:
            errs.append(f"meta.schema_version debe ser '{SCHEMA_VERSION}' (llegó {meta.get('schema_version')!r})")
        if not meta.get("generado"):
            errs.append("falta meta.generado")
    sk = d.get("skus")
    if not (isinstance(sk, dict) and isinstance(sk.get("cols"), list) and isinstance(sk.get("rows"), list)):
        errs.append("'skus' debe tener 'cols' y 'rows' (listas)")
    else:
        n = len(sk["cols"])
        if any(not isinstance(r, list) or len(r) != n for r in sk["rows"]):
            errs.append("hay filas de 'skus' con distinta cantidad de columnas que 'cols'")
    cap = d.get("capital")
    if not (isinstance(cap, dict) and isinstance(cap.get("meses"), list) and isinstance(cap.get("series"), dict)):
        errs.append("'capital' debe tener 'meses' (lista) y 'series' (objeto)")
    return errs


def datos_por_sku(db) -> tuple[dict[str, dict], dict]:
    """SKU normalizado → {clase, alerta} del último snapshot (columnas `clase` y `alerta` de `skus`; la alerta puede faltar)."""
    from rentabilidad.pricing_pm import norm_sku

    f = db.query(ProyeccionSnapshot).order_by(ProyeccionSnapshot.id.desc()).first()
    if f is None:
        return {}, {}
    sk = (f.payload or {}).get("skus") or {}
    cols = [str(c).strip().lower() for c in sk.get("cols") or []]
    if "sku" not in cols:
        return {}, {"version": f.id, "generado": f.generado}
    i = cols.index("sku")
    j = cols.index("clase") if "clase" in cols else None
    k = cols.index("alerta") if "alerta" in cols else None
    out = {}
    for r in sk.get("rows") or []:
        if len(r) > i and r[i]:
            out[norm_sku(r[i])] = {"clase": str(r[j]).strip().upper() if j is not None and len(r) > j and r[j] else "",
                                   "alerta": str(r[k]).strip().upper() if k is not None and len(r) > k and r[k] else ""}
    return out, {"version": f.id, "generado": f.generado}


@router.get("/dashboard")
def dashboard(request: Request, version: int | None = None):
    _exigir_clave(request)
    with _db.sesion() as db:
        q = db.query(ProyeccionSnapshot)
        f = q.filter(ProyeccionSnapshot.id == version).first() if version is not None else q.order_by(ProyeccionSnapshot.id.desc()).first()
        if f is None:
            raise HTTPException(status_code=404, detail="No hay un snapshot de la proyección cargado" + (f" con la versión {version}" if version is not None else "") + ".")
        payload, v = f.payload, f.id
    return JSONResponse(payload, headers={"Cache-Control": "no-store", "X-Proyeccion-Version": str(v)})


@router.get("/versiones")
def versiones(request: Request):
    _exigir_clave(request)
    with _db.sesion() as db:
        filas = db.query(ProyeccionSnapshot).order_by(ProyeccionSnapshot.id.desc()).all()
        out = [{"version": f.id, "generado": f.generado, "subido_en": f.subido_en.isoformat(), "schema_version": f.schema_version, "tamano_bytes": f.tamano_bytes} for f in filas]
    return JSONResponse({"versiones": out, "conservar": CONSERVAR}, headers={"Cache-Control": "no-store"})


@router.post("/snapshot")
async def subir_snapshot(request: Request):
    _exigir_clave(request)
    cuerpo = await request.body()
    if len(cuerpo) > MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"El snapshot supera {MAX_BYTES // (1024 * 1024)} MB.")
    try:
        d = json.loads(cuerpo)
    except ValueError:
        raise HTTPException(status_code=422, detail="El cuerpo no es JSON válido.")
    errs = validar_payload(d)
    if errs:
        raise HTTPException(status_code=422, detail={"mensaje": "El snapshot no cumple el contrato de datos v1.0.", "errores": errs[:20]})
    with _db.sesion() as db:
        f = ProyeccionSnapshot(subido_en=datetime.now(timezone.utc).replace(tzinfo=None), generado=str(d["meta"]["generado"])[:32],
                               schema_version=d["meta"]["schema_version"], tamano_bytes=len(cuerpo), payload=d)
        db.add(f)
        db.flush()
        nueva = f.id
        for v in db.query(ProyeccionSnapshot).order_by(ProyeccionSnapshot.id.desc()).offset(CONSERVAR).all():
            db.delete(v)
    return {"ok": True, "version": nueva, "conservar": CONSERVAR, "tamano_bytes": len(cuerpo)}
