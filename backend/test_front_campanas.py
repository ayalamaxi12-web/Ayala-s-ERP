"""Simulador de Campañas ML (docs/index.html): lógica pura de filtros, orden y validación de %. Se corre en node. El margen NO se calcula
en el front: lo calcula el backend (test_campanas_ml*.py). Se saltea sin node."""
import json
import os
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scripts'))
import paridad_margenes as pm  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which('node'), reason='sin node')
FUNS = ('cpPctValido', 'cpMargen', 'cpModificada', 'cpClaseMargen', 'cpFiltrar', 'cpOrdenar')


def _js(expr, datos):
    src = open(pm.INDEX, encoding='utf-8').read()
    fns = '\n'.join(pm.extraer_funcion(src, n) for n in FUNS)
    js = fns + "\nconst D=JSON.parse(process.argv[1]);console.log(JSON.stringify(" + expr + "));"
    return json.loads(subprocess.run(['node', '-e', js, json.dumps(datos)], capture_output=True, text=True, check=True).stdout)


def _f(fila, sku, margen, edit=True, avisos=(), pct=5, titulo='T'):
    return {'fila': fila, 'sku': sku, 'item_id': 'MLA%d' % fila, 'titulo': titulo, 'editable': edit, 'avisos': list(avisos),
            'seller_pct': pct, 'margenes': ({'contado': {'margen': margen}, '3': {'margen': (margen or 0) - 5}} if margen is not None else {})}


FILAS = [_f(6, 'AAA', 30), _f(7, 'BBB', 12, avisos=['x']), _f(8, 'CCC', -3, edit=False), _f(9, None, None), _f(10, 'DDD', 18, pct=9)]
ORIG = {6: 5, 7: 5, 8: 5, 9: 5, 10: 5}
BASE = {'search': '', 'soloEdit': False, 'soloMod': False, 'soloAviso': False, 'soloBajo': False, 'plan': 'contado', 'obj': 20}


@pytest.mark.parametrize('v,ok', [(5, True), (80, True), (4, False), (81, False), (7.5, False), (34.846, False), (None, False)])
def test_ml_solo_acepta_enteros_entre_5_y_80(v, ok):
    assert _js('cpPctValido(D)', v) is ok


def _filtrar(**k):
    return [f['fila'] for f in _js('cpFiltrar(D.f,D.fl,D.o)', {'f': FILAS, 'fl': dict(BASE, **k), 'o': {str(a): b for a, b in ORIG.items()}})]


def test_filtros():
    assert _filtrar() == [6, 7, 8, 9, 10]
    assert _filtrar(soloEdit=True) == [6, 7, 9, 10]
    assert _filtrar(soloBajo=True) == [7, 8, 10]          # margen < 20 con la cuota de referencia; sin margen no entra
    assert _filtrar(soloBajo=True, plan='3') == [7, 8, 10]  # margen a 3 cuotas = contado − 5: 25, 7, −8, 13
    assert _filtrar(soloMod=True) == [10]
    assert _filtrar(soloAviso=True) == [7]
    assert _filtrar(search='mla9') == [9] and _filtrar(search='ccc') == [8]


def test_orden_por_margen_deja_sin_margen_al_final():
    o = lambda m: [f['fila'] for f in _js('cpOrdenar(D.f,D.m,"contado")', {'f': FILAS, 'm': m})]
    assert o('margen_asc') == [8, 7, 10, 6, 9] and o('margen_desc') == [6, 10, 7, 8, 9] and o('excel') == [6, 7, 8, 9, 10]
    assert o('sku')[:4] == [6, 7, 8, 10] and o('sku')[-1] == 9


def test_color_del_margen():
    c = lambda m: _js('cpClaseMargen(D.m,D.o)', {'m': m, 'o': 20})
    assert c(None) == 'var(--text3)' and c(-1) == 'var(--red)' and c(10) == 'var(--yellow)' and c(20) == 'var(--green)'
