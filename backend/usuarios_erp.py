"""Usuarios del ERP: login con usuario y contraseña, y accesos por módulo.

- Un admin (el «usuario total») crea usuarios y tilda a qué módulos entra cada uno (página «Accesos»). Un usuario común ve en su ERP solo los módulos tildados.
- Las claves se guardan hasheadas (scrypt) y las sesiones son un token firmado con HMAC (`ERP_SESSION_SECRET`, o derivado de `ERP_API_KEY`) que vence a las 12 horas; cambiar la clave
  o desactivar al usuario invalida sus sesiones abiertas.
- El primer admin sale de las variables de Railway `ERP_ADMIN_USER` y `ERP_ADMIN_PASSWORD` (no se escriben en el repositorio ni en el chat): si todavía no hay ningún admin, se crea con ellas.
- Mientras no exista ningún usuario, el ERP sigue abierto como hasta ahora (`estado()` informa `login_requerido: False`).

OJO, alcance de esta primera etapa: la segmentación es de PANTALLAS. Los endpoints de datos del backend todavía no exigen la sesión; filtrarlos por usuario en el servidor es la etapa siguiente.
Sin FastAPI ni red: recibe una sesión de SQLAlchemy.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone

# (id = data-page del menú, nombre, sección). El orden es el del menú. «accesos» NO está acá: es solo del admin.
MODULOS = [
    ("dashboard", "Ventas & Rentabilidad", "Dashboard"), ("ventas-hoy", "Ventas de hoy", "Dashboard"), ("historico", "Histórico de Unidades", "Dashboard"),
    ("cobranzas", "Cobranzas", "Dashboard"), ("brasil", "Brasil", "Dashboard"),
    ("ayala-core", "Motor de Precios", "Ayala Core"),
    ("verificar-ecom", "Verificar Ecom", "Gestión de Precios"), ("verificar-tactica", "Verificar Táctica", "Gestión de Precios"),
    ("full-ml", "Full ML", "Mercado Libre"), ("posventa-ml", "Posventa ML", "Mercado Libre"), ("ofertas-margen", "Precios y ofertas ML", "Mercado Libre"), ("campanas-ml", "Campañas ML", "Mercado Libre"),
    ("analisis-competencia", "Análisis de Competencia", "Mercado Libre"),
    ("fravega", "Frávega", "Otros markets"), ("megatone", "Megatone", "Otros markets"), ("oncity", "OnCity", "Otros markets"),
    ("proyeccion", "Proyección 2027", "Compras"), ("distribucion", "Distribuidores", "Distribución"),
    ("config", "Configuración", "Sistema"), ("reglas", "Criterios de precio", "Sistema"),
]
IDS_MODULOS = [m[0] for m in MODULOS]
TTL_SESION_SEG = 12 * 3600
MAX_INTENTOS = 5
BLOQUEO_SEG = 600
MIN_CLAVE = 8
_FALLOS: dict[str, list[float]] = {}
_LOCK = threading.Lock()


class UsuarioInvalido(ValueError):
    """Dato inválido al crear o editar (mensaje en castellano para quien administra). → 422"""


class CredencialesInvalidas(Exception):
    """Usuario o clave incorrectos, usuario inactivo o sesión vencida. → 401"""


class NoAutorizado(Exception):
    """Sesión válida pero sin permiso para eso (no es admin). → 403"""


class Bloqueado(Exception):
    """Demasiados intentos fallidos. → 429"""


class SesionNoConfigurada(Exception):
    """Falta `ERP_SESSION_SECRET` (o `ERP_API_KEY`) en el servidor: sin eso no se pueden firmar sesiones. → 503"""


# ── claves ─────────────────────────────────────────────────────────────────

def hashear(clave: str) -> str:
    sal = secrets.token_bytes(16)
    h = hashlib.scrypt(clave.encode("utf-8"), salt=sal, n=2 ** 14, r=8, p=1, dklen=32)
    return "scrypt$16384$8$1$" + base64.b64encode(sal).decode() + "$" + base64.b64encode(h).decode()


def verificar_clave(clave: str, almacenado: str) -> bool:
    try:
        _, n, r, p, sal, h = almacenado.split("$")
        calc = hashlib.scrypt((clave or "").encode("utf-8"), salt=base64.b64decode(sal), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(h))
    except Exception:  # noqa: BLE001 -- un hash roto nunca deja entrar
        return False


def _validar_clave_nueva(clave: str) -> str:
    if len(clave or "") < MIN_CLAVE:
        raise UsuarioInvalido(f"La contraseña tiene que tener al menos {MIN_CLAVE} caracteres.")
    return clave


# ── sesión (token firmado) ──────────────────────────────────────────────────

def _secreto() -> bytes:
    s = os.environ.get("ERP_SESSION_SECRET") or ""
    if not s:
        k = os.environ.get("ERP_API_KEY") or ""
        if not k:
            raise SesionNoConfigurada("El servidor no tiene ERP_SESSION_SECRET (ni ERP_API_KEY) configurada: no se pueden abrir sesiones.")
        s = "erp-sesion:" + k
    return hashlib.sha256(s.encode("utf-8")).digest()


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(t: str) -> bytes:
    return base64.urlsafe_b64decode(t + "=" * (-len(t) % 4))


def crear_token(usuario: str, version: int, ahora: float | None = None) -> str:
    cuerpo = _b64(json.dumps({"u": usuario, "v": version, "e": int((ahora or time.time()) + TTL_SESION_SEG)}, separators=(",", ":")).encode())
    return cuerpo + "." + _b64(hmac.new(_secreto(), cuerpo.encode(), hashlib.sha256).digest())


def leer_token(token: str, ahora: float | None = None) -> dict | None:
    try:
        cuerpo, firma = (token or "").split(".")
        if not hmac.compare_digest(_unb64(firma), hmac.new(_secreto(), cuerpo.encode(), hashlib.sha256).digest()):
            return None
        d = json.loads(_unb64(cuerpo))
        return d if d["e"] > (ahora or time.time()) else None
    except SesionNoConfigurada:
        raise
    except Exception:  # noqa: BLE001
        return None


# ── base ────────────────────────────────────────────────────────────────────

def _modulos_de(u) -> list[str]:
    try:
        return [m for m in json.loads(u.modulos or "[]") if m in IDS_MODULOS]
    except ValueError:
        return []


def vista(u) -> dict:
    return {"usuario": u.usuario, "nombre": u.nombre or u.usuario, "rol": u.rol, "activo": bool(u.activo),
            "modulos": list(IDS_MODULOS) if u.rol == "admin" else _modulos_de(u),
            "creado": u.creado.isoformat() if u.creado else None, "ultimo_ingreso": u.ultimo_ingreso.isoformat() if u.ultimo_ingreso else None}


def _ahora_db() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _norm_usuario(usuario: str) -> str:
    u = (usuario or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9._-]{3,40}", u):
        raise UsuarioInvalido("El usuario tiene que tener entre 3 y 40 caracteres: letras, números, punto, guion o guion bajo.")
    return u


def _validar_modulos(modulos) -> list[str]:
    lista = list(modulos or [])
    raros = [m for m in lista if m not in IDS_MODULOS]
    if raros:
        raise UsuarioInvalido(f"Módulo desconocido: {raros[0]}")
    return [m for m in IDS_MODULOS if m in lista]          # sin repetidos y en el orden del menú


def asegurar_admin(sesion_fn) -> None:
    """Si hay `ERP_ADMIN_USER` y `ERP_ADMIN_PASSWORD` y todavía no existe ningún admin, lo crea."""
    from rentabilidad.models import UsuarioErp
    nombre, clave = (os.environ.get("ERP_ADMIN_USER") or "").strip().lower(), os.environ.get("ERP_ADMIN_PASSWORD") or ""
    if not nombre or not clave:
        return
    with sesion_fn() as db:
        if db.query(UsuarioErp).filter(UsuarioErp.rol == "admin").first() is not None:
            return
        try:
            u = _norm_usuario(nombre)
            _validar_clave_nueva(clave)
        except UsuarioInvalido:
            return                                          # variables mal puestas: no se crea nada (y el ERP sigue abierto)
        db.add(UsuarioErp(usuario=u, nombre=nombre, rol="admin", modulos="[]", pass_hash=hashear(clave), activo=True, version_sesion=1, creado=_ahora_db()))


def estado(sesion_fn) -> dict:
    """`login_requerido` es True apenas existe algún usuario: desde ahí el ERP pide ingresar."""
    from rentabilidad.models import UsuarioErp
    asegurar_admin(sesion_fn)
    with sesion_fn() as db:
        return {"login_requerido": db.query(UsuarioErp).first() is not None}


def _fallos_recientes(clave: str, ahora: float) -> list[float]:
    f = [t for t in _FALLOS.get(clave, []) if ahora - t < BLOQUEO_SEG]
    _FALLOS[clave] = f
    return f


def login(sesion_fn, usuario: str, clave: str, ip: str = "", ahora: float | None = None) -> dict:
    from rentabilidad.models import UsuarioErp
    _secreto()
    asegurar_admin(sesion_fn)
    u_norm = (usuario or "").strip().lower()
    llave = f"{u_norm}|{ip}"
    t = ahora or time.time()
    with _LOCK:
        if len(_fallos_recientes(llave, t)) >= MAX_INTENTOS:
            raise Bloqueado("Demasiados intentos. Probá de nuevo en unos minutos.")
    with sesion_fn() as db:
        u = db.query(UsuarioErp).filter(UsuarioErp.usuario == u_norm).first()
        # se verifica siempre (aun si el usuario no existe) para que no se note por el tiempo de respuesta
        ok = verificar_clave(clave, u.pass_hash if u else hashear("x" * 12))
        if not (u and ok and u.activo):
            with _LOCK:
                _FALLOS.setdefault(llave, []).append(t)
            raise CredencialesInvalidas("Usuario o contraseña incorrectos.")
        u.ultimo_ingreso = _ahora_db()
        db.flush()
        with _LOCK:
            _FALLOS.pop(llave, None)
        return {"token": crear_token(u.usuario, u.version_sesion, ahora), "usuario": vista(u)}


def usuario_de_token(sesion_fn, token: str, ahora: float | None = None) -> dict:
    """La vista del usuario dueño de la sesión, o `CredencialesInvalidas` si venció, se firmó mal, se desactivó o cambió su clave."""
    from rentabilidad.models import UsuarioErp
    d = leer_token(token, ahora)
    if not d:
        raise CredencialesInvalidas("La sesión venció: ingresá de nuevo.")
    with sesion_fn() as db:
        u = db.query(UsuarioErp).filter(UsuarioErp.usuario == d["u"]).first()
        if not u or not u.activo or u.version_sesion != d["v"]:
            raise CredencialesInvalidas("La sesión ya no es válida: ingresá de nuevo.")
        return vista(u)


def exigir_admin(sesion_fn, token: str) -> dict:
    v = usuario_de_token(sesion_fn, token)
    if v["rol"] != "admin":
        raise NoAutorizado("Solo el administrador puede hacer esto.")
    return v


# ── administración (solo admin: lo verifica el endpoint con `exigir_admin`) ───

def listar(sesion_fn) -> list[dict]:
    from rentabilidad.models import UsuarioErp
    with sesion_fn() as db:
        return [vista(u) for u in db.query(UsuarioErp).order_by(UsuarioErp.usuario).all()]


def crear(sesion_fn, usuario: str, nombre: str, clave: str, modulos, rol: str = "usuario") -> dict:
    from rentabilidad.models import UsuarioErp
    u_norm = _norm_usuario(usuario)
    _validar_clave_nueva(clave)
    if rol not in ("admin", "usuario"):
        raise UsuarioInvalido("El rol tiene que ser admin o usuario.")
    mods = _validar_modulos(modulos)
    with sesion_fn() as db:
        if db.query(UsuarioErp).filter(UsuarioErp.usuario == u_norm).first():
            raise UsuarioInvalido("Ya existe un usuario con ese nombre.")
        u = UsuarioErp(usuario=u_norm, nombre=(nombre or "").strip()[:80] or u_norm, rol=rol, modulos=json.dumps(mods), pass_hash=hashear(clave), activo=True, version_sesion=1,
                       creado=_ahora_db())
        db.add(u)
        db.flush()
        return vista(u)


def editar(sesion_fn, usuario: str, nombre=None, modulos=None, activo=None, clave=None, rol=None) -> dict:
    """Cambia lo que se pasa (lo demás queda igual). Nueva clave o desactivar suben la versión de sesión: se cierran sus sesiones abiertas. Siempre queda al menos un admin activo."""
    from rentabilidad.models import UsuarioErp
    with sesion_fn() as db:
        u = db.query(UsuarioErp).filter(UsuarioErp.usuario == (usuario or "").strip().lower()).first()
        if not u:
            raise UsuarioInvalido("Ese usuario no existe.")
        quedaria_sin_admin = (u.rol == "admin" and u.activo) and (activo is False or (rol is not None and rol != "admin"))
        if quedaria_sin_admin and db.query(UsuarioErp).filter(UsuarioErp.rol == "admin", UsuarioErp.activo.is_(True), UsuarioErp.id != u.id).count() == 0:
            raise UsuarioInvalido("Tiene que quedar al menos un administrador activo.")
        if nombre is not None:
            u.nombre = nombre.strip()[:80] or u.usuario
        if modulos is not None:
            u.modulos = json.dumps(_validar_modulos(modulos))
        if rol is not None:
            if rol not in ("admin", "usuario"):
                raise UsuarioInvalido("El rol tiene que ser admin o usuario.")
            u.rol = rol
        if activo is not None:
            if bool(activo) != bool(u.activo):
                u.version_sesion += 1
            u.activo = bool(activo)
        if clave:
            u.pass_hash = hashear(_validar_clave_nueva(clave))
            u.version_sesion += 1
        db.flush()
        return vista(u)


def cambiar_clave(sesion_fn, usuario: str, actual: str, nueva: str) -> dict:
    """El propio usuario cambia su clave (pide la actual). Cierra las demás sesiones y devuelve una sesión nueva."""
    from rentabilidad.models import UsuarioErp
    _validar_clave_nueva(nueva)
    with sesion_fn() as db:
        u = db.query(UsuarioErp).filter(UsuarioErp.usuario == (usuario or "").strip().lower()).first()
        if not u or not verificar_clave(actual, u.pass_hash):
            raise CredencialesInvalidas("La contraseña actual no es correcta.")
        u.pass_hash = hashear(nueva)
        u.version_sesion += 1
        db.flush()
        return {"token": crear_token(u.usuario, u.version_sesion), "usuario": vista(u)}
