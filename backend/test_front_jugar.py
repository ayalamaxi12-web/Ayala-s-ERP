"""Simulador "Jugar mi precio" de Análisis de Competencia (docs/index.html): precio por forma de venta, cantidad, combos, margen objetivo y rivales por vendedor.
Lógica pura extraída del HTML y corrida en node; el margen se compara contra el motor oficial (`precio_a_margen` / `margen_a_precio`). Se saltea sin node."""
import json
import os
import shutil
import subprocess
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scripts'))
import paridad_margenes as pm  # noqa: E402
from rentabilidad.motor_precios import EntradaMotor, margen_a_precio, precio_a_margen  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which('node'), reason='sin node')
INDEX = pm.INDEX
FUNS = ('cfgN', 'compExtraFijo', 'ofmPorTramo', 'mlEnvioRegla', 'mlMargenUnico', 'compMargenAt', 'acNormBusq', 'acComparable', 'acPrecioParaIgualar', 'acFormas', 'acPrecioUnit', 'acLinea', 'acRolRank',
        'acJugarCalcular', 'acPrecioParaMargen')


def _js(caso):
    src = open(INDEX, encoding='utf-8').read()
    fns = '\n'.join(pm.extraer_funcion(src, n) for n in FUNS)
    tramos = [[float(t['hasta']), float(t['valor'])] for t in pm.tramos_costo_fijo_ml(pm.parametros_seed()) if t['hasta'] is not None] + [[None, 0]]
    cuotas = {'reducida': 5, 'planes': pm.planes_ml_js()}
    js = ("global.window={COMPDESC:{orden:" + ("true" if caso.get("con_orden") else "false") + "}};const CRIT_ML={comision:15.5,iibb:5,cheque:1.2,orden:149.12};const ML_COSTO_ORDEN=149.12;global.qs=()=>null;global.S={shippingThreshold:33000,shippingCost:8500};const ML_COSTO_FIJO={tramos:" + json.dumps(tramos) + "};"
          "const AC={skuPorKey:{}};const AC_ROL_ORDEN={Rey:0,Media:1,Barato:2};\n" + fns +
          "\nconst c=JSON.parse(process.argv[1]);const pmd=c.pm||{};const ctx={margenAt:compMargenAt,cuotas:c.cuotas,umbral:33000,envio:8500,tc:1000,pm:pmd,"
          "iva:(sku,p)=>(c.ivas||{})[sku.toLowerCase()]||(p&&p.iva)||1.21,costoUsd:sku=>(c.costos||{})[sku.toLowerCase()]||0};"
          "let out;if(c.op==='calcular')out=acJugarCalcular(c.f,c.sim,ctx);else if(c.op==='igualar')out=c.args.map(a=>acPrecioParaIgualar(a[0],a[1],ctx));"
          "else if(c.op==='comparable')out=c.args.map(a=>acComparable(a[0],a[1],ctx));else if(c.op==='margen')out=c.args.map(a=>acPrecioParaMargen(a[0],a[1],a[2],a[3],ctx));"
          "console.log(JSON.stringify(out));")
    return json.loads(subprocess.run(['node', '-e', js, json.dumps(dict(caso, cuotas=cuotas))], capture_output=True, text=True, check=True).stdout)


def _fila(**k):
    base = {'sku': 'PV-1', 'key': 'pv-1', 'costoUsd': 10, 'iva': 1.21, 'pmML': 30000, 'Rey': [], 'Media': [], 'Barato': [], 'Otros': []}
    return dict(base, **k)


def _sim(**k):
    return dict({'q': 0, 'px': {}, 'extra': [], 'rivalCombo': 0}, **k)


def _ref(i, rol, precio, cant=1, ent=None):
    return {'id': i, 'rol': rol, 'entidad': ent or 'E' + i, 'precio': precio, 'cantidad': cant}


def _motor(precio, costo, iva, plan, envio=8500):
    return float(precio_a_margen(Decimal(str(precio)), EntradaMotor(canal='ML', costo=Decimal(str(costo)), iva_factor=Decimal(str(iva)), plan=plan, envio=Decimal(envio)),
                                 pm.parametros_seed()).margen)


PLANES = {'contado': None, 'reducida': 'reducida', '3': '3', '6': '6', '9': '9', '12': '12'}


@pytest.mark.parametrize('X,iva', [(9000, 1.21), (20000, 1.21), (28000, 1.105), (33000, 1.21), (80000, 1.105)])
def test_margen_por_forma_de_venta_con_el_mismo_precio_coincide_con_el_motor(X, iva):
    r = _js({'op': 'calcular', 'f': _fila(iva=iva), 'sim': _sim(px={'contado': X})})
    assert [f['id'] for f in r['formas']] == list(PLANES) and r['ok']
    for fm in r['formas']:
        assert abs(fm['m'] - _motor(X, 10000, iva, PLANES[fm['id']])) < 1e-4 and fm['T'] == X


def test_sin_precio_propio_las_formas_siguen_al_contado_y_este_al_pm():
    r = _js({'op': 'calcular', 'f': _fila(), 'sim': _sim()})
    assert r['x0'] == 30000 and all(f['x'] == 30000 and f['propio'] is False for f in r['formas'])
    r = _js({'op': 'calcular', 'f': _fila(), 'sim': _sim(px={'contado': 25000})})
    assert all(f['x'] == 25000 for f in r['formas'])


def test_precio_distinto_por_forma_cada_una_con_el_motor_a_SU_precio():
    px = {'contado': 20000, '6': 24000, '12': 27000}
    r = _js({'op': 'calcular', 'f': _fila(), 'sim': _sim(px=px)})
    por = {f['id']: f for f in r['formas']}
    assert [por[k]['x'] for k in ('contado', 'reducida', '3', '6', '9', '12')] == [20000, 20000, 20000, 24000, 20000, 27000]
    assert por['6']['propio'] and not por['3']['propio']
    for k, plan in (('contado', None), ('3', '3'), ('6', '6'), ('12', '12')):
        assert abs(por[k]['m'] - _motor(por[k]['x'], 10000, 1.21, plan)) < 1e-4


def test_cantidad_N_multiplica_precio_y_costo_y_escala_al_rival_a_igual_cantidad():
    f = _fila(Rey=[_ref('A', 'Rey', 24990, 1, 'GEOTEK')], Barato=[_ref('B', 'Barato', 52000, 2, 'ELEPHANT')])
    r = _js({'op': 'calcular', 'f': f, 'sim': _sim(q=2, px={'contado': 20000})})
    c = r['formas'][0]
    assert r['qm'] == 2 and c['T'] == 40000 and abs(c['m'] - _motor(40000, 20000, 1.21, None)) < 1e-4           # margen del pack: precio y costo × 2
    a, b = r['rivales'][0], r['rivales'][1]
    assert a['entidad'] == 'GEOTEK' and a['su'] == 49980 and a['mio'] == 48500 and a['masBarato'] is False        # su ×1 escalado a ×2 vs mi ×2 (+ envío desde $33.000)
    assert b['entidad'] == 'ELEPHANT' and b['su'] == 52000 and b['mio'] == 48500
    auto = _js({'op': 'calcular', 'f': f, 'sim': _sim(px={'contado': 20000})})
    assert auto['rivales'][0]['mio'] == 20000 and auto['rivales'][1]['mio'] == 48500                               # auto: cada rival a SU cantidad (como antes)


def test_el_caso_del_usuario_mi_1_unidad_contra_su_pack_x2_ya_no_parece_ganar():
    f = _fila(Barato=[_ref('B', 'Barato', 52000, 2, 'ELEPHANT')])
    una = _js({'op': 'calcular', 'f': f, 'sim': _sim(q=1, px={'contado': 30000})})['rivales'][0]
    assert una['su'] == 26000 and una['mio'] == 30000 and una['masBarato'] is True       # a 1 unidad, su unidad sale 26.000: me gana (antes parecía que yo ganaba)


def test_combo_suma_precios_costos_y_usa_iva_ponderado():
    f = _fila(pmML=20000)
    ivas = {'pv-2': 1.105}
    r = _js({'op': 'calcular', 'f': f, 'sim': _sim(px={'contado': 20000}, extra=[{'key': 'pv-2', 'q': 2, 'x': 0}]),
             'pm': {'pv-2': {'ml': 15000}}, 'costos': {'pv-2': 6}, 'ivas': ivas})
    c = r['formas'][0]
    T = 20000 + 2 * 15000
    neto = 20000 / 1.21 + 2 * 15000 / 1.105
    assert r['combo'] and c['T'] == T and r['costoTot'] == (10 + 2 * 6) * 1000
    assert abs(c['m'] - _motor(T, 22000, T / neto, None)) < 1e-4
    assert r['rivales'] == [] and r['extras'][0]['sku'] == 'PV-2' and r['extras'][0]['x'] == 15000


def test_combo_contra_el_combo_del_rival_cargado_a_mano():
    r = _js({'op': 'calcular', 'f': _fila(), 'sim': _sim(px={'contado': 20000}, extra=[{'key': 'pv-2', 'q': 1, 'x': 14000}], rivalCombo=30000),
             'pm': {'pv-2': {'ml': 15000}}, 'costos': {'pv-2': 6}})
    rc = r['rivalCombo']
    assert rc['mio'] == 34000 + 8500 and rc['masBarato'] is True and round(rc['difPct'], 1) == -29.4     # 34.000 ≥ $33.000: mi comparable suma el envío, como siempre
    assert rc['igualarX'] == 16000                                           # para igualar 30.000 con el otro SKU a 14.000, este tiene que ir a 16.000


def test_sin_costo_en_un_sku_del_combo_no_inventa_margen():
    r = _js({'op': 'calcular', 'f': _fila(), 'sim': _sim(px={'contado': 20000}, extra=[{'key': 'pv-2', 'q': 1, 'x': 0}]), 'pm': {'pv-2': {'ml': 15000}}, 'costos': {}})
    assert r['sinCosto'] is True and all(f['m'] is None for f in r['formas'])


def test_rivales_cuentan_vendedores_unicos_no_publicaciones():
    muchas = [_ref(f'A{i}', '' if i else 'Barato', 20000 + i * 100, 1, 'GEOTEK') for i in range(12)]
    f = _fila(Barato=muchas[:1], Otros=muchas[1:] + [_ref('B', '', 40000, 1, 'ELEPHANT'), _ref('C', '', 15000, 1, ' Tecno vibe '), _ref('C2', '', 14000, 1, 'tecnovibe')])
    r = _js({'op': 'calcular', 'f': f, 'sim': _sim(px={'contado': 30000})})
    assert r['pubs'] == 15 and r['total'] == 3                               # 15 publicaciones, 3 vendedores (GEOTEK ×12, ELEPHANT, Tecnovibe ×2 aunque se escriba distinto)
    assert r['masBaratos'] == 2                                              # GEOTEK (20.000) y Tecnovibe (14.000) < 30.000; ELEPHANT 40.000 no
    g = next(v for v in r['rivales'] if v['entidad'] == 'GEOTEK')
    assert g['pubs'] == 12 and g['su'] == 20000 and g['rol'] == 'Barato'     # se muestra su publicación más barata y el rol más alto que tenga


@pytest.mark.parametrize('m,iva,costo,plan', [(0.15, 1.21, 8000, None), (0.25, 1.21, 8000, '6'), (0.20, 1.105, 15000, '12'), (0.30, 1.21, 40000, '3'), (0.10, 1.21, 3000, 'reducida')])
def test_precio_para_un_margen_objetivo_cumple_el_margen_y_coincide_con_el_motor(m, iva, costo, plan):
    T = _js({'op': 'margen', 'args': [[m, iva, costo, 0 if plan is None else (5 if plan == 'reducida' else pm.planes_ml_js()[plan]), None]]})[0]
    assert T is not None
    assert _motor(T, costo, iva, plan) >= m - 1e-6 and _motor(T - 1, costo, iva, plan) < m + 1e-4              # cumple y es (casi) el mínimo
    mot = float(margen_a_precio(Decimal(str(m)), EntradaMotor(canal='ML', costo=Decimal(str(costo)), iva_factor=Decimal(str(iva)), plan=plan, envio=Decimal(8500)),
                                pm.parametros_seed(), redondear=False).precio)
    assert abs(T - mot) <= 1 or _motor(T, costo, iva, plan) >= m                   # y no se aleja del motor oficial (si hay dos soluciones por los tramos, el nuestro es el más bajo)


def test_margen_imposible_o_sin_costo_devuelve_null():
    assert _js({'op': 'margen', 'args': [[0.99, 1.21, 8000, 0, None], [0.2, 1.21, 0, 0, None]]}) == [None, None]


@pytest.mark.parametrize('precio,c', [(9990, 1), (24990, 1), (52000, 2), (45000, 1), (99000, 3), (33000, 1), (36000, 1)])
def test_igualar_deja_mi_comparable_igual_al_del_rival_salvo_la_franja_del_umbral(precio, c):
    x = _js({'op': 'igualar', 'args': [[precio, c]]})[0]
    comp = _js({'op': 'comparable', 'args': [[x, c]]})[0]
    if 33000 <= precio < 33000 + 8500:
        assert comp < 33000
    else:
        assert abs(comp - precio) <= c


def test_comparable_suma_envio_desde_el_umbral_y_multiplica_por_cantidad():
    assert _js({'op': 'comparable', 'args': [[20000, 1], [33000, 1], [20000, 2], [10000, 2]]}) == [20000, 41500, 48500, 20000]


def test_sin_precio_pm_y_sin_precio_propio_no_calcula():
    r = _js({'op': 'calcular', 'f': _fila(pmML=None), 'sim': _sim()})
    assert r['ok'] is False
