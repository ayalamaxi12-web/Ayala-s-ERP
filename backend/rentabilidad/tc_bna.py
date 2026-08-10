"""Tipo de cambio BNA — implementación propia para `rentabilidad/`, mismo
principio que `gsheets.py` (no se importa de `backend/main.py` para no
acoplar este paquete al resto del backend; ver docstring de gsheets.py).

Mismo scraping que `/tc/bna` de `main.py` (misma URL, mismo regex, mismo
criterio de "venta" del dólar billete) — reimplementado, no reutilizado,
para no crear un import circular (`main.py` ya importa `rentabilidad.api`).

Pedido de Maxx (2026-08-10): cuando el ERP corre Ecom por período (consulta
o cierre), el TC no lo escribe una persona a mano — se toma el que informa
el BNA en el momento de correr. Sigue siendo **un solo TC para todo el
período** (regla ya confirmada, no cambia acá): se resuelve una vez al
ejecutar, no por orden ni por día.
"""
import re
import time
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
    propio estado — mismo TTL de 1 hora que `/tc/bna` en `main.py`."""

    def __init__(self, fetch_html: Callable[[], str] | None = None, ahora: Callable[[], float] | None = None):
        self._fetch_html = fetch_html or _fetch_html_real
        self._ahora = ahora or time.time
        self._valor: Decimal | None = None
        self._vence = 0.0

    def obtener(self) -> Decimal:
        if self._valor is not None and self._ahora() < self._vence:
            return self._valor
        tc = _venta_de_html(self._fetch_html())
        self._valor = tc
        self._vence = self._ahora() + 3600
        return tc


_cliente_default = TcBnaClient()


def obtener_tc_bna() -> Decimal:
    """Instancia compartida a nivel de proceso (mismo criterio que el
    cache de `main.py`: un valor, reutilizado por 1 hora, para todos los
    llamadores del backend)."""
    return _cliente_default.obtener()
