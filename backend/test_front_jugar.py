"""Simulador "Jugar mi precio" de la pantalla Análisis de Competencia (docs/index.html: acComparable / acPrecioParaIgualar / acJugarCalcular).
Lógica pura extraída del HTML y corrida en node; el margen se compara contra el motor oficial (`precio_a_margen`, con plan = cuota). Se saltea sin node."""
import json
import os
import shutil
import subprocess
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scripts'))
import paridad_margenes as pm  # noqa: E402
from rentabilidad.motor_precios import EntradaMotor, precio_a_margen  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which('node'), reason='sin node')
INDEX = pm.INDEX


def _js(caso):
    src = open(INDEX, encoding='utf-8').read()
    fns = '\n'.join(pm.extraer_funcion(src, n) for n in ('cfgN', 'compExtraFijo', 'compMargenAt', 'acComparable', 'acPrecioParaIgualar', 'acJugarCalcular'))
    tramos = [[float(t['hasta']), float(t['valor'])] for t in pm.tramos_costo_fijo_ml(pm.parametros_seed()) if t['hasta'] is not None] + [[None, 0]]
    cuotas = {'reducida': 5, 'planes': pm.planes_ml_js()}
    js = ("global.window={};global.qs=()=>null;global.S={shippingThreshold:33000,shippingCost:8500};const ML_COSTO_FIJO={tramos:" + json.dumps(tramos) + "};\n" + fns +
          "\nconst c=JSON.parse(process.argv[1]);const ctx={margenAt:compMargenAt,cuotas:c.cuotas,umbral:33000,envio:8500,tc:c.tc};"
          "console.log(JSON.stringify(c.op==='calcular'?acJugarCalcular(c.f,c.X,ctx):c.op==='igualar'?c.args.map(a=>acPrecioParaIgualar(a[0],a[1],ctx)):c.args.map(a=>acComparable(a[0],a[1],ctx))));")
    return json.loads(subprocess.run(['node', '-e', js, json.dumps(dict(caso, cuotas=cuotas, tc=1000))], capture_output=True, text=True, check=True).stdout)


def _fila(**k):
    base = {'sku': 'PV-1', 'costoUsd': 10, 'iva': 1.21, 'pmML': 30000, 'Rey': [], 'Media': [], 'Barato': [], 'Otros': []}
    return dict(base, **k)


def _ref(i, rol, precio, cant=1):
    return {'id': i, 'rol': rol, 'entidad': 'E' + i, 'precio': precio, 'cantidad': cant}


@pytest.mark.parametrize('X,iva', [(9000, 1.21), (20000, 1.21), (28000, 1.105), (33000, 1.21), (80000, 1.105)])
def test_margen_por_forma_de_pago_coincide_con_el_motor(X, iva):
    r = _js({'op': 'calcular', 'f': _fila(iva=iva), 'X': X})
    par = pm.parametros_seed()
    esperado = {'Contado': None, 'Reducida': 'reducida', '3c': '3', '6c': '6', '9c': '9', '12c': '12'}
    filas = {'Contado': r['contado']} | {p['label']: p for p in r['planes']}
    for label, plan in esperado.items():
        mot = precio_a_margen(Decimal(X), EntradaMotor(canal='ML', costo=Decimal(10000), iva_factor=Decimal(str(iva)), plan=plan, envio=Decimal(8500)), par)
        assert abs(filas[label]['m'] - float(mot.margen)) < 1e-4, (label, X)


def test_desglose_cierra_y_sin_costo_o_sin_tc_no_inventa_margen():
    r = _js({'op': 'calcular', 'f': _fila(), 'X': 20000})
    d = r['contado']['d']
    assert abs(d['neto'] - d['com'] - d['extra'] - d['envio'] - d['iibb'] - d['impch'] - d['costo'] - r['contado']['mars']) < 0.01
    sc = _js({'op': 'calcular', 'f': _fila(costoUsd=0), 'X': 20000})
    assert sc['sinCosto'] is True and sc['contado']['m'] is None and all(p['m'] is None for p in sc['planes'])
    assert _js({'op': 'calcular', 'f': _fila(), 'X': 0})['ok'] is False


def test_comparable_suma_envio_desde_el_umbral_y_multiplica_por_cantidad():
    assert _js({'op': 'comparable', 'args': [[20000, 1], [33000, 1], [20000, 2], [10000, 2]]}) == [20000, 41500, 48500, 20000]


@pytest.mark.parametrize('precio,c', [(9990, 1), (24990, 1), (52000, 2), (45000, 1), (99000, 3), (33000, 1), (36000, 1)])
def test_igualar_deja_mi_comparable_igual_al_del_rival_salvo_la_franja_del_umbral(precio, c):
    x = _js({'op': 'igualar', 'args': [[precio, c]]})[0]
    comp = _js({'op': 'comparable', 'args': [[x, c]]})[0]
    if 33000 <= precio < 33000 + 8500:      # franja sin solución exacta: queda por debajo del umbral
        assert comp < 33000
    else:
        assert abs(comp - precio) <= c      # como mucho el redondeo de la división por la cantidad


def test_rivales_posicion_y_diferencias():
    f = _fila(Rey=[_ref('A', 'Rey', 24990)], Barato=[_ref('B', 'Barato', 52000, 2)], Otros=[_ref('C', '', 0)])
    r = _js({'op': 'calcular', 'f': f, 'X': 30000})
    assert [v['id'] for v in r['rivales']] == ['A', 'B'] and r['masBaratos'] == 2          # la de precio 0 no se compara
    a, b = r['rivales']
    assert a['mio'] == 30000 and round(a['difPct'], 1) == -16.7 and a['masBarato'] is True
    assert b['mio'] == 68500 and b['igualar'] == 21750
    r2 = _js({'op': 'calcular', 'f': f, 'X': 21000})
    assert r2['masBaratos'] == 0
