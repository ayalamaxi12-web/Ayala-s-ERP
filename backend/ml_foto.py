"""Foto guardada de los módulos de Mercado Libre, alertas persistentes y caché de lotes. Sin FastAPI ni red: recibe una sesión de SQLAlchemy (`rentabilidad.db.sesion()`).

Patrón (pedido de Maxx, empieza en Full ML y se replica a Ofertas ML y el resto): al abrir un módulo se muestra de inmediato la última lectura exitosa
("foto"), con "Última actualización: hace X" y un botón "Actualizar". Reglas:
  - Una sola foto exitosa por (módulo, cuenta, parámetros). La nueva reemplaza a la anterior en la MISMA transacción que migra las alertas: si algo falla,
    queda la anterior intacta.
  - Un intento fallido nunca toca la foto: solo anota el mensaje (sin URL) y la hora, para mostrar "Falló la última actualización, mostrando datos de [fecha]".
  - Las alertas viven aparte (`ml_alerta`): primera vez, última vez vista y estado (activa, ya_no_aparece, vista). Se actualizan con cada foto, nunca se borran
    solas salvo las ya vistas, a los 90 días.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone

from rentabilidad.models import MlAlerta, MlFoto, MlLoteCache

RETENCION_VISTAS_DIAS = 90
VIDA_LOTE_MIN = 180
ACTIVA, YA_NO_APARECE, VISTA = "activa", "ya_no_aparece", "vista"


def ahora() -> datetime:
    """UTC sin zona (como el resto de las tablas del ERP)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def clave_params(**kw) -> str:
    """Parámetros que cambian la lectura, en un texto estable (`a=1;b=2`). Vacío si no hay."""
    return ";".join(f"{k}={kw[k]}" for k in sorted(kw))[:64]


_URL = re.compile(r"https?://\S+")


def mensaje_para_usuario(exc: BaseException) -> str:
    """Texto corto y claro para mostrar, SIN la URL completa (las de ML llevan ids de vendedor y de publicación)."""
    txt = _URL.sub("", str(exc) or exc.__class__.__name__).strip(" :-,")
    if "429" in txt and "demasiadas" not in txt:
        txt = "Mercado Libre respondió 429 (demasiadas consultas seguidas)"
    return (txt or "Error al leer Mercado Libre")[:240]


# ── Foto ──

def leer(db, modulo: str, cuenta: str, params: str | None = None) -> MlFoto | None:
    """La foto de esa clave. Con `params=None`, la más reciente con datos de ese módulo y cuenta (lo que se muestra al abrir)."""
    q = db.query(MlFoto).filter(MlFoto.modulo == modulo, MlFoto.cuenta == cuenta)
    if params is not None:
        return q.filter(MlFoto.params == params).first()
    return q.filter(MlFoto.payload.isnot(None)).order_by(MlFoto.obtenido_en.desc()).first()


def vista_foto(f: MlFoto | None) -> dict:
    if f is None:
        return {"existe": False}
    return {"existe": f.payload is not None, "modulo": f.modulo, "cuenta": f.cuenta, "params": f.params,
            "obtenido_en": f.obtenido_en.isoformat() + "Z" if f.obtenido_en else None, "estado": f.estado, "incompletos": f.incompletos or 0,
            "duracion_seg": float(f.duracion_seg) if f.duracion_seg is not None else None, "payload": f.payload,
            "error_msg": f.error_msg, "error_en": f.error_en.isoformat() + "Z" if f.error_en else None}


def guardar_exito(db, modulo: str, cuenta: str, params: str, payload: dict, estado: str, incompletos: int, duracion_seg: float,
                  alertas: list[dict], no_tocar: set[str] | None = None, cuando: datetime | None = None) -> MlFoto:
    """Guarda la foto nueva y migra las alertas, en ese orden y en la transacción del llamador (`sesion()` hace commit al salir o rollback si algo falla)."""
    cuando = cuando or ahora()
    sincronizar_alertas(db, modulo, alertas, cuando, no_tocar)
    f = leer(db, modulo, cuenta, params)
    if f is None:
        f = MlFoto(modulo=modulo, cuenta=cuenta, params=params)
        db.add(f)
    f.obtenido_en, f.estado, f.incompletos, f.duracion_seg, f.payload = cuando, estado, incompletos, duracion_seg, payload
    f.error_msg = f.error_en = None
    purgar_vistas(db, cuando)
    db.flush()
    return f


def guardar_fallo(db, modulo: str, cuenta: str, params: str, mensaje: str, cuando: datetime | None = None) -> MlFoto:
    """Anota el intento fallido SIN tocar la foto anterior (`payload` y `obtenido_en` quedan como estaban)."""
    f = leer(db, modulo, cuenta, params)
    if f is None:
        f = MlFoto(modulo=modulo, cuenta=cuenta, params=params, incompletos=0)
        db.add(f)
    f.error_msg, f.error_en = mensaje[:500], cuando or ahora()
    db.flush()
    return f


# ── Alertas ──

def sincronizar_alertas(db, modulo: str, alertas: list[dict], cuando: datetime, no_tocar: set[str] | None = None) -> dict:
    """`alertas`: [{"tipo", "clave", "detalle"}] de la foto nueva. Las que siguen se actualizan, las nuevas se crean y las `activa` que ya no aparecen pasan
    a `ya_no_aparece` (no se borran). `no_tocar`: claves cuya lectura quedó incompleta en una foto parcial -- no se puede afirmar que "ya no aparecen".
    Una `vista` sigue `vista` aunque reaparezca (la persona ya la reconoció) y se borra a los 90 días de vista."""
    no_tocar = no_tocar or set()
    nuevas = {(a["tipo"], str(a["clave"])[:128]): a.get("detalle") for a in alertas}
    existentes = {(a.tipo, a.clave): a for a in db.query(MlAlerta).filter(MlAlerta.modulo == modulo).all()}
    creadas = actualizadas = desaparecidas = 0
    for (tipo, clave), detalle in nuevas.items():
        a = existentes.get((tipo, clave))
        if a is None:
            db.add(MlAlerta(modulo=modulo, tipo=tipo, clave=clave, primera_vez=cuando, ultima_vez=cuando, estado=ACTIVA, detalle=detalle))
            creadas += 1
        else:
            a.ultima_vez, a.detalle = cuando, detalle
            if a.estado == YA_NO_APARECE:
                a.estado = ACTIVA
            actualizadas += 1
    for (tipo, clave), a in existentes.items():
        if (tipo, clave) not in nuevas and a.estado == ACTIVA and clave not in no_tocar:
            a.estado = YA_NO_APARECE
            desaparecidas += 1
    db.flush()
    return {"creadas": creadas, "actualizadas": actualizadas, "ya_no_aparecen": desaparecidas}


def listar_alertas(db, modulo: str) -> list[dict]:
    filas = db.query(MlAlerta).filter(MlAlerta.modulo == modulo).order_by(MlAlerta.estado, MlAlerta.primera_vez.desc()).all()
    orden = {ACTIVA: 0, YA_NO_APARECE: 1, VISTA: 2}
    filas.sort(key=lambda a: (orden.get(a.estado, 9), a.tipo, a.clave))
    return [{"id": a.id, "modulo": a.modulo, "tipo": a.tipo, "clave": a.clave, "estado": a.estado, "detalle": a.detalle,
             "primera_vez": a.primera_vez.isoformat() + "Z", "ultima_vez": a.ultima_vez.isoformat() + "Z",
             "vista_en": a.vista_en.isoformat() + "Z" if a.vista_en else None} for a in filas]


def marcar_vista(db, alerta_id: str, cuando: datetime | None = None) -> bool:
    a = db.query(MlAlerta).filter(MlAlerta.id == alerta_id).first()
    if a is None:
        return False
    a.estado, a.vista_en = VISTA, cuando or ahora()
    db.flush()
    return True


def purgar_vistas(db, cuando: datetime | None = None) -> int:
    """Borra las alertas `vista` hace más de 90 días. Las activas y las `ya_no_aparece` nunca se borran solas."""
    limite = (cuando or ahora()) - timedelta(days=RETENCION_VISTAS_DIAS)
    n = db.query(MlAlerta).filter(MlAlerta.estado == VISTA, MlAlerta.vista_en < limite).delete(synchronize_session=False)
    db.flush()
    return n


# ── Caché de lotes (para no repetir consultas ya hechas) ──

class CacheLotes:
    """Interfaz `get(clave)` / `put(clave, lista)` que usa `MLFullClient`. Cada llamada abre su propia sesión, así un lote leído queda guardado aunque la
    actualización falle más adelante: el reintento no lo vuelve a pedir."""

    def __init__(self, sesion_fn, vida_min: int = VIDA_LOTE_MIN):
        self._sesion, self._vida = sesion_fn, vida_min

    @staticmethod
    def _id(clave: str) -> str:
        return hashlib.sha1(clave.encode()).hexdigest()

    def get(self, clave: str):
        try:
            with self._sesion() as db:
                f = db.query(MlLoteCache).filter(MlLoteCache.clave == self._id(clave)).first()
                if f is not None and f.obtenido_en >= ahora() - timedelta(minutes=self._vida):
                    return f.payload
        except Exception:
            return None
        return None

    def put(self, clave: str, datos: list) -> None:
        try:
            with self._sesion() as db:
                limite = ahora() - timedelta(minutes=self._vida)
                db.query(MlLoteCache).filter(MlLoteCache.obtenido_en < limite).delete(synchronize_session=False)
                f = db.query(MlLoteCache).filter(MlLoteCache.clave == self._id(clave)).first()
                if f is None:
                    db.add(MlLoteCache(clave=self._id(clave), obtenido_en=ahora(), payload=datos))
                else:
                    f.obtenido_en, f.payload = ahora(), datos
        except Exception:
            pass  # la caché nunca debe tumbar la lectura
