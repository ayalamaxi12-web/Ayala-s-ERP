"""Carga de ofertas por Excel (docs/index.html): qué filas cuentan como pendientes, a qué campañas pueden ir y cómo se estado cada una. Lógica pura en node."""
import json
import shutil
import subprocess

import pytest

from test_front_analisis import INDEX, _fn

pytestmark = pytest.mark.skipif(not shutil.which('node'), reason='sin node')

FNS = ('ofxPendientes', 'ofxPuedeEn', 'ofxEstadoFila')


def js(cuerpo):
    src = open(INDEX, encoding='utf-8').read()
    fns = '\n'.join(_fn(src, n) for n in FNS)
    out = subprocess.run(['node', '-e', fns + '\n' + cuerpo], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


FILAS = [
    {'mla': 'A', 'bloqueos': [], 'candidatas': [{'id': 'C1'}, {'id': 'C2'}], 'estado': None},
    {'mla': 'B', 'bloqueos': ['no existe'], 'candidatas': [], 'estado': None},
    {'mla': 'C', 'bloqueos': [], 'candidatas': [{'id': 'C2'}], 'estado': None},
    {'mla': 'D', 'bloqueos': [], 'candidatas': [{'id': 'C1'}], 'estado': 'ok'},
    {'mla': 'E', 'bloqueos': [], 'candidatas': [], 'estado': 'error'},
]


def test_pendientes_son_las_que_no_estan_aplicadas_ni_bloqueadas_y_se_cuentan_por_campana():
    r = js(f"const OFX={{filas:{json.dumps(FILAS)},sel:null}};"
           "const p=ofxPendientes();console.log(JSON.stringify([p.map(f=>f.mla),p.filter(f=>ofxPuedeEn(f,'C1')).length,p.filter(f=>ofxPuedeEn(f,'C2')).length]))")
    assert r == [['A', 'C', 'E'], 1, 2]


def test_estado_de_cada_fila_segun_la_campana_elegida():
    r = js(f"const OFX={{filas:{json.dumps(FILAS)},sel:'C1'}};console.log(JSON.stringify(OFX.filas.map(f=>ofxEstadoFila(f)[0])))")
    assert r == ['lista', 'no', 'pend', 'ok', 'error']          # C no entra en C1 → pendiente; B bloqueada → no se puede
    r = js(f"const OFX={{filas:{json.dumps(FILAS)},sel:null}};console.log(JSON.stringify(OFX.filas.map(f=>ofxEstadoFila(f)[0])))")
    assert r == ['lista', 'no', 'lista', 'ok', 'error']
