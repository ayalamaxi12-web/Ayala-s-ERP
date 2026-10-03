"""Exportación de ventas Ecom con las columnas del reporte de facturación."""
from contextlib import contextmanager
from datetime import date

import pytest

from rentabilidad import api, export_ventas_ecom as ex
from rentabilidad.models import CierreRentabilidad, VentaEcom

from .conftest import d
from .test_fravega import db_multihilo  # noqa: F401 (fixture)

P = "2026-09-23_2026-10-22"


def _venta(db, orden, dia, excluido=False, **k):
    base = dict(
        periodo=P, numero_orden=orden, skus_vendidos="TN670COMP", fecha_creacion_venta=dia, estado_pago="Cobrado",
        costo_sin_iva=d("10"), canal_de_venta="Mercadolibre", comision_venta=d("1500"), comision_cobro=d(0),
        costo_envio=d(0), precio_sin_iva=d("10000"), precio_final=d("12100"), imp_cheque=d("145.2"), iibb=d("500"),
        neto=d("7705.68"), costo_total=d("15400"), rentabilidad=d("-7694.32"), pm="Veronica", tc=d("1540"),
        vinculacion="OK", iva=d("1.21"), facturacion_iva=d("14641"), dias_de_stock="Sin ventas", excluido=excluido,
        pct_rentabilidad=d("-0.998"),
    )
    base.update(k)
    db.add(VentaEcom(**base))


def test_columnas_en_el_orden_del_reporte_y_valores(db_session):
    _venta(db_session, "2", date(2026, 10, 2))
    _venta(db_session, "1", date(2026, 10, 2))
    _venta(db_session, "3", date(2026, 10, 1))
    _venta(db_session, "4", date(2026, 10, 2), excluido=True, estado_pago="Reembolsado")
    db_session.flush()
    res = ex.exportar_ventas(db_session, P, dia=date(2026, 10, 2))
    assert res["total"] == 2 and [f["Numero Orden"] for f in res["filas"]] == ["1", "2"]
    f = res["filas"][0]
    assert list(f) == res["columnas"] and len(res["columnas"]) == 49
    assert res["columnas"][0] == "Numero Orden" and res["columnas"][-1] == "% Rentabilidad"
    assert f["FechaCreacionVenta"] == "2026-10-02" and f["Precio Final"] == 12100.0
    assert f["Total Impuestos"] == 2100.0  # Precio Final − Precio SIN IVA
    assert f["Costo por Operacion Ecom"] == 149.12
    assert f["EstadoVenta"] is None and "EstadoVenta" in res["columnas_sin_dato"]
    assert ex.exportar_ventas(db_session, P)["total"] == 3
    assert ex.exportar_ventas(db_session, P, dia=date(2026, 10, 2), incluir_excluidas=True)["total"] == 3


@pytest.fixture()
def cliente(db_multihilo, monkeypatch):  # noqa: F811
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    @contextmanager
    def _sesion():
        yield db_multihilo
        db_multihilo.flush()

    monkeypatch.setattr(api, "sesion", _sesion)
    monkeypatch.setattr(api, "ayer_en_argentina", lambda: date(2026, 10, 2))
    monkeypatch.setenv("RENT_REPORTE_TOKEN", "secreto")
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def test_endpoint(cliente, db_multihilo):
    _venta(db_multihilo, "1", date(2026, 10, 2))
    _venta(db_multihilo, "2", date(2026, 10, 1))
    db_multihilo.add(CierreRentabilidad(periodo=P, desde=date(2026, 9, 23), hasta=date(2026, 10, 2)))
    db_multihilo.flush()
    url = "/rentabilidad/reporte/ecom/ventas"
    assert cliente.get(url).status_code == 401
    h = {"X-Reporte-Token": "secreto"}
    r = cliente.get(url, headers=h).json()
    assert r["dia"] == "2026-10-02" and r["total"] == 1 and r["avisos"] == []
    assert cliente.get(url, headers=h, params={"fecha": "2026-10-01"}).json()["total"] == 1
    r = cliente.get(url, headers=h, params={"todo_el_ciclo": "true"}).json()
    assert r["dia"] is None and r["total"] == 2 and r["periodo"] == P
    r = cliente.get(url, headers=h, params={"fecha": "2026-10-05"}).json()
    assert r["total"] == 0 and "todavía no guardó" in r["avisos"][0]
