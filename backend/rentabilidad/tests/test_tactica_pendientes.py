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
            self.description = [(c,) for c in ("nro", "creado", "ultimo", "total", "moneda", "recid", "cliente", "vendedor", "escenario")]

    def fetchall(self):
        if "COUNT(*)" in self.last:
            return [(self.total,)]
        if "pedidositems" in self.last:
            return self.items
        return self.pedidos


def fila(nro, ultimo, recid, total=1000.0, moneda=1, cliente="ACME SA", vendedor="Laura", creado=datetime(2026, 10, 1), escenario="VENTAS Esperando Pago"):
    return (nro, creado, ultimo, total, moneda, recid, cliente, vendedor, escenario)


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
    assert "Parados 3 días o más: 3 (cerrar o anular: 2 · activar: 1)" in txt and "Pendientes en total: 363" in txt
    assert "  Laura: 3 (cerrar 2 · activar 1) · ARS 2.000 · USD 250" in txt          # montos por moneda, sin mezclarlas
    assert "#1002" not in txt and "SKU-C" not in txt                                 # el mail ya no trae el detalle de cada pedido
    assert len(mail["filas"]) == 3                                                    # el Sheet recibe todos
    assert "POR PM" not in txt                                                         # sin función de PM, no hay sección de PM


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


def _guardar(db, filas_extra, escenario="PREVENTA Pago Total"):
    ped = []
    for i, (dias, vend, monto, skus) in enumerate(filas_extra):
        ult = datetime(2026, 11, 6) - __import__("datetime").timedelta(days=dias)
        ped.append({"nro": 2000 + i, "cliente": "C", "vendedor": vend, "monto": monto, "moneda": "ARS", "skus": skus, "ultimo": ult, "creado": ult,
                    "dias": dias, "nivel": tp.nivel_de(dias), "escenario": escenario})
    tp.guardar_corrida(db, HOY, ped, 500)


def test_mail_resumen_por_vendedor_con_montos_y_atraso_viejo(db_session):
    from decimal import Decimal
    _guardar(db_session, [(8, "Laura", Decimal(100), "A"), (40, "Laura", Decimal(250), "B"), (4, "Maca", Decimal(50), "C"), (5, "Maca", Decimal(0), "D")])
    m = tp.armar_mail(db_session, HOY)
    t = m["texto"]
    assert "  Laura: 2 (cerrar 2 · activar 0) · ARS 350" in t
    assert "  Maca: 2 (cerrar 0 · activar 2) · ARS 50" in t
    assert t.index("  Laura:") < t.index("  Maca:")                                  # primero quien más tiene para cerrar
    assert "de los parados, con más de 30 días: 1" in t
    assert [f["atraso_viejo"] for f in m["filas"]].count(True) == 1


def test_mail_aparta_a_maxi_las_notas_de_credito_y_las_preventas(db_session):
    from decimal import Decimal
    _guardar(db_session, [(10, "Laura", Decimal(100), "A"), (12, "Maximiliano Ayala", Decimal(5), "B"), (9, "jacqueline romero", Decimal(0), "C"),
                          (8, "Jacqueline  Romero", Decimal(0), "D"), (7, "Mariannys Rodriguez", Decimal(0), "E"), (4, "Maca", Decimal(1), "F"),
                          (9, "Laura", Decimal(7), "PV-NOV26-GL-5000, ENVIOS-BSAS-C1"), (8, "Maximiliano Ayala", Decimal(1), "PV-Y")])
    m = tp.armar_mail(db_session, HOY)
    t = m["texto"]
    assert "Parados 3 días o más: 2 (cerrar o anular: 1 · activar: 1)" in t              # solo Laura «A» y Maca cuentan arriba
    assert "Aparte, no cuentan arriba: jacqueline romero 2 · Mariannys Rodriguez 1 · Maximiliano Ayala 2 · preventas (PV-) 1" in t
    assert "  Maximiliano Ayala:" not in t and "  jacqueline romero:" not in t          # no aparecen en el resumen por vendedor
    assert "2 pedidos" in m["asunto"]
    grupos = {f["skus"]: f["grupo"] for f in m["filas"]}
    assert grupos["A"] == "pendientes" and grupos["B"] == "propios" and grupos["C"] == "notas_credito" and grupos["E"] == "notas_credito"
    assert grupos["PV-NOV26-GL-5000, ENVIOS-BSAS-C1"] == "preventas" and grupos["PV-Y"] == "propios"   # Maxi tiene prioridad sobre preventa
    assert len(m["filas"]) == 8                                                           # el Sheet recibe TODAS
    assert tp.es_preventa("PV-A") and tp.es_preventa("X, pv-b") and not tp.es_preventa("TN1060COMP, ENVIOS-CABA") and not tp.es_preventa("")


def test_mail_por_pm_con_monto_y_el_pm_va_a_las_filas(db_session):
    from decimal import Decimal
    pms = {"A1": "Laura", "A2": "Laura", "B1": "Matias", "C1": "SIN PM"}
    _guardar(db_session, [(10, "Nico", Decimal(100), "A1, A2, ENVIOS-CABA"), (9, "Nico", Decimal(50), "B1, A1, A2"), (5, "Pame", Decimal(30), "B1"),
                          (4, "Pame", Decimal(20), "C1"), (4, "Pame", Decimal(10), "ENVIOS-CABA")])
    m = tp.armar_mail(db_session, HOY, pm_fn=lambda sku: pms.get(sku))
    t = m["texto"]
    assert "POR PM (pedidos · monto" in t
    assert "  Laura: 2 (cerrar 2 · activar 0) · ARS 150" in t          # gana el PM con más ítems (los ENVIOS no cuentan)
    assert "  Matias: 1 (cerrar 0 · activar 1) · ARS 30" in t
    assert "  Sin PM: 2 (cerrar 0 · activar 2) · ARS 30" in t           # sin SKU con PM (o solo envío)
    assert {f["skus"]: f["pm"] for f in m["filas"]}["B1, A1, A2"] == "Laura"


def test_si_falla_la_planilla_de_pm_el_mail_sale_igual_sin_esa_seccion(db_session):
    from decimal import Decimal
    _guardar(db_session, [(10, "Nico", Decimal(100), "A1")])
    def roto(sku):
        raise RuntimeError("Sheets caído")
    m = tp.armar_mail(db_session, HOY, pm_fn=roto)
    assert m["hay_datos"] and "POR VENDEDOR" in m["texto"] and "POR PM: no disponible hoy" in m["texto"]
    assert m["filas"][0]["pm"] == ""


def test_estado_pago_segun_el_escenario():
    casos = {"VENTAS Esperando Pago": "Esperando pago", "PREVENTA Esperando Pago": "Esperando pago", "PREVENTA Pago Total": "Pagado",
             "PREVENTA Pago Parcial": "Pago parcial", "VENTAS Pago Enviado": "Pago a confirmar", "COBRA Pago Recibido Mostrador (NO FACTURAR) a Confirmar": "Pago a confirmar",
             "COBRA Autorizado a Armar": "Pagado", "COBRA Autorizado": "Pagado", "DEPO Recibido": tp.PAGO_SIN_DATO, "FACTURAR Preventa": tp.PAGO_SIN_DATO,
             "empty": tp.PAGO_SIN_DATO, "": tp.PAGO_SIN_DATO, None: tp.PAGO_SIN_DATO, "  ventas   ESPERANDO PAGO ": "Esperando pago"}
    for escenario, esperado in casos.items():
        assert tp.estado_pago_de(escenario) == esperado, escenario


def test_el_escenario_se_trae_se_guarda_y_sale_en_el_mail_y_en_las_filas(db_session):
    pedidos, total = tp.consultar_pendientes(cur_base(), HOY)
    assert {p["escenario"] for p in pedidos} == {"VENTAS Esperando Pago"}
    assert "p.Escenario AS escenario" in tp.SQL_PEDIDOS
    tp.guardar_corrida(db_session, HOY, pedidos, total)
    assert db_session.query(TacticaPendiente).filter_by(fecha=HOY).first().escenario == "VENTAS Esperando Pago"
    m = tp.armar_mail(db_session, HOY)
    assert all(f["escenario"] == "VENTAS Esperando Pago" and f["estado_pago"] == "Esperando pago" for f in m["filas"])
