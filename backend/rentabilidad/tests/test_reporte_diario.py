"""Reporte diario ECOM (solo lectura) para n8n."""
from datetime import date, datetime
from decimal import Decimal

import pytest

from rentabilidad.models import CierreRentabilidad, VentaEcom
from rentabilidad.reporte_diario import reporte_diario

PERIODO = "2026-09-23_2026-10-22"


def _venta(orden, dia, pf, rent, **kw):
    base = dict(
        periodo=PERIODO, numero_orden=orden, skus_vendidos="SKU-A", fecha_creacion_venta=dia,
        costo_sin_iva=Decimal(1), comision_venta=Decimal(0), costo_envio=Decimal(0),
        precio_final=Decimal(pf), precio_sin_iva=Decimal(pf) / Decimal("1.21"),
        rentabilidad=None if rent is None else Decimal(rent), tc=Decimal(1540), pm="Veronica",
        canal_de_venta="Mercadolibre Carrito", es_full=False, origen_comision="API",
    )
    base.update(kw)
    return VentaEcom(**base)


@pytest.fixture()
def ciclo(db_session):
    d27, d26 = date(2026, 9, 27), date(2026, 9, 26)
    db_session.add_all([
        _venta("1", d27, "12100", "1000", skus_vendidos="TONER-1", es_full=True),
        _venta("2", d27, "24200", "-500", skus_vendidos="PLANCHA-1", pm="Matias"),
        _venta("3", d27, "6050", None, skus_vendidos=""),  # costo 0 sin SKU
        _venta("4", d26, "60500", "9000", skus_vendidos="TONER-1", canal_de_venta="Fravega",
               origen_comision="ESTIMADO_FRAVEGA", orden_externa="v1frvg-01"),
        _venta("5", d27, "12100", "2000", canal_de_venta="OnCity", skus_vendidos="SOPORTE-1"),
        _venta("6", d27, "1", "1", excluido=True),  # excluida: no cuenta
        _venta("7", date(2026, 9, 28), "999", "9"),  # posterior a `dia`: no cuenta
    ])
    db_session.add(CierreRentabilidad(
        periodo=PERIODO, desde=date(2026, 9, 23), hasta=date(2026, 9, 27), ecom_guardado=True,
        ecom_origen="api", generado_en=datetime(2026, 9, 28, 9, 1), tc_ecom=Decimal("1443.10"),
        tc_ecom_origen="BNA dólar billete venta, consultado 2026-09-28 06:00 ART",
    ))
    db_session.flush()
    return db_session


def test_ayer_y_acumulado(ciclo):
    r = reporte_diario(ciclo, date(2026, 9, 27))
    assert r["periodo"] == PERIODO and r["avisos"] == []
    ayer, acum = r["general"]["ayer"], r["general"]["acumulado_ciclo"]
    assert ayer["ordenes"] == 4 and ayer["facturacion"] == 54450.0 and ayer["rentabilidad"] == 2500.0
    assert acum["ordenes"] == 5 and acum["facturacion"] == 114950.0
    assert ayer["rentabilidad_pct"] == round(2500 / (54450 / 1.21) * 100, 2)


def test_por_pm_con_sus_top_skus(ciclo):
    pms = {p["pm"]: p for p in reporte_diario(ciclo, date(2026, 9, 27))["general"]["por_pm"]["ciclo"]}
    assert pms["Veronica"]["ordenes"] == 4
    assert pms["Veronica"]["top_skus"][0] == {"sku": "TONER-1", "facturacion": 72600.0}
    assert len(pms["Veronica"]["top_skus"]) == 2
    assert pms["Matias"]["rentabilidad"] == -500.0


def test_top_del_dia_y_perdidas(ciclo):
    g = reporte_diario(ciclo, date(2026, 9, 27))["general"]
    assert g["ayer_mas_facturaron"][0]["sku"] == "PLANCHA-1"
    assert [x["sku"] for x in g["ayer_en_perdida"]] == ["PLANCHA-1"]


def test_alertas(ciclo):
    a = reporte_diario(ciclo, date(2026, 9, 27))["general"]["alertas"]
    assert a["costo_cero"] == [{"orden": "3", "skus": "(sin SKU)", "fecha": "2026-09-27",
                                "canal": "Mercadolibre Carrito", "facturacion": 6050.0}]
    assert a["sin_sku"] == ["3"]
    assert a["fravega_estimadas"] == {"ordenes": 1, "facturacion": 60500.0}
    assert a["tc"] == {"valor": 1443.1, "origen": "BNA dólar billete venta, consultado 2026-09-28 06:00 ART"}


def test_full_y_marketplaces(ciclo):
    fm = reporte_diario(ciclo, date(2026, 9, 27))["full_y_marketplaces"]
    assert fm["full"]["ciclo"]["ordenes"] == 1 and fm["full"]["mas_facturaron"][0]["sku"] == "TONER-1"
    assert fm["fravega"]["ciclo"]["facturacion"] == 60500.0 and fm["fravega"]["ayer"]["ordenes"] == 0
    assert fm["fravega"]["comision_estimada_ordenes"] == 1
    assert fm["oncity"]["ciclo"]["rentabilidad"] == 2000.0
    assert fm["megatone"]["ciclo"]["ordenes"] == 0 and "Sin órdenes" in fm["megatone"]["nota"]


def test_avisa_si_la_corrida_no_llego_hasta_el_dia(ciclo):
    r = reporte_diario(ciclo, date(2026, 9, 28))
    assert any("llegan hasta 2026-09-27" in a for a in r["avisos"])


def test_sin_cierre_avisa_y_no_rompe(db_session):
    r = reporte_diario(db_session, date(2026, 9, 27))
    assert r["general"]["acumulado_ciclo"]["ordenes"] == 0
    assert "no corrió" in r["avisos"][0]


def test_endpoint_con_token(ciclo, monkeypatch):
    from contextlib import contextmanager

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from rentabilidad import api

    @contextmanager
    def _sesion():
        yield ciclo

    monkeypatch.setattr(api, "sesion", _sesion)
    monkeypatch.setattr(api, "reporte_diario", lambda db, fecha, top: {"dia": str(fecha), "top": top})
    monkeypatch.setenv("RENT_REPORTE_TOKEN", "secreto")
    app = FastAPI()
    app.include_router(api.router)
    c = TestClient(app)
    assert c.get("/rentabilidad/reporte/ecom/diario").status_code == 401
    r = c.get("/rentabilidad/reporte/ecom/diario?fecha=2026-09-27&top=3", headers={"X-Reporte-Token": "secreto"})
    assert r.status_code == 200 and r.json() == {"dia": "2026-09-27", "top": 3}
    assert c.get("/rentabilidad/reporte/ecom/diario?token=secreto&top=0").status_code == 422
