"""Ofertas ML con foto guardada y lectura automática diaria.

La lectura completa (campañas + descuentos propios, las dos cuentas) es lenta. Ahora:
  - Corre sola todas las mañanas (por defecto 06:30, hora Argentina; `OFERTAS_AUTO_HORA`, y `OFERTAS_AUTO=0` la apaga) y deja el resultado guardado en la base
    (`ml_foto`, módulo «ofertas»): cualquiera que abra «Precios y ofertas ML» ve de inmediato lo último, con fecha y hora de la última actualización.
  - Si el backend estaba apagado a esa hora, la lectura corre apenas vuelve (primer chequeo después de la hora). Si falla, reintenta cada 30 minutos sin tocar la foto anterior.
  - Cualquiera puede pedir «Actualizar ahora»: una sola lectura corre a la vez (si ya hay una en curso se engancha a esa).
  - GET  /ml-ofertas/foto              última foto exitosa + si hay una lectura en curso (no lee ML)
  - POST /ml-ofertas/foto/actualizar   lanza la lectura completa (el progreso se sigue en `GET /ml-ofertas/status/{job_id}`)
**Solo lectura**: no escribe en Mercado Libre, en Ecom ni en ningún Sheet.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable

from fastapi import APIRouter, BackgroundTasks, HTTPException

import ml_foto
import ml_ofertas
from rentabilidad import db as _db

router = APIRouter(prefix="/ml-ofertas/foto", tags=["ml-ofertas-foto"])

MODULO, CUENTA = "ofertas", "todas"
PARAMS = ml_foto.clave_params(propias=1)          # la lectura completa (con los descuentos propios)
HORA_DEFAULT = "06:30"
REINTENTO_TRAS_FALLO_MIN = 30
CHEQUEO_SEG = 300
_ZONA_AR = timezone(timedelta(hours=-3))

_estado_lock = threading.Lock()
_activo: dict = {"job_id": None}


def hora_objetivo() -> tuple[int, int]:
    txt = os.environ.get("OFERTAS_AUTO_HORA", HORA_DEFAULT)
    try:
        h, m = txt.split(":")
        return min(max(int(h), 0), 23), min(max(int(m), 0), 59)
    except ValueError:
        h, m = HORA_DEFAULT.split(":")
        return int(h), int(m)


def auto_activa() -> bool:
    return os.environ.get("OFERTAS_AUTO", "1") != "0"


def corriendo() -> str | None:
    jid = _activo["job_id"]
    if jid and (ml_ofertas.estado_job(jid) or {}).get("status") == "running":
        return jid
    return None


def toca_actualizar(ahora_utc: datetime, ultima_foto_utc: datetime | None, ultimo_fallo_utc: datetime | None) -> bool:
    """¿Corresponde lanzar la lectura automática ahora? Después de la hora del día y sin una foto exitosa de HOY (hora Argentina); tras un fallo, espera 30 minutos."""
    ar = ahora_utc.astimezone(_ZONA_AR)
    h, m = hora_objetivo()
    if (ar.hour, ar.minute) < (h, m):
        return False
    if ultima_foto_utc is not None and ultima_foto_utc.replace(tzinfo=timezone.utc).astimezone(_ZONA_AR).date() == ar.date():
        return False
    if ultimo_fallo_utc is not None and (ahora_utc - ultimo_fallo_utc.replace(tzinfo=timezone.utc)) < timedelta(minutes=REINTENTO_TRAS_FALLO_MIN):
        return False
    return True


def correr_y_guardar(job_id: str, tc: float, origen: str = "manual") -> None:
    """La lectura completa y su guardado. El progreso vive en `ml_ofertas._jobs[job_id]` (lo que ya sigue la pantalla)."""
    t0 = time.time()
    ml_ofertas.iniciar_job(job_id, None, True, tc)
    est = ml_ofertas.estado_job(job_id) or {}
    try:
        with _db.sesion() as db:
            if est.get("status") == "done" and est.get("result"):
                ml_foto.guardar_exito(db, MODULO, CUENTA, PARAMS, {**est["result"], "origen": origen}, "completa", 0, round(time.time() - t0, 1), [])
            else:
                ml_foto.guardar_fallo(db, MODULO, CUENTA, PARAMS, ml_foto.mensaje_para_usuario(Exception(((est.get("log") or ["falló la lectura"])[-1]))))
    except Exception as e:  # noqa: BLE001 -- si la base falla, la pantalla igual recibe el resultado del job
        est.setdefault("log", []).append(f"No se pudo guardar la foto: {ml_foto.mensaje_para_usuario(e)}")


def lanzar(agregar_tarea: Callable, tc: float, origen: str) -> dict:
    with _estado_lock:
        en_curso = corriendo()
        if en_curso:
            return {"job_id": en_curso, "status": "ya_corriendo"}
        job_id = f"mlofertas_{int(time.time())}"
        ml_ofertas._jobs[job_id] = {"status": "running", "log": ["En cola..."], "result": None, "progress": None}
        _activo["job_id"] = job_id
    agregar_tarea(correr_y_guardar, job_id, tc, origen)
    return {"job_id": job_id, "status": "started"}


def vista() -> dict:
    with _db.sesion() as db:
        out = ml_foto.vista_foto(ml_foto.leer(db, MODULO, CUENTA, PARAMS))
    out["job_id"] = corriendo()
    out["auto"] = {"activa": auto_activa(), "hora": "%02d:%02d" % hora_objetivo()}
    return out


@router.get("")
def foto(meta: bool = False):
    """`meta=true`: solo fecha/estado/si hay una lectura en curso, sin los datos (para chequear barato si hay algo más nuevo)."""
    try:
        out = vista()
        if meta:
            out.pop("payload", None)
        return out
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=ml_foto.mensaje_para_usuario(e))


def iniciar_programador(tc_fn: Callable[[], Decimal]) -> threading.Thread | None:
    """Hilo que cada 5 minutos mira si toca la lectura de la mañana. No hace nada si `OFERTAS_AUTO=0`."""
    if not auto_activa():
        return None

    def _bucle():
        while True:
            try:
                with _db.sesion() as db:
                    f = ml_foto.leer(db, MODULO, CUENTA, PARAMS)
                    ultima = f.obtenido_en if f is not None and f.payload is not None else None
                    fallo = f.error_en if f is not None else None
                ahora = datetime.now(timezone.utc)
                if corriendo() is None and toca_actualizar(ahora, ultima, fallo):
                    tc = float(tc_fn())
                    job_id = f"mlofertas_auto_{int(time.time())}"
                    with _estado_lock:
                        ml_ofertas._jobs[job_id] = {"status": "running", "log": ["En cola (automática)..."], "result": None, "progress": None}
                        _activo["job_id"] = job_id
                    correr_y_guardar(job_id, tc, "automatica")
            except Exception:  # noqa: BLE001 -- el programador nunca se cae: reintenta en el próximo chequeo
                pass
            time.sleep(CHEQUEO_SEG)

    t = threading.Thread(target=_bucle, name="ofertas-foto-diaria", daemon=True)
    t.start()
    return t
