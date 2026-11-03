import json
from datetime import datetime

import pytest

import picking

SELLERS = {"IT": "115764017", "MT": "34801784"}
QR = '{"id":"48418925767","sender_id":115764017,"hash_code":null,"security_digit":null}'


class Ws:
    def __init__(self, filas=None):
        self.filas = filas if filas is not None else [list(picking.COLS)]

    def row_values(self, n):
        return self.filas[0] if self.filas else []

    def get_all_values(self):
        return [list(f) for f in self.filas]

    def append_row(self, fila, value_input_option=None):
        self.filas.append(list(fila))


class Ss:
    def __init__(self, ws):
        self.ws = ws

    def worksheet(self, t):
        return self.ws


class Resp:
    def __init__(self, code, data=None):
        self.status_code, self._d = code, data or {}

    def json(self):
        return self._d


def hdr(c):
    return {"c": c}


AHORA = datetime(2026, 11, 3, 14, 5, 9, tzinfo=picking.ART)


def test_parsear_qr_json_y_numero_suelto():
    assert picking.parsear_qr(QR) == ("48418925767", "115764017")
    assert picking.parsear_qr("48418925767") == ("48418925767", None)
    for malo in ("", "hola", "123"):
        with pytest.raises(picking.PickingError):
            picking.parsear_qr(malo)


def test_cuenta_del_vendedor():
    assert picking.cuenta_de_vendedor("115764017", SELLERS) == "IT"
    assert picking.cuenta_de_vendedor("34801784", SELLERS) == "MT"
    assert picking.cuenta_de_vendedor(None, SELLERS) is None
    with pytest.raises(picking.PickingError):
        picking.cuenta_de_vendedor("999", SELLERS)


def test_escanear_registra_y_la_segunda_vez_bloquea():
    ws = Ws()
    llamadas = []

    def get(url, h):
        llamadas.append(url)
        return Resp(200, {"order_id": 2000015844977409})

    r = picking.escanear(Ss(ws), QR, "Juan", SELLERS, hdr, get, AHORA)
    assert r["estado"] == "ok" and r["venta"] == "2000015844977409" and r["cuenta"] == "IT"
    assert ws.filas[1] == ["48418925767", "2000015844977409", "IT", "2026-11-03", "14:05:09", "Juan"]
    r2 = picking.escanear(Ss(ws), QR, "Pedro", SELLERS, hdr, get, AHORA)
    assert r2["estado"] == "duplicada" and r2["fecha"] == "2026-11-03" and r2["hora"] == "14:05:09" and r2["operador"] == "Juan"
    assert len(ws.filas) == 2 and len(llamadas) == 1            # no duplicó ni volvió a llamar a ML


def test_si_ml_no_responde_igual_registra_sin_venta():
    ws = Ws()
    r = picking.escanear(Ss(ws), QR, "", SELLERS, hdr, lambda u, h: Resp(404), AHORA)
    assert r["estado"] == "ok" and r["venta"] == "" and "aviso" in r and len(ws.filas) == 2


def test_numero_suelto_prueba_las_dos_cuentas():
    visto = []

    def get(url, h):
        visto.append(h["c"])
        return Resp(200, {"order_id": 77}) if h["c"] == "MT" else Resp(403)

    r = picking.escanear(Ss(Ws()), "48418925767", "", SELLERS, hdr, get, AHORA)
    assert visto == ["IT", "MT"] and r["cuenta"] == "MT" and r["venta"] == "77"


def test_si_cambian_los_encabezados_no_escribe():
    ws = Ws([["Otra", "cosa"]])
    with pytest.raises(picking.PickingError):
        picking.escanear(Ss(ws), QR, "", SELLERS, hdr, lambda u, h: Resp(200, {"order_id": 1}), AHORA)
    assert len(ws.filas) == 1
