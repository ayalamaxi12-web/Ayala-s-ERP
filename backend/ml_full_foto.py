"""Full ML con foto guardada: conciliación de stock y simulador de reposición.

Antes cada botón disparaba la lectura entera de ML en vivo y un 429 de `stock/fulfillment/operations/search` tiraba todo el trabajo. Ahora:
  - GET  /ml-full/foto/{conciliacion|reposicion}              última foto exitosa + alertas + si hay una actualización corriendo (no lee ML)
  - POST /ml-full/foto/{conciliacion|reposicion}/actualizar   lee de a poco (ritmo bajo, reintentos con espera creciente, lotes ya leídos no se repiten)
  - GET  /ml-full/foto/estado/{job_id}                        progreso de esa actualización
  - POST /ml-full/foto/alertas/{id}/vista                     marca una alerta como vista
Solo lectura: no escribe en Mercado Libre, en Ecom ni en ningún Sheet. Los endpoints viejos (`/ml-full/conciliar/*`, `/ml-full/reposicion/*`) siguen ahí.

Datos compartidos: actualizar la reposición lee la conciliación UNA vez (o reutiliza la foto de conciliación si tiene menos de `REUSO_CONCILIACION_MIN`)
y guarda también la foto de conciliación; las dos pantallas nunca leen dos veces lo mismo. Una sola actualización corre a la vez (comparten la cuota de ML).
"""
from __future__ import annotations

import threading
import time
import uuid
from datetime import date, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException

import ml_foto
from ml_auth import SELLERS
from ml_full import (EcomFullAdapter, FilaConciliacion, MLFullClient, ResultadoConciliacion, TacticaStockSheetAdapter, conciliar, registrar_historial_conciliacion)
from ml_full import detalle_operaciones as ml_full_detalle
from ml_reposicion import calcular_reposicion_mla
from rentabilidad import db as _db
from rentabilidad.ingesta_ecom_api import EcomApiClient

router = APIRouter(prefix="/ml-full/foto", tags=["ml-full-foto"])

MOD_CONC, MOD_REPO = "full_conciliacion", "full_reposicion"
MODULOS = {"conciliacion": MOD_CONC, "reposicion": MOD_REPO}
CUENTA = "todas"
REUSO_CONCILIACION_MIN = 30

_jobs: dict[str, dict] = {}
_activo: dict[str, str] = {}      # módulo -> job_id corriendo
_turno = threading.Lock()         # una actualización a la vez
_estado_lock = threading.Lock()


# ── Serialización y alertas ──

def serializar_conciliacion(r: ResultadoConciliacion) -> dict:
    return {"filas": [{"sku": f.sku, "stock_ml": f.stock_ml, "stock_ecom": f.stock_ecom, "diferencia": f.diferencia, "publicaciones": f.publicaciones,
                       "parent_sku": f.parent_sku} for f in r.filas],
            "incidencias_sku": r.incidencias_sku, "incidencias_sin_vincular": r.incidencias_sin_vincular, "skus_no_en_ecom": r.skus_no_en_ecom,
            "skus_incompletos": r.skus_incompletos, "publicaciones_activas": r.publicaciones_activas}


def resultado_desde_payload(p: dict) -> ResultadoConciliacion:
    filas = [FilaConciliacion(sku=f["sku"], stock_ml=f["stock_ml"], stock_ecom=f["stock_ecom"], diferencia=f["diferencia"],
                              publicaciones=f.get("publicaciones", []), parent_sku=f.get("parent_sku")) for f in p["filas"]]
    return ResultadoConciliacion(filas=filas, incidencias_sku=p.get("incidencias_sku", []), incidencias_sin_vincular=p.get("incidencias_sin_vincular", []),
                                 skus_no_en_ecom=p.get("skus_no_en_ecom", []), skus_incompletos=p.get("skus_incompletos", []),
                                 publicaciones_activas=p.get("publicaciones_activas", []))


def serializar_reposicion(r, params: dict) -> dict:
    return {"filas": [f.__dict__ for f in r.filas], "incidencias_sku": r.incidencias_sku, "incidencias_sin_vincular": r.incidencias_sin_vincular,
            "skus_no_en_ecom": r.skus_no_en_ecom, "skus_incompletos": r.skus_incompletos, "ordenes_dias_sin_leer": getattr(r, "ordenes_dias_sin_leer", []), "params": {**params, **getattr(r, "periodo", {})}}


def alertas_conciliacion(p: dict) -> list[dict]:
    """Las que hoy muestra Full ML sin guardarlas: diferencia de stock, publicación sin SKU, sin vincular en Ecom y SKU sin match en Ecom."""
    out = [{"tipo": "diferencia_stock", "clave": f["sku"], "detalle": {"stock_ml": f["stock_ml"], "stock_ecom": f["stock_ecom"], "diferencia": f["diferencia"]}}
           for f in p["filas"] if f.get("diferencia")]
    out += [{"tipo": "sin_sku", "clave": i["item_id"], "detalle": i} for i in p.get("incidencias_sku", [])]
    out += [{"tipo": "sin_vincular", "clave": f"{i['item_id']}|{i['motivo']}"[:128], "detalle": i} for i in p.get("incidencias_sin_vincular", [])]
    out += [{"tipo": "sku_no_en_ecom", "clave": s, "detalle": None} for s in p.get("skus_no_en_ecom", [])]
    return out


def alertas_reposicion(p: dict) -> list[dict]:
    """Venta censurada: el producto quebró en Full con ventas recientes y la tasa diaria se corrigió."""
    return [{"tipo": "venta_censurada", "clave": f["item_id"], "detalle": {"sku": f["sku"], "ventas_periodo": f["ventas_periodo"], "stock_full": f["stock_full"]}}
            for f in p["filas"] if f.get("censurado") and not f.get("dato_anterior")]


def _fusionar_filas(nuevo: dict, previo: dict | None, clave: str, incompleto) -> set[str]:
    """Foto parcial: lo que no se pudo leer se completa con la foto anterior (marcado `dato_anterior`) en vez de desaparecer. Devuelve las claves sin leer."""
    sin_leer = {f[clave] for f in nuevo["filas"] if incompleto(f)}
    if previo:
        viejas = {f[clave]: f for f in previo.get("filas", [])}
        nuevo["filas"] = [({**viejas[f[clave]], "dato_anterior": True} if incompleto(f) and f[clave] in viejas else f) for f in nuevo["filas"]]
    return sin_leer


# ── Actualización ──

def _log(job_id: str, txt: str) -> None:
    _jobs[job_id]["log"].append(txt)


def _params_repo(dias_ventas, semanas_objetivo, contar_deposito: bool, fraccion_deposito: float = 0.3) -> str:
    """Con el interruptor activado la clave es la de siempre + `deposito=1`; apagado, es exactamente la clave de antes (las fotos viejas siguen sirviendo)."""
    return ml_foto.clave_params(dias_ventas=dias_ventas, semanas_objetivo=semanas_objetivo, **({"deposito": round(fraccion_deposito * 100)} if contar_deposito else {}))


def _foto_previa(modulo: str, params: str | None, sesion_fn) -> dict | None:
    with sesion_fn() as db:
        f = ml_foto.leer(db, modulo, CUENTA, params)
        return f.payload if f is not None and f.payload is not None else None


def _conciliacion_reutilizable(sesion_fn, ahora: datetime) -> ResultadoConciliacion | None:
    with sesion_fn() as db:
        f = ml_foto.leer(db, MOD_CONC, CUENTA, "")
        if f is not None and f.payload is not None and f.estado == "completa" and f.obtenido_en and f.obtenido_en >= ahora - timedelta(minutes=REUSO_CONCILIACION_MIN):
            return resultado_desde_payload(f.payload)
    return None


def _guardar_conciliacion(sesion_fn, res: ResultadoConciliacion, previo: dict | None, t0: float) -> tuple[str, int]:
    p = serializar_conciliacion(res)
    sin_leer = set(res.skus_incompletos)
    if previo and sin_leer:
        viejas = {f["sku"]: f for f in previo.get("filas", [])}
        p["filas"] += [{**viejas[s], "dato_anterior": True} for s in sorted(sin_leer) if s in viejas]
    estado = "parcial" if sin_leer else "completa"
    with sesion_fn() as db:
        ml_foto.guardar_exito(db, MOD_CONC, CUENTA, "", p, estado, len(sin_leer), round(time.monotonic() - t0, 1), alertas_conciliacion(p), no_tocar=sin_leer)
    return estado, len(sin_leer)


def _anotar_historial(job_id: str, res: ResultadoConciliacion, historial_fn) -> None:
    """Agrega la columna de esta lectura al Sheet «Historial» de la conciliación (una columna por lectura, una fila por SKU). Corría solo en el job viejo
    (`ml_full.iniciar_job`); al pasar a la foto guardada quedó sin escribirse. Los SKU que no se pudieron leer no están en `filas`: quedan en blanco.
    Si falla no tira la actualización: queda en el log."""
    try:
        _log(job_id, f"Historial de conciliación actualizado: {historial_fn(res)}")
    except Exception as e:  # noqa: BLE001
        _log(job_id, f"No se pudo actualizar el historial en Sheets: {e}")


def actualizar(job_id: str, modulo: str, dias_ventas: int = 30, semanas_objetivo: float = 3, fecha_llegada: date | None = None, contar_deposito: bool = True, fraccion_deposito: float = 0.3, *,
               sesion_fn=None, ml_fn=None, ecom_fn=None, tactica_fn=None, historial_fn=None) -> None:
    """Corre una actualización completa y la deja guardada. Siempre termina el job (éxito o error): el botón del front nunca queda esperando. Las fábricas
    `*_fn` son para los tests."""
    sesion_fn = sesion_fn or _db.sesion
    ml_fn = ml_fn or (lambda cache: MLFullClient(cache=cache))
    ecom_fn = ecom_fn or (lambda: EcomFullAdapter(EcomApiClient()))
    tactica_fn = tactica_fn or TacticaStockSheetAdapter
    historial_fn = historial_fn or registrar_historial_conciliacion
    mod = MODULOS[modulo]
    params = _params_repo(dias_ventas, semanas_objetivo, contar_deposito, fraccion_deposito) if modulo == "reposicion" else ""
    _log(job_id, "Esperando que termine otra actualización de Full ML..." if _turno.locked() else "Iniciando actualización...")
    with _turno:
        _jobs[job_id].update(status="running", progress=None)
        t0 = time.monotonic()
        try:
            def _progreso(actual, total, fase):
                _jobs[job_id]["progress"] = {"current": actual, "total": total, "label": fase}
            ml = ml_fn(ml_foto.CacheLotes(sesion_fn))
            ecom = ecom_fn()
            ahora = ml_foto.ahora()
            previo_conc = _foto_previa(MOD_CONC, "", sesion_fn)
            if modulo == "reposicion":
                res_conc = _conciliacion_reutilizable(sesion_fn, ahora)
                if res_conc is not None and contar_deposito and not res_conc.publicaciones_activas:
                    res_conc = None     # conciliación guardada antes de sumar las publicaciones activas: se vuelve a leer
                if res_conc is None:
                    _log(job_id, "Leyendo stock de Full y vinculaciones...")
                    res_conc = conciliar(ml, ecom, progreso_cb=_progreso)
                    _guardar_conciliacion(sesion_fn, res_conc, previo_conc, t0)
                    _anotar_historial(job_id, res_conc, historial_fn)
                else:
                    _log(job_id, "Reutilizo la conciliación guardada hace menos de %d min (no se vuelve a leer)." % REUSO_CONCILIACION_MIN)
                previo = _foto_previa(MOD_REPO, params, sesion_fn)
                _log(job_id, "Leyendo ventas y envíos de Full...")
                res = calcular_reposicion_mla(ml, ecom, tactica_fn(), dias_ventas=dias_ventas, semanas_objetivo=semanas_objetivo, fecha_llegada=fecha_llegada,
                                              progreso_cb=_progreso, resultado_conciliacion=res_conc, contar_deposito=contar_deposito, fraccion_deposito=fraccion_deposito)
                payload = serializar_reposicion(res, {"dias_ventas": dias_ventas, "semanas_objetivo": semanas_objetivo, "contar_deposito": contar_deposito, "fraccion_deposito": fraccion_deposito,
                                                      "fecha_llegada": (fecha_llegada or date.today()).isoformat()})
                sin_leer = _fusionar_filas(payload, previo, "item_id", lambda f: f.get("datos_incompletos"))
                n_inc = len(set(res.skus_incompletos))
                estado = "parcial" if n_inc or sin_leer or res.ordenes_dias_sin_leer else "completa"
                with sesion_fn() as db:
                    ml_foto.guardar_exito(db, mod, CUENTA, params, payload, estado, n_inc, round(time.monotonic() - t0, 1), alertas_reposicion(payload),
                                          no_tocar=sin_leer)
            else:
                res = conciliar(ml, ecom, progreso_cb=_progreso)
                estado, n_inc = _guardar_conciliacion(sesion_fn, res, previo_conc, t0)
                _anotar_historial(job_id, res, historial_fn)
            _jobs[job_id]["progress"] = None
            _log(job_id, "Listo." if estado == "completa" else f"Listo con datos incompletos para {n_inc} SKU.")
            _jobs[job_id]["status"] = "done"
        except Exception as e:  # noqa: BLE001 -- cualquier falla deja la foto anterior y se informa
            msg = ml_foto.mensaje_para_usuario(e)
            try:
                with sesion_fn() as db:
                    ml_foto.guardar_fallo(db, mod, CUENTA, params, msg)
            except Exception:  # noqa: BLE001
                pass
            _jobs[job_id]["progress"] = None
            _log(job_id, f"Error: {msg}")
            _jobs[job_id].update(status="error", message=msg)
        finally:
            with _estado_lock:
                if _activo.get(mod) == job_id:
                    _activo.pop(mod, None)


def estado_job(job_id: str) -> dict | None:
    return _jobs.get(job_id)


# ── Endpoints ──

def _modulo(nombre: str) -> str:
    if nombre not in MODULOS:
        raise HTTPException(status_code=404, detail="Módulo desconocido (conciliacion o reposicion).")
    return MODULOS[nombre]


@router.get("/estado/{job_id}")
def estado_endpoint(job_id: str):
    return estado_job(job_id) or {"status": "not_found"}


@router.get("/detalle/{inventory_id}")
def detalle_inventario(inventory_id: str, cuenta: str, dias: int = 30, desde: date | None = None, hasta: date | None = None):
    """Para verificar a mano: las operaciones CRUDAS que lee el simulador para UN `inventory_id`, en el mismo rango de fechas. Solo lectura, en vivo y sin caché."""
    hoy = date.today()
    hasta = hasta or hoy
    desde = desde or (hasta - timedelta(days=min(max(dias, 1), 60)))
    if cuenta not in SELLERS:
        raise HTTPException(status_code=422, detail="Cuenta desconocida (IT o MT).")
    try:
        return ml_full_detalle(MLFullClient(), cuenta, inventory_id, desde.isoformat(), hasta.isoformat())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=ml_foto.mensaje_para_usuario(e))


@router.get("/{modulo}")
def foto(modulo: str, dias_ventas: int | None = None, semanas_objetivo: float | None = None, contar_deposito: bool = True, fraccion_deposito: float = 0.3):
    mod = _modulo(modulo)
    params = _params_repo(dias_ventas, semanas_objetivo, contar_deposito, fraccion_deposito) if (modulo == "reposicion" and dias_ventas is not None and semanas_objetivo is not None) else ("" if modulo == "conciliacion" else None)
    with _db.sesion() as db:
        out = ml_foto.vista_foto(ml_foto.leer(db, mod, CUENTA, params))
        out["alertas"] = ml_foto.listar_alertas(db, mod)
    out["job_id"] = _activo.get(mod)
    return out


@router.post("/{modulo}/actualizar")
def actualizar_endpoint(modulo: str, background_tasks: BackgroundTasks, fecha_llegada: date | None = None, dias_ventas: int = 30, semanas_objetivo: float = 3,
                        contar_deposito: bool = True, fraccion_deposito: float = 0.3):
    mod = _modulo(modulo)
    if modulo == "reposicion" and fecha_llegada is None:
        raise HTTPException(status_code=422, detail="Falta la fecha estimada de llegada.")
    with _estado_lock:
        if mod in _activo and _jobs.get(_activo[mod], {}).get("status") in ("queued", "running"):
            return {"job_id": _activo[mod], "status": "ya_corriendo"}
        job_id = f"mlfoto_{modulo}_{uuid.uuid4().hex[:8]}"
        _jobs[job_id] = {"status": "queued", "log": [], "progress": None, "modulo": mod}
        _activo[mod] = job_id
    background_tasks.add_task(actualizar, job_id, modulo, min(max(dias_ventas, 1), 60), semanas_objetivo, fecha_llegada, contar_deposito, min(max(fraccion_deposito, 0.0), 1.0))
    return {"job_id": job_id, "status": "started"}


@router.post("/alertas/{alerta_id}/vista")
def alerta_vista(alerta_id: str):
    with _db.sesion() as db:
        if not ml_foto.marcar_vista(db, alerta_id):
            raise HTTPException(status_code=404, detail="Alerta no encontrada.")
    return {"ok": True}
