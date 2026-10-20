"""3.3 Vista por categoría (docs/index.html: acCategoriasArmar / acCatOrdenar / acTiendaHtml / acCatHtml). Lógica y HTML extraídos del HTML y corridos en node con datos
SINTÉTICOS; se saltea sin node."""
import json
import re
import shutil
import subprocess

import pytest

from test_front_analisis import INDEX, _fn

pytestmark = pytest.mark.skipif(not shutil.which('node'), reason='sin node')
FUNS = ('acCatDiag', 'acPl', 'acCatDiagHtml', 'acMediana', 'acCatSkus', 'acTiendaConteo', 'acRolRank', 'acCategoriasArmar', 'acCatOrdenar', 'acPctAR', 'acTiendaFilaHtml', 'acTiendasPanelHtml', 'acCatHtml', 'acEsc', 'acFechaCorta', 'fmt$')


def js(cuerpo, datos):
    s = open(INDEX, encoding='utf-8').read()
    iconos = s[s.index('// ICONOS-INICIO'):s.index('// ICONOS-FIN')]
    src = iconos + '\n'.join(_fn(s, n) for n in FUNS) + '\n' + re.search(r"const AC_ROL_ORDEN=\{.*?\};", s).group(0)
    codigo = src + "\nconst X=JSON.parse(process.argv[1]);const norm=s=>String(s||'').trim().toLowerCase();global.AC={catAb:{}};\n" + cuerpo
    return json.loads(subprocess.run(['node', '-e', codigo, json.dumps(datos)], capture_output=True, text=True, check=True).stdout)


def r(precio, diff, cant=1, cambio=False):
    return {'precio': precio, '_diff': diff, 'cantidad': cant, '_cambioHoy': cambio}


def fila(sku, rey=(), media=(), barato=()):
    f = {'key': sku.lower(), 'sku': sku, 'Rey': list(rey), 'Media': list(media), 'Barato': list(barato), 'Otros': []}
    f['refs'] = f['Rey'] + f['Media'] + f['Barato']
    return f


def cat(sub, rol, ent, eid, skus='', desact=False):
    return {'subcategoria': sub, 'rol': rol, 'entidad': ent, 'entidad_id': eid, 'slug': ent.lower(), 'skus_nuestros': skus, 'actualizado': '2026-10-20', 'desactualizada': desact}


def tienda(eid, ent, leidas, mediana=None, var=None, completa=True, nuevas=None, desap=None, motivo='', deb=''):
    return {'entidad_id': eid, 'entidad': ent, 'ultimo': {'fecha': '2026-10-20', 'leidas': leidas, 'declaradas': leidas, 'completa': completa, 'motivo': motivo,
                                                          'mediana_7d': mediana, 'var_pct': var, 'estado_debilidad': deb, 'nuevas': nuevas, 'desaparecidas': desap}, 'serie': []}


D = {'categorias': [cat('Toner', 'Rey', 'TIENDA A', 'E1', 'SKU-9001, sku-9002; SKU-9003'), cat('Toner', 'Media', 'TIENDA B', 'E2', 'SKU-9001, SKU-9002, SKU-9003'),
                    cat('Toner', 'Barato', 'TIENDA C', 'E3', 'SKU-9001', desact=True), cat('Tinta', 'Rey', 'TIENDA A', 'E1', 'SKU-9004'), cat('Cable', 'Rey', 'TIENDA D', '', '')],
     'tiendas': [tienda('E1', 'TIENDA A', 120, 150, '-20', nuevas=0, desap=7), tienda('E2', 'TIENDA B', 48, 118, '', completa=False, motivo='captcha'),
                 tienda('', 'tienda d', 30)]}
FILAS = [fila('SKU-9001', rey=[r(900, -10)], barato=[r(800, -20)]), fila('SKU-9002', rey=[r(1100, 5)], barato=[r(1200, 10, cant=2)]), fila('SKU-9004', rey=[r(500, -5)])]


def armar(hay=False, filas=FILAS, modo='sub'):
    return js("console.log(JSON.stringify(acCatOrdenar(acCategoriasArmar(X.D,X.filas,X.hay,norm),X.modo).map(g=>({sub:g.sub,n:g.nSkus,rows:g.rows.map(f=>f.sku),conRey:g.conRey,reyGana:g.reyGana,"
              "barMedP:g.barMedP,barMedD:g.barMedD,conBarato:g.conBarato,t:g.tiendas.map(t=>[t.rol,t.entidad,t.conteo&&t.conteo.leidas]) }))))", {'D': D, 'filas': filas, 'hay': hay, 'modo': modo})


def test_agrupa_por_subcategoria_y_cuenta_skus_y_rey():
    g = {x['sub']: x for x in armar()}
    assert list(g) == ['Cable', 'Tinta', 'Toner']                                                                   # A-Z
    t = g['Toner']
    assert t['n'] == 3 and t['rows'] == ['SKU-9001', 'SKU-9002']                                                      # SKU-9003 está en la planilla pero sin competencia cargada
    assert (t['conRey'], t['reyGana']) == (2, 1)                                                                      # solo en SKU-9001 el Rey es más barato
    assert [x[0] for x in t['t']] == ['Rey', 'Media', 'Barato']


def test_mediana_del_barato_por_unidad_y_diferencia():
    t = next(x for x in armar() if x['sub'] == 'Toner')
    assert t['conBarato'] == 2 and t['barMedP'] == (800 + 600) / 2 and t['barMedD'] == -5                              # el kit x2 de 1.200 vale 600 por unidad; difs -20 y 10
    assert next(x for x in armar() if x['sub'] == 'Cable')['barMedP'] is None


def test_conteo_de_tienda_por_id_o_por_nombre():
    g = {x['sub']: x for x in armar()}
    assert g['Toner']['t'][0][2] == 120 and g['Toner']['t'][1][2] == 48 and g['Toner']['t'][2][2] is None             # TIENDA C sin conteo
    assert g['Cable']['t'][0][2] == 30                                                                                # sin Entidad_ID: se une por nombre normalizado


def test_con_filtro_activo_se_ocultan_las_subcategorias_sin_sku_visibles():
    assert [x['sub'] for x in armar(hay=True, filas=[FILAS[2]])] == ['Tinta']
    assert [x['sub'] for x in armar(hay=False, filas=[FILAS[2]])] == ['Cable', 'Tinta', 'Toner']


def test_orden_por_donde_nos_gana_el_rey_y_por_tienda_mas_debil():
    assert [x['sub'] for x in armar(modo='ganan')][:2] == ['Tinta', 'Toner']                                          # 1 y 1: desempata por nombre
    assert [x['sub'] for x in armar(modo='var')][0] == 'Tinta'                                                        # tienda A -20 % vs su mediana (también en Toner, pero Tinta va primero por nombre)


def test_html_conteo_mediana_nuevas_incompleta_y_sin_datos():
    h = js("global.AC={catAb:{'Toner':true}};const gs=acCatOrdenar(acCategoriasArmar(X.D,X.filas,false,norm),'sub');console.log(JSON.stringify([acCatHtml(gs),acCatHtml([])]))",
           {'D': D, 'filas': FILAS})
    izq, der = h[0].split('aria-label="Tiendas"')                      # tabla de subcategorías | panel lateral de tiendas
    assert 'TIENDA A <b>120</b>' in izq and 'TIENDA C <b>—</b>' in izq and '3 / 3' not in izq and '2 / 3' in izq             # Rey · Media · Barata con leídas; SKU con competencia / en planilla
    assert 'aria-expanded="true"' in izq and 'acCatVerSku(2,0)' in izq and '>1</b> <span style="color:var(--texto-suave)">de 2' in izq and 'de 2' in izq   # el Rey nos gana en 1 de 2
    assert '120 / 120' in der and '150 <span style="color:var(--texto-suave)">−20,0%</span>' in der and '+0 / −7' in der           # leídas / ML, mediana 7 d con signo, nuevas / desaparecidas
    assert 'lectura incompleta' in der and 'captcha' in der and 'fuera de planilla' in der and 'sin conteo de publicaciones todavía' in der
    assert 'aria-label="Tiendas"' in h[0] and h[1].startswith('<div') and 'Sin subcategorías' in h[1]


def test_diagnostico_de_lo_que_no_se_pudo_cruzar():
    d = js("const gs=acCategoriasArmar(X.D,X.filas,false,norm);console.log(JSON.stringify([acCatDiag(gs),acCatDiagHtml(acCatDiag(gs)),acCatDiagHtml({})]))", {'D': D, 'filas': FILAS})
    assert d[0] == {'subs': 3, 'sinSkus': 1, 'sinCompetencia': 0, 'skusSinCompetencia': 1, 'tiendas': 5, 'tiendasSinConteo': 1, 'incompletas': 1, 'fueraPlanilla': 1}
    assert '1 subcategoría con SKUs_Nuestros vacío' in d[1] and '1 de 5 tiendas sin conteo' in d[1] and d[2] == ''
