"""Rechequeo de ventas Ecom: agrega SOLO las que faltan en el ERP y en el Sheet «Historial Automatizaciones»."""
from datetime import date
from decimal import Decimal

import pytest

from rentabilidad import rechequeo_ecom as rc
from rentabilidad.models import VentaEcom

from .conftest import d

P = "2026-10-23_2026-11-22"


def _v(orden, dia=date(2026, 11, 5), excluido=False, estado="Cobrado", **k):
    base = dict(periodo=P, numero_orden=orden, skus_vendidos="SKU1", fecha_creacion_venta=dia, estado_pago=estado, excluido=excluido, costo_sin_iva=d("10"), canal_de_venta="Mercadolibre",
                comision_venta=d("1210"), comision_cobro=d(0), costo_envio=d("605"), precio_sin_iva=d("10000"), precio_final=d("12100"), imp_cheque=d("145.2"), iibb=d("500"),
                neto=d("7000"), costo_total=d("15400"), rentabilidad=d("-8400"), pm="Laura", tc=d("1540"), pct_rentabilidad=d("-0.84"))
    base.update(k)
    return VentaEcom(**base)


class _Hoja:
    def __init__(self, numeros, encabezados=("Numero Orden", "Precio Final", "Comision Venta", "Comision Venta SIN IVA", "Columna Nueva"), filas=None):
        self.numeros, self.encabezados, self.titulo, self.escritas, self.pisadas = set(numeros), list(encabezados), "Ecom", [], []
        self.filas_por_numero = filas if filas is not None else {n: [i + 2] for i, n in enumerate(sorted(self.numeros))}

    def actualizar(self, items):
        self.pisadas += items
        return len(items)

    def agregar(self, filas):
        self.escritas += filas
        return len(filas)


def test_ultimo_ciclo_cerrado():
    assert rc.ultimo_ciclo_cerrado(date(2026, 11, 24)) == (date(2026, 10, 23), date(2026, 11, 22))
    assert rc.ultimo_ciclo_cerrado(date(2026, 11, 23)) == (date(2026, 10, 23), date(2026, 11, 22))
    assert rc.ultimo_ciclo_cerrado(date(2026, 12, 10)) == (date(2026, 10, 23), date(2026, 11, 22))


def test_revisar_cuenta_y_no_escribe_nada(db_session):
    db_session.add(_v("A")); db_session.add(_v("B", excluido=True, estado="Pendiente")); db_session.flush()
    frescas = [_v("A"), _v("B"), _v("C"), _v("D", excluido=True, estado="Pendiente")]          # C es nueva; B ahora está cobrada; D sigue sin cobrar
    frescas[1].excluido = False
    hoja = _Hoja({"A"})
    r = rc.comparar_y_aplicar(db_session, frescas, hoja, date(2026, 10, 23), date(2026, 11, 22), ejecutar=False)
    assert (r["en_ecom"], r["cobradas"], r["sin_cobrar_excluidas"]) == (4, 3, 1)
    assert (r["faltan_en_erp"], r["reactivadas_en_erp"], r["faltan_en_sheet"]) == (2, 1, 2)       # C y D faltan en el ERP; B se reactiva; B y C faltan en el Sheet
    assert not r["ejecutado"] and hoja.escritas == [] and db_session.query(VentaEcom).count() == 2


def test_confirmar_agrega_solo_las_que_faltan_y_alinea_columnas_por_encabezado(db_session):
    db_session.add(_v("A")); db_session.flush()
    frescas = [_v("A"), _v("C", comision_venta=d("1210"), costo_envio=d("605"), fecha_creacion_venta=date(2026, 11, 18))]
    hoja = _Hoja({"A"})
    r = rc.comparar_y_aplicar(db_session, frescas, hoja, date(2026, 10, 23), date(2026, 11, 22), ejecutar=True, costo_operacion=d("149.12"))
    assert r["agregadas_a_erp"] == 1 and r["agregadas_al_sheet"] == 1
    assert {v.numero_orden for v in db_session.query(VentaEcom).all()} == {"A", "C"}
    assert db_session.query(VentaEcom).filter_by(numero_orden="C").one().periodo == P                # el período sale de la fecha de la orden
    fila = hoja.escritas[0]
    assert fila["Numero Orden"] == "C" and fila["Precio Final"] == 12100.0
    assert fila["Comision Venta SIN IVA"] == 1000.0         # 18/11: ya con el criterio sin IVA
    # segunda vez: no duplica
    hoja.numeros.add("C")
    r2 = rc.comparar_y_aplicar(db_session, [_v("A"), _v("C")], hoja, date(2026, 10, 23), date(2026, 11, 22), ejecutar=True)
    assert r2["faltan_en_erp"] == 0 and r2["faltan_en_sheet"] == 0 and len(hoja.escritas) == 1


def test_una_orden_sin_cobrar_que_ahora_esta_cobrada_reemplaza_a_la_guardada(db_session):
    db_session.add(_v("B", excluido=True, estado="Pendiente", neto=None, rentabilidad=None)); db_session.flush()
    hoja = _Hoja(set())
    r = rc.comparar_y_aplicar(db_session, [_v("B")], hoja, date(2026, 10, 23), date(2026, 11, 22), ejecutar=True)
    filas = db_session.query(VentaEcom).filter_by(numero_orden="B").all()
    assert r["reactivadas_en_erp"] == 1 and len(filas) == 1 and filas[0].excluido is False and filas[0].estado_pago == "Cobrado"
    assert r["agregadas_al_sheet"] == 1 and hoja.escritas[0]["Numero Orden"] == "B"


def test_los_numeros_de_orden_se_comparan_sin_ceros_decimales():
    assert rc.norm_orden(1387291.0) == "1387291" and rc.norm_orden(" 1387291.0 ") == "1387291" and rc.norm_orden("v90781066frvg-01") == "v90781066frvg-01"


class _WS:
    def __init__(self, titulo, cab, col):
        self.title, self._cab, self._col = titulo, cab, col

    def row_values(self, n): return self._cab

    def col_values(self, n): return ["Numero Orden", *self._col]


class _SS:
    def __init__(self, hojas): self._h = hojas
    def worksheets(self): return self._h
    def worksheet(self, t): return next(h for h in self._h if h.title == t)


class _GC:
    def __init__(self, hojas): self._ss = _SS(hojas)
    def open_by_key(self, k): return self._ss


def test_detecta_la_pestana_de_ventas_por_sus_encabezados():
    cab = ["Numero Orden", "Comision Venta", "Precio Final"]
    gc = _GC([_WS("Maca", ["Fecha", "SKU"], []), _WS("Ecom Nov", cab, ["1", "2.0"])])
    h = rc.HojaSheet.detectar(gc)
    assert h.titulo == "Ecom Nov" and h.numeros == {"1", "2"}
    with pytest.raises(ValueError, match="No encontré"):
        rc.HojaSheet.detectar(_GC([_WS("Maca", ["Fecha"], [])]))
    with pytest.raises(ValueError, match="más de una"):
        rc.HojaSheet.detectar(_GC([_WS("A", cab, []), _WS("B", cab, [])]))
    assert rc.HojaSheet.detectar(_GC([_WS("A", cab, []), _WS("Ventas Ecom", cab, [])])).titulo == "Ventas Ecom"


def test_confirmar_sin_revision_previa_da_409():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from rentabilidad import api
    app = FastAPI()
    app.include_router(api.router)
    c = TestClient(app)
    assert c.post("/rentabilidad/rechequeo/ecom", json={"ejecutar": True, "revision_id": "nada"}).status_code == 409
    assert c.post("/rentabilidad/rechequeo/ecom", json={"desde": "2026-11-05", "hasta": "2026-11-01"}).status_code == 422
    assert c.get("/rentabilidad/rechequeo/ecom/status/x").json() == {"status": "not_found"}


def test_frávega_con_comision_real_pisa_la_fila_del_sheet_en_vez_de_duplicarla(db_session):
    ahora_real = _v("F1", canal_de_venta="Fravega", origen_comision="LIQUIDACION_FRAVEGA", orden_externa="F-1", comision_venta=d("3000"), fecha_creacion_venta=date(2026, 11, 20))
    estimada = _v("F2", canal_de_venta="Fravega", origen_comision="ESTIMADO_FRAVEGA", orden_externa="F-2")
    ml = _v("M1")
    hoja = _Hoja({"F1", "F2", "M1"}, filas={"F1": [5, 9], "F2": [6], "M1": [7]})
    r = rc.comparar_y_aplicar(db_session, [ahora_real, estimada, ml], hoja, date(2026, 10, 23), date(2026, 11, 22), ejecutar=True)
    assert r["faltan_en_sheet"] == 0 and r["agregadas_al_sheet"] == 0                           # ninguna se duplica
    assert r["fravega_con_comision_real"] == 1 and r["fravega_con_comision_estimada"] == 1 and r["fravega_a_pisar_en_sheet"] == 1 and r["fravega_pisadas_en_sheet"] == 2
    assert sorted(n for n, _ in hoja.pisadas) == [5, 9]                                         # solo la de comisión real (y todas sus filas); ni la estimada ni la de ML
    assert all(f["Numero Orden"] == "F1" and f["Comision Venta"] == 3000.0 for _, f in hoja.pisadas)
    assert hoja.escritas == []


def test_si_frávega_no_se_cerro_no_se_pisa_nada(db_session):
    real = _v("F1", canal_de_venta="Fravega", origen_comision="LIQUIDACION_FRAVEGA", orden_externa="F-1")
    hoja = _Hoja({"F1"})
    r = rc.comparar_y_aplicar(db_session, [real], hoja, date(2026, 10, 23), date(2026, 11, 22), ejecutar=True, pisar_fravega=False)
    assert r["fravega_a_pisar_en_sheet"] == 0 and r["fravega_pisadas_en_sheet"] == 0 and hoja.pisadas == []


def test_la_hoja_real_pisa_por_lotes_sin_agregar_filas():
    class _WSX:
        title = "Ecom"
        def __init__(self): self.lotes = []
        def row_values(self, n): return ["Numero Orden", "Precio Final", "Comision Venta"]
        def col_values(self, n): return ["Numero Orden", "A", "F1", "F1"]
        def batch_update(self, datos, value_input_option=None): self.lotes.append((datos, value_input_option))
    ws = _WSX()
    h = rc.HojaSheet(ws)
    assert h.filas_por_numero == {"A": [2], "F1": [3, 4]}
    assert h.actualizar([(3, {"Numero Orden": "F1", "Precio Final": 100.0, "Comision Venta": 5.0}), (4, {"Numero Orden": "F1", "Comision Venta": 5.0})]) == 2
    datos, modo = ws.lotes[0]
    assert modo == "USER_ENTERED" and datos[0] == {"range": "A3:C3", "values": [["F1", 100.0, 5.0]]} and datos[1]["range"] == "A4:C4" and datos[1]["values"] == [["F1", "", 5.0]]


def test_revision_de_frávega_avisa_si_la_sesion_vencio_y_cuenta_cuantas_se_cierran(monkeypatch):
    from decimal import Decimal as D
    from rentabilidad import api, fravega_seller as fs
    f1 = _v("F1", canal_de_venta="Fravega", origen_comision="ESTIMADO_FRAVEGA", orden_externa="F-1")
    f2 = _v("F2", canal_de_venta="Fravega", origen_comision="ESTIMADO_FRAVEGA", orden_externa="F-2")
    ml = _v("M1")
    ordenes = [fs.OrdenProximaLiquidacion("F-1", "Facturada", date(2026, 11, 5), D(100), D(20), D(5), D(0), D(75)),
               fs.OrdenProximaLiquidacion("F-2", "Devuelta", date(2026, 11, 5), D(100), D(20), D(5), D(0), D(75))]
    monkeypatch.setattr(fs, "traer_proxima_liquidacion", lambda: ordenes)
    r = api._fravega_en_revision(True, [f1, f2, ml])
    assert r["ok"] and r["orden_ecom"] == 2 and r["se_cierran"] == 1 and r["ordenes_en_proxima_liquidacion"] == 2         # la devuelta queda estimada
    def vencida(): raise fs.SesionFravegaVencida("renová las cookies")
    monkeypatch.setattr(fs, "traer_proxima_liquidacion", vencida)
    r2 = api._fravega_en_revision(True, [f1])
    assert not r2["ok"] and "cookies" in r2["error"]
    assert api._fravega_en_revision(False, [f1]) == {"pedido": False}
