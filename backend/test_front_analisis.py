"""Lógica de la pantalla Análisis de Competencia (docs/index.html: acArmar / acFiltrar / acOrdenar). Se extrae del HTML y corre en node; se saltea si no hay node."""
import json
import os
import re
import shutil
import subprocess

import pytest

INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'docs', 'index.html')
pytestmark = pytest.mark.skipif(not shutil.which('node'), reason='sin node')


def _fn(src, nombre):
    i = src.index(f'function {nombre}(')
    j = src.index('{', i)
    n = 0
    for k in range(j, len(src)):
        n += (src[k] == '{') - (src[k] == '}')
        if n == 0:
            return src[i:k + 1]


def correr(D, filtros, orden='sku'):
    src = open(INDEX, encoding='utf-8').read()
    fns = '\n'.join(_fn(src, n) for n in ('acComparable', 'acAgregar', 'acArmar', 'acFiltrar', 'acOrdenar'))
    js = fns + """
const D=JSON.parse(process.argv[1]),F=JSON.parse(process.argv[2]);F.vend=new Set(F.vend||[]);
// margenAt de prueba: margen = (precio/iva - costoARS)/(precio/iva): suficiente para ver que se llama con el precio y el costo correctos
const ctx={pm:{'pv-1':{ml:10000,pmName:'Vero'},'pv-2':{ml:50000,pmName:'Mati'}},cat:s=>({'pv-1':'Toners','pv-2':'Tintas'}[s.toLowerCase()]||''),
 costoUsd:s=>({'pv-1':5,'pv-2':0}[s.toLowerCase()]||0),iva:()=>1.21,tc:1000,margenAt:(p,i,c)=>({m:(p/i-c)/(p/i)}),umbral:33000,envio:8500,normSku:s=>String(s||'').trim().toLowerCase()};
const filas=acOrdenar(acFiltrar(acArmar(D,ctx),F),process.argv[3]);
console.log(JSON.stringify(filas.map(f=>({sku:f.sku,cat:f.cat,pm:f.pmName,mgActual:f.mgActual,Rey:f.Rey.map(r=>[r.id,r.precio,r._mi,r._diff,r._mg,r._cambioHoy]),Media:f.Media.map(r=>r.id),Barato:f.Barato.map(r=>r.id),Otros:f.Otros.map(r=>r.id)}))));
"""
    out = subprocess.run(['node', '-e', js, json.dumps(D), json.dumps(filtros), orden], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def ref(i, sku, ent, rol, precio, ant=None, desde=None, cant=1):
    u = {'fecha': '2026-10-10', 'precio': precio} if precio else None
    return {'id': i, 'sku': sku, 'entidad': ent, 'rol': rol, 'cantidad': cant, 'link': f'https://x/{i}', 'ultimo': u,
            'anterior': {'fecha': '2026-10-09', 'precio': ant} if ant else None, 'delta_pct': round((precio - ant) / ant * 100, 2) if ant and precio else None,
            'desde': desde or ('2026-10-10' if ant and precio and ant != precio else '2026-10-01'), 'ganador': None, 'ultima_lectura': None, 'serie': []}


D = {'referencias': [ref('A', 'PV-1', 'GEOTEK', 'Rey', 9000, 10000), ref('B', 'PV-1', 'TECNO', 'Barato', 12100, 12100), ref('C', 'PV-1', 'OTRO', '', 8000),
                     ref('D', 'PV-2', 'GEOTEK', 'Rey', 40000, cant=2), ref('E', 'PV-3', 'GEOTEK', 'Media', None)]}


def test_arma_roles_diferencia_y_margen_si_igualo():
    f = correr(D, {})
    pv1 = next(x for x in f if x['sku'] == 'PV-1')
    assert [r[0] for r in pv1['Rey']] == ['A'] and pv1['Media'] == [] and pv1['Barato'] == ['B'] and pv1['Otros'] == ['C']      # rol vacío -> Otros
    rey = pv1['Rey'][0]
    assert rey[2] == 10000 and round(rey[3], 2) == -10.0                         # nuestro 10.000 vs 9.000
    assert round(rey[4], 4) == round((9000 / 1.21 - 5000) / (9000 / 1.21), 4)    # margen si igualo: precio del rival, costo 5 USD × TC 1000
    assert rey[5] is True                                                         # cambió en la última lectura (bajó de 10.000)
    assert round(pv1['mgActual'], 4) == round((10000 / 1.21 - 5000) / (10000 / 1.21), 4)


def test_kit_compara_contra_nuestro_precio_por_cantidad_mas_envio_y_sin_costo_no_hay_margen():
    pv2 = next(x for x in correr(D, {}) if x['sku'] == 'PV-2')
    r = pv2['Rey'][0]
    assert r[2] == 100000 + 8500 and round(r[3], 2) == round((40000 - 108500) / 108500 * 100, 2)   # 50.000 × 2 = 100.000 ≥ 33.000: + envío
    assert r[4] is None and pv2['mgActual'] is None                              # PV-2 no tiene costo: sin margen (no inventa)


def test_sku_sin_pm_ni_categoria_y_ref_sin_precio():
    pv3 = next(x for x in correr(D, {}) if x['sku'] == 'PV-3')
    assert pv3['cat'] == 'Sin categoría' and pv3['pm'] == 'Sin PM' and pv3['Media'] == ['E']


def test_filtros_vendedor_categoria_pm_buscador_y_solo_cambios():
    assert [x['sku'] for x in correr(D, {'vend': ['TECNO']})] == ['PV-1'] and correr(D, {'vend': ['TECNO']})[0]['Rey'] == []   # solo se ven las refs de TECNO
    assert [x['sku'] for x in correr(D, {'cats': ['Tintas']})] == ['PV-2']
    assert [x['sku'] for x in correr(D, {'pms': ['Vero']})] == ['PV-1']
    assert [x['sku'] for x in correr(D, {'search': 'pv-3'})] == ['PV-3']
    assert [x['sku'] for x in correr(D, {'search': 'tecno'})] == ['PV-1']        # también busca por vendedor
    assert [x['sku'] for x in correr(D, {'soloCambios': True})] == ['PV-1']
    assert [x['sku'] for x in correr(D, {'soloGanan': True})] == ['PV-1', 'PV-2']   # PV-3 sin PM/precio: no se puede decir que nos ganan


def test_orden_por_cambio_y_por_diferencia():
    assert [x['sku'] for x in correr(D, {}, 'cambio')][0] == 'PV-1'
    assert [x['sku'] for x in correr(D, {}, 'dif')][:2] == ['PV-2', 'PV-1']      # PV-2 es la que más barato nos tiene (-63%); PV-3 (sin dato) al final
