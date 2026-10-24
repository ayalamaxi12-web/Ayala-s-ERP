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
    fns = '\n'.join(_fn(src, n) for n in ('acNormBusq', 'acSugerencias', 'acComparable', 'acAgregar', 'acArmar', 'acFiltrar', 'acOrdenar'))
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


def _sug(q, skus, maxn=10):
    src = open(INDEX, encoding='utf-8').read()
    fns = '\n'.join(_fn(src, n) for n in ('acNormBusq', 'acSugerencias'))
    js = fns + "\nconsole.log(JSON.stringify(acSugerencias(process.argv[1],JSON.parse(process.argv[2]).map(s=>({sku:s})),Number(process.argv[3])).map(f=>f.sku)));"
    return json.loads(subprocess.run(['node', '-e', js, q, json.dumps(skus), str(maxn)], capture_output=True, text=True, check=True).stdout)


def test_sugerencias_del_buscador_ignoran_guiones_espacios_y_mayusculas_y_ordenan_exacto_prefijo_contiene():
    skus = ['PV-120', 'PV-12', 'XPV-12B', 'PV-1', 'KG002BK', 'pv-125']
    assert _sug('pv12', skus) == ['PV-12', 'PV-120', 'pv-125', 'XPV-12B']       # exacto, luego por prefijo, luego "contiene"
    assert _sug('PV 12', skus)[0] == 'PV-12' and _sug('pv-1', skus)[0] == 'PV-1'
    assert _sug('kg00', skus) == ['KG002BK'] and _sug('zzz', skus) == [] and _sug('', skus) == [] and _sug('  ', skus) == []
    assert len(_sug('pv', [f'PV-{i}' for i in range(30)], 8)) == 8


def test_el_filtro_por_sku_tambien_ignora_guiones_y_espacios():
    assert [x['sku'] for x in correr(D, {'search': 'pv1'})] == ['PV-1'] and [x['sku'] for x in correr(D, {'search': 'PV 3'})] == ['PV-3']


def test_orden_por_cambio_y_por_diferencia():
    assert [x['sku'] for x in correr(D, {}, 'cambio')][0] == 'PV-1'
    assert [x['sku'] for x in correr(D, {}, 'dif')][:2] == ['PV-2', 'PV-1']      # PV-2 es la que más barato nos tiene (-63%); PV-3 (sin dato) al final


def _vend(q, lista):
    src = open(INDEX, encoding='utf-8').read()
    fns = '\n'.join(_fn(src, n) for n in ('acNormTxt', 'acBuscarVendedores', 'acResaltar')) + "\nfunction acEsc(t){return String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;');}"
    js = fns + "\nconst r=acBuscarVendedores(process.argv[1],JSON.parse(process.argv[2]));console.log(JSON.stringify(r.map(x=>[x.v,acResaltar(x.v,x.i,x.n)])));"
    return json.loads(subprocess.run(['node', '-e', js, q, json.dumps(lista)], capture_output=True, text=True, check=True).stdout)


def test_buscador_de_vendedores_coincide_en_cualquier_parte_sin_mayusculas_ni_tildes_y_resalta():
    lista = ['Tecnología Sur', 'Técnico Norte', 'Distribuidora Ñandú', 'ElectroHogar', 'Mundo Tóner', 'PC Store']
    assert [x[0] for x in _vend('TEC', lista)] == ['Técnico Norte', 'Tecnología Sur']          # mayúsculas y tildes no importan; sin tope de resultados
    assert [x[0] for x in _vend('nandu', lista)] == ['Distribuidora Ñandú']                       # Ñ y ú
    assert [x[0] for x in _vend('hogar', lista)] == ['ElectroHogar']                              # cualquier parte del nombre, no solo el comienzo
    assert _vend('tecnologia', lista)[0][1] == '<mark>Tecnología</mark> Sur'                      # resalta con el texto original (con tilde)
    assert _vend('  ', lista) == [] and _vend('zzz', lista) == []
    assert len(_vend('a', [f'Vend {i}' for i in range(60)] + ['Alfa'])) == 1                       # sin tope: todos los que coinciden
    assert [x[0] for x in _vend('o', ['Zeta', 'Oro', 'Boa'])] == ['Oro', 'Boa']                  # primero los que empiezan con lo escrito


def test_el_buscador_y_el_filtro_de_vendedores_son_accesibles_y_no_quedan_botones_fijos():
    s = open(INDEX, encoding='utf-8').read()
    for a in ('role="combobox"', 'aria-expanded="false"', 'aria-controls="ac-sug"', 'aria-autocomplete="list"', 'id="ac-sug" class="ac-sug" role="listbox"'):
        assert a in s, a
    assert 'role="option"' in s and 'aria-activedescendant' in s and "Ver todos los vendedores" in s and 'aria-controls="ac-vend-panel"' in s
    assert 'Limpiar vendedores' in s and 'Mostrando solo los SKU de' in s and 'acVendBtns' not in s
