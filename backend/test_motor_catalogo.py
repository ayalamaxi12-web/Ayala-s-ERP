"""Motor de Precios: catálogo completo de SKU, IVA de las variantes, refresco por faltante y «IVA del SKU» manual."""
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

import ayala_core
import main
from rentabilidad import costos_ecom as ce


def _productos():
    return [
        # el caso de Maxx: artículo «PINMK-CIRC-3IN1-» con IVA 21 % y dos variantes con SKU propio y costo 19,17
        {"sku": "PINMK-CIRC-3IN1-", "tax": "21", "variants": [{"sku": "PINMK-CIRC-3IN1-BL", "cost": "19.17"}, {"sku": "PINMK-CIRC-3IN1-PK", "cost": "19.17"}]},
        {"sku": "CB435A-436A-CE285AUNIVCOMP", "tax": "10.5", "variants": [{"sku": "", "cost": "12.5"}]},
        {"sku": "SINCOSTO", "tax": "21", "variants": [{"sku": "", "cost": "0"}]},
        {"sku": "AMBIGUO", "tax": "21", "variants": [{"sku": "", "cost": "5"}, {"sku": "", "cost": "7"}]},
        {"sku": "SINIVA", "tax": "0", "variants": [{"sku": "", "cost": "3"}]},
    ]


def test_la_variante_con_sku_propio_hereda_el_iva_del_articulo():
    cat = ce.armar_catalogo(_productos())
    assert cat.factor_iva("PINMK-CIRC-3IN1-PK") == D("1.21") and cat.factor_iva("PINMK-CIRC-3IN1-BL") == D("1.21")     # antes la PK daba SIN_IVA
    assert cat.costo("PINMK-CIRC-3IN1-PK") == D("19.17") and cat.factor_iva("CB435A-436A-CE285AUNIVCOMP") == D("1.105")
    assert cat.factor_iva("SINIVA") is None


def test_estados_y_motivos_en_texto():
    cat = ce.armar_catalogo(_productos())
    assert [cat.estado_costo(s) for s in ("PINMK-CIRC-3IN1-PK", "SINCOSTO", "AMBIGUO", "NOEXISTE")] == ["ok", "sin_costo", "ambiguo", "no_existe"]
    assert "sin costo cargado" in cat.motivo_sin_costo("SINCOSTO") and "costos distintos" in cat.motivo_sin_costo("AMBIGUO")
    assert "no figura en el catálogo" in cat.motivo_sin_costo("NOEXISTE")
    assert ("SINIVA", "ok", False) in cat.todos_los_skus() and len(cat.todos_los_skus()) == 6


class _Cliente:
    pass


@pytest.fixture
def api(monkeypatch):
    cat = ce.armar_catalogo(_productos())
    monkeypatch.setattr(ce, "obtener_catalogo", lambda *a, **k: cat)
    monkeypatch.setattr(main.costos_ecom, "proveedores_de_costo_e_iva",
                        lambda: (ce.CostoEcomProvider(lambda: cat), ce.IvaConRespaldoEcom(tactica=_TacticaVacia(), catalogo=lambda: cat)))
    monkeypatch.setattr(main, "tc_info_rapido", lambda: {"tc": D("1450"), "source": "cache", "fecha": None})
    return TestClient(main.app), cat


class _TacticaVacia:
    def precargar(self): pass
    def factor(self, sku): return None


def test_catalogo_completo_para_el_selector(api):
    cl, cat = api
    d = cl.get("/ayala-core/catalogo-skus").json()
    assert d["total"] == 6 and ["SINCOSTO", "sin_costo", True] in d["skus"] and ["PINMK-CIRC-3IN1-PK", "ok", True] in d["skus"]
    assert any(s[0] == "CB435A-436A-CE285AUNIVCOMP" for s in d["skus"])


def test_la_variante_tocada_hoy_calcula_con_el_iva_del_articulo(api):
    cl, _ = api
    r = cl.get("/ayala-core/motor-lote", params={"skus": "PINMK-CIRC-3IN1-BL,PINMK-CIRC-3IN1-PK"}).json()["resultados"]
    assert all("error" not in x and x["iva_factor"] == 1.21 for x in r) and r[0]["precios"] == r[1]["precios"]      # mismo costo y mismo IVA: mismos precios


def test_errores_en_texto_y_un_sku_con_error_no_frena_el_lote(api):
    cl, _ = api
    r = {x["sku"]: x for x in cl.get("/ayala-core/motor-lote", params={"skus": "CB435A-436A-CE285AUNIVCOMP,SINCOSTO,SINIVA,NOEXISTE"}).json()["resultados"]}
    assert "error" not in r["CB435A-436A-CE285AUNIVCOMP"]
    assert "sin costo cargado" in r["SINCOSTO"]["error"] and "no figura en el catálogo" in r["NOEXISTE"]["error"]
    assert "sin IVA en Ecom ni en Táctica: corregilo en Ecom o cargalo a mano" in r["SINIVA"]["error"]


def test_iva_manual_en_un_sku_sin_iva_y_solo_como_respaldo_en_un_lote(api):
    cl, _ = api
    d = cl.get("/ayala-core/sku/SINIVA/motor", params={"iva": 10.5}).json()
    assert d["iva_factor"] == 1.105
    assert cl.get("/ayala-core/sku/SINIVA/motor", params={"iva": 12}).status_code == 422
    # SKU puntual: la persona lo pidió, pisa; en un lote solo completa los que no tienen IVA (los que calculan bien no cambian)
    puntual = cl.get("/ayala-core/sku/CB435A-436A-CE285AUNIVCOMP/motor", params={"iva": 21}).json()
    lote = {x["sku"]: x for x in cl.get("/ayala-core/motor-lote", params={"skus": "CB435A-436A-CE285AUNIVCOMP,SINIVA", "iva": 21}).json()["resultados"]}
    assert puntual["iva_factor"] == 1.21 and lote["CB435A-436A-CE285AUNIVCOMP"]["iva_factor"] == 1.105 and lote["SINIVA"]["iva_factor"] == 1.21


def test_diagnostico_de_los_sku_que_no_calculan_sin_tocarlos(api, monkeypatch):
    cl, cat = api
    monkeypatch.setattr(ce, "IvaConRespaldoEcom", lambda *a, **k: ce.IvaConRespaldoEcom.__wrapped__() if False else _Resp(cat))
    d = cl.get("/ayala-core/catalogo-skus/diagnostico").json()
    assert d["total_catalogo"] == 6 and d["no_calculan"] == 3 and d["resumen"] == {"sin_costo": 1, "ambiguo": 1, "sin_iva": 1}
    assert {f["sku"]: f["motivo"] for f in d["filas"]} == {"AMBIGUO": "ambiguo", "SINCOSTO": "sin_costo", "SINIVA": "sin_iva"}


class _Resp:
    tactica_caida = False
    def __init__(self, cat): self.cat = cat
    def precargar(self): pass
    def factor_con_origen(self, sku):
        f = self.cat.factor_iva(sku)
        return (f, "ECOM") if f else (None, None)


# ── refresco UNA vez si falta (máx. cada 10 min) ──

def test_refresca_la_foto_una_sola_vez_por_ventana_de_10_minutos(monkeypatch):
    monkeypatch.undo()
    from rentabilidad import costos_ecom as ce2
    ce2.limpiar_cache()
    llamadas = []
    reloj = {"t": 1000.0}
    nuevo = ce.armar_catalogo(_productos())

    def descargar():
        llamadas.append(reloj["t"])
        return nuevo
    kw = dict(ahora=lambda: reloj["t"], descargar=descargar, db_factory=_BaseFalsa)
    assert ce2.refrescar_por_faltante(**kw) is True
    reloj["t"] += 300
    assert ce2.refrescar_por_faltante(**kw) is False          # a los 5 min no
    reloj["t"] += 400
    assert ce2.refrescar_por_faltante(**kw) is True           # a los 11 min sí
    assert len(llamadas) == 2
    ce2.limpiar_cache()


def _BaseFalsa():
    raise RuntimeError("sin base en el test")        # `refrescar` sirve igual desde memoria si la base no escribe


def test_un_sku_que_falta_refresca_y_si_aparece_calcula(monkeypatch):
    viejo = ce.armar_catalogo([p for p in _productos() if not p["sku"].startswith("PINMK")])
    nuevo = ce.armar_catalogo(_productos())
    estado = {"cat": viejo, "refrescos": 0}

    def refresco(*a, **k):
        estado["refrescos"] += 1
        estado["cat"] = nuevo
        return True
    monkeypatch.setattr(main.costos_ecom, "refrescar_por_faltante", refresco)
    monkeypatch.setattr(main.costos_ecom, "proveedores_de_costo_e_iva",
                        lambda: (ce.CostoEcomProvider(lambda: estado["cat"]), ce.IvaConRespaldoEcom(tactica=_TacticaVacia(), catalogo=lambda: estado["cat"])))
    monkeypatch.setattr(main, "tc_info_rapido", lambda: {"tc": D("1450"), "source": "cache", "fecha": None})
    r = TestClient(main.app).get("/ayala-core/motor-lote", params={"skus": "PINMK-CIRC-3IN1-PK"}).json()["resultados"][0]
    assert "error" not in r and estado["refrescos"] == 1


def test_ml_sin_cambios_informa_el_costo_por_orden_que_ya_incluye_su_precio(api):
    cl, _ = api
    r = cl.get("/ayala-core/motor-lote", params={"skus": "PINMK-CIRC-3IN1-BL"}).json()["resultados"][0]
    p = r["parametros"]
    assert p["costo_orden"] == 149.12 and p["comision_pct"] == 15.5      # antes la tarjeta decía «sin costo por orden» aunque el precio ya lo incluía
