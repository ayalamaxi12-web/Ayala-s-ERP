"""Módulo Frávega: lectura del listado, reglas de escritura (apagada por defecto, verificación) y margen con el motor de siempre."""
from datetime import date
from decimal import Decimal

import pytest

import fravega_catalogo as fc
from rentabilidad import motor_precios as m
from rentabilidad.fravega_seller import SesionFravegaVencida
from rentabilidad.fravega_vista import margen_fravega
from rentabilidad.pricing_pm import DatosSku
from .conftest import d

COOK = {"X-SELLER-AUTH": "tok", "X-FVG-SELLER-ID": "sel", "X-SELLER-APP": "app"}
PLAN6 = {"_id": "p6", "name": "IMPORTADOS: 6 cuotas sin interés v6", "commission": 10.6, "validity": {"expiration": "2027-05-31T18:00:00.000Z"}}


def _item(i, ref, plan=PLAN6):
    return {"id": i, "sku": "123", "refId": ref, "title": "T", "active": True, "itemState": "Published", "status": {"message": "Ok"},
            "price": {"list": 303599, "sale": 303599, "net": 250908.26}, "stock": {"quantity": 50},
            "associatedPlan": {"from": "2026-10-02T13:00:00Z", "to": "2027-05-31T18:00:00Z", "plan": plan}}


class R:
    def __init__(self, status=200, data=None):
        self.status_code, self._d = status, data or {}

    def json(self):
        return self._d


def test_traer_items_pagina_y_normaliza():
    paginas = {1: {"items": [_item("a", "PLANCHA-SUB-GORRA")], "totalPages": 2}, 2: {"items": [_item("b", "SANDMAK1P ")], "totalPages": 2}}
    pedido = []

    def req(metodo, url, params, cuerpo, headers):
        pedido.append((params["page"], "authorization" in headers))
        return R(200, paginas[params["page"]])
    items = fc.traer_items(COOK, req)
    assert [i["ref_id"] for i in items] == ["PLANCHA-SUB-GORRA", "SANDMAK1P"]
    assert items[0]["plan"]["cuotas"] == "6" and items[0]["plan"]["comision"] == Decimal("10.6") and items[0]["venta"] == Decimal("303599")
    assert pedido == [(1, False), (2, False)]          # primero solo con cookies


def test_si_frávega_rechaza_con_cookies_se_reintenta_con_authorization_y_si_no_avisa_sesion_vencida():
    vistos = []

    def req(metodo, url, params, cuerpo, headers):
        vistos.append("authorization" in headers)
        return R(401)
    with pytest.raises(SesionFravegaVencida):
        fc.traer_items(COOK, req)
    assert vistos == [False, True]


def test_la_escritura_esta_apagada_por_defecto(monkeypatch):
    monkeypatch.delenv("FRAVEGA_ESCRITURA", raising=False)
    llamadas = []
    with pytest.raises(fc.EscrituraApagada):
        fc.poner_precio("a", d("100"), d("90"), d("74"), 5, True, COOK, lambda *a: llamadas.append(a) or R())
    with pytest.raises(fc.EscrituraApagada):
        fc.poner_plan("a", PLAN6, None, COOK, lambda *a: llamadas.append(a) or R())
    assert llamadas == []


def test_poner_precio_manda_lista_venta_y_neto_y_valida(monkeypatch):
    monkeypatch.setenv("FRAVEGA_ESCRITURA", "1")
    visto = {}

    def req(metodo, url, params, cuerpo, headers):
        visto.update(metodo=metodo, url=url, cuerpo=cuerpo)
        return R(200)
    fc.poner_precio("a1", d("100000"), d("90000"), d("74380.17"), 124, True, COOK, req)
    assert visto["metodo"] == "PUT" and visto["url"].endswith("/v1/item/a1/partial")
    assert visto["cuerpo"] == {"price": {"list": 100000.0, "sale": 90000.0, "net": 74380.17}, "stock": {"quantity": 124}, "active": True}   # como lo manda el portal (capturado en vivo)
    with pytest.raises(ValueError):
        fc.poner_precio("a1", d("100"), d("200"), d("1"), 5, True, COOK, req)           # venta > lista
    with pytest.raises(fc.FravegaRechazo) as e:
        fc.poner_precio("a1", d("100"), d("90"), d("1"), 5, True, COOK, lambda *a: R(409, {"error": {"fields": {"price": "x"}}}))
    assert e.value.campos == {"price": "x"}


def test_poner_plan_manda_el_plan_completo_con_su_vigencia(monkeypatch):
    monkeypatch.setenv("FRAVEGA_ESCRITURA", "1")
    visto = {}
    fc.poner_plan("a1", PLAN6, None, COOK, lambda m_, u, p, c, h: visto.update(u=u, c=c) or R(200))
    assert visto["u"].endswith("/v1/item/a1/plan") and visto["c"]["plan"]["_id"] == "p6" and visto["c"]["to"] == "2027-05-31T18:00:00.000Z"


def test_planes_en_uso_sin_repetidos_ordenados_por_cuotas():
    p12 = {"_id": "p12", "name": "IMPORTADOS: 12 cuotas sin interés"}
    items = [fc.normalizar_item(_item("a", "A", p12)), fc.normalizar_item(_item("b", "B")), fc.normalizar_item(_item("c", "C"))]
    assert [p["_id"] for p in fc.planes_en_uso(items)] == ["p6", "p12"]


def test_margen_usa_el_motor_de_frávega_y_el_plan(db_session):
    par = m.cargar_parametros(db_session, date(2026, 10, 29))
    datos = DatosSku(d("10"), d("1.21"), None, None, None)
    r6, _ = margen_fravega(d("60000"), datos, d("1500"), par, "6", None)
    e = m.EntradaMotor(canal="FRAVEGA", costo=d("15000"), iva_factor=d("1.21"), plan="6")
    assert r6["margen"] == pytest.approx(float(m.precio_a_margen(d("60000"), e, par).margen) * 100, abs=0.01)
    r12, _ = margen_fravega(d("60000"), datos, d("1500"), par, "12", None)
    assert r12["margen"] < r6["margen"]                                         # más cuotas, más comisión
    assert margen_fravega(d("60000"), datos, d("1500"), par, "7", None)[0] is None                 # un plan que no existe no se inventa
    assert margen_fravega(d("60000"), DatosSku(None, None, None, None, None), d("1500"), par, "6", None)[1] == ["Sin costo vigente en Ecom"]


def test_el_iva_de_los_cargos_de_fravega_en_el_motor_es_0_desde_el_29_10(db_session):
    assert m.cargar_parametros(db_session, date(2026, 10, 28)).valor("FRAVEGA", "iva_cargos") == d("0.21")
    assert m.cargar_parametros(db_session, date(2026, 10, 29)).valor("FRAVEGA", "iva_cargos") == 0
    assert m.cargar_parametros(db_session, date(2026, 10, 29)).valor("WEB", "iva_cargos") == d("0.21")   # los demás canales no se tocan


def test_el_error_de_sesion_dice_que_status_devolvio_frávega():
    with pytest.raises(SesionFravegaVencida) as e:
        fc.traer_items(COOK, lambda *a: R(401))
    assert "sin authorization: 401" in str(e.value) and "con authorization: 401" in str(e.value)


def test_stock_general_y_ventas_solo_de_fravega(db_session):
    from rentabilidad import config
    from rentabilidad.fravega_vista import stock_general_por_sku, ventas_por_sku
    from rentabilidad.models import VentaEcom
    from rentabilidad.tests.test_fravega import _fila_fravega, _guardar
    filas = [["SKU", "Stock"], ["PLANCHA-SUB-GORRA", "1.250"], ["OTRO", "-"], ["SANDMAK1P", "7"]]
    assert stock_general_por_sku(lambda sid, tab: filas) == {"PLANCHA-SUB-GORRA": 1250, "SANDMAK1P": 7}
    hoy = date(2026, 10, 29)
    _guardar(db_session, _fila_fravega(numero_orden="1", orden_externa="FVG-a", skus_vendidos="PLANCHA-SUB-GORRA", fecha_creacion=date(2026, 10, 20)), periodo="2026-10-20_2026-10-20")
    _guardar(db_session, _fila_fravega(numero_orden="2", orden_externa=None, canal_de_venta="OnCity", origen_comision="ESTIMADO_ONCITY",
                                       skus_vendidos="PLANCHA-SUB-GORRA", fecha_creacion=date(2026, 10, 21)), periodo="2026-10-21_2026-10-21")
    v = ventas_por_sku(db_session, hoy)["PLANCHA-SUB-GORRA"]
    assert v["ordenes_30"] == 1 and v["dias_con_venta_60"] == 1               # la de OnCity no cuenta


def test_si_frávega_falla_con_un_tamano_de_pagina_se_reintenta_con_el_del_portal():
    tamanos = []

    def req(metodo, url, params, cuerpo, headers):
        tamanos.append(params["size"])
        return R(500) if params["size"] > 10 else R(200, {"items": [_item("a", "A")], "totalPages": 1})
    assert [i["ref_id"] for i in fc.traer_items(COOK, req)] == ["A"] and tamanos == [25, 10]


def test_un_status_inesperado_dice_cual_fue_y_que_contestó_frávega():
    class R404(R):
        text = "no existe la ruta"
    with pytest.raises(RuntimeError) as e:
        fc.traer_items(COOK, lambda *a: R404(404))
    assert "404" in str(e.value) and "no existe la ruta" in str(e.value)


def test_el_endpoint_devuelve_el_motivo_en_vez_de_un_500_sin_cors(monkeypatch):
    from fastapi.testclient import TestClient
    import fravega_api
    import main
    monkeypatch.setattr(fravega_api, "_CACHE", {"t": 0.0, "items": []})
    monkeypatch.setattr(fc, "traer_items", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Frávega respondió 404")))
    r = TestClient(main.app, raise_server_exceptions=False).get("/fravega/catalogo")
    assert r.status_code == 502 and "404" in r.json()["detail"]


def test_un_rechazo_de_escritura_trae_la_respuesta_de_frávega_y_lo_que_se_envio(monkeypatch):
    monkeypatch.setenv("FRAVEGA_ESCRITURA", "1")

    class R500(R):
        text = "internal error en la base"

        def json(self):
            raise ValueError
    with pytest.raises(fc.FravegaRechazo) as e:
        fc.poner_precio("a1", d("100"), d("90"), d("74"), 5, True, COOK, lambda *a: R500(500))
    assert "500" in str(e.value) and "internal error en la base" in str(e.value) and '"sale": 90.0' in str(e.value)


def test_si_frávega_responde_500_pero_aplico_el_precio_se_informa_como_aplicado(monkeypatch):
    from fastapi.testclient import TestClient
    import fravega_api
    import main
    monkeypatch.setenv("FRAVEGA_ESCRITURA", "1")
    antes = fc.normalizar_item({**_item("a1", "PLANCHA-SUB-GORRA"), "price": {"list": 100, "sale": 90, "net": 81.4}})
    ahora = {**antes, "lista": d("100"), "venta": d("89")}
    monkeypatch.setattr(fravega_api, "_CACHE", {"t": 9e12, "items": [antes]})
    monkeypatch.setattr(fravega_api, "_items", lambda forzar=False: [antes])
    def explota(*a, **k):
        raise fc.FravegaRechazo("Frávega rechazó el cambio (500): sin detalle")
    monkeypatch.setattr(fc, "poner_precio", explota)
    monkeypatch.setattr(main, "_registrar_historial_oferta_lote", lambda filas: None)
    cuerpo = {"id": "a1", "ref_id": "PLANCHA-SUB-GORRA", "lista": 100, "venta": 89, "operador": "Maxi A."}
    monkeypatch.setattr(fc, "releer_item", lambda *a, **k: ahora)
    r = TestClient(main.app, raise_server_exceptions=False).post("/fravega/precio", json=cuerpo)
    assert r.status_code == 200 and r.json()["verificado"] and "quedó aplicado" in r.json()["aviso"]
    monkeypatch.setattr(fc, "releer_item", lambda *a, **k: antes)               # no se aplicó: error con lo que se releyó
    r = TestClient(main.app, raise_server_exceptions=False).post("/fravega/precio", json=cuerpo)
    assert r.status_code == 422 and "NO quedó aplicado" in r.json()["detail"]


def test_si_frávega_acepta_pero_todavia_muestra_el_precio_anterior_queda_pendiente_sin_error(monkeypatch):
    from fastapi.testclient import TestClient
    import fravega_api
    import main
    monkeypatch.setenv("FRAVEGA_ESCRITURA", "1")
    antes = fc.normalizar_item({**_item("a1", "SAFEBOX-KEYS"), "price": {"list": 100, "sale": 90, "net": 81.4}})
    monkeypatch.setattr(fravega_api, "_items", lambda forzar=False: [antes])
    monkeypatch.setattr(fravega_api.time, "sleep", lambda s: None)
    monkeypatch.setattr(fc, "poner_precio", lambda *a, **k: None)                    # Frávega responde 200
    monkeypatch.setattr(fc, "releer_item", lambda *a, **k: antes)                    # pero sigue mostrando el precio viejo
    monkeypatch.setattr(main, "_registrar_historial_oferta_lote", lambda filas: None)
    r = TestClient(main.app, raise_server_exceptions=False).post("/fravega/precio", json={"id": "a1", "ref_id": "SAFEBOX-KEYS", "lista": 100, "venta": 89, "operador": "Maxi A."})
    assert r.status_code == 200 and r.json()["pendiente"] and not r.json()["verificado"] and "demorar" in r.json()["aviso"]


def test_sin_plan_es_venta_simple_solo_comision_base_y_da_mas_margen_que_con_cuotas(db_session):
    par = m.cargar_parametros(db_session, date(2026, 10, 29))
    datos = DatosSku(d("10"), d("1.105"), None, None, None)
    simple, av = margen_fravega(d("60000"), datos, d("1500"), par, None, None)
    assert simple is not None and "Sin cuotas" in av[0] and simple["cargos"].get("financiera", 0) == 0
    c3, _ = margen_fravega(d("60000"), datos, d("1500"), par, "3", None)
    assert simple["margen"] > c3["margen"]
    assert margen_fravega(d("60000"), datos, d("1500"), par, "contado", None)[0]["margen"] == simple["margen"]
