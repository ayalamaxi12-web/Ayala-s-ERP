from datetime import date, datetime

import pytest

import tactica_pedidos
import tactica_pendientes as tp
from rentabilidad.models import TacticaPendiente

HOY = date(2026, 11, 6)


class Cur:
    """Cursor de prueba: responde según la consulta y guarda todo lo que se le pide (para verificar que sea solo lectura)."""

    def __init__(self, pedidos, items, total=363):
        self.pedidos, self.items, self.total, self.q, self.params = pedidos, items, total, [], []

    def execute(self, sql, params=()):
        self.q.append(sql)
        self.params.append(params)
        self.last = sql
        if "COUNT(*)" in sql:
            self.description = [("n",)]
        elif "pedidositems" in sql:
            self.description = [("IDPedido",), ("Codigo",)]
        else:
            self.description = [(c,) for c in ("nro", "creado", "ultimo", "total", "moneda", "recid", "cliente", "vendedor")]

    def fetchall(self):
        if "COUNT(*)" in self.last:
            return [(self.total,)]
        if "pedidositems" in self.last:
            return self.items
        return self.pedidos


def fila(nro, ultimo, recid, total=1000.0, moneda=1, cliente="ACME SA", vendedor="Laura", creado=datetime(2026, 10, 1)):
    return (nro, creado, ultimo, total, moneda, recid, cliente, vendedor)


def cur_base():
    return Cur(
        [fila(1001, datetime(2026, 11, 3, 10), "R1"), fila(1002, datetime(2026, 10, 25, 9), "R2", moneda=2, total=250.5),
         fila(1003, datetime(2026, 11, 4, 9), "R3"), fila(1004, datetime(2026, 10, 30, 23, 59), "R4")],
        [("R1", "SKU-A  "), ("R1", "SKU-B"), ("R1", "SKU-A"), ("R2", "SKU-C")])


def test_niveles_y_orden_por_dias():
    c = cur_base()
    pedidos, total = tp.consultar_pendientes(c, HOY)
    assert total == 363
    por = {p["nro"]: p for p in pedidos}
    assert [p["nro"] for p in pedidos] == [1002, 1004, 1001]                 # 12, 7, 3 días; 1003 (2 días) no entra
    assert por[1001]["dias"] == 3 and por[1001]["nivel"] == "activar"
    assert por[1004]["dias"] == 7 and por[1004]["nivel"] == "cerrar_o_anular"
    assert por[1002]["dias"] == 12 and por[1002]["moneda"] == "USD"
    assert por[1001]["skus"] == "SKU-A, SKU-B"                               # sin espacios ni repetidos


def test_las_consultas_son_solo_lectura_y_con_nolock():
    c = cur_base()
    tp.consultar_pendientes(c, HOY)
    assert len(c.q) == 3
    for q in c.q:
        tactica_pedidos.verificar_select(q)
        assert "WITH (NOLOCK)" in q
    assert c.params[0] == (tp.ESTADO_PENDIENTE,)                             # estado 0 = Pendiente


def test_guardar_historial_y_mail(db_session):
    pedidos, total = tp.consultar_pendientes(cur_base(), HOY)
    r = tp.guardar_corrida(db_session, HOY, pedidos, total)
    assert r == {"estado": "ok", "total_pendientes": 363, "parados": 3, "cerrar_o_anular": 2, "activar": 1}
    mail = tp.armar_mail(db_session, HOY)
    assert mail["hay_datos"] and "2 para cerrar o anular" in mail["asunto"]
    txt = mail["texto"]
    assert txt.index("CERRAR O ANULAR") < txt.index("ACTIVAR")
    assert txt.index("#1002") < txt.index("#1004") < txt.index("#1001")       # primero cerrar/anular, por días de mayor a menor; después activar
    assert "USD 250" in txt and "SKU-C" in txt


def test_repetir_el_dia_reemplaza_y_conserva_otros_dias(db_session):
    p, t = tp.consultar_pendientes(cur_base(), HOY)
    tp.guardar_corrida(db_session, date(2026, 11, 5), p, t)
    tp.guardar_corrida(db_session, HOY, p, t)
    tp.guardar_corrida(db_session, HOY, p[:1], t)                              # misma fecha: reemplaza
    assert db_session.query(TacticaPendiente).filter_by(fecha=HOY).count() == 1
    assert db_session.query(TacticaPendiente).filter_by(fecha=date(2026, 11, 5)).count() == 3
    h = tp.historial_pedido(db_session, 1002)
    assert [x["fecha"] for x in h] == ["2026-11-05", "2026-11-06"]


def test_sin_corrida_del_dia_avisa_que_no_hay_datos(db_session):
    m = tp.armar_mail(db_session, HOY)
    assert not m["hay_datos"] and "No se recibieron datos de Táctica hoy: revisar la PC o la VPN." in m["texto"]


def test_error_se_anota_y_no_pisa_una_corrida_buena(db_session):
    tp.registrar_error(db_session, HOY, "túnel caído")
    m = tp.armar_mail(db_session, HOY)
    assert not m["hay_datos"] and "túnel caído" in m["texto"]
    p, t = tp.consultar_pendientes(cur_base(), HOY)
    tp.guardar_corrida(db_session, HOY, p, t)
    tp.registrar_error(db_session, HOY, "otro error")                          # ya hay una buena: no la pisa
    assert tp.armar_mail(db_session, HOY)["hay_datos"]


def test_sin_pedidos_parados(db_session):
    tp.guardar_corrida(db_session, HOY, [], 120)
    m = tp.armar_mail(db_session, HOY)
    assert m["hay_datos"] and "sin pedidos pendientes parados" in m["asunto"]
