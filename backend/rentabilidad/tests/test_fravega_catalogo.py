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
        fc.poner_precio("a", d("100"), d("90"), d("74"), COOK, lambda *a: llamadas.append(a) or R())
    with pytest.raises(fc.EscrituraApagada):
        fc.poner_plan("a", PLAN6, None, COOK, lambda *a: llamadas.append(a) or R())
    assert llamadas == []


def test_poner_precio_manda_lista_venta_y_neto_y_valida(monkeypatch):
    monkeypatch.setenv("FRAVEGA_ESCRITURA", "1")
    visto = {}

    def req(metodo, url, params, cuerpo, headers):
        visto.update(metodo=metodo, url=url, cuerpo=cuerpo)
        return R(200)
    fc.poner_precio("a1", d("100000"), d("90000"), d("74380.17"), COOK, req)
    assert visto["metodo"] == "PUT" and visto["url"].endswith("/v1/item/a1/partial")
    assert visto["cuerpo"] == {"price": {"list": 100000.0, "sale": 90000.0, "net": 74380.17}}
    with pytest.raises(ValueError):
        fc.poner_precio("a1", d("100"), d("200"), d("1"), COOK, req)           # venta > lista
    with pytest.raises(fc.FravegaRechazo) as e:
        fc.poner_precio("a1", d("100"), d("90"), d("1"), COOK, lambda *a: R(409, {"error": {"fields": {"price": "x"}}}))
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
    assert margen_fravega(d("60000"), datos, d("1500"), par, None, None)[0] is None
    assert margen_fravega(d("60000"), DatosSku(None, None, None, None, None), d("1500"), par, "6", None)[1] == ["Sin costo vigente en Ecom"]
