"""Cargador compartido de Inteligencia Comercial (docs/index.html: INTEL, intelCargarEntidades / intelCargarReferencias): lo usan Entidades y Referencias
(SKUs & Referencias, que también lo usaba, está jubilada). Corre en node con un fetchSheet falso y datos SINTÉTICOS; se saltea sin node."""
import json
import re
import shutil
import subprocess

import pytest

from test_front_analisis import INDEX, _fn

pytestmark = pytest.mark.skipif(not shutil.which('node'), reason='sin node')
REFS = [['Referencia_ID', 'SKU', 'Entidad_ID', 'Tipo'], ['R1', 'SKU-9001', 'E1', 'Competencia'], ['R2', 'SKU-9001', 'E2', 'Distribuidor'], ['R3', 'SKU-9002', 'E9', 'Mayorista'], ['', '', '', '']]
ENTS = [['Entidad_ID', 'Nombre'], ['E1', 'TIENDA A'], ['E2', 'TIENDA B']]


def correr(cuerpo, hojas=None):
    s = open(INDEX, encoding='utf-8').read()
    src = s[s.index('// ICONOS-INICIO'):s.index('// ICONOS-FIN')] + _fn(s, 'referenciasAvisoHtml') + '\n' + re.search(r"const INTEL=\{.*?\};", s).group(0) + '\n' + re.search(r"const INTEL_RANGO_REFS=.*?;", s).group(0) + '\n' + _fn(s, '_rowsToObjs') + '\n'
    for n in ('intelCargarEntidades', 'intelCargarReferencias'):                                  # son async: _fn busca 'function nombre('
        i = s.index(f'async function {n}(')
        j = s.index('{', i)
        d = 0
        for k in range(j, len(s)):
            d += (s[k] == '{') - (s[k] == '}')
            if d == 0:
                src += s[i:k + 1] + '\n'
                break
    pre = ("const H=JSON.parse(require('fs').readFileSync(0,'utf8'));const llamadas=[];global.COMP_SHEET_ID='SHEET';"
           "global.fetchSheet=async(id,rango)=>{llamadas.push(rango);const k=rango.split('!')[0];if(!(k in H))throw new Error('no existe');return H[k];};\n")
    out = subprocess.run(['node', '-e', src + '\n' + pre + '(async()=>{' + cuerpo + '})();'],
                         input=json.dumps(hojas if hojas is not None else {'Referencias_Mercado': REFS, 'Entidades': ENTS}), capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def test_carga_entidades_y_referencias_descarta_filas_vacias():
    r = correr("const a=await intelCargarEntidades(),b=await intelCargarReferencias();console.log(JSON.stringify([a,b,INTEL.referencias.length,INTEL.entidades.length,INTEL.referencias[0].SKU,INTEL.entidades[1].Nombre,llamadas]))")
    assert r[:4] == [True, True, 3, 2] and r[4] == 'SKU-9001' and r[5] == 'TIENDA B'          # la fila vacía de referencias se descarta
    assert r[6] == ['Entidades!A1:Z1000', 'Referencias_Mercado!A1:Z5000']                       # rangos por defecto


def test_el_rango_se_puede_elegir_y_una_pestana_inexistente_devuelve_false_sin_tocar_el_estado():
    r = correr("await intelCargarReferencias('Referencias_Mercado!A1:Z1000');const antes=INTEL.referencias.length;const f=await intelCargarEntidades();console.log(JSON.stringify([llamadas,f,antes,INTEL.referencias.length,INTEL.entidades.length]))",
               {'Referencias_Mercado': REFS})
    assert r == [['Referencias_Mercado!A1:Z1000', 'Entidades!A1:Z1000'], False, 3, 3, 0]


def test_sku_e_inventario_de_la_pagina_jubilada_ya_no_estan_en_el_html():
    s = open(INDEX, encoding='utf-8').read()
    for rastro in ('page-intel-comercial', 'loadIntelComercial', 'renderIntelComercial', 'INTEL.bySku', 'intelReindexar', 'btn-load-intel-comercial', 'data-page="intel-comercial"'):
        assert rastro not in s, rastro
    assert "page==='intel-comercial'){page='analisis-competencia'" in s                            # el link viejo lleva a Análisis de Competencia
    for vive in ('page-intel-entidades', 'page-intel-referencias', 'loadEntidadesPage', 'loadReferenciasPage'):
        assert vive in s, vive                                                                       # Entidades y Referencias NO se tocan


def filas(n):
    """n filas en total (encabezado incluido), como las devuelve el Sheet hasta la última con datos."""
    return [REFS[0]] + [[f'R{i}', f'SKU-{i}', 'E1', 'Competencia'] for i in range(1, n)]


def test_aviso_de_limite_cuando_la_lectura_llega_al_tope_de_filas():
    cuerpo = "const f=await intelCargarReferencias(X.rango);console.log(JSON.stringify([f,INTEL.referencias.length,INTEL.refsTope,INTEL.refsTruncadas]))"
    pagina = lambda n, rango=None: correr(cuerpo.replace('X.rango', repr(rango) if rango else 'undefined'), {'Referencias_Mercado': filas(n)})
    assert pagina(5000) == [True, 4999, 5000, True]                           # 5000 filas = el tope: puede haber más
    assert pagina(4999) == [True, 4998, 5000, False]                          # una menos: se leyó todo
    assert pagina(1000, 'Referencias_Mercado!A1:Z1000') == [True, 999, 1000, True]   # el tope sale del rango pedido
    assert pagina(3) == [True, 2, 5000, False]


def test_texto_del_aviso_visible_y_sin_aviso_cuando_no_se_alcanza():
    h = correr("console.log(JSON.stringify([referenciasAvisoHtml(true,4999,5000),referenciasAvisoHtml(false,10,5000)]))")
    assert '4.999' in h[0] and '5.000' in h[0] and 'Puede haber más referencias en el Sheet' in h[0] and '<svg' in h[0] and h[1] == ''


def test_la_pagina_referencias_ya_no_pide_solo_1000_filas():
    s = open(INDEX, encoding='utf-8').read()
    i = s.index('async function loadReferenciasPage'); cuerpo = s[i:s.index('function renderReferenciasPage')]
    assert 'A1:Z1000' not in cuerpo and 'intelCargarReferencias()' in cuerpo and 'referenciasAvisoLimite()' in cuerpo
    assert INTEL_RANGO_REFS in s if False else "const INTEL_RANGO_REFS='Referencias_Mercado!A1:Z5000'" in s
