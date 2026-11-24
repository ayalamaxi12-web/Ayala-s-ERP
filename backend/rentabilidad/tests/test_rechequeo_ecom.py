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
    def __init__(self, numeros, encabezados=("Numero Orden", "Precio Final", "Comision Venta SIN IVA", "Columna Nueva")):
        self.numeros, self.encabezados, self.titulo, self.escritas = set(numeros), list(encabezados), "Ecom", []

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
