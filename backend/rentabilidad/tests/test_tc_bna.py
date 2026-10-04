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


def _bna_caido():
    raise RuntimeError("BNA caído")


def test_guarda_el_tc_cada_vez_que_el_bna_responde_bien():
    guardados = []
    cliente = TcBnaClient(fetch_html=lambda: _HTML_REAL, guardar=guardados.append)
    info = cliente.obtener_info()
    assert info["source"] == "bna" and info["tc"] == Decimal("1460.50")
    assert guardados == [Decimal("1460.50")]


def test_si_el_bna_no_responde_usa_el_ultimo_guardado():
    from datetime import datetime, timezone

    fecha = datetime(2026, 10, 1, tzinfo=timezone.utc)
    cliente = TcBnaClient(fetch_html=_bna_caido, leer_ultimo=lambda: (Decimal("1399.00"), fecha))
    info = cliente.obtener_info()
    assert info == {"tc": Decimal("1399.00"), "source": "ultimo_guardado", "fecha": fecha}
    assert cliente.obtener() == Decimal("1399.00")


def test_si_el_html_no_trae_la_fila_tambien_cae_al_ultimo_guardado():
    from datetime import datetime, timezone

    cliente = TcBnaClient(fetch_html=lambda: "<html></html>",
                          leer_ultimo=lambda: (Decimal("1399.00"), datetime.now(timezone.utc)))
    assert cliente.obtener() == Decimal("1399.00")


def test_sin_bna_y_sin_guardado_falla_nunca_devuelve_1():
    cliente = TcBnaClient(fetch_html=_bna_caido, leer_ultimo=lambda: None)
    with pytest.raises(TcBnaError):
        cliente.obtener()
    with pytest.raises(TcBnaError):
        TcBnaClient(fetch_html=_bna_caido).obtener()


def test_un_error_al_guardar_no_tira_el_tc_bueno():
    def guardar(_):
        raise RuntimeError("base caída")

    assert TcBnaClient(fetch_html=lambda: _HTML_REAL, guardar=guardar).obtener() == Decimal("1460.50")


def test_persistencia_en_db_guarda_y_lee(db_session, monkeypatch):
    from contextlib import contextmanager

    from rentabilidad import db as db_mod
    from rentabilidad import tc_bna

    @contextmanager
    def _sesion():
        yield db_session

    monkeypatch.setattr(db_mod, "sesion", _sesion)
    assert tc_bna._leer_de_db() is None
    tc_bna._guardar_en_db(Decimal("1450.25"))
    tc_bna._guardar_en_db(Decimal("1460.50"))  # se pisa, no se acumula
    valor, fecha = tc_bna._leer_de_db()
    assert valor == Decimal("1460.500000") and fecha is not None
