"""Motor de precios, etapa 2: lectura de las planillas de PM, carga en
`pricing_sku` con vigencia y vista de todos los SKU con filtros. Las
planillas de prueba replican la estructura real de las 4 planillas
(relevadas 2026-09-29), con pocas filas."""
from contextlib import contextmanager
from datetime import date, datetime

import openpyxl
import pytest

from rentabilidad import api, pricing_pm as pp
from rentabilidad.models import LiquidacionFravega, PricingSku, VentaEcom

from .conftest import d
from .test_fravega import db_multihilo  # noqa: F401 (fixture)

HOY = date(2026, 9, 29)
TC = d("1540")


def _veronica():
    """Estructura Verónica / Cristian: "Forma De Pago" web, "%" para ML,
    "Fravega" precio + "Fravega" casilla, "On City" casilla."""
    return [
        ["SKU", "Desc", "WEB NUEVO", "Forma De Pago", "%", "Precio Con Envio Prod. +$33000 ML",
         "Fravega", "Fravega", "On City", "PM", "Fecha de Cambio de Precio"],
        ["INKCARTHP951XLY", "x", 3699.0, "3· Cuotas", 1.081081, 3999, 3999, False, False, "Veronica", datetime(2026, 2, 13)],
        ["EPGMR137GREEN ", "x", 16399.0, "3· Cuotas", 1.13, 18539, 19679.0, True, True, "Veronica", datetime(2026, 6, 5)],
        ["SIN-WEB", "x", None, "Simple", "-", None, None, False, False, "Veronica", None],
        ["EPGMR137GREEN", "dup", 1, "Simple", 1, 1, 1, False, False, "Veronica", None],
        [None, None, None],
    ]


def _laura():
    """Laura: forma de pago web en "3 Cuotas", "% ML" y la condición ML en
    la "Forma De Pago" que le sigue."""
    return [
        ["SKU", "WEB NUEVO", "3 Cuotas", "Forma De Pago", "% ML", "Forma De Pago", "Fravega", "Fravega", "On City", "PM"],
        ["TESTER 21", 69159.0, "3 Cuotas", "Simple", 1.2, "Simple", 82999, True, False, "Laura"],
        ["PV-OCT26-MONI", 69159.0, "Simple", "30", 1.4, "6 Cuotas", 96829, True, False, "Laura"],
    ]


def _matias():
    """Matías: fila de títulos de grupo arriba, sin precio Frávega propio
    (solo la casilla) → toma el precio ML."""
    return [
        ["SKU", "GRUPO", "", "", "", ""],
        ["SKU", "WEB NUEVO", "Forma De Pago", "%", "Fravega", "On City"],
        ["JS10000-SC", 56999.0, "3· Cuotas", 1.2000000000000002, True, False],
    ]


# ── Lectura ──

def test_lee_estructura_veronica():
    lec = pp.leer_planilla_pm(_veronica())
    a, b, c = lec.filas
    assert (a.sku, a.precio_web, a.forma_pago_web, a.pct_ml) == ("INKCARTHP951XLY", d("3699"), "3", d("1.081081"))
    assert a.precio_fravega is None and a.precio_oncity is None  # casillas sin tildar
    assert a.fecha_cambio == date(2026, 2, 13) and a.condicion_ml == "contado"
    assert b.sku == "EPGMR137GREEN" and b.precio_fravega == d("19679") and b.precio_oncity == d("19679")
    assert c.precio_web is None and c.pct_ml is None and c.forma_pago_web == "1"
    assert lec.duplicados == ["EPGMR137GREEN"] and lec.sin_precio_web == ["SIN-WEB"]


def test_lee_estructura_laura_y_saltea_testers():
    (f,) = pp.leer_planilla_pm(_laura()).filas
    assert f.sku == "PV-OCT26-MONI"
    assert f.forma_pago_web == "1"  # columna "3 Cuotas" = forma de pago web
    assert f.pct_ml == d("1.4") and f.condicion_ml == "6"
    assert f.precio_fravega == d("96829")


def test_lee_estructura_matias_frav_toma_precio_ml():
    (f,) = pp.leer_planilla_pm(_matias()).filas
    assert f.pct_ml == d("1.2")  # el float de Excel se limpia
    assert f.precio_fravega == d("68399")  # ROUNDDOWN(56999 × 1,2; -1) + 9
    assert pp.precio_ml(f.precio_web, f.pct_ml) == d("68399")


def test_sku_numerico_de_excel_no_queda_con_punto_cero():
    assert pp.norm_sku(1020000172.0) == "1020000172"
    assert pp.norm_sku(" tn670comp\u200b") == "TN670COMP"


def test_texto_de_sheets_se_entiende():
    assert pp._num("$ 3.699,50") == d("3699.5")
    assert pp._num("108,1081%") == d("1.081081")
    assert pp._num("#N/A") is None and pp._num("-") is None


def test_planilla_sin_titulos_es_invalida():
    with pytest.raises(pp.PlanillaPmInvalida):
        pp.leer_planilla_pm([["Producto", "Precio"], ["x", 1]])


# ── Carga ──

def test_carga_nueva_luego_sin_cambios_luego_cambio(db_session):
    r = pp.cargar_precios_pm(db_session, pp.leer_planilla_pm(_veronica()), "maxi", HOY)
    assert (r.leidos, r.nuevos, r.cambiados, r.sin_cambios) == (3, 3, 0, 0)
    ink = pp.vigentes(db_session)["INKCARTHP951XLY"]
    assert ink.vigente_desde == date(2026, 2, 13) and ink.cargado_por == "maxi"

    r = pp.cargar_precios_pm(db_session, pp.leer_planilla_pm(_veronica()), "maxi", HOY)
    assert (r.nuevos, r.cambiados, r.sin_cambios) == (0, 0, 3)
    assert db_session.query(PricingSku).count() == 3

    filas = _veronica()
    filas[1][2] = 3999.0  # nuevo precio web, misma fecha de cambio vieja
    r = pp.cargar_precios_pm(db_session, pp.leer_planilla_pm(filas), "maxi", HOY)
    assert (r.nuevos, r.cambiados, r.sin_cambios) == (0, 1, 2)
    nuevo = pp.vigentes(db_session)["INKCARTHP951XLY"]
    assert nuevo.precio_web == d("3999") and nuevo.vigente_desde == HOY
    assert pp.vigentes(db_session, date(2026, 9, 1))["INKCARTHP951XLY"].precio_web == d("3699")
    assert len(pp.historial(db_session, "inkcarthp951xly")) == 2


# ── Vista ──

_DATOS = {
    "INKCARTHP951XLY": pp.DatosSku(d("0.95"), d("1.21"), "Veronica", "Insumo De Impresion", "Tinta"),
    "EPGMR137GREEN": pp.DatosSku(d("5.96"), d("1.21"), "Cristian", "Perifericos", "Gamer"),
    "SIN-WEB": pp.DatosSku(None, None, "Veronica", None, None),
}


def _datos(sku):
    return _DATOS[pp.norm_sku(sku)]


def _vista(db, **filtros):
    return pp.vista_pricing(db, _datos, TC, HOY, pp.FiltrosVista(**filtros), periodo_real="P")


def test_vista_calcula_cada_canal_con_el_motor(db_session):
    pp.cargar_precios_pm(db_session, pp.leer_planilla_pm(_veronica()), "maxi", HOY)
    filas = {f["sku"]: f for f in _vista(db_session)}
    g = filas["EPGMR137GREEN"]
    assert set(g["canales"]) == {"WEB", "ML", "FRAVEGA", "ONCITY"}
    assert g["canales"]["ML"]["precio"] == d("18539")
    par = pp.motor.cargar_parametros(db_session, HOY)
    esperado = pp.motor.precio_a_margen(d("18539"), pp.motor.EntradaMotor(
        canal="ML", costo=d("5.96") * TC, iva_factor=d("1.21"), categoria="Perifericos", plan="contado"), par)
    assert g["canales"]["ML"]["margen"] == esperado.margen
    assert g["canales"]["FRAVEGA"]["avisos"] == [pp._AVISO_FEE["promedio"]]
    assert g["canales"]["ONCITY"]["margen"] is not None
    assert filas["SIN-WEB"]["canales"] == {}
    assert filas["INKCARTHP951XLY"]["pm"] == "Veronica"


def test_ml_desde_33000_avisa_que_falta_el_envio(db_session):
    filas = [["SKU", "WEB NUEVO", "Forma De Pago", "%"], ["EPGMR137GREEN", 40000, "Simple", 1]]
    pp.cargar_precios_pm(db_session, pp.leer_planilla_pm(filas), "maxi", HOY)
    (fila,) = _vista(db_session)
    assert fila["canales"]["ML"]["avisos"] == ["Sin envío: falta el costo real de envío de la publicación"]


def test_sin_costo_no_calcula_y_lo_dice(db_session):
    _DATOS["X-SIN-COSTO"] = pp.DatosSku(None, d("1.21"), "Laura", None, None)
    pp.cargar_precios_pm(db_session, pp.leer_planilla_pm([["SKU", "WEB NUEVO"], ["X-SIN-COSTO", 1000]]), "maxi", HOY)
    (fila,) = _vista(db_session)
    assert fila["canales"]["WEB"]["margen"] is None
    assert fila["canales"]["WEB"]["avisos"] == ["Sin costo vigente en Táctica"]


def test_filtros(db_session):
    pp.cargar_precios_pm(db_session, pp.leer_planilla_pm(_veronica()), "maxi", HOY)
    assert [f["sku"] for f in _vista(db_session, pm="cristian")] == ["EPGMR137GREEN"]
    assert [f["sku"] for f in _vista(db_session, categoria="insumo de impresion")] == ["INKCARTHP951XLY"]
    assert [f["sku"] for f in _vista(db_session, canal="FRAVEGA")] == ["EPGMR137GREEN"]
    assert [f["sku"] for f in _vista(db_session, buscar="951")] == ["INKCARTHP951XLY"]
    negativos = _vista(db_session, solo_negativos=True)
    assert all(any(c["margen"] is not None and c["margen"] < 0 for c in f["canales"].values()) for f in negativos)
    assert _vista(db_session, margen_max=d("-5")) == []
    # SIN-WEB no trae fecha de cambio: rige desde la carga (hoy)
    assert [f["sku"] for f in _vista(db_session, cambiado_desde=date(2026, 6, 1))] == ["EPGMR137GREEN", "SIN-WEB"]


def test_margen_real_solo_ordenes_de_un_sku_por_canal(db_session):
    def venta(n, skus, canal, rent, sin_iva):
        db_session.add(VentaEcom(
            periodo="P", numero_orden=n, skus_vendidos=skus, canal_de_venta=canal, rentabilidad=d(rent),
            precio_sin_iva=d(sin_iva), precio_final=d(sin_iva) * d("1.21"), fecha_creacion_venta=HOY, excluido=False,
            costo_sin_iva=d(1), comision_venta=d(0), costo_envio=d(0), tc=TC,
        ))
    venta("1", "EPGMR137GREEN", "Mercadolibre", "1000", "10000")
    venta("2", "EPGMR137GREEN", "Mercadolibre Carrito", "500", "10000")
    venta("3", "EPGMR137GREEN, INKCARTHP951XLY", "Mercadolibre", "9999", "1")  # kit: afuera
    venta("4", "EPGMR137GREEN", "Woocommerce", "-100", "1000")
    db_session.flush()
    real = pp.margen_real(db_session, "P")
    assert real[("EPGMR137GREEN", "ML")] == {"margen": d("0.0750"), "ordenes": 2}
    assert real[("EPGMR137GREEN", "WEB")]["margen"] == d("-0.1000")


# ── Endpoints ──

@pytest.fixture()
def cliente(db_multihilo, monkeypatch):  # noqa: F811
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    @contextmanager
    def _sesion():
        yield db_multihilo
        db_multihilo.flush()

    monkeypatch.setattr(api, "sesion", _sesion)
    monkeypatch.setattr(api, "_datos_sku_fn", lambda avisos: _datos)
    monkeypatch.setattr(api, "_resolver_tc", lambda tc: TC)
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def _xlsx(path, filas):
    wb = openpyxl.Workbook()
    wb.active.title = "Portada"
    ws = wb.create_sheet("Veronica")
    for f in filas:
        ws.append(f)
    wb.save(path)


def test_endpoints_carga_vista_y_ficha(cliente, tmp_path):
    path = tmp_path / "VENTAS POR CANALES VERONICA.xlsx"
    _xlsx(path, _veronica())
    with open(path, "rb") as f:
        r = cliente.post("/rentabilidad/pricing/carga-pm", files={"archivo": (path.name, f)}, data={"cargado_por": "maxi"})
    assert r.status_code == 200, r.text
    assert r.json()["nuevos"] == 3 and r.json()["duplicados"] == ["EPGMR137GREEN"]

    r = cliente.get("/rentabilidad/pricing/skus", params={"pm": "Cristian"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1 and body["filas"][0]["sku"] == "EPGMR137GREEN"

    r = cliente.get("/rentabilidad/pricing/skus/epgmr137green")
    assert r.status_code == 200, r.text
    ficha = r.json()
    assert "cargos" in ficha["canales"]["WEB"] and ficha["historial"][0]["cargado_por"] == "maxi"
    assert cliente.get("/rentabilidad/pricing/skus/NO-EXISTE").status_code == 404
    assert cliente.get("/rentabilidad/pricing/skus", params={"canal": "TACTICA"}).status_code == 422


def test_endpoint_carga_rechaza_archivo_sin_titulos(cliente, tmp_path):
    path = tmp_path / "otra.xlsx"
    _xlsx(path, [["Producto"], ["x"]])
    with open(path, "rb") as f:
        r = cliente.post("/rentabilidad/pricing/carga-pm", files={"archivo": (path.name, f)}, data={"cargado_por": "maxi"})
    assert r.status_code == 422


def test_fravega_usa_el_fee_historico_del_sku_de_las_liquidaciones(db_session):
    pp.cargar_precios_pm(db_session, pp.leer_planilla_pm(_veronica()), "maxi", HOY)
    for orden, skus in (("v1frvg-01", "EPGMR137GREEN"), ("v2frvg-01", "EPGMR137GREEN"), ("v3frvg-01", "EPGMR137GREEN, X")):
        db_session.add(VentaEcom(
            periodo="P", numero_orden=orden, skus_vendidos=skus, canal_de_venta="Fravega", orden_externa=orden,
            precio_sin_iva=d(1), precio_final=d(1), costo_sin_iva=d(1), comision_venta=d(0), costo_envio=d(0), tc=TC,
        ))
    for orden, fee in (("v1frvg-01", "1016"), ("v2frvg-01", "2755"), ("v3frvg-01", "9999")):
        db_session.add(LiquidacionFravega(orden=orden, valor_sku=d(1), comision=d(0), fee_logistico=d(fee),
                                          liquidacion_desde=date(2026, 6, 1), liquidacion_hasta=date(2026, 6, 15)))
    db_session.flush()
    assert pp.fee_historico_fravega(db_session) == {"EPGMR137GREEN": d("1885.50")}
    g = next(f for f in _vista(db_session) if f["sku"] == "EPGMR137GREEN")["canales"]["FRAVEGA"]
    assert g["avisos"] == [pp._AVISO_FEE["historico"]]
    par = pp.motor.cargar_parametros(db_session, HOY)
    esperado = pp.motor.precio_a_margen(d("19679"), pp.motor.EntradaMotor(
        canal="FRAVEGA", costo=d("5.96") * TC, iva_factor=d("1.21"), fee_logistico=d("1885.50")), par)
    assert g["margen"] == esperado.margen


def test_seed_agrega_parametros_nuevos_sin_tocar_los_cargados(db_session):
    from rentabilidad import seed
    from rentabilidad.models import PricingParametro

    fila = db_session.query(PricingParametro).filter_by(canal="ONCITY", clave="fee_logistico_default").one()
    db_session.delete(fila)
    iibb = db_session.query(PricingParametro).filter_by(canal="*", clave="iibb").one()
    iibb.valor = d("0.065")
    db_session.flush()
    seed.seed_pricing(db_session)
    db_session.flush()
    assert db_session.query(PricingParametro).filter_by(canal="ONCITY", clave="fee_logistico_default").count() == 1
    assert db_session.query(PricingParametro).filter_by(canal="*", clave="iibb").one().valor == d("0.065")
