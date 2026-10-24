"""Ofertas ML (docs/index.html): tabla compacta, búsqueda predictiva, resumen como filtros y paginación. Lógica pura extraída del HTML y corrida en node. Se saltea sin node."""
import json
import shutil
import subprocess

import pytest

from test_front_analisis import INDEX, _fn

pytestmark = pytest.mark.skipif(not shutil.which('node'), reason='sin node')


def js(cuerpo, *funcs, extra=''):
    src = open(INDEX, encoding='utf-8').read()
    fns = '\n'.join(_fn(src, n) for n in funcs)
    out = subprocess.run(['node', '-e', "function acEsc(t){return String(t==null?'':t).replace(/&/g,'&amp;').replace(/</g,'&lt;');}\n" + extra + fns + '\n' + cuerpo], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


FILAS = [
    {'item_id': 'MLA1', 'sku': 'PV-1', 'titulo': 'Tóner Negro HP 85A', '_margen': {'margenPct': 0.05}, '_pmDiffPct': 0.2, '_alerta': None, 'incidencia': None},
    {'item_id': 'MLA2', 'sku': 'PV-12', 'titulo': 'Cartucho Canon', '_margen': {'margenPct': 0.30}, '_pmDiffPct': 5.0, '_alerta': 'sin stock', 'incidencia': None},
    {'item_id': 'MLA3', 'sku': '', 'sku_ml': 'KG-9', 'titulo': 'Teclado ÑANDÚ', '_margen': None, '_pmDiffPct': None, '_alerta': None, 'incidencia': 'sin costo'},
]
CTX = {'umbral': 10, 'tol': 1.5}


def test_busqueda_por_sku_titulo_o_mla_sin_mayusculas_ni_tildes_con_resaltado():
    f = json.dumps(FILAS)
    cuerpo = lambda q: f"const r=ofmBuscarOfertas({json.dumps(q)},{f},50);console.log(JSON.stringify([r.total,r.lista.map(x=>x.item_id)]));"
    fns = ('ofmNormTxt', 'ofmBuscarOfertas')
    assert js(cuerpo('toner'), *fns) == [1, ['MLA1']]                  # título, sin tilde ni mayúsculas
    assert js(cuerpo('nandu'), *fns) == [1, ['MLA3']]                  # Ñ y Ú
    assert js(cuerpo('mla2'), *fns) == [1, ['MLA2']]                   # MLA
    assert js(cuerpo('pv-1'), *fns) == [2, ['MLA1', 'MLA2']]           # SKU: el que empieza igual primero (PV-1 y PV-12)
    assert js(cuerpo('kg'), *fns) == [1, ['MLA3']]                     # usa sku_ml si no hay sku
    assert js(cuerpo('  '), *fns) == [0, []] and js(cuerpo('zzz'), *fns) == [0, []]
    r = js("const f=[];for(let i=0;i<120;i++)f.push({item_id:'MLA'+i,sku:'S'+i,titulo:'Producto '+i});const r=ofmBuscarOfertas('prod',f,50);console.log(JSON.stringify([r.total,r.lista.length]));", *fns)
    assert r == [120, 50]                                              # el total cuenta todas, la lista se corta en 50
    assert js("console.log(JSON.stringify(ofmResaltar('Tóner Negro','toner')))", 'ofmNormTxt', 'ofmResaltar') == '<mark>Tóner</mark> Negro'


def test_los_estados_del_resumen_filtran_y_se_combinan():
    f = json.dumps(FILAS)
    base = "const ctx={umbral:10,tol:1.5,tipoDe:x=>'X',pmDe:x=>'P',catDe:x=>'C'};"
    fns = ('ofmNormTxt', 'ofmCumpleStat', 'ofmFiltrar')
    cuerpo = lambda stat, extra='': base + f"const r=ofmFiltrar({f},{{q:'',stat:new Set({json.dumps(stat)}){extra}}},ctx);console.log(JSON.stringify(r.map(x=>x.item_id)));"
    assert js(cuerpo(['bajo']), *fns) == ['MLA1']                      # margen 5 % < umbral 10 %
    assert js(cuerpo(['dif']), *fns) == ['MLA2']                       # |5,0| > 1,5; la de 0,2 no; null no cuenta
    assert js(cuerpo(['alerta']), *fns) == ['MLA2']
    assert js(cuerpo(['incid']), *fns) == ['MLA3']
    assert js(cuerpo(['conMargen']), *fns) == ['MLA1', 'MLA2']
    assert js(cuerpo(['bajo', 'dif']), *fns) == []                     # se combinan con Y
    assert js(cuerpo([]), *fns) == ['MLA1', 'MLA2', 'MLA3']
    assert js(base + f"const r=ofmFiltrar({f},{{q:'canon',stat:new Set()}},ctx);console.log(JSON.stringify(r.map(x=>x.item_id)));", *fns) == ['MLA2']
    assert js(base.replace("tipoDe:x=>'X'", "tipoDe:x=>x.item_id==='MLA1'?'ML':'PRICE_DISCOUNT'") + f"const r=ofmFiltrar({f},{{q:'',stat:new Set(),tipo:'ML'}},ctx);console.log(JSON.stringify(r.map(x=>x.item_id)));", *fns) == ['MLA1']


def test_paginacion_de_25_con_desde_hasta_de_total():
    p = lambda t, pg, pp=25: js(f"console.log(JSON.stringify(ofmPaginar({t},{pg},{pp})))", 'ofmPaginar')
    assert p(599, 1) == {'pagina': 1, 'paginas': 24, 'desde': 1, 'hasta': 25}
    assert p(599, 24) == {'pagina': 24, 'paginas': 24, 'desde': 576, 'hasta': 599}
    assert p(599, 99)['pagina'] == 24 and p(599, 0)['pagina'] == 1     # se mantiene dentro del rango
    assert p(0, 1) == {'pagina': 1, 'paginas': 1, 'desde': 0, 'hasta': 0}
    assert p(25, 1) == {'pagina': 1, 'paginas': 1, 'desde': 1, 'hasta': 25}


def test_el_buscador_es_un_combobox_y_el_resumen_son_botones():
    s = open(INDEX, encoding='utf-8').read()
    for a in ('id="ofm-search" role="combobox" aria-expanded="false" aria-controls="ofm-sug" aria-autocomplete="list"', 'id="ofm-sug" class="ofm-sug" role="listbox"', 'role="option"', 'aria-activedescendant'):
        assert a in s, a
    assert s.count('class="stat-card" data-stat=') == 6 and 'aria-pressed="false" onclick="ofmStatToggle(' in s
    assert 'id="ofm-chips"' in s and 'Limpiar filtros' in s and 'id="ofm-pag"' in s and '<div class="ofm-card' not in s.split('function ofmRender()')[1].split('// Búsqueda predictiva')[0]
    assert 'ofm-filter-bajo-umbral' not in s and 'ofm-filter-dif-pm' not in s          # ahora son los botones del resumen
