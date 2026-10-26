"""Simulador de reposición: demanda de Full + mi depósito. Caso guía: W1105ACOMP, muy vendido, con la publicación SIN Full (se vende desde mi depósito)."""
from datetime import date

import pytest

import ml_reposicion as rep
from ml_full import FactorPack, MLFullClient

HOY = date(2026, 10, 25)


def _item(i, sku, inv=None, lt="fulfillment"):
    return {"id": i, "title": f"Pub {i}", "shipping": {"logistic_type": lt}, "seller_custom_field": sku, "inventory_id": inv, "variations": []}


class FakeML(MLFullClient):
    def __init__(self, items, stock, full, pagado, dias_fallidos=()):
        super().__init__(get_fn=lambda *a, **k: {}, token_fn=lambda c: "t")
        self._items, self._stock, self._full, self._pagado, self._df = items, stock, full, pagado, list(dias_fallidos)
    def items_activos(self, c): return [i["id"] for i in self._items.get(c, [])]
    def detalle_items(self, ids, c): return [i for i in self._items.get(c, []) if i["id"] in ids]
    def stock_fulfillment(self, inv, c): return {"available_quantity": self._stock.get(inv, 0)}
    def ventas_full_por_inventory(self, c, ids, d, h): return {k: v for k, v in self._full.get(c, {}).items() if k in ids}
    def envios_pendientes_por_inventory(self, c, ids, d, h): return {}
    def ventas_pagadas_por_item(self, c, d, h): return dict(self._pagado.get(c, {})), list(self._df)


class FakeEcom:
    def __init__(self, links, pitec, negativo=()):
        self.links, self.pitec, self.negativo = links, pitec, set(negativo)
    def factor_pack(self, item_id):
        sku = self.links.get(item_id)
        return FactorPack(item_sku={sku[0]: sku[1]}) if sku else None
    def stock_full_por_sku(self, sku, parent=None): return 0
    def stock_disponible_por_sku(self, sku, parent=None): return -3 if sku in self.negativo else self.pitec.get(sku)


class FakeTactica:
    def __init__(self, d): self.d = d
    def stock_por_sku(self, sku): return self.d.get(sku)


def armar(**kw):
    items = {"IT": [_item("MLA1", "SKUFULL", "INV1"), _item("MLA2", "W1105ACOMP", None, lt="default"), _item("MLA3", "NOLINK", None, lt="default")], "MT": []}
    ml = FakeML(items, {"INV1": 20}, {"IT": {"INV1": {"unidades": 30, "primera": "2026-10-01", "ultima": "2026-10-24"}}},
                {"IT": {("MLA1", None): 50, ("MLA2", None): 90, ("MLA3", None): 12}}, kw.get("dias_fallidos", ()))
    ecom = FakeEcom({"MLA1": ("SKUFULL", 1), "MLA2": ("W1105ACOMP", 1)}, {"SKUFULL": 100, "W1105ACOMP": 40}, kw.get("negativo", ()))
    return ml, ecom, FakeTactica({"SKUFULL": 10, "W1105ACOMP": 15})


def correr(contar, **kw):
    ml, ecom, tac = armar(**kw)
    return rep.calcular_reposicion_mla(ml, ecom, tac, cuentas=["IT", "MT"], hoy=HOY, fecha_llegada=HOY, contar_deposito=contar)


def test_apagado_es_identico_al_de_hoy():
    r = correr(False)
    assert [f.item_id for f in r.filas] == ["MLA1"]                      # solo la publicación con inventario en Full
    f = r.filas[0]
    assert (f.ventas_periodo, f.ventas_full, f.ventas_deposito, f.ventas_diarias) == (30, 30, 0, 1.0)


def test_w1105acomp_aparece_con_sus_ventas_y_su_sugerido():
    r = correr(True)
    por = {f.item_id: f for f in r.filas}
    w = por["MLA2"]
    # no tuvo ventas en Full ni stock en Full: vende 90 desde mi depósito (referencia) y se manda UNA PARTE (30 %), no todo
    assert (w.sku, w.ventas_full, w.ventas_deposito, w.deposito_usado, w.ventas_periodo) == ("W1105ACOMP", 0, 90, 27, 27) and "no_full" in w.flags
    assert (w.stock_full, w.stock_a_llegada, w.ventas_diarias) == (0, 0.0, 0.9)
    assert w.stock_objetivo == 18.9 and w.cantidad_enviar == 19 and w.sugerido == 19        # 0,9/día × 21 días
    assert w.stock_ecom == 40 and w.stock_tactica == 15


def test_no_cuenta_dos_veces_lo_de_full():
    por = {f.item_id: f for f in correr(True).filas}
    f = por["MLA1"]
    # pagado 50 en total, 30 salieron de Full: mi depósito es 20 (no 50). Ya opera en Full: la demanda es SOLO la de Full; lo de mi depósito queda como dato
    assert (f.ventas_full, f.ventas_deposito, f.deposito_usado, f.ventas_periodo) == (30, 20, 0, 30)


def test_publicacion_sin_vincular_y_sin_sku_se_ven_como_fila_con_su_motivo():
    por = {f.item_id: f for f in correr(True).filas}
    n = por["MLA3"]
    assert n.sku == "NOLINK" and "sin_vincular" in n.flags and "sin_ecom" in n.flags and n.sugerido == 0


def test_reparto_del_mismo_sku_a_la_que_mas_vende():
    ml, ecom, tac = armar()
    ml._items["IT"].append(_item("MLA4", "W1105ACOMP", None, lt="default"))
    ml._pagado["IT"][("MLA4", None)] = 10
    ecom.links["MLA4"] = ("W1105ACOMP", 1)
    r = rep.calcular_reposicion_mla(ml, ecom, tac, cuentas=["IT", "MT"], hoy=HOY, fecha_llegada=HOY, contar_deposito=True)
    por = {f.item_id: f for f in r.filas}
    assert por["MLA2"].sugerido == 19 and por["MLA4"].sugerido == 2     # el disponible (55) alcanza para las dos: cada una lo suyo


def test_stock_negativo_de_ecom_es_0_con_aviso_y_tactica_sin_dato_se_marca():
    ml, ecom, tac = armar(negativo=["W1105ACOMP"])
    tac.d.pop("W1105ACOMP")
    r = rep.calcular_reposicion_mla(ml, ecom, tac, cuentas=["IT", "MT"], hoy=HOY, fecha_llegada=HOY, contar_deposito=True)
    w = {f.item_id: f for f in r.filas}["MLA2"]
    assert w.stock_ecom == 0 and w.stock_tactica is None and {"ecom_negativo", "sin_tactica"} <= set(w.flags)
    assert any("negativo" in a for a in w.avisos) and any("Táctica" in a for a in w.avisos) and w.sugerido == 0


def test_dias_de_ordenes_sin_leer_se_informan():
    r = correr(True, dias_fallidos=["2026-10-03"])
    assert r.ordenes_dias_sin_leer == ["IT 2026-10-03", "MT 2026-10-03"]
    assert all(any("incompletas" in a for a in f.avisos) for f in r.filas)


def test_encendido_sin_ventas_de_deposito_da_lo_mismo_que_apagado():
    ml, ecom, tac = armar()
    ml._pagado = {"IT": {("MLA1", None): 30}}                          # todo lo pagado salió de Full
    on = rep.calcular_reposicion_mla(ml, ecom, tac, cuentas=["IT", "MT"], hoy=HOY, fecha_llegada=HOY, contar_deposito=True)
    ml2, ecom2, tac2 = armar()
    off = rep.calcular_reposicion_mla(ml2, ecom2, tac2, cuentas=["IT", "MT"], hoy=HOY, fecha_llegada=HOY, contar_deposito=False)
    campos = ("item_id", "ventas_periodo", "ventas_diarias", "stock_objetivo", "stock_a_llegada", "cantidad_enviar", "sugerido")
    assert [[getattr(f, c) for c in campos] for f in on.filas] == [[getattr(f, c) for c in campos] for f in off.filas]


def test_lectura_de_ordenes_dia_por_dia_pagina_y_reporta_dias_fallidos():
    from ml_full import MLCuotaAgotada
    llamadas = []

    def get(url, params, headers):
        llamadas.append((params["order.date_created.from"][:10], params["offset"]))
        if params["order.date_created.from"].startswith("2026-10-02"):
            raise MLCuotaAgotada(429)
        orden = {"order_items": [{"item": {"id": "MLA9", "variation_id": None}, "quantity": 2}]}
        return {"results": [orden] * (50 if params["offset"] == 0 else 10), "paging": {"total": 60}}

    ml = MLFullClient(get_fn=get, token_fn=lambda c: "t")
    acum, fallidos = ml.ventas_pagadas_por_item("IT", "2026-10-01", "2026-10-03")
    assert acum == {("MLA9", None): 2 * 60 * 2} and fallidos == ["2026-10-02"]      # dos días leídos (60 órdenes × 2 u.), uno fallido
    assert ("2026-10-01", 50) in llamadas                                             # segunda página


def test_el_resultado_trae_el_rango_exacto_leido():
    r = correr(True)
    assert r.periodo == {"desde": "2026-09-25", "hasta": "2026-10-25", "dias": 30}


def test_detalle_de_operaciones_crudas_para_verificar_a_mano():
    from ml_full import detalle_operaciones
    ops = {"SALE_CONFIRMATION": [{"inventory_id": "I1", "date_created": "2026-10-03T10:00:00Z", "detail": {"available_quantity": -2}},
                                 {"inventory_id": "I1", "date_created": "2026-10-01T10:00:00Z", "detail": {"available_quantity": -3}}],
           "INBOUND_RECEPTION": [{"inventory_id": "I1", "date_created": "2026-10-05T10:00:00Z", "detail": {"available_quantity": 8},
                                  "result": {"total": 10, "available_quantity": 8, "not_available_quantity": 2}, "external_references": [{"type": "inbound_id", "value": "71384203"}]}]}

    def get(url, params, headers):
        assert params["date_from"] == "2026-09-25" and params["date_to"] == "2026-10-25"
        return {"results": [dict(o) for o in ops[params["type"]]], "paging": {}}
    d = detalle_operaciones(MLFullClient(get_fn=get, token_fn=lambda c: "t"), "IT", "I1", "2026-09-25", "2026-10-25")
    assert d["total_ventas"] == 5 and [v["fecha"][:10] for v in d["ventas"]] == ["2026-10-01", "2026-10-03"]
    e = d["envios"][0]
    assert (e["inbound_id"], e["total"], e["disponible"], e["no_disponible"]) == ("71384203", 10, 8, 2) and e["resultado_crudo"]["total"] == 10 and e["referencias"][0]["value"] == "71384203"


def test_con_stock_o_ventas_en_full_nunca_se_suma_el_deposito_y_el_quiebre_corrige_la_venta_diaria():
    ml, ecom, tac = armar()
    # quebró: 0 en Full, 50 ventas de Full entre el 01/10 y el 11/10, y vende mucho desde mi depósito
    ml._full = {"IT": {"INV1": {"unidades": 50, "primera": "2026-10-01", "ultima": "2026-10-11"}}}
    ml._stock = {"INV1": 0}
    ml._pagado = {"IT": {("MLA1", None): 247}}
    f = {x.item_id: x for x in rep.calcular_reposicion_mla(ml, ecom, tac, cuentas=["IT", "MT"], hoy=HOY, fecha_llegada=HOY, contar_deposito=True).filas}["MLA1"]
    assert f.censurado and f.deposito_usado == 0 and f.ventas_deposito == 197 and f.ventas_periodo == 50
    assert f.ventas_diarias == 4.55                                     # 50 ventas en 11 días (01/10 al 11/10, ambos extremos): la venta diaria real, sin sumar el depósito


def test_si_las_ventas_de_full_no_se_pudieron_leer_no_se_estima_con_el_deposito():
    ml, ecom, tac = armar()
    ml._items["IT"].append(_item("MLA6", "SKUINC", "INVX"))
    ml._full["IT"]["INVX"] = {"unidades": 13, "primera": "2026-10-01", "ultima": "2026-10-18"}
    ml._pagado["IT"][("MLA6", None)] = 39
    ecom.links["MLA6"] = ("SKUINC", 1)
    ecom.pitec["SKUINC"] = 100
    ml.lotes_fallidos = [{"cuenta": "IT", "tipo": "SALE_CONFIRMATION", "inventory_ids": ["INVX"]}]
    f = {x.item_id: x for x in rep.calcular_reposicion_mla(ml, ecom, tac, cuentas=["IT", "MT"], hoy=HOY, fecha_llegada=HOY, contar_deposito=True).filas}.get("MLA6")
    assert f is not None and f.datos_incompletos and f.deposito_usado == 0


@pytest.fixture(autouse=True)
def _sin_cache_de_vinculacion():
    rep._cache_vinculacion.clear()
    yield
    rep._cache_vinculacion.clear()


def test_vinculaciones_en_paralelo_con_cache_y_una_falla_no_tira_la_corrida():
    llamadas = []

    class E(FakeEcom):
        def factor_pack(self, item_id):
            llamadas.append(item_id)
            if item_id == "MLA3":
                raise RuntimeError("Ecom no responde")
            return super().factor_pack(item_id)
    ml, _, tac = armar()
    ecom = E({"MLA1": ("SKUFULL", 1), "MLA2": ("W1105ACOMP", 1)}, {"SKUFULL": 100, "W1105ACOMP": 40})
    r = rep.calcular_reposicion_mla(ml, ecom, tac, cuentas=["IT", "MT"], hoy=HOY, fecha_llegada=HOY, contar_deposito=True)
    por = {f.item_id: f for f in r.filas}
    assert por["MLA2"].sugerido == 19 and any("vinculación" in a for a in por["MLA3"].avisos)     # la falla de MLA3 se informa, el resto sigue
    rep.calcular_reposicion_mla(ml, ecom, tac, cuentas=["IT", "MT"], hoy=HOY, fecha_llegada=HOY, contar_deposito=True)
    assert llamadas.count("MLA2") == 1 and llamadas.count("MLA3") == 2    # MLA2 salió de la caché; solo se reintentó la que había fallado (MLA3)
