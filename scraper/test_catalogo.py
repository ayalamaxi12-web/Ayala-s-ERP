"""Catálogo con wid: precio de la oferta del competidor + precio de la GANADORA (dato aparte).
Cubre la lógica pura, la secuencia de estrategias del lector (con un navegador simulado), la vía API, la escritura en
Historial_Precios y —si hay node + jsdom— el extractor JS de la tarjeta de la oferta contra HTML de ejemplo."""
import json
import os
import shutil
import subprocess

import pytest

import config  # noqa: F401  (agrega backend/ al path)
import competencia_db as cdb
import corrida
import eventos as ev
import ml_api
import ml_selenium as mls
import paginas_ml as pml
from fakes import SS, LectorFalso
from test_scraper import HOY, L_WID, L_WID2, L_ITEM, base, maca, ok, tienda

URL = 'https://www.mercadolibre.com.ar/camara/p/MLA61689399?pdp_filters=x&wid=MLA3314429922'
PAG = {'url': 'https://www.mercadolibre.com.ar/camara/p/MLA61689399', 'texto': 'x', 'precio': '$ 32.980',
       'vendedor': 'Tienda oficial MTL'}                 # lo que ML muestra primero: la GANADORA
TARJETA = {'encontrada': True, 'precio': '31.500', 'texto': 'Vendido por GEOTEK\n$ 31.500\nEnvío gratis', 'via': 'tarjeta_wid'}


# ── lógica pura ───────────────────────────────────────────────────────────────
def test_catalogo_sin_tarjeta_conserva_el_precio_ganador_pero_no_inventa_el_del_competidor():
    r = pml.clasificar_oferta_en_catalogo(PAG, None, None, URL)
    assert r['estado'] == 'Sin lectura' and r['precio'] is None
    assert r['precio_ganador'] == 32980 and r['vendedor_ganador'] == 'MTL'
    assert 'no encontré la tarjeta' in r['detalle']


def test_catalogo_con_tarjeta_del_wid_da_precio_del_competidor_y_del_ganador():
    r = pml.clasificar_oferta_en_catalogo(PAG, TARJETA, None, URL)       # sin saber de antemano quién es: el wid lo identifica
    assert (r['estado'], r['precio'], r['vendedor'], r['via']) == ('OK', 31500, 'GEOTEK', 'tarjeta_wid')
    assert r['precio_ganador'] == 32980 and r['vendedor_ganador'] == 'MTL'
    assert pml.clasificar_oferta_en_catalogo(PAG, TARJETA, 'GEOTEK', URL)['estado'] == 'OK'
    otro = pml.clasificar_oferta_en_catalogo(PAG, TARJETA, 'TECNOVIBEARG', URL)
    assert otro['estado'] == 'Otro vendedor' and otro['precio'] is None and otro['precio_ganador'] == 32980


def test_catalogo_bloqueo_y_caida_se_respetan():
    assert pml.clasificar_oferta_en_catalogo({'url': 'https://x/login', 'texto': '', 'precio': ''}, None, None, URL)['estado'] == 'Bloqueado'
    caida = {'url': URL, 'texto': 'Esta publicación ya no está disponible', 'precio': ''}
    assert pml.clasificar_oferta_en_catalogo(caida, None, None, URL)['estado'] == 'Caida'


def test_vendedor_de_texto():
    assert pml.vendedor_de_texto('Vendido por GEOTEK\n$ 1') == 'GEOTEK'
    assert pml.vendedor_de_texto('Tienda oficial Delivery Cartuchos') == 'Delivery Cartuchos'
    assert pml.vendedor_de_texto('Por Mercado Libre\n$ 5') == 'Mercado Libre'
    assert pml.vendedor_de_texto('solo un precio') == ''


# ── vía API ───────────────────────────────────────────────────────────────────
class Resp:
    def __init__(self, status, j): self.status_code, self._j = status, j
    def json(self): return self._j


def api_con(respuestas):
    cola = list(respuestas)
    return ml_api.ApiCatalogo('https://b', 'k', log=lambda m: None, http=lambda url, params, headers, timeout: cola.pop(0))


def test_api_encuentra_la_oferta_del_wid_y_la_ganadora():
    a = api_con([Resp(200, {'results': [{'item_id': 'MLA111', 'price': 900, 'seller_id': 7},
                                        {'item_id': 'MLA3314429922', 'price': 31500, 'seller_id': 9}], 'paging': {'total': 2}}),
                 Resp(200, {'buy_box_winner': {'price': 32980, 'seller_id': 5}})])
    r = a.leer('MLA61689399', 'MLA3314429922')
    assert (r['estado'], r['precio'], r['seller_id'], r['precio_ganador']) == ('OK', 31500, 9, 32980)


def test_api_wid_que_no_esta_y_circuito_que_se_abre_tras_3_errores():
    a = api_con([Resp(200, {'results': [], 'paging': {'total': 0}}), Resp(200, {})])
    assert a.leer('MLA1', 'MLA2')['estado'] == 'No esta'
    err = api_con([Resp(200, {'message': 'forbidden', 'status': 403})] * 3)
    for _ in range(3):
        r = err.leer('MLA1', 'MLA2')
        assert r['estado'] == 'Error' and r['http'] == 403
    assert err.apagada and not err.disponible()
    assert ml_api.ApiCatalogo('', '', http=lambda *a, **k: None).disponible() is False      # sin configurar: no se usa


# ── secuencia de estrategias del lector (navegador simulado) ─────────────────
class LectorSim(mls.LectorML):
    """Reemplaza solo el navegador: páginas por URL, tarjetas y 'más opciones' simuladas."""
    def __init__(self, paginas, tarjetas=None, clic=False, api=None):
        super().__init__(api=api)
        self.paginas, self.tarjetas, self.hay_clic, self.visitas, self.actual = paginas, tarjetas or {}, clic, [], None
        self.abierto = False

    def _snapshot(self, url):
        self.visitas.append(url)
        self.actual, self.abierto = url, False
        return self.paginas[url]

    def _snapshot_actual(self): return self.paginas[self.actual]
    def _buscar_oferta(self, wid): return self.tarjetas.get((self.actual, self.abierto), {'encontrada': False})
    def _evidencia(self, wid): return {'wid_veces_en_html': 0}

    def _abrir_opciones(self):
        self.abierto = self.hay_clic
        return {'clic': self.hay_clic, 'texto': 'Más opciones de compra'}

    def cerrar(self): pass


DIRECTO = 'https://articulo.mercadolibre.com.ar/MLA-3314429922'


def test_lector_toma_la_tarjeta_en_la_pagina_original_sin_gastar_mas_estrategias():
    lec = LectorSim({URL: PAG}, {(URL, False): TARJETA})
    r = lec.leer_publicacion(URL)
    assert (r['estado'], r['precio'], r['via'], r['precio_ganador']) == ('OK', 31500, 'tarjeta_wid', 32980)
    assert lec.visitas == [URL]                                        # no abrió el ítem directo


def test_lector_abre_mas_opciones_cuando_la_tarjeta_no_esta_a_la_vista():
    lec = LectorSim({URL: PAG}, {(URL, True): TARJETA}, clic=True)
    r = lec.leer_publicacion(URL)
    assert (r['estado'], r['precio'], r['via'], r['precio_ganador']) == ('OK', 31500, 'opciones_de_compra', 32980)


def test_lector_cae_a_la_api_y_despues_al_item_directo():
    api = api_con([Resp(200, {'results': [{'item_id': 'MLA3314429922', 'price': 31000, 'seller_id': 9}], 'paging': {'total': 1}}),
                   Resp(200, {'buy_box_winner': {'price': 32980}})])
    r = LectorSim({URL: PAG}, api=api).leer_publicacion(URL)
    assert (r['estado'], r['precio'], r['via']) == ('OK', 31000, 'api')
    directo = {'url': DIRECTO + '-x', 'texto': 'x', 'precio': '7.131', 'vendedor': 'TECNOVIBEARG'}     # ítem tradicional: no redirige
    r = LectorSim({URL: PAG, DIRECTO: directo}).leer_publicacion(URL)
    assert (r['estado'], r['precio'], r['via'], r['precio_ganador']) == ('OK', 7131, 'item_directo', 32980)


def test_lector_catalogo_irresoluble_queda_sin_lectura_pero_con_precio_ganador():
    redirige = {'url': 'https://www.mercadolibre.com.ar/camara/p/MLA61689399', 'texto': 'x', 'precio': '32.980', 'vendedor': 'TIENDADEINFORMATICA'}
    r = LectorSim({URL: PAG, DIRECTO: redirige}).leer_publicacion(URL, diagnostico=True)
    assert r['estado'] == 'Sin lectura' and r['precio'] is None and r['precio_ganador'] == 32980
    assert [p['paso'] for p in r['pasos']] == ['pagina_original', 'opciones_de_compra', 'item_directo']
    assert 'evidencia' in r


def test_lector_bloqueo_corta_en_el_primer_paso():
    bloqueo = {'url': 'https://www.mercadolibre.com.ar/jms/mla/lgz/login', 'texto': '', 'precio': ''}
    lec = LectorSim({URL: bloqueo})
    assert lec.leer_publicacion(URL)['estado'] == 'Bloqueado' and lec.visitas == [URL]


def test_item_directo_y_catalogo_sin_wid_no_buscan_tarjetas():
    item = {'url': L_ITEM, 'texto': 'x', 'precio': '1.000', 'vendedor': 'GEOTEK'}
    r = LectorSim({L_ITEM: item}).leer_publicacion(L_ITEM)
    assert (r['estado'], r['precio'], r['via']) == ('OK', 1000, 'pagina_original') and 'precio_ganador' not in r
    sin_wid = 'https://www.mercadolibre.com.ar/toner/p/MLA777'
    r = LectorSim({sin_wid: {'url': sin_wid, 'texto': 'x', 'precio': '500', 'vendedor': 'X'}}).leer_publicacion(sin_wid)
    assert r['estado'] == 'Sin lectura' and r['precio_ganador'] == 500


# ── escritura: Precio_Ganador junto al del competidor; el evento solo mira el competidor ──────────
def test_corrida_guarda_precio_ganador_y_el_evento_no_lo_mira():
    ss = base()
    pubs = lambda p, g: {L_WID: dict(ok(p, 'GEOTEK'), precio_ganador=g, vendedor_ganador='MTL', via='tarjeta_wid'),
                         L_WID2: {'estado': 'Sin lectura', 'precio': None, 'precio_ganador': 99}}
    tiendas = {f'https://listado.mercadolibre.com.ar/tienda/{s}': tienda() for s in ('tecnovibe', 'american-computers', 'geotek')}
    lec = LectorFalso(tiendas=tiendas, pubs=pubs(2000, 2500))
    r = corrida.correr(ss, maca(), lec, hoy='05/10/2026', pausa=False, log=lambda m: None, solo='publicaciones')
    h = ss.tab('Historial_Precios')
    assert h[0][-2:] == ['Precio_Ganador', 'Vendedor_Ganador']
    fila = next(f for f in h[1:] if f[5] == 2000)
    assert fila[-2:] == [2500, 'MTL'] and len(h) == 2                     # el Sin lectura NO genera fila (aunque se vio al ganador)
    assert r['publicaciones']['via'] == {'tarjeta_wid': 1} and r['publicaciones']['solo_precio_ganador'] == 1
    # día siguiente: el GANADOR baja pero el competidor no se mueve -> NO hay evento; si se mueve el competidor, sí
    lec.pubs = pubs(2000, 1800)
    r2 = corrida.correr(ss, maca(), lec, hoy='06/10/2026', pausa=False, log=lambda m: None, solo='publicaciones')
    assert r2['eventos'] == {}
    lec.pubs = pubs(1900, 1800)
    r3 = corrida.correr(ss, maca(), lec, hoy='07/10/2026', pausa=False, log=lambda m: None, solo='publicaciones')
    assert r3['eventos'] == {'Bajo': 1}


def test_historial_existente_de_13_columnas_se_extiende_sin_mover_nada():
    ss = base()
    ss.w['Historial_Precios'] = type(ss.w['Entidades'])('Historial_Precios', [cdb.HISTORIAL_HEADERS, ['REF-X', 'S', 'E', '01/10/2026', '', 10, '', '', '', 'OK', '', 'V-*', 'l']])
    lec = LectorFalso(tiendas={}, pubs={L_WID: dict(ok(2000, 'GEOTEK'), precio_ganador=2500, vendedor_ganador='MTL'), L_WID2: ok(1, 'GEOTEK')})
    corrida.correr(ss, maca(), lec, hoy=HOY, pausa=False, log=lambda m: None, solo='publicaciones')
    h = ss.tab('Historial_Precios')
    assert h[0][:13] == cdb.HISTORIAL_HEADERS and h[0][13:] == ['Precio_Ganador', 'Vendedor_Ganador']
    assert h[1][:13] == ['REF-X', 'S', 'E', '01/10/2026', '', 10, '', '', '', 'OK', '', 'V-*', 'l']      # lo viejo, intacto


# ── extractor JS contra HTML de ejemplo (necesita node + jsdom; si no, se saltea) ─────────────
def _node_jsdom():
    node = shutil.which('node')
    if not node:
        return None
    r = subprocess.run([node, '-e', "require('jsdom')"], capture_output=True, env=dict(os.environ))
    return node if r.returncode == 0 else None


def _correr_js(js, html, arg):
    runner = r"""
const {JSDOM} = require('jsdom');
const [js, html, arg] = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const dom = new JSDOM(html, {runScripts: 'outside-only'});
Object.defineProperty(dom.window.HTMLElement.prototype, 'innerText', {get() { return this.textContent; }});
const f = dom.window.eval('(function(){' + js + '\n})');
console.log(JSON.stringify(f.apply(null, [arg])));
"""
    r = subprocess.run([shutil.which('node'), '-e', runner], input=json.dumps([js, html, arg]), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def money(v, previo=False):
    return (f'<s class="andes-money-amount andes-money-amount--previous"><span class="andes-money-amount__fraction">{v}</span></s>' if previo
            else f'<span class="andes-money-amount"><span class="andes-money-amount__fraction">{v}</span></span>')


@pytest.mark.skipif(_node_jsdom() is None, reason='sin node/jsdom')
def test_js_tarjeta_por_wid():
    wid = '3314429922'
    ganadora = f'<div class="buybox">{money("32.980")}<span>Vendido por MTL</span></div>'
    tarjeta = lambda extra='': f'<div class="otra-oferta"><a href="/p/MLA61689399?wid=MLA{wid}">Ver</a>{money("33.500", True)}{money("31.500")}<span>Vendido por GEOTEK</span>{extra}</div>'
    otras = f'<div class="otra-oferta"><a href="/p/MLA61689399?wid=MLA999">x</a>{money("40.000")}<span>Vendido por OTRO</span></div>'
    doc = lambda body, head='': f'<html><head>{head}</head><body>{body}</body></html>'

    r = _correr_js(mls.JS_OFERTA_POR_WID, doc(ganadora + tarjeta() + otras), wid)
    assert r['encontrada'] and r['precio'] == '31.500' and 'GEOTEK' in r['texto'] and 'OTRO' not in r['texto']     # el tachado no cuenta
    assert pml.clasificar_oferta_en_catalogo(PAG, r, None, URL)['precio'] == 31500
    # el wid solo en la URL canónica del <head> NO es una tarjeta
    canon = f'<link rel="canonical" href="https://www.mercadolibre.com.ar/p/MLA61689399?wid=MLA{wid}">'
    r = _correr_js(mls.JS_OFERTA_POR_WID, doc(ganadora + otras, canon), wid)
    assert r['encontrada'] is False and r['motivo'] == 'el wid no aparece en la página'
    # si el wid está en un contenedor enorme con muchos precios no es una tarjeta (ambiguo)
    enorme = '<div>' + tarjeta().replace('<div class="otra-oferta">', '').replace('</div>', '', 1) + money("1") + money("2") + money("3") + '</div>'
    r = _correr_js(mls.JS_OFERTA_POR_WID, doc(enorme), wid)
    assert r['encontrada'] is False
    # el wid de la propia ganadora (buy box): devuelve el precio principal
    buy = f'<div class="buybox"><form action="/buy"><input name="item_id" value="MLA{wid}"></form>{money("32.980")}<span>Vendido por MTL</span></div>'
    assert _correr_js(mls.JS_OFERTA_POR_WID, doc(buy), wid)['precio'] == '32.980'
