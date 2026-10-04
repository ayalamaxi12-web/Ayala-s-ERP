"""Tipo de cambio BNA — implementación propia para `rentabilidad/`, mismo
principio que `gsheets.py`.

ÚNICO scraper del BNA del backend (criterio de margen §7, 2026-10): `/tc/bna`
y `ml_ofertas` en `main.py` lo usan desde acá. Dólar billete, venta, del día;
si el BNA no responde, el último TC que respondió bien (guardado en la base,
tabla `tc_bna_guardado`). Si tampoco hay uno guardado, falla — nunca devuelve
1 ni un valor fijo.

Pedido de Maxx (2026-08-10): cuando el ERP corre Ecom por período (consulta
o cierre), el TC no lo escribe una persona a mano — se toma el que informa
el BNA en el momento de correr. Sigue siendo **un solo TC para todo el
período** (regla ya confirmada, no cambia acá): se resuelve una vez al
ejecutar, no por orden ni por día.
"""
import re
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable

_URL = "https://bna.com.ar/Personas"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
_PATRONES = (
    r'Dolar U\.S\.A</td>\s*<td>([\d,\.]+)</td>\s*<td>([\d,\.]+)</td>',
    r'<td class="tit">Dolar U\.S\.A</td>\s*<td>([\d,\.]+)</td>\s*<td>([\d,\.]+)</td>',
)

class TcBnaError(RuntimeError):
    """No se pudo obtener/parsear el TC del BNA."""


def _venta_de_html(html: str) -> Decimal:
    for patron in _PATRONES:
        m = re.search(patron, html)
        if m:
            venta_str = m.group(2).replace(".", "").replace(",", ".")
            return Decimal(venta_str)
    raise TcBnaError("No se encontró la fila 'Dolar U.S.A' en la página del BNA.")


def _fetch_html_real() -> str:
    import requests

    return requests.get(_URL, headers=_HEADERS, timeout=10).text


class TcBnaClient:
    """Cache en instancia (no global de módulo) para que cada test tenga su
    propio estado — mismo TTL de 1 hora que tenía `/tc/bna` en `main.py`.

    `guardar` / `leer_ultimo` (inyectables) persisten el último TC bueno; sin
    inyectar, no persisten (tests, uso suelto) — la instancia compartida del
    proceso usa la base."""

    def __init__(self, fetch_html: Callable[[], str] | None = None, ahora: Callable[[], float] | None = None,
                 guardar: Callable[[Decimal], None] | None = None,
                 leer_ultimo: Callable[[], tuple[Decimal, datetime] | None] | None = None):
        self._fetch_html = fetch_html or _fetch_html_real
        self._ahora = ahora or time.time
        self._guardar = guardar
        self._leer_ultimo = leer_ultimo
        self._valor: Decimal | None = None
        self._vence = 0.0

    def obtener_info(self) -> dict:
        """{"tc": Decimal, "source": "bna" | "cache" | "ultimo_guardado",
        "fecha": datetime | None}. Levanta TcBnaError si no hay BNA ni TC
        guardado."""
        if self._valor is not None and self._ahora() < self._vence:
            return {"tc": self._valor, "source": "cache", "fecha": None}
        try:
            tc = _venta_de_html(self._fetch_html())
            if tc <= 0:
                raise TcBnaError(f"TC del BNA inválido: {tc}")
        except Exception as e:
            ultimo = None
            if self._leer_ultimo:
                try:
                    ultimo = self._leer_ultimo()
                except Exception:
                    ultimo = None
            if ultimo is None:
                raise TcBnaError(f"No se pudo obtener el TC del BNA ({e}) y no hay un TC guardado.") from e
            valor, fecha = ultimo
            return {"tc": valor, "source": "ultimo_guardado", "fecha": fecha}
        self._valor = tc
        self._vence = self._ahora() + 3600
        if self._guardar:
            try:
                self._guardar(tc)
            except Exception:
                pass  # no poder guardar el respaldo no debe tirar un TC bueno
        return {"tc": tc, "source": "bna", "fecha": datetime.now(timezone.utc)}

    def obtener(self) -> Decimal:
        return self.obtener_info()["tc"]


def _guardar_en_db(tc: Decimal) -> None:
    from .db import sesion
    from .models import TcBnaGuardado

    with sesion() as db:
        fila = db.get(TcBnaGuardado, "ultimo")
        if fila is None:
            db.add(TcBnaGuardado(id="ultimo", valor=tc, obtenido_en=datetime.now(timezone.utc)))
        else:
            fila.valor, fila.obtenido_en = tc, datetime.now(timezone.utc)


def _leer_de_db() -> tuple[Decimal, datetime] | None:
    from .db import sesion
    from .models import TcBnaGuardado

    with sesion() as db:
        fila = db.get(TcBnaGuardado, "ultimo")
        return (Decimal(fila.valor), fila.obtenido_en) if fila is not None and fila.valor and fila.valor > 0 else None


_cliente_default = TcBnaClient(guardar=_guardar_en_db, leer_ultimo=_leer_de_db)


def obtener_tc_bna() -> Decimal:
    """Instancia compartida a nivel de proceso: un valor, reutilizado por 1
    hora, para todos los llamadores del backend."""
    return _cliente_default.obtener()


def obtener_tc_bna_info() -> dict:
    """Igual que `obtener_tc_bna` pero con el origen (bna / cache /
    ultimo_guardado) — para `/tc/bna` y para avisar en pantalla."""
    return _cliente_default.obtener_info()
