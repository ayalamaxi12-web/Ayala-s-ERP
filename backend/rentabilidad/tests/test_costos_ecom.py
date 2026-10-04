"""Catálogo de costos de Ecom (fuente primaria de costo) — sin red: el cliente
de GraphQL se reemplaza por un doble."""
from decimal import Decimal

import pytest

from rentabilidad import costos_ecom as ce
from rentabilidad.costos_ecom import CatalogoCostos

D = Decimal


def _prod(sku, variantes, tax=21):
    return {"sku": sku, "tax": tax, "variants": [{"sku": v[0], "cost": v[1]} for v in variantes]}


def test_producto_de_una_variante_toma_el_costo_de_la_variante():
    cat = ce.armar_catalogo([_prod("GLOBAL-G720S", [(None, 166.6)])])
    assert cat.costo("GLOBAL-G720S") == D("166.6")


def test_variantes_con_el_mismo_costo_dan_ese_costo():
    cat = ce.armar_catalogo([_prod("A", [(None, 4.69), (None, 4.69)])])
    assert cat.costo("A") == D("4.69")


def test_variantes_sin_sku_propio_y_costo_distinto_son_ambiguas_no_se_elige_una():
    cat = ce.armar_catalogo([_prod("A", [(None, 5.24), (None, 4.69)])])
    assert cat.costo("A") is None
    assert cat.ambiguos["A"] == [D("4.69"), D("5.24")]


def test_variantes_con_sku_propio_se_indexan_por_ese_sku():
    cat = ce.armar_catalogo([_prod("MADRE", [("MADRE-R", 10), ("MADRE-N", 12)])])
    assert cat.costo("MADRE-R") == D("10") and cat.costo("MADRE-N") == D("12")
    assert cat.costo("MADRE") is None and "MADRE" not in cat.ambiguos


def test_costo_cero_o_vacio_es_sin_costo_no_costo_cero():
    cat = ce.armar_catalogo([_prod("A", [(None, 0)]), _prod("B", [(None, None)])])
    assert cat.costo("A") is None and cat.costo("B") is None
    assert cat.sin_costo == {"A", "B"}


def test_el_sku_se_busca_sin_espacios_de_padding():
    cat = ce.armar_catalogo([_prod("TN1060COMP  ", [(None, 1.56)])])
    assert cat.costo("TN1060COMP") == D("1.56") and cat.costo(" TN1060COMP ") == D("1.56")


def test_iva_del_articulo_solo_21_o_10_5():
    cat = ce.armar_catalogo([_prod("A", [(None, 1)], tax=21), _prod("B", [(None, 1)], tax=10.5), _prod("C", [(None, 1)], tax=27)])
    assert cat.factor_iva("A") == D("1.21") and cat.factor_iva("B") == D("1.105") and cat.factor_iva("C") is None


class _Cliente:
    def __init__(self, paginas, fallos=None):
        self.paginas, self.fallos, self.pedidas = paginas, dict(fallos or {}), []

    def graphql(self, query, variables):
        p = variables["page"]
        self.pedidas.append(p)
        if self.fallos.get(p, 0) > 0:
            self.fallos[p] -= 1
            raise RuntimeError("Internal server error")
        return {"products": {"find": {"pageInfo": {"page": p, "pageCount": len(self.paginas)}, "data": self.paginas[p - 1]}}}


def _sin_dormir(_):
    pass


def test_descarga_recorre_todas_las_paginas():
    c = _Cliente([[_prod("A", [(None, 1)])], [_prod("B", [(None, 2)])]])
    cat = ce.descargar_catalogo(c, dormir=_sin_dormir)
    assert c.pedidas == [1, 2] and cat.costo("A") == D("1") and cat.costo("B") == D("2")


def test_descarga_reintenta_una_pagina_con_error_transitorio():
    c = _Cliente([[_prod("A", [(None, 1)])]], fallos={1: 2})
    assert ce.descargar_catalogo(c, dormir=_sin_dormir).costo("A") == D("1")


def test_descarga_falla_si_una_pagina_no_responde_nunca_catalogo_a_medias():
    c = _Cliente([[_prod("A", [(None, 1)])], [_prod("B", [(None, 2)])]], fallos={2: 99})
    with pytest.raises(ce.CatalogoEcomError):
        ce.descargar_catalogo(c, dormir=_sin_dormir)


def test_catalogo_vacio_es_error():
    with pytest.raises(ce.CatalogoEcomError):
        ce.descargar_catalogo(_Cliente([[]]), dormir=_sin_dormir)


@pytest.fixture(autouse=True)
def _cache_limpio():
    ce.limpiar_cache()
    yield
    ce.limpiar_cache()


def test_cache_de_una_hora_no_vuelve_a_bajar_el_catalogo():
    llamadas = []

    def bajar():
        llamadas.append(1)
        return ce.armar_catalogo([_prod("A", [(None, 1)])])

    t = {"n": 1000.0}
    ce.obtener_catalogo(bajar, ahora=lambda: t["n"])
    t["n"] += 1800
    ce.obtener_catalogo(bajar, ahora=lambda: t["n"])
    assert len(llamadas) == 1
    t["n"] += 3700
    ce.obtener_catalogo(bajar, ahora=lambda: t["n"])
    assert len(llamadas) == 2


def test_si_el_refresco_falla_se_sigue_con_el_ultimo_catalogo_bueno():
    t = {"n": 1000.0}
    ce.obtener_catalogo(lambda: ce.armar_catalogo([_prod("A", [(None, 1)])]), ahora=lambda: t["n"])
    t["n"] += 4000

    def roto():
        raise RuntimeError("Ecom caído")

    assert ce.obtener_catalogo(roto, ahora=lambda: t["n"]).costo("A") == D("1")


def test_sin_catalogo_previo_y_ecom_caido_falla():
    def roto():
        raise RuntimeError("Ecom caído")

    with pytest.raises(RuntimeError):
        ce.obtener_catalogo(roto)


def test_proveedor_de_costo_misma_interfaz_que_el_de_tactica():
    cat = ce.armar_catalogo([_prod("A", [(None, 3)])])
    p = ce.CostoEcomProvider(catalogo=lambda: cat)
    p.precargar()
    assert p.obtener("A") == D("3")
    assert p.obtener_con_origen("A") == (D("3"), "ECOM")
    assert p.obtener_con_origen("NO-EXISTE") == (None, None)


class _IvaTactica:
    def __init__(self, factores=None, cae=False):
        self.factores, self.cae = factores or {}, cae

    def precargar(self):
        if self.cae:
            raise ConnectionError("sin túnel")

    def factor(self, sku):
        if self.cae:
            raise ConnectionError("sin túnel")
        return self.factores.get(sku)


def test_iva_usa_tactica_si_responde_aunque_ecom_diga_otra_cosa():
    cat = ce.armar_catalogo([_prod("A", [(None, 1)], tax=21)])
    iva = ce.IvaConRespaldoEcom(tactica=_IvaTactica({"A": D("1.105")}), catalogo=lambda: cat)
    iva.precargar()
    assert iva.factor("A") == D("1.105") and not iva.tactica_caida


def test_iva_cae_al_de_ecom_si_tactica_no_responde():
    cat = ce.armar_catalogo([_prod("A", [(None, 1)], tax=10.5)])
    iva = ce.IvaConRespaldoEcom(tactica=_IvaTactica(cae=True), catalogo=lambda: cat)
    iva.precargar()
    assert iva.tactica_caida and iva.factor("A") == D("1.105")


def test_iva_cae_al_de_ecom_si_tactica_no_tiene_el_sku():
    cat = ce.armar_catalogo([_prod("A", [(None, 1)], tax=21)])
    assert ce.IvaConRespaldoEcom(tactica=_IvaTactica({}), catalogo=lambda: cat).factor("A") == D("1.21")


def test_cruce_con_tactica_alerta_solo_las_diferencias_sobre_la_tolerancia():
    ecom = {"A": D("100"), "B": D("100"), "C": D("100"), "D": D("0")}
    tactica = {"A": D("100.5"), "B": D("110"), "C": D("80"), "D": D("5"), "X": D("9")}
    difs = ce.cruzar_costos(ecom, tactica, D("1"))
    assert [d["sku"] for d in difs] == ["C", "B"]  # A (0,5%) bajo tolerancia; D sin costo Ecom; X no está en Ecom
    assert difs[0]["dif_pct"] == D("-20.00") and difs[1]["dif_pct"] == D("10.00")
