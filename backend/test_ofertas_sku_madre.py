"""«Buscar una publicación puntual» con SKU madre: el costo sale de la vinculación de Ecom o de las variantes, no se pierde por ser madre."""
from decimal import Decimal as D
from types import SimpleNamespace

import ml_ofertas as mo
from rentabilidad.costos_ecom import CatalogoCostos, CostoEcomProvider, armar_catalogo


def _prov(productos):
    cat = armar_catalogo(productos)
    return CostoEcomProvider(lambda: cat), SimpleNamespace(factor=lambda sku: cat.iva.get(sku))


PROD = [{"sku": "AURI-EPGMR035", "tax": 21, "variants": [{"sku": "AURI-EPGMR035-NEGRO", "cost": 10}, {"sku": "AURI-EPGMR035-BLANCO", "cost": 12}]},
        {"sku": "IGUALES", "tax": 21, "variants": [{"sku": "IGUALES-A", "cost": 5}, {"sku": "IGUALES-B", "cost": 5}]},
        {"sku": "SIMPLE", "tax": 10.5, "variants": [{"sku": "", "cost": 7}]}]


def test_el_catalogo_recuerda_las_variantes_de_cada_madre_y_sobrevive_al_json():
    from rentabilidad import costos_ecom as ce
    cat = armar_catalogo(PROD)
    assert cat.variantes_de("AURI-EPGMR035") == [("AURI-EPGMR035-NEGRO", D("10")), ("AURI-EPGMR035-BLANCO", D("12"))]
    otra = ce._armar(__import__("json").loads(ce.catalogo_a_json(cat)), 0.0)
    assert otra.variantes_de("IGUALES") == [("IGUALES-A", D("5")), ("IGUALES-B", D("5"))]
    assert ce._armar({"costos": {}, "iva": {}, "ambiguos": {}, "sin_costo": []}, 0.0).variantes_de("X") == []     # foto vieja sin variantes


def test_con_sku_propio_con_costo_no_cambia_nada():
    c, i = _prov(PROD)
    r = mo.resolver_costo_e_iva_con_madre(c, i, "SIMPLE", "MLA1")
    assert r["via"] == "sku_ml" and r["costo_usd"] == D("7") and r["iva_factor"] == D("1.105") and r["incidencia"] is None


def test_madre_con_vinculacion_de_ecom_usa_la_variante_exacta():
    c, i = _prov(PROD)
    pack = SimpleNamespace(variantes=[{"sku": "AURI-EPGMR035-NEGRO", "qty": 1, "parent_sku": "AURI-EPGMR035", "atributos": []}])
    r = mo.resolver_costo_e_iva_con_madre(c, i, "AURI-EPGMR035", "MLA1", lambda iid: pack)
    assert r["via"] == "vinculacion_ecom" and r["sku_calculo"] == "AURI-EPGMR035-NEGRO" and r["costo_usd"] == D("10") and r["iva_factor"] == D("1.21") and r["incidencia"] is None


def test_vinculacion_de_un_pack_multiplica_el_costo_por_la_cantidad():
    c, i = _prov(PROD)
    pack = SimpleNamespace(variantes=[{"sku": "AURI-EPGMR035-BLANCO", "qty": 2}])
    assert mo.resolver_costo_e_iva_con_madre(c, i, "AURI-EPGMR035", "MLA1", lambda iid: pack)["costo_usd"] == D("24")


def test_sin_vinculacion_y_variantes_de_igual_costo_se_usa_ese_costo():
    c, i = _prov(PROD)
    r = mo.resolver_costo_e_iva_con_madre(c, i, "IGUALES", "MLA1", lambda iid: None)
    assert r["via"] == "variantes_iguales" and r["costo_usd"] == D("5") and r["iva_factor"] == D("1.21")


def test_variantes_de_costo_distinto_sin_vinculacion_no_se_elige_al_azar_y_se_muestran():
    c, i = _prov(PROD)
    r = mo.resolver_costo_e_iva_con_madre(c, i, "AURI-EPGMR035", "MLA1", lambda iid: (_ for _ in ()).throw(RuntimeError("Ecom caído")))
    assert r["incidencia"] == "SIN_COSTO" and r["costo_usd"] is None and "cuestan distinto" in r["motivo"]
    assert [v["sku"] for v in r["variantes_madre"]] == ["AURI-EPGMR035-NEGRO", "AURI-EPGMR035-BLANCO"]


def test_mla_sin_sku_en_ml_pero_vinculado_en_ecom_se_resuelve_por_la_vinculacion():
    c, i = _prov(PROD)
    pack = SimpleNamespace(variantes=[{"sku": "AURI-EPGMR035-NEGRO", "qty": 1}])
    assert mo.resolver_costo_e_iva_con_madre(c, i, None, "MLA1", lambda iid: pack)["sku_calculo"] == "AURI-EPGMR035-NEGRO"
    assert mo.resolver_costo_e_iva_con_madre(c, i, None, "MLA1", None)["incidencia"] == "SIN_SKU"


def test_front_pm_por_sku_de_calculo_y_notas_del_sku_madre():
    import json
    import os
    import subprocess
    from scripts.paridad_margenes import extraer_funcion
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'docs', 'index.html'), encoding='utf-8').read()
    js = ("const acEsc=s=>String(s);const normSku=s=>String(s).toLowerCase();const ofgNota=(t,x)=>t+':'+x;const S={pmData:{'auri-epgmr035-negro':{ml:722656}}};"
          + extraer_funcion(src, "ofmPmRec") + extraer_funcion(src, "ofmNotaSkuMadre") + """
const a={sku:'AURI-EPGMR035',sku_calculo:'AURI-EPGMR035-NEGRO',via_sku:'vinculacion_ecom',cantidad_vinculada:1};
const b={sku:'AURI-EPGMR035',incidencia:'SIN_COSTO',motivo_sin_costo:'sus variantes cuestan distinto',variantes_madre:[{sku:'A-N',costo_usd:10},{sku:'A-B',costo_usd:null}]};
console.log(JSON.stringify([ofmPmRec(a),ofmPmRec({sku:'X'}),ofmNotaSkuMadre(a),ofmNotaSkuMadre(b),ofmNotaSkuMadre({sku:'S',via_sku:'sku_ml'})]));""")
    r = json.loads(subprocess.run(['node', '-e', js], capture_output=True, text=True, check=True).stdout)
    assert r[0] == {'ml': 722656} and r[1] is None
    assert 'variante vinculada en Ecom' in r[2] and 'AURI-EPGMR035-NEGRO' in r[2]
    assert 'cuestan distinto' in r[3] and 'A-N (USD 10)' in r[3] and 'A-B (sin costo)' in r[3] and r[4] == ''
