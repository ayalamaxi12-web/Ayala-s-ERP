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
FUNS = ('cpPctValido', 'cpMargen', 'cpModificada', 'cpClaseMargen', 'cpFiltrar', 'cpValorOrden', 'cpOrdenar', 'cpTramoFijo', 'cpMargenLocal', 'cpR2',
        'cpRecalcular', 'cpPctMax', 'cpDifMargenes')


def _js(expr, datos):
    src = open(pm.INDEX, encoding='utf-8').read()
    fns = '\n'.join(pm.extraer_funcion(src, n) for n in FUNS)
    js = "const CP_PLANES=['contado','3','6','9','12'];\n" + fns + "\nconst D=JSON.parse(require('fs').readFileSync(0,'utf8'));console.log(JSON.stringify(" + expr + "));"
    return json.loads(subprocess.run(['node', '-e', js], input=json.dumps(datos), capture_output=True, text=True, check=True).stdout)


def _f(fila, sku, margen, edit=True, avisos=(), pct=5, titulo='T'):
    return {'fila': fila, 'sku': sku, 'item_id': 'MLA%d' % fila, 'titulo': titulo, 'editable': edit, 'avisos': list(avisos),
            'descuento_total_pct': pct, 'margenes': ({'contado': {'margen': margen}, '3': {'margen': (margen or 0) - 5}} if margen is not None else {})}


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


def _orden(col, dir=1, plan='contado'):
    return [f['fila'] for f in _js('cpOrdenar(D.f,D.s,D.p)', {'f': FILAS, 's': {'col': col, 'dir': dir}, 'p': plan})]


def test_orden_por_columna_en_las_dos_direcciones_con_vacios_al_final():
    assert _orden('excel') == [6, 7, 8, 9, 10] and _orden('excel', -1) == [10, 9, 8, 7, 6]
    assert _orden('margen') == [8, 7, 10, 6, 9] and _orden('margen', -1) == [6, 10, 7, 8, 9]   # el 9 no tiene margen: siempre al final
    assert _orden('c_3') == [8, 7, 10, 6, 9] and _orden('c_3', -1)[-1] == 9
    assert _orden('sku')[:4] == [6, 7, 8, 10] and _orden('sku')[-1] == 9 and _orden('sku', -1)[-1] == 9
    assert _orden('desc')[-1] == 10 and _orden('desc', -1)[0] == 10   # 10 es el de mayor descuento (pct=9 vs 5)
    assert _orden('avisos', -1)[0] == 7                                  # el único con avisos


def test_color_del_margen():
    c = lambda m: _js('cpClaseMargen(D.m,D.o)', {'m': m, 'o': 20})
    assert c(None) == 'var(--text3)' and c(-1) == 'var(--red)' and c(10) == 'var(--yellow)' and c(20) == 'var(--green)'


# ── Cálculo local: el margen al jugar el descuento sale de la misma cuenta que el motor ──
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from decimal import Decimal  # noqa: E402
from rentabilidad import campanas_ml as cm  # noqa: E402


def _M():
    return json.loads(json.dumps(cm.params_front(pm.parametros_seed())))


CASOS = [(lista, T, meli, usd, iva, plan)
         for lista in (9905, 15999, 16000, 20000, 23999, 24000, 32999, 33000, 33001, 75303.1, 148039)
         for T in (5, 12, 30, 50)
         for meli in (0, 202.35, 2635.61)
         for usd, iva in ((2, 1.21), (20, 1.105))
         for plan in ('contado', '3', '12')
         if lista * T / 100 >= meli]


def test_margen_local_coincide_con_el_motor():
    par = pm.parametros_seed()
    tc = 1500
    entradas = [{'lista': l, 'T': T, 'meli': m, 'usd': u, 'iva': i, 'plan': p, 'com': 0.15 if l % 2 else 0.155} for l, T, m, u, i, p in CASOS]
    js = _js('D.c.map(c=>{const r=cpMargenLocal({costo_usd:c.usd,costo:c.usd*D.tc,iva:c.iva,envio:8500,comision:c.com},c.lista,c.meli,c.T,D.M,c.plan,D.tc);return r&&r.margen;})',
             {'c': entradas, 'M': _M(), 'tc': tc})
    peor = 0
    for c, local in zip(CASOS, js):
        l, T, m, u, i, p = c
        pc = Decimal(str(l)) * (1 - Decimal(T) / 100)
        pv = pc + Decimal(str(m))
        ref = cm.margen_oferta(pv, pc, p, Decimal(u) * tc, Decimal(str(i)), par, Decimal(8500), Decimal(str(l)), Decimal(str(0.15 if l % 2 else 0.155))).margen * 100
        peor = max(peor, abs(local - float(ref)))
    assert len(CASOS) > 200 and peor < 0.011, peor


def _fila_calc(**k):
    f = {'fila': 6, 'precio_original': 20000.0, 'meli_monto': 0, 'precio_pm': 19000.0, 'descuento_total_pct': 5.0, 'avisos': ['x', 'ML pide el descuento TOTAL entero entre 5 y 80: 5.5'],
         'calc': {'costo_usd': 2, 'costo': 3000, 'iva': 1.21, 'envio': 0, 'comision': 0.15}, 'margenes': {}}
    return dict(f, **k)


def test_recalcular_actualiza_precios_vendedor_y_margenes():
    f = _js('cpRecalcular(D.f,10,D.M,1500)', {'f': _fila_calc(meli_monto=100), 'M': _M()})
    assert f['descuento_total_pct'] == 10 and f['precio_cliente'] == 18000 and f['precio_vendedor'] == 18100
    assert f['seller_monto'] == 1900 and f['seller_pct'] == 9.5 and f['meli_pct'] == 0.5 and f['dif_vs_pm_pct'] == -5.26
    assert set(f['margenes']) == {'contado', '3', '6', '9', '12'} and f['avisos'] == ['x']
    ms = [f['margenes'][p]['margen'] for p in ('contado', '3', '6', '9', '12')]
    assert ms == sorted(ms, reverse=True)


def test_recalcular_sin_costo_no_inventa_margen_y_avisa_si_ml_pone_mas_que_el_total():
    f = _js('cpRecalcular(D.f,10,D.M,1500)', {'f': _fila_calc(calc=None), 'M': _M()})
    assert f['margenes'] == {} and f['precio_cliente'] == 18000
    g = _js('cpRecalcular(D.f,5,D.M,1500)', {'f': _fila_calc(meli_monto=1500), 'M': _M()})   # ML pone $1.500 y el 5% de 20.000 son $1.000
    assert g['margenes'] == {} and any('supera ese descuento total' in a for a in g['avisos'])


def test_pct_max_es_entero_cumple_el_objetivo_y_el_siguiente_no():
    f, M = _fila_calc(), _M()
    T = _js('cpPctMax(D.f,D.M,"contado",D.o,1500)', {'f': f, 'M': M, 'o': 15})
    assert isinstance(T, int) and 5 <= T <= 80
    ok = lambda t: _js('cpRecalcular(D.f,D.t,D.M,1500).margenes.contado.margen', {'f': f, 'M': M, 't': t})
    assert ok(T) >= 15 and (T == 80 or ok(T + 1) < 15)
    assert _js('cpPctMax(D.f,D.M,"contado",D.o,1500)', {'f': f, 'M': M, 'o': 99}) is None
    assert _js('cpPctMax(D.f,D.M,"contado",D.o,1500)', {'f': _fila_calc(calc=None), 'M': M, 'o': 1}) is None


def test_pct_max_del_front_coincide_con_el_del_backend():
    par = pm.parametros_seed()
    f = _fila_calc(meli_monto=202.35)
    T = _js('cpPctMax(D.f,D.M,"3",D.o,1500)', {'f': f, 'M': _M(), 'o': 12})
    ref = cm.pct_max_para_margen(20000, 202.35 / 20000 * 100, Decimal('0.12'), '3', Decimal(3000), Decimal('1.21'), par, comision=Decimal('0.15'))
    assert T == ref


def test_paridad_aleatoria_del_margen_local_con_el_motor():
    """3.000 casos al azar (lista, descuento, aporte de ML, costo, IVA, cuota, envío): el navegador nunca difiere del motor en más de 0,005 pp,
    que es el redondeo del margen a 4 decimales del motor. Igual, el valor que manda es el del backend (cpConfirmar)."""
    import random
    random.seed(11)
    par, tc = pm.parametros_seed(), 1500
    cs = []
    for _ in range(3000):
        lista = round(random.choice([random.uniform(3000, 16500), random.uniform(15000, 34000), random.uniform(30000, 250000)]), 2)
        T = random.randint(5, 80)
        meli = round(random.choice([0, 0, random.uniform(0, lista * T / 100)]), 2)
        cs.append({'lista': lista, 'T': T, 'meli': meli, 'usd': round(random.uniform(0.5, 120), 2), 'iva': random.choice([1.21, 1.105]),
                   'plan': random.choice(['contado', '3', '6', '9', '12']), 'envio': random.choice([0, 8500, 14000]),
                   'com': random.choice([0.14, 0.144, 0.15, 0.155, 0.16])})
    out = _js('D.c.map(c=>{const r=cpMargenLocal({costo_usd:c.usd,costo:c.usd*D.tc,iva:c.iva,envio:c.envio,comision:c.com},c.lista,c.meli,c.T,D.M,c.plan,D.tc);return r&&[r.margen,r.rentabilidad];})',
              {'c': cs, 'M': _M(), 'tc': tc})
    peor = peor_r = 0
    for c, (mg, rent) in zip(cs, out):
        pc = Decimal(str(c['lista'])) * (1 - Decimal(c['T']) / 100)
        pv = pc + Decimal(str(c['meli']))
        ref = cm.margen_oferta(pv, pc, c['plan'], Decimal(str(c['usd'])) * tc, Decimal(str(c['iva'])), par, Decimal(c['envio']), Decimal(str(c['lista'])), Decimal(str(c['com'])))
        peor, peor_r = max(peor, abs(mg - float(ref.margen) * 100)), max(peor_r, abs(rent - float(ref.rentabilidad)))
    assert peor < 0.0051 and peor_r < 0.0051, (peor, peor_r)


def test_diferencia_entre_dos_calculos_de_la_misma_fila():
    a = {'margenes': {'contado': {'margen': 10.0}, '3': {'margen': 5.0}}}
    b = {'margenes': {'contado': {'margen': 10.004}, '3': {'margen': 4.99}}}
    assert abs(_js('cpDifMargenes(D.a,D.b)', {'a': a, 'b': b}) - 0.01) < 1e-9
    assert _js('cpDifMargenes(D.a,D.a)', {'a': a}) == 0
    assert _js('cpDifMargenes(D.a,D.b)', {'a': a, 'b': {'margenes': {}}}) == 999   # uno tiene margen y el otro no: es una diferencia grande


# ── Ventas reales de SEW-MINI ($26.599, tramo 24.000–33.000): el envío de productos < $33.000 es $0 ──
def test_el_envio_de_productos_menores_a_33000_nunca_se_descuenta():
    par = pm.parametros_seed()
    for lista in (9905, 26599, 32999):
        r = cm.margen_oferta(Decimal(lista), Decimal(lista), 'contado', Decimal(5000), Decimal('1.21'), par, Decimal(8500), Decimal(lista))
        assert r.cargos['envio'] == 0, lista                      # aunque alguien pase un envío, por debajo del umbral no se descuenta
    assert cm.margen_oferta(Decimal(33000), Decimal(33000), 'contado', Decimal(5000), Decimal('1.21'), par, Decimal(8500), Decimal(33000)).cargos['envio'] == 8500
    # el navegador: mismo criterio
    out = _js('D.l.map(l=>{const a=cpMargenLocal({costo:5000,iva:1.21,envio:8500,comision:0.155},l,0,5,D.M,"contado",1);const b=cpMargenLocal({costo:5000,iva:1.21,envio:0,comision:0.155},l,0,5,D.M,"contado",1);return a.margen-b.margen;})',
              {'l': [9905, 26599, 32999, 33000], 'M': _M()})
    assert out[:3] == [0, 0, 0] and out[3] < 0


def test_desglose_de_las_dos_ventas_reales_de_sew_mini():
    """FULL: comisión 15%, costo fijo $3.400, envío $0, impuestos $240 → recibe $18.968.
    FLEX: comisión 15%, costo fijo $3.320, envío +$8.990 (lo paga el comprador), impuestos $321 → recibe $27.957."""
    par, p = pm.parametros_seed(), Decimal('26599')
    r = cm.margen_oferta(p, p, 'contado', Decimal(5000), Decimal('1.21'), par, Decimal(0), p, Decimal('0.15'))
    assert r.cargos['comision'] == Decimal('3989.85') and r.cargos['costo_fijo'] == Decimal('3320.00') and r.cargos['envio'] == 0
    imp = p * cm.IMPUESTOS_ML_PCT
    assert abs(float(imp) - 240) < 1                                          # impuestos de la venta Full: 0,904% de $26.599
    flex = p - r.cargos['comision'] - r.cargos['costo_fijo'] + Decimal(8990) - (p + Decimal(8990)) * cm.IMPUESTOS_ML_PCT
    assert abs(float(flex) - 27957) < 1                                       # Flex cierra con el costo fijo de la tabla
    full = p - r.cargos['comision'] - Decimal(3400) - imp
    assert abs(float(full) - 18968) < 1.5                                     # Full cierra con 3.400: $80 más que la tabla
