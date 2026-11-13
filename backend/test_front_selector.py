"""Selector múltiple (Canal, Categoría, PM…) de docs/index.html: «Todos» = todas tildadas y destildar una deja «todas menos esa»."""
import json
import os
import shutil
import subprocess

import pytest

from scripts.paridad_margenes import extraer_funcion

INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'docs', 'index.html')
pytestmark = pytest.mark.skipif(not shutil.which('node'), reason='sin node')
FNS = ('msEsTodos', 'msTildada', 'toggleMSValue', 'selectAllMS', 'msNinguno', 'clearMS', 'getMSValues', 'updateMSTrigger')
CANALES = ['Mercadolibre', 'Fravega', 'Tactica', 'Web', 'Ecom', 'OnCity', 'Megatone', 'Mercadolibre Carrito']


def js(cuerpo):
    src = open(INDEX, encoding='utf-8').read()
    cod = ('const trig={textContent:""};const document={querySelector:()=>trig};const renderMSOptions=()=>{};\n'
           'const msState={c:{selected:new Set(),ninguno:false,all:' + json.dumps(CANALES) + '}};const sel=()=>getMSValues("c");const txt=()=>trig.textContent;\n'
           + '\n'.join(extraer_funcion(src, n) for n in FNS) + '\n' + cuerpo)
    return json.loads(subprocess.run(['node', '-e', cod], capture_output=True, text=True, check=True).stdout)


def test_todos_sin_filtro_y_destildar_una_deja_todas_menos_esa():
    r = js('updateMSTrigger("c");const a=[sel(),txt(),msTildada(msState.c,"Tactica")];toggleMSValue("c","Tactica");updateMSTrigger("c");'
           'console.log(JSON.stringify({a,b:sel(),t:txt(),tild:[msTildada(msState.c,"Tactica"),msTildada(msState.c,"Web")]}))')
    assert r['a'] == [None, 'Todos', True]                                          # Todos: sin filtro y se ve tildada
    assert r['b'] == [c for c in CANALES if c != 'Tactica'] and len(r['b']) == 7
    assert r['t'] == 'Todos menos Tactica' and r['tild'] == [False, True]


def test_volver_a_tildar_la_que_se_saco_vuelve_a_todos():
    r = js('toggleMSValue("c","Tactica");toggleMSValue("c","Tactica");updateMSTrigger("c");console.log(JSON.stringify([sel(),txt()]))')
    assert r == [None, 'Todos']


def test_ninguno_destilda_todo_y_se_arma_una_seleccion_desde_cero():
    r = js('msNinguno("c");const a=[sel(),txt()];toggleMSValue("c","Web");toggleMSValue("c","Ecom");const b=[sel(),txt()];toggleMSValue("c","Web");toggleMSValue("c","Ecom");'
           'console.log(JSON.stringify({a,b,c:sel()}))')
    assert r['a'] == [[], 'Ninguno']                                                 # «ninguno» deja pasar nada
    assert r['b'] == [['Web', 'Ecom'], '2 seleccionados'] and r['c'] == []            # al destildar la última vuelve a «ninguno», no a Todos


def test_tildar_todas_a_mano_vuelve_a_todos_y_los_botones_todos_y_limpiar():
    r = js('msNinguno("c");' + ''.join(f'toggleMSValue("c",{json.dumps(c)});' for c in CANALES) + 'const a=sel();msNinguno("c");selectAllMS("c");const b=sel();msNinguno("c");clearMS("c");'
           'console.log(JSON.stringify([a,b,sel()]))')
    assert r == [None, None, None]


def test_texto_del_selector_con_pocas_o_muchas_elegidas():
    r = js('toggleMSValue("c","Web");toggleMSValue("c","Ecom");updateMSTrigger("c");const a=txt();toggleMSValue("c","Ecom");toggleMSValue("c","Ecom");'
           'msNinguno("c");["Web","Ecom","Fravega"].forEach(x=>toggleMSValue("c",x));updateMSTrigger("c");console.log(JSON.stringify([a,txt()]))')
    assert r == ['Todos menos Web, Ecom', '3 seleccionados']


def test_con_una_sola_opcion_destildarla_deja_ninguno():
    src = open(INDEX, encoding='utf-8').read()
    cod = ('const trig={textContent:""};const document={querySelector:()=>trig};const renderMSOptions=()=>{};const msState={c:{selected:new Set(),ninguno:false,all:["Unico"]}};\n'
           + '\n'.join(extraer_funcion(src, n) for n in FNS) + '\ntoggleMSValue("c","Unico");console.log(JSON.stringify(getMSValues("c")))')
    assert json.loads(subprocess.run(['node', '-e', cod], capture_output=True, text=True, check=True).stdout) == []
