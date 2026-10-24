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
    src = re.search(r"const INTEL=\{.*?\};", s).group(0) + '\n' + re.search(r"const INTEL_RANGO_REFS=.*?;", s).group(0) + '\n' + _fn(s, '_rowsToObjs') + '\n'
    for n in ('intelCargarEntidades', 'intelCargarReferencias'):                                  # son async: _fn busca 'function nombre('
        i = s.index(f'async function {n}(')
        j = s.index('{', i)
        d = 0
        for k in range(j, len(s)):
            d += (s[k] == '{') - (s[k] == '}')
            if d == 0:
                src += s[i:k + 1] + '\n'
                break
    pre = ("const H=JSON.parse(process.argv[1]);const llamadas=[];global.COMP_SHEET_ID='SHEET';"
           "global.fetchSheet=async(id,rango)=>{llamadas.push(rango);const k=rango.split('!')[0];if(!(k in H))throw new Error('no existe');return H[k];};\n")
    out = subprocess.run(['node', '-e', src + '\n' + pre + '(async()=>{' + cuerpo + '})();', json.dumps(hojas if hojas is not None else {'Referencias_Mercado': REFS, 'Entidades': ENTS})],
                         capture_output=True, text=True, check=True).stdout
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
