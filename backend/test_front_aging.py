"""Ventas & Rentabilidad (docs/index.html): filtros «Aging» (SKUs de stock a liquidar) y «Resultado» (con / sin pérdida), independientes entre sí."""
import json
import os
import shutil
import subprocess

import pytest

from scripts.paridad_margenes import extraer_funcion

INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'docs', 'index.html')
pytestmark = pytest.mark.skipif(not shutil.which('node'), reason='sin node')
FNS = ('normSku', 'agingKey', 'dashEsAging', 'dashEsPerdida', '_dashData', '_dashFilters', 'getFiltered')


def js(cuerpo, datos):
    src = open(INDEX, encoding='utf-8').read()
    base = ('let AGING_SKUS=new Set(),allSalesData=[],vivoSalesData=[],activeFilters={},vivoFilters={},vivoCompare={};\n'
            + '\n'.join(extraer_funcion(src, n) for n in FNS) + '\nconst D=JSON.parse(process.argv[1]);\n')
    return json.loads(subprocess.run(['node', '-e', base + cuerpo, json.dumps(datos)], capture_output=True, text=True, check=True).stdout)


def v(num, skus, rent, fecha='2026-11-10'):
    return {'numOrden': num, 'skus': skus, 'rentabilidad': rent, 'fechaStr': fecha, 'canal': 'ML', 'categoria': 'C', 'pm': 'Laura'}


# 1 renta con aging a pérdida · 2 renta común a pérdida · 3 aging con ganancia · 4 común con ganancia · 5 combo mixto (un SKU de aging + uno común) a pérdida · 6 renta 0
VENTAS = [v('1', ['TN1060COMP'], -500), v('2', ['CF283ACOMP'], -100), v('3', ['W1105ACOMP'], 300), v('4', ['Q2612ACOMP'], 900), v('5', ['TN1060COMP', 'Q2612ACOMP'], -50), v('6', ['X'], 0)]
AGING = ['tn1060comp', 'W1105ACOMP']                                  # el listado de aging: se compara sin distinguir mayúsculas


def ordenes(aging, res):
    cuerpo = ('AGING_SKUS=new Set(D.a.map(agingKey));allSalesData=D.v;activeFilters={aging:D.f,resultado:D.r};'
              'console.log(JSON.stringify(getFiltered("hist").data1.map(x=>x.numOrden)))')
    return js(cuerpo, {'a': AGING, 'v': VENTAS, 'f': aging, 'r': res})


def test_sin_filtros_estan_todas():
    assert ordenes('todos', 'todos') == ['1', '2', '3', '4', '5', '6']


def test_solo_aging_y_sin_aging_se_reparten_las_ventas_sin_perderse_ninguna():
    solo, sin = ordenes('solo', 'todos'), ordenes('sin', 'todos')
    assert solo == ['1', '3', '5']                                      # alguno de sus SKU es de aging (el combo mixto también)
    assert sin == ['2', '4', '6']
    assert sorted(solo + sin) == ['1', '2', '3', '4', '5', '6']


def test_resultado_con_perdida_es_estrictamente_menor_a_cero_y_sin_perdida_es_el_resto():
    assert ordenes('todos', 'con') == ['1', '2', '5']
    assert ordenes('todos', 'sin') == ['3', '4', '6']                   # la de rentabilidad 0 no es pérdida


def test_aging_y_resultado_se_combinan_son_cosas_distintas():
    assert ordenes('solo', 'con') == ['1', '5']                         # aging que dio pérdida
    assert ordenes('sin', 'con') == ['2']                               # a pérdida SIN estar contemplada: lo que hay que mirar
    assert ordenes('solo', 'sin') == ['3']
    assert ordenes('sin', 'sin') == ['4', '6']                          # la renta general «sana»: sin aging y sin pérdida


def test_sin_listado_de_aging_nada_es_aging():
    r = js('allSalesData=D.v;activeFilters={aging:"solo"};const a=getFiltered("hist").data1.length;activeFilters={aging:"sin"};console.log(JSON.stringify([a,getFiltered("hist").data1.length]))',
           {'v': VENTAS})
    assert r == [0, 6]


def test_el_aging_ignora_espacios_y_mayusculas_en_los_sku():
    r = js('AGING_SKUS=new Set(D.a.map(agingKey));console.log(JSON.stringify(D.v.map(dashEsAging)))',
           {'a': ['choppsub-gls-frost-blue-16oz'], 'v': [{'skus': ['CHOPPSUB-GLS-FROST-BLUE -16OZ']}, {'skus': ['OTRO']}]})
    assert r == [True, False]
