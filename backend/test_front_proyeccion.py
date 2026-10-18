"""Botón "Cargar snapshot" de la página Proyección 2027 (docs/index.html): valida el archivo y lo sube con el fetch del ERP.
Lógica real extraída del HTML y corrida en node con fetch/confirm/qs simulados; datos SINTÉTICOS, sin red. Se saltea sin node."""
import json
import os
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scripts'))
import paridad_margenes as pm  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which('node'), reason='sin node')
SRC = open(pm.INDEX, encoding='utf-8').read()
BUENO = json.dumps({"meta": {"schema_version": "1.0", "generado": "2000-01-01"}, "kpis": {"reyes": 1}}, ensure_ascii=False)


def _correr(caso):
    """caso: texto, size, nombre, bu, confirma, resp ({status, json}) o error (fetch rechaza). Devuelve {msg, color, fetchs, confirms, recargas}."""
    fns = pm.extraer_funcion(SRC, 'proyeccionValidarArchivo') + '\nasync ' + pm.extraer_funcion(SRC, 'proyeccionSubir')
    js = ("global.window={};const PROY_MAX_BYTES=20*1024*1024;const c=JSON.parse(process.argv[1]);const el={style:{},textContent:''};const fetchs=[],confirms=[];let recargas=0;"
          "global.qs=()=>el;global.getBackendUrl=()=>c.bu;global.confirm=t=>{confirms.push(t);return c.confirma;};global.proyeccionCargar=async()=>{recargas++;};"
          "global.fetch=async(u,o)=>{fetchs.push({u,method:o.method,body:o.body,headers:o.headers});if(c.error)throw new Error(c.error);"
          "return{status:c.resp.status,ok:c.resp.status<400,json:async()=>c.resp.json};};\n" + fns +
          "\n(async()=>{const file={name:c.nombre,size:c.size==null?c.texto.length:c.size,text:async()=>c.texto};await proyeccionSubir(file);"
          "console.log(JSON.stringify({msg:el.textContent,color:el.style.color,fetchs,confirms,recargas}));})();")
    return json.loads(subprocess.run(['node', '-e', js, json.dumps(dict({'bu': 'https://backend.test', 'confirma': True, 'nombre': 'demo.json', 'texto': BUENO}, **caso))],
                                     capture_output=True, text=True, check=True).stdout)


def test_subida_ok_manda_el_mismo_cuerpo_y_muestra_la_version():
    r = _correr({'resp': {'status': 200, 'json': {'ok': True, 'version': 7, 'conservar': 20}}})
    assert r['msg'] == '✅ Versión 7 cargada.' and r['color'] == 'var(--green)'
    f, = r['fetchs']
    assert f['u'] == 'https://backend.test/proyeccion-2027/snapshot' and f['method'] == 'POST' and f['body'] == BUENO
    assert f['headers'] == {'Content-Type': 'application/json'}  # la clave NUNCA la pone esta función: la agrega el wrapper de fetch
    assert r['recargas'] == 1 and 'demo.json' in r['confirms'][0]


def test_no_json_no_sube_nada():
    r = _correr({'texto': 'esto no es json'})
    assert r['msg'].startswith('❌ el archivo no es un JSON válido') and r['fetchs'] == [] and r['confirms'] == []


@pytest.mark.parametrize('texto,frag', [
    ('[1,2]', 'debe ser un objeto'), ('{"kpis":{}}', 'falta "meta"'),
    (json.dumps({'meta': {'schema_version': '2.0'}}), 'el archivo trae "2.0"'), (json.dumps({'meta': {}}), 'el archivo trae null'),
])
def test_contrato_invalido_se_rechaza_en_el_navegador(texto, frag):
    r = _correr({'texto': texto})
    assert frag in r['msg'] and r['color'] == 'var(--red)' and r['fetchs'] == []


def test_si_no_confirma_no_se_sube():
    r = _correr({'confirma': False, 'resp': {'status': 200, 'json': {'version': 1}}})
    assert r['msg'] == 'Carga cancelada.' and r['fetchs'] == [] and r['recargas'] == 0


def test_sin_url_de_backend_o_archivo_enorme():
    assert 'Falta la URL del backend' in _correr({'bu': ''})['msg']
    r = _correr({'size': 21 * 1024 * 1024})
    assert 'más de 20 MB' in r['msg'] and r['fetchs'] == []


@pytest.mark.parametrize('status,body,frag', [
    (401, {}, 'Clave del backend faltante o incorrecta'), (503, {}, 'ERP_API_KEY'), (413, {}, 'tamaño'), (500, {}, 'Error 500'),
    (422, {'detail': {'mensaje': 'x', 'errores': ["falta la clave 'skus'", "falta la clave 'capital'"]}}, "falta la clave 'skus'; falta la clave 'capital'"),
    (422, {'detail': 'El cuerpo no es JSON válido.'}, 'El cuerpo no es JSON válido.'),
])
def test_errores_del_backend_se_muestran_y_no_se_recarga(status, body, frag):
    r = _correr({'resp': {'status': status, 'json': body}})
    assert frag in r['msg'] and r['msg'].startswith('❌') and r['recargas'] == 0


def test_falla_de_red_se_muestra():
    r = _correr({'error': 'Failed to fetch'})
    assert r['msg'] == '❌ Failed to fetch' and r['recargas'] == 0


def test_el_boton_y_el_selector_estan_en_la_pagina_y_el_wrapper_agrega_la_clave():
    assert 'Cargar snapshot' in SRC and 'id="proy-file"' in SRC and 'accept=".json,application/json"' in SRC
    assert "h.set('X-ERP-Key',key)" in SRC  # el wrapper de fetch del ERP que usa la clave guardada en el navegador
