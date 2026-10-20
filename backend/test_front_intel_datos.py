"""Cargador compartido de Inteligencia Comercial (docs/index.html: INTEL, intelCargarEntidades / intelCargarReferencias / intelReindexar): lo usan SKUs & Referencias,
Entidades y Referencias. Corre en node con un fetchSheet falso y datos SINTÉTICOS; se saltea sin node."""
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
    src = re.search(r"const INTEL=\{.*?\};", s).group(0) + '\n' + re.search(r"const INTEL_RANGO_REFS=.*?;", s).group(0) + '\n' + '\n'.join(
        _fn(s, n) if f'function {n}(' in s else '' for n in ('_rowsToObjs', 'intelReindexar')) + '\n'
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


def test_carga_indexa_por_sku_y_une_cada_referencia_con_su_entidad():
    r = correr("const a=await intelCargarEntidades(),b=await intelCargarReferencias();console.log(JSON.stringify([a,b,Object.keys(INTEL.bySku),INTEL.bySku['SKU-9001'].map(x=>x._entidad&&x._entidad.Nombre),INTEL.bySku['SKU-9002'][0]._entidad,INTEL.referencias.length,llamadas]))")
    assert r[:2] == [True, True] and r[2] == ['SKU-9001', 'SKU-9002']
    assert r[3] == ['TIENDA A', 'TIENDA B'] and r[4] is None                    # E9 no existe: referencia sin entidad, no rompe
    assert r[5] == 3                                                            # la fila vacía se descarta
    assert r[6] == ['Entidades!A1:Z1000', 'Referencias_Mercado!A1:Z5000']     # rangos por defecto


def test_el_rango_se_puede_elegir_y_una_pestana_inexistente_devuelve_false_sin_tocar_el_estado():
    r = correr("await intelCargarReferencias('Referencias_Mercado!A1:Z1000');const antes=INTEL.referencias.length;const f=await intelCargarEntidades();console.log(JSON.stringify([llamadas,f,antes,INTEL.referencias.length,INTEL.entidades.length]))",
               {'Referencias_Mercado': REFS})
    assert r == [['Referencias_Mercado!A1:Z1000', 'Entidades!A1:Z1000'], False, 3, 3, 0]


def test_las_referencias_se_reindexan_cuando_llegan_las_entidades_despues():
    r = correr("await intelCargarReferencias();const sin=INTEL.bySku['SKU-9001'][0]._entidad;await intelCargarEntidades();console.log(JSON.stringify([sin,INTEL.bySku['SKU-9001'][0]._entidad.Nombre]))")
    assert r == [None, 'TIENDA A']
