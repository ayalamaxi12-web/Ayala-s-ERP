"""Fase 1: conteo diario por tienda (Tiendas_Conteo), completitud de la lectura, línea base desde las V-* y medidor de celdas."""
import json
import os
import shutil
import subprocess

import pytest

import config
import competencia_db as cdb
import celdas
import corrida
import ml_selenium as mls
import paginas_ml as pml
import tiendas_conteo as tc
from fakes import SS, LectorFalso
from test_scraper import base, maca, tienda


# ── declaradas y completitud ──────────────────────────────────────────────────
def test_parse_declaradas():
    assert pml.parse_declaradas('1.234 resultados') == 1234
    assert pml.parse_declaradas('1 resultado') == 1
    assert pml.parse_declaradas('Más de 2.000 resultados') == 2000
    assert pml.parse_declaradas('sin números') is None and pml.parse_declaradas('') is None


def test_evaluar_completitud():
    ok = lambda *a, **k: pml.evaluar_completitud(*a, **k)[0]
    assert ok(185, 185, 'sin_siguiente') and ok(170, 185, 'sin_siguiente')               # 92% >= 90%
    c, motivo = pml.evaluar_completitud(150, 185, 'sin_siguiente')
    assert c is False and '150 de 185' in motivo and '81%' in motivo
    assert ok(100, None, 'sin_siguiente')                                               # ML no declara: llegó al final
    assert not ok(100, None, 'tope_paginas') and not ok(100, None, 'excepcion')         # cortada y sin dato para validar
    assert ok(185, 185, 'tope_paginas')                                                 # cortada pero los números cierran
    assert not ok(0, 185, 'sin_siguiente') and ok(0, 0, 'sin_siguiente')                # tienda realmente vacía
    assert not ok(100, 100, 'sin_siguiente', bloqueado=True)


# ── conteo, mediana y variación ───────────────────────────────────────────────
def fila(f, eid, n, completa='Si'):
    return [f, '', eid, 'X', n, '', '', completa, '', '', '', '', '', '', 'Scraper']


def hoja_conteo(*filas):
    return [tc.CONTEO_HEADERS] + [list(f) for f in filas]


def test_validas_previas_ignora_incompletas_otras_tiendas_y_hoy():
    h = hoja_conteo(fila('01/10/2026', 'E1', 100), fila('02/10/2026', 'E1', 10, 'No'), fila('03/10/2026', 'E2', 999),
                    fila('04/10/2026', 'E1', 102), fila('05/10/2026', 'E1', 50), fila('06/10/2026', 'E1', 1))
    assert tc.validas_previas(h, 'E1', '05/10/2026') == [((2026, 10, 1), 100), ((2026, 10, 4), 102)]


def test_mediana_exige_minimo_y_no_calcula_variacion_si_la_lectura_es_incompleta():
    prev = [((2026, 10, d), n) for d, n in ((1, 100), (2, 104), (3, 98))]
    assert tc.mediana_y_variacion(prev[:2], 100, True) == ('', '')                     # menos de 3 lecturas completas
    assert tc.mediana_y_variacion(prev, 80, True) == (100, -20.0)
    assert tc.mediana_y_variacion(prev, 80, False) == (100, '')                        # incompleta: no se compara
    # solo cuentan las últimas 7
    recientes = [((2026, 10, d), 100 + d) for d in range(1, 8)]                        # 101..107
    viejas = [((2026, 9, d), 1000) for d in range(1, 10)]
    assert tc.mediana_y_variacion(viejas + recientes, 100, True)[0] == 104             # las 9 viejas quedan fuera


def test_registrar_upsert_reemplaza_el_mismo_dia_y_la_siembra_no_pisa():
    ss = SS({})
    f = tc.fila_conteo('05/10/2026', '17:30', 'E1', 'TIENDA', 180, 185, 4, True, '', [])
    assert tc.registrar(ss, [f]) == (1, 0, 0)
    f2 = tc.fila_conteo('05/10/2026', '18:00', 'E1', 'TIENDA', 181, 185, 4, True, '', [])
    assert tc.registrar(ss, [f2]) == (0, 1, 0)                                        # mismo día: reemplaza
    assert len(ss.tab(tc.CONTEO_SHEET)) == 2 and ss.tab(tc.CONTEO_SHEET)[1][4] == 181
    semilla = tc.fila_conteo('05/10/2026', '', 'E1', 'TIENDA', 999, None, None, True, 'sembrado', [], tc.FUENTE_SEMILLA)
    otra = tc.fila_conteo('01/10/2026', '', 'E1', 'TIENDA', 170, None, None, True, 'sembrado', [], tc.FUENTE_SEMILLA)
    assert tc.registrar(ss, [semilla, otra], solo_nuevas=True) == (1, 0, 1)            # el real del 05/10 NO se pisa
    assert [f[4] for f in ss.tab(tc.CONTEO_SHEET)[1:]] == [181, 170]


# ── línea base desde las V-* ──────────────────────────────────────────────────
V_HDR = ['Titulo', 'Precio ($)', 'Precio Tachado ($)', 'Descuento', 'Cuotas', 'Ventas', 'Link', 'SKU', 'Cantidad',
         'Precio ($) 12/06/2026', 'Tachado ($) 12/06/2026', 'Desc 12/06/2026', 'Cuotas 12/06/2026',
         'Precio ($) 17/06/2026', 'Tachado ($) 17/06/2026', 'Desc 17/06/2026', 'Cuotas 17/06/2026',
         'Precio ($) 17/06/2026', 'Tachado ($) 17/06/2026', 'Desc 17/06/2026', 'Cuotas 17/06/2026']


def test_siembra_desde_v_solo_tiendas_de_a_y_cuenta_publicaciones_con_precio():
    f = lambda p1, p2, p3='': ['t', '', '', '', '', '', 'l', '', '', p1, '', '', '', p2, '', '', '', p3, '', '', '']
    v = {'V - TECNOVIBEARG': [V_HDR, f('1.000', '1.100'), f('2.000', ''), f('3.000', '3.000')],
         'V - TIENDAFONOPEL': [V_HDR, f('1', '1')],                      # distribuidor: no es de A
         'V - GLOBAL ELECTRONICS GROUP': [V_HDR, f('1', '1')]}          # nosotros: no
    ents = [['Entidad_ID', 'Nombre', 'Tipo'], ['ENT-1', 'TECNOVIBEARG', 'Competencia'], ['ENT-2', 'TIENDAFONOPEL', 'Competencia']]
    filas, avisos = tc.sembrar_desde_v(v, ents, config.ALIAS_TIENDAS.values())
    assert [(x['Fecha'], x['Leidas'], x['Fuente']) for x in filas] == [('12/06/2026', 3, tc.FUENTE_SEMILLA), ('17/06/2026', 2, tc.FUENTE_SEMILLA)]
    assert all(x['Entidad_ID'] == 'ENT-1' and x['Completa'] == 'Si' for x in filas) and avisos == []
    # sin la entidad en la base no se siembra (y se avisa)
    filas, avisos = tc.sembrar_desde_v(v, [ents[0]], config.ALIAS_TIENDAS.values())
    assert filas == [] and 'TECNOVIBEARG' in avisos[0]


# ── la corrida guarda el conteo ───────────────────────────────────────────────
URL_TV = 'https://listado.mercadolibre.com.ar/tienda/tecnovibe'
URL_AC = 'https://listado.mercadolibre.com.ar/tienda/american-computers'
URL_GK = 'https://listado.mercadolibre.com.ar/tienda/geotek'


def _items(n, desde=0):
    return [(f't{i}', f'https://articulo.mercadolibre.com.ar/MLA-{100000000 + i}-x', 10 + i) for i in range(desde, desde + n)]


def _lector(n_tv=20, decl_tv=20, **extra):
    return LectorFalso(tiendas={URL_TV: dict(tienda(*_items(n_tv)), declaradas=decl_tv, paginas=1, fin='sin_siguiente'),
                                URL_AC: dict(tienda(*_items(5, 500)), declaradas=5, paginas=1, fin='sin_siguiente'),
                                URL_GK: dict(tienda(*_items(3, 900)), declaradas=3, paginas=1, fin='sin_siguiente'), **extra}, pubs={})


def correr(ss, lec, dia, **kw):
    return corrida.correr(ss, maca(), lec, hoy=dia, pausa=False, log=lambda m: None, descubrir=False, solo='perfiles', **kw)


def test_la_corrida_escribe_un_conteo_por_tienda_y_dia_y_reemplaza_si_se_repite():
    ss = base()
    r = correr(ss, _lector(), '05/10/2026')
    h = ss.tab(tc.CONTEO_SHEET)
    assert h[0][:8] == ['Fecha', 'Hora', 'Entidad_ID', 'Entidad', 'Leidas', 'Declaradas_ML', 'Paginas', 'Completa'] and len(h) == 1 + 3
    fila_tv = next(f for f in h[1:] if f[3] == 'TECNOVIBEARG')
    assert (fila_tv[4], fila_tv[5], fila_tv[6], fila_tv[7]) == (20, 20, 1, 'Si')
    assert r['tiendas'][0]['leidas'] == 20
    correr(ss, _lector(n_tv=21, decl_tv=21), '05/10/2026')                 # misma fecha: reemplaza, no duplica
    h2 = ss.tab(tc.CONTEO_SHEET)
    assert len(h2) == len(h) and next(f for f in h2[1:] if f[3] == 'TECNOVIBEARG')[4] == 21


def test_la_linea_base_ignora_dias_incompletos_y_marca_la_variacion():
    ss = base()
    for d, n in (('01/10/2026', 20), ('02/10/2026', 22), ('03/10/2026', 21)):
        correr(ss, _lector(n_tv=n, decl_tv=n), d)
    correr(ss, _lector(n_tv=8, decl_tv=22), '04/10/2026')                    # lectura cortada: leyó 8 de 22 -> INCOMPLETA
    r = correr(ss, _lector(n_tv=15, decl_tv=15), '05/10/2026')               # día válido con 15
    filas = {f[0]: f for f in ss.tab(tc.CONTEO_SHEET)[1:] if f[3] == 'TECNOVIBEARG'}
    assert filas['04/10/2026'][7] == 'No' and '8 de 22' in filas['04/10/2026'][8] and filas['04/10/2026'][12] == ''
    # el 05/10 compara contra la mediana de 01,02,03 (el 04 incompleto no cuenta): 21 -> 15 = -28,6%
    assert (filas['05/10/2026'][11], filas['05/10/2026'][12]) == (21, -28.6)
    txt = corrida.texto_resumen(r)
    assert 'Conteo por tienda' in txt and 'TECNOVIBEARG: 15 leídas / 15 declaradas' in txt and 'mediana 21 (-28.6%)' in txt


def test_un_dia_bloqueado_queda_registrado_como_incompleto():
    ss = base()
    lec = _lector()
    lec.tiendas[URL_AC] = {'estado': 'bloqueado', 'items': [], 'detalle': 'ML pidió login'}
    with pytest.raises(corrida.CorridaBloqueada):
        correr(ss, lec, '05/10/2026')
    f = next(f for f in ss.tab(tc.CONTEO_SHEET)[1:] if f[3] == 'AMERICANCOMPUTERS')
    assert f[7] == 'No' and 'login' in f[8].lower()


def test_sin_escribir_no_crea_la_pestana_de_conteo():
    ss = base()
    correr(ss, _lector(), '05/10/2026', escribir=False)
    assert tc.CONTEO_SHEET not in ss.w


# ── medidor de celdas ─────────────────────────────────────────────────────────
class _Meta:
    def __init__(self, hojas): self.h = hojas
    def fetch_sheet_metadata(self, params=None):
        return {'sheets': [{'properties': {'title': n, 'gridProperties': {'rowCount': r, 'columnCount': c}}} for n, (r, c) in self.h.items()]}


def test_medidor_de_celdas_y_avisos():
    m = celdas.medir(_Meta({'Historial': (100000, 15), 'V - A': (5000, 30), 'Chica': (10, 10)}))
    assert m['total'] == 1_500_000 + 150_000 + 100 and m['nivel'] == 'ok' and m['mayores'][0][0] == 'Historial'
    assert 'Celdas usadas: 1.65M / 10M (16%)' in celdas.texto(m) and '⚠' not in celdas.texto(m)
    m = celdas.medir(_Meta({'X': (400000, 15)}))                                # 6M = 60%
    assert m['nivel'] == '60' and 'Más del 60%' in celdas.texto(m)
    assert celdas.medir(_Meta({'X': (600000, 15)}))['nivel'] == '80'
    assert 'no se pudo medir' in celdas.texto(celdas.medir(object()))           # el medidor nunca rompe una corrida


def test_el_resumen_de_la_corrida_incluye_el_medidor():
    ss = base()
    r = correr(ss, _lector(), '05/10/2026')
    assert r['celdas']['total'] > 0 and 'Celdas usadas:' in corrida.texto_resumen(r)


# ── extractor JS de "N resultados" (necesita node + jsdom; si no, se saltea) ─────────────────
def _node_jsdom():
    node = shutil.which('node')
    if not node:
        return None
    return node if subprocess.run([node, '-e', "require('jsdom')"], capture_output=True).returncode == 0 else None


@pytest.mark.skipif(_node_jsdom() is None, reason='sin node/jsdom')
def test_js_declaradas():
    runner = r"""
const {JSDOM} = require('jsdom');
const [js, html] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const dom = new JSDOM(html, {runScripts: 'outside-only'});
Object.defineProperty(dom.window.HTMLElement.prototype, 'innerText', {get() { return this.textContent; }});
console.log(JSON.stringify(dom.window.eval('(function(){' + js + '\n})')()));
"""
    def correr_js(html):
        r = subprocess.run([shutil.which('node'), '-e', runner], input=json.dumps([mls.JS_DECLARADAS, html]), capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)
    r = correr_js('<body><span class="ui-search-search-result__quantity-results">1.234 resultados</span></body>')
    assert pml.parse_declaradas(r['texto']) == 1234                                 # por selector conocido
    r = correr_js('<body><div><p class="otra-clase">Mostrando 2.593 resultados</p></div></body>')
    assert pml.parse_declaradas(r['texto']) == 2593 and r['candidatos'][0]['clase'] == 'otra-clase'   # por texto
    assert pml.parse_declaradas(correr_js('<body><p>nada</p></body>')['texto']) is None
