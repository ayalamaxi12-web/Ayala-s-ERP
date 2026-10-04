"""Clave compartida (`X-ERP-Key`) para los endpoints del backend que escriben
o exponen credenciales.

Qué protege (ver `requiere_clave`):
  - todo POST / PUT / PATCH / DELETE (escrituras a ML, Ecom, Sheets, la base y
    los jobs que gastan recursos);
  - `GET /ml/token` (devuelve el token OAuth vivo de ML);
  - `GET /ml-proxy` (lecturas con el token del servidor).

Qué NO protege (sigue abierto):
  - `/`, `/health`, `/tc/bna` y el resto de los GET de solo lectura;
  - `GET /rentabilidad/reporte/*`: tiene su propio `X-Reporte-Token`
    (`RENT_REPORTE_TOKEN`) y lo consume n8n -- no se toca;
  - OPTIONS (preflight de CORS).

Modo permisivo: si `ERP_API_KEY` NO está definida en el entorno, no se bloquea
nada y solo se loguea qué requests protegidos llegaron sin clave válida. Así se
puede desplegar el código antes de activar la clave. Definir `ERP_API_KEY`
(Railway → Variables) es lo que activa el bloqueo; borrarla lo desactiva.

Es middleware ASGI (no decoradores por endpoint) para que un endpoint nuevo
quede protegido por defecto.
"""
import hmac
import json
import os

HEADER_CLAVE = "x-erp-key"

_RUTAS_GET_PROTEGIDAS = ("/ml/token", "/ml-proxy")
_METODOS_ESCRITURA = ("POST", "PUT", "PATCH", "DELETE")

_MAX_AVISADOS = 500
_avisados: set = set()


def requiere_clave(metodo: str, path: str) -> bool:
    """True si ese método + ruta es de los que exigen `X-ERP-Key`."""
    metodo = metodo.upper()
    if metodo in _METODOS_ESCRITURA:
        return True
    if metodo in ("GET", "HEAD"):
        p = path.rstrip("/") or "/"
        return p in _RUTAS_GET_PROTEGIDAS
    return False


def clave_valida(esperada: str, recibida: str | None) -> bool:
    if not recibida:
        return False
    return hmac.compare_digest(recibida.encode("utf-8"), esperada.encode("utf-8"))


class ClaveERPMiddleware:
    """Middleware ASGI. Leer `ERP_API_KEY` en cada request (no al importar)
    para que tests y cambios de entorno no dependan del orden de import."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not requiere_clave(scope["method"], scope["path"]):
            await self.app(scope, receive, send)
            return

        esperada = os.environ.get("ERP_API_KEY", "").strip()
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        ok = bool(esperada) and clave_valida(esperada, headers.get(HEADER_CLAVE))

        if ok:
            await self.app(scope, receive, send)
            return

        if not esperada:
            # Modo permisivo: pasa, pero deja rastro de quién todavía llama sin clave.
            clave_log = (scope["method"], scope["path"])
            if clave_log not in _avisados and len(_avisados) < _MAX_AVISADOS:
                _avisados.add(clave_log)
                print(f"[auth] PERMISIVO (ERP_API_KEY sin definir): {scope['method']} {scope['path']} "
                      f"sin clave verificada, origin={headers.get('origin', '-')}")
            await self.app(scope, receive, send)
            return

        detalle = "Clave del backend faltante o inválida (header X-ERP-Key)."
        cuerpo = json.dumps({"detail": detalle}).encode()
        await send({"type": "http.response.start", "status": 401,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(cuerpo)).encode())]})
        await send({"type": "http.response.body", "body": cuerpo})
