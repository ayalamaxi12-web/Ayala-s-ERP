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


def _guardar(db, filas_extra):
    ped = []
    for i, (dias, vend, monto, skus) in enumerate(filas_extra):
        ult = datetime(2026, 11, 6) - __import__("datetime").timedelta(days=dias)
        ped.append({"nro": 2000 + i, "cliente": "C", "vendedor": vend, "monto": monto, "moneda": "ARS", "skus": skus, "ultimo": ult, "creado": ult,
                    "dias": dias, "nivel": tp.nivel_de(dias)})
    tp.guardar_corrida(db, HOY, ped, 500)


def test_mail_el_tope_es_por_grupo_y_activar_siempre_se_ve(db_session):
    from decimal import Decimal
    _guardar(db_session, [(10, "Laura", Decimal(100), "A")] * (tp.MAX_FILAS_GRUPO + 15) + [(4, "Maca", Decimal(100), "B")] * 3)
    m = tp.armar_mail(db_session, HOY)
    t = m["texto"]
    assert "ACTIVAR (3 a 6 días) · 3" in t and t.count("  #") == tp.MAX_FILAS_GRUPO + 3          # 40 de cerrar + los 3 de activar
    assert "… y 15 más (están en el Sheet)." in t
    assert len(m["filas"]) == tp.MAX_FILAS_GRUPO + 18                                          # el Sheet recibe TODOS


def test_mail_resumen_por_vendedor_atraso_viejo_y_avisos(db_session):
    from decimal import Decimal
    _guardar(db_session, [(8, "Laura", Decimal(100), "A"), (40, "Laura", Decimal(100), "B"), (90, "Maca", Decimal(0), "X"), (4, "Maca", Decimal(50), "C")])
    m = tp.armar_mail(db_session, HOY)
    t = m["texto"]
    assert "  Laura: 2 (cerrar 2 · activar 0)" in t and "  Maca: 2 (cerrar 1 · activar 1)" in t
    assert "Para revisar: 1 con monto 0" in t
    assert "ATRASO VIEJO (más de 30 días) · 2" in t
    detalle = t[: t.index("ATRASO VIEJO")]
    assert "#2000" in detalle and "#2001" not in detalle and "#2002" not in detalle           # los de más de 30 días no se listan en el mail
    assert [f["atraso_viejo"] for f in m["filas"]].count(True) == 2


def test_mail_aparta_a_maxi_y_las_notas_de_credito_y_las_pone_en_su_grupo(db_session):
    from decimal import Decimal
    _guardar(db_session, [(10, "Laura", Decimal(100), "A"), (12, "Maximiliano Ayala", Decimal(5), "B"), (9, "jacqueline romero", Decimal(0), "C"),
                          (8, "Jacqueline  Romero", Decimal(0), "D"), (7, "Mariannys Rodriguez", Decimal(0), "E"), (4, "Maca", Decimal(1), "F")])
    m = tp.armar_mail(db_session, HOY)
    t = m["texto"]
    assert "parados 3 días o más: 2 (cerrar o anular: 1 · activar: 1)" in t                  # solo Laura y Maca cuentan arriba
    assert "Aparte, no cuentan arriba: jacqueline romero 2 · Mariannys Rodriguez 1 · Maximiliano Ayala 1" in t
    detalle = t[: t.index("El detalle completo")]
    assert "#2000" in detalle and "#2005" in detalle and "#2001" not in detalle and "#2002" not in detalle  # las apartadas no se listan
    assert "5 pedidos" not in m["asunto"] and "2 pedidos" in m["asunto"]
    grupos = {f["vendedor"]: f["grupo"] for f in m["filas"]}
    assert grupos["Maximiliano Ayala"] == "propios" and grupos["jacqueline romero"] == "notas_credito"
    assert grupos["Jacqueline  Romero"] == "notas_credito" and grupos["Mariannys Rodriguez"] == "notas_credito" and grupos["Laura"] == "pendientes"
    assert len(m["filas"]) == 6                                                              # el Sheet recibe TODAS


def test_preventas_van_a_su_grupo_y_el_vendedor_apartado_tiene_prioridad(db_session):
    from decimal import Decimal
    _guardar(db_session, [(10, "Laura", Decimal(100), "A"), (12, "Laura", Decimal(5), "PV-NOV26-GL-5000, ENVIOS-BSAS-C1"), (9, "Maca", Decimal(1), "pv-x"),
                          (8, "Maximiliano Ayala", Decimal(1), "PV-Y")])
    m = tp.armar_mail(db_session, HOY)
    t = m["texto"]
    assert "parados 3 días o más: 1 (cerrar o anular: 1 · activar: 0)" in t                    # solo el pedido «A» cuenta arriba
    assert "Aparte, no cuentan arriba: Maximiliano Ayala 1 · preventas (PV-) 2" in t
    grupos = {f["skus"]: f["grupo"] for f in m["filas"]}
    assert grupos["A"] == "pendientes" and grupos["pv-x"] == "preventas" and grupos["PV-NOV26-GL-5000, ENVIOS-BSAS-C1"] == "preventas"
    assert grupos["PV-Y"] == "propios"                                                         # Maxi tiene prioridad sobre preventa
    assert tp.es_preventa("PV-A") and tp.es_preventa("X, pv-b") and not tp.es_preventa("TN1060COMP, ENVIOS-CABA") and not tp.es_preventa("")
