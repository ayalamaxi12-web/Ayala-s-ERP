"""TC del BNA — mismo scraping que `/tc/bna` de `main.py`, reimplementado
para no acoplar `rentabilidad/` al resto del backend. `TcBnaClient` acepta
`fetch_html`/`ahora` inyectados, sin red real."""
from decimal import Decimal

import pytest

from rentabilidad.tc_bna import TcBnaClient, TcBnaError

_HTML_REAL = """
<table><tbody><tr>
<td>Dolar U.S.A</td><td>1.440,00</td><td>1.460,50</td>
</tr></tbody></table>
"""

_HTML_FALLBACK = """
<table><tbody><tr>
<td class="tit">Dolar U.S.A</td><td>1.440,00</td><td>1.460,50</td>
</tr></tbody></table>
"""


def test_parsea_la_columna_venta_no_la_de_compra():
    cliente = TcBnaClient(fetch_html=lambda: _HTML_REAL)
    assert cliente.obtener() == Decimal("1460.50")


def test_usa_el_patron_de_respaldo_si_cambia_el_html():
    cliente = TcBnaClient(fetch_html=lambda: _HTML_FALLBACK)
    assert cliente.obtener() == Decimal("1460.50")


def test_falla_claro_si_no_encuentra_la_fila():
    cliente = TcBnaClient(fetch_html=lambda: "<html>sin esa fila</html>")
    with pytest.raises(TcBnaError):
        cliente.obtener()


def test_cachea_una_hora_no_pide_html_de_nuevo():
    llamadas = {"n": 0}

    def fetch_html():
        llamadas["n"] += 1
        return _HTML_REAL

    ahora = {"t": 1000.0}
    cliente = TcBnaClient(fetch_html=fetch_html, ahora=lambda: ahora["t"])
    cliente.obtener()
    ahora["t"] += 1800  # 30 min despues, todavia dentro del cache de 1h
    cliente.obtener()
    assert llamadas["n"] == 1


def test_vuelve_a_pedir_html_despues_de_una_hora():
    llamadas = {"n": 0}

    def fetch_html():
        llamadas["n"] += 1
        return _HTML_REAL

    ahora = {"t": 1000.0}
    cliente = TcBnaClient(fetch_html=fetch_html, ahora=lambda: ahora["t"])
    cliente.obtener()
    ahora["t"] += 3700  # más de 1 hora
    cliente.obtener()
    assert llamadas["n"] == 2
