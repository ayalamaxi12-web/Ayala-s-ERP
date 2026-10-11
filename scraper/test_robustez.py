"""Corrida DESATENDIDA: si Chrome se cae se reabre y se reintenta, Chrome se recicla antes de quedarse sin memoria, la
paginación no se frena por un clic tapado y la corrida se puede reanudar. Sin red ni navegador (driver simulado)."""
import pytest

import config
import errores
import ml_selenium as mls
import paginas_ml as pml
import corrida
import tiendas_conteo as tc
from errores import CorridaCortada, NavegadorCaido
from fakes import LectorFalso
from test_scraper import HOY, L_ITEM, L_WID, L_WID2, base, maca, ok, tienda

MSG_REAL = ('invalid session id: session deleted as the browser has closed the connection\\nfrom disconnected: not connected to DevTools')


def test_reconoce_errores_de_sesion_pero_no_los_de_una_pagina():
    assert errores.es_error_de_sesion(Exception(MSG_REAL.replace('\\n', '\n')))
    assert errores.es_error_de_sesion(Exception('Message: chrome not reachable'))
    assert errores.es_error_de_sesion(Exception("HTTPConnectionPool(host='localhost', port=51234): Max retries exceeded with url: /session/abc/url "
                                                "(Caused by NewConnectionError: Failed to establish a new connection)"))
    assert not errores.es_error_de_sesion(Exception('net::ERR_INTERNET_DISCONNECTED'))          # falla de red de UNA página
    assert not errores.es_error_de_sesion(Exception('element click intercepted'))
    assert not errores.es_error_de_sesion(Exception('HTTPSConnectionPool(host=sheets.googleapis.com): Max retries exceeded'))

    class TimeoutException(Exception):
        pass
    assert errores.es_timeout(TimeoutException('x')) and not errores.es_timeout(Exception('x'))


def test_url_de_la_pagina_siguiente_por_offset():
    u = 'https://listado.mercadolibre.com.ar/tienda/geotek'
    assert pml.url_pagina_siguiente(u, 1, 48) == u + '_Desde_49'
    assert pml.url_pagina_siguiente(u + '_Desde_49', 2, 48) == u + '_Desde_97'
    assert pml.url_pagina_siguiente(u + '?x=1#frag', 1, 48) == u + '_Desde_49'                  # sin parámetros de seguimiento
    assert pml.url_pagina_siguiente(u + '_NoIndex_True', 1, 48) == u + '_Desde_49_NoIndex_True'
    assert pml.url_pagina_siguiente(u, 1, 0) is None


# ── reintentos y reciclado del navegador ─────────────────────────────────────────────────────────────────────────
class Lector(mls.LectorML):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.log = lambda m: None
        self.cerrados = 0

    def cerrar(self):
        self.cerrados += 1
        self._driver = None


def test_si_chrome_se_cae_se_reabre_y_se_reintenta_esa_lectura():
    lec, llamadas = Lector(), {'n': 0}

    def lectura():
        llamadas['n'] += 1
        if llamadas['n'] <= 2:
            raise Exception(MSG_REAL)
        return {'estado': 'OK'}
    assert lec._con_reintento(lectura, lambda m: {'estado': 'Error', 'detalle': m}) == {'estado': 'OK'}
    assert llamadas['n'] == 3 and lec.reinicios == 2 and lec.cerrados == 2


def test_si_una_lectura_mata_a_chrome_siempre_se_devuelve_error_y_se_sigue():
    lec = Lector()

    def siempre():
        raise Exception(MSG_REAL)
    r = lec._con_reintento(siempre, lambda m: {'estado': 'Error', 'detalle': m})
    assert r['estado'] == 'Error' and 'se cayó' in r['detalle']
    assert lec.reinicios == config.REINTENTOS_SESION + 1                       # y dejó Chrome reabierto para la próxima


def test_un_error_que_no_es_de_sesion_no_se_reintenta():
    lec = Lector()
    with pytest.raises(ValueError):
        lec._con_reintento(lambda: (_ for _ in ()).throw(ValueError('otro')), lambda m: None)
    assert lec.reinicios == 0


def test_demasiados_reinicios_cortan_con_navegador_caido(monkeypatch):
    monkeypatch.setattr(config, 'MAX_REINICIOS', 3)
    lec = Lector()
    for _ in range(3):
        lec.reiniciar('x')
    with pytest.raises(NavegadorCaido):
        lec.reiniciar('x')


class FD:
    """Driver simulado: páginas de tarjetas por URL."""
    def __init__(self, paginas=None, declaradas='100 resultados'):
        self.paginas, self.declaradas, self.current_url, self.visitas, self.js = paginas or {}, declaradas, '', [], []

    def get(self, url):
        self.current_url = url
        self.visitas.append(url)

    def set_page_load_timeout(self, s): pass
    def find_elements(self, *a): return [1]

    def find_element(self, *a):
        raise Exception('no such element')

    def execute_script(self, js, *a):
        self.js.append(js)
        if js is mls.JS_TARJETAS:
            return self.paginas.get(self.current_url, [])
        if js is mls.JS_DECLARADAS:
            return {'texto': self.declaradas, 'candidatos': []}
        if js is mls.JS_PAGINACION:
            return {'url': self.current_url, 'paginacion_html': '', 'controles': [], 'tarjetas': 0, 'altura': 0}
        if js is mls.JS_VER_MAS:
            return False
        if 'readyState' in js:
            return 'complete'
        if 'scrollHeight' in js:
            return 100
        return 'texto normal'


class LectorFD(mls.LectorML):
    def __init__(self, fd, **kw):
        super().__init__(**kw)
        self.log, self.fd = (lambda m: None), fd

    def driver(self): return self.fd
    def cerrar(self): pass


def cards(n, desde=0):
    return [{'title': f't{i}', 'link': f'https://articulo.mercadolibre.com.ar/MLA-{200000000 + i}-x', 'price': 10 + i, 'orig_price': '',
             'discount': '', 'cuotas': ''} for i in range(desde, desde + n)]


def test_el_chrome_se_recicla_cada_tantas_navegaciones(monkeypatch):
    monkeypatch.setattr(config, 'RECICLAR_CADA_NAVEGACIONES', 3)
    lec = LectorFD(FD())
    for i in range(7):
        lec._ir(f'https://x/{i}', '.poly-card')
    assert lec.reinicios == 2                                  # al pasar la 3ª y la 6ª navegación


def test_siguiente_hace_clic_por_javascript_si_algo_tapa_el_boton():
    class Padre:
        def get_attribute(self, n): return 'andes-pagination__button andes-pagination__button--next'

    class Boton:
        clicks = 0

        def find_element(self, *a): return Padre()
        def click(self): raise Exception('element click intercepted: Other element would receive the click')

    class Driver(FD):
        def __init__(self):
            super().__init__()
            self.boton, self.js_clicks = Boton(), 0

        def find_element(self, *a): return self.boton

        def execute_script(self, js, *a):
            if 'click()' in js:
                self.js_clicks += 1
                return None
            return None
    d = Driver()
    assert LectorFD(d)._siguiente() is True and d.js_clicks == 1               # antes esto se tomaba por "no hay más páginas"


def test_tienda_sin_boton_siguiente_pero_con_publicaciones_pendientes_sigue_por_offset():
    u = 'https://listado.mercadolibre.com.ar/tienda/geotek'
    fd = FD({u: cards(48), u + '_Desde_49': cards(48, 48), u + '_Desde_97': cards(4, 96)})
    r = LectorFD(fd).leer_tienda(u)
    assert (len(r['items']), r['declaradas'], r['paginas'], r['fin']) == (100, 100, 3, 'sin_siguiente')
    assert r['completa'] is True and r['via_paginacion'] == {'desde_url': 2}


def test_si_el_offset_no_trae_nada_nuevo_la_tienda_queda_incompleta_con_evidencia():
    u = 'https://listado.mercadolibre.com.ar/tienda/geotek'
    fd = FD({u: cards(48), u + '_Desde_49': cards(48)}, declaradas='122 resultados')        # la "página 2" repite lo mismo
    r = LectorFD(fd).leer_tienda(u)
    assert len(r['items']) == 48 and r['completa'] is False and '48 de 122' in r['motivo']
    assert 'evidencia_paginacion' in r                                                       # qué controles había: para arreglarlo
    assert r['via_paginacion'] == {'desde_url': 1}


def test_tienda_que_pagina_normal_no_usa_los_planes_b():
    class FDok(FD):
        def __init__(self):
            super().__init__({'https://l/t': cards(48), 'https://l/t2': cards(10, 48)}, '58 resultados')
            self.pag = 0

        def find_element(self, *a):
            class Padre:
                def get_attribute(self, n): return 'andes-pagination__button--next' if self.sig else 'andes-pagination__button--next andes-pagination__button--disabled'

            class El:
                def __init__(self, fd): self.fd = fd
                def find_element(self, *x):
                    p = Padre(); p.sig = self.fd.current_url == 'https://l/t'; return p
                def click(self): self.fd.current_url = 'https://l/t2'
            return El(self)
    r = LectorFD(FDok()).leer_tienda('https://l/t')
    assert r['completa'] and len(r['items']) == 58 and r['via_paginacion'] == {'boton': 1}


# ── corrida desatendida ────────────────────────────────────────────────────────────────────────────────────────
URL_TV = 'https://listado.mercadolibre.com.ar/tienda/tecnovibe'
URL_AC = 'https://listado.mercadolibre.com.ar/tienda/american-computers'
URL_GK = 'https://listado.mercadolibre.com.ar/tienda/geotek'


def _t(n, desde=0):
    return dict(tienda(*[(f't{i}', f'https://articulo.mercadolibre.com.ar/MLA-{300000000 + i}-x', 10 + i) for i in range(desde, desde + n)]),
                declaradas=n, paginas=1, fin='sin_siguiente')


def correr(ss, lec, dia=HOY, **kw):
    return corrida.correr(ss, maca(), lec, hoy=dia, pausa=False, log=lambda m: None, descubrir=False, **kw)


def test_si_chrome_no_se_recupera_la_corrida_escribe_lo_leido_y_se_corta_con_resumen():
    ss = base()
    lec = LectorFalso(tiendas={URL_TV: _t(20), URL_AC: NavegadorCaido('Chrome se reinició 8 veces'), URL_GK: _t(3, 900)}, pubs={})
    with pytest.raises(CorridaCortada) as e:
        correr(ss, lec, solo='perfiles')
    assert 'Chrome se cayó' in str(e.value) and e.value.resumen['corte'] == str(e.value)
    assert [f[3] for f in ss.tab(tc.CONTEO_SHEET)[1:]] == ['TECNOVIBEARG']                   # la tienda leída antes de la caída quedó guardada
    assert ('tienda', URL_GK) not in lec.llamadas                                            # y no siguió con una caída sin resolver
    assert 'CORRIDA CORTADA' in corrida.texto_resumen(e.value.resumen) and '--reanudar' in corrida.texto_resumen(e.value.resumen)


def test_una_publicacion_que_explota_no_corta_las_demas():
    ss = base()
    tiendas = {u: _t(1) for u in (URL_TV, URL_AC, URL_GK)}
    lec = LectorFalso(tiendas=tiendas, pubs={L_WID: RuntimeError('boom'), L_WID2: ok(3000, 'GEOTEK')})
    r = correr(ss, lec, solo='publicaciones')
    assert r['publicaciones']['error'] >= 1 and r['publicaciones']['ok'] >= 1 and r['lecturas'] >= 1
    assert any('RuntimeError: boom' in a for a in r['avisos'])


def test_reanudar_no_repite_lo_que_ya_se_hizo_hoy():
    ss = base()
    pubs = {L_WID: ok(2000, 'GEOTEK'), L_WID2: ok(3000, 'GEOTEK'), L_ITEM: ok(1000, 'GEOTEK')}
    lec = LectorFalso(tiendas={URL_TV: _t(20), URL_AC: _t(5, 500), URL_GK: _t(3, 900)}, pubs=dict(pubs))
    correr(ss, lec)
    n_hist = len(ss.tab('Historial_Precios'))
    lec2 = LectorFalso(tiendas={URL_TV: _t(20), URL_AC: _t(5, 500), URL_GK: _t(3, 900)}, pubs=dict(pubs))
    r = correr(ss, lec2, reanudar=True)
    assert lec2.llamadas == [] and r['perfiles']['saltados_reanudar'] == 3 and r['publicaciones']['ya_hechas'] >= 1
    assert len(ss.tab('Historial_Precios')) == n_hist and 'MODO REANUDAR' in corrida.texto_resumen(r)
    # una tienda que ayer quedó INCOMPLETA sí se vuelve a leer
    ss2 = base()
    inc = dict(_t(10), declaradas=100)
    correr(ss2, LectorFalso(tiendas={URL_TV: inc, URL_AC: _t(5, 500), URL_GK: _t(3, 900)}), solo='perfiles')
    lec3 = LectorFalso(tiendas={URL_TV: _t(100), URL_AC: _t(5, 500), URL_GK: _t(3, 900)})
    correr(ss2, lec3, solo='perfiles', reanudar=True)
    assert [c for c in lec3.llamadas] == [('tienda', URL_TV)]


def test_tiempo_maximo_corta_escribiendo_lo_que_hay(monkeypatch):
    ss = base()
    reloj = {'n': 0}

    def tiempo():
        reloj['n'] += 1
        return 0 if reloj['n'] <= 3 else 10 ** 9                 # pasa "mucho tiempo" después de la primera tienda
    monkeypatch.setattr(corrida.time, 'time', tiempo)
    lec = LectorFalso(tiendas={URL_TV: _t(20), URL_AC: _t(5, 500), URL_GK: _t(3, 900)})
    with pytest.raises(CorridaCortada) as e:
        correr(ss, lec, solo='perfiles', max_minutos=1)
    assert 'tiempo máximo' in str(e.value) and len(ss.tab(tc.CONTEO_SHEET)) >= 2


def test_los_reinicios_de_chrome_aparecen_en_el_resumen():
    ss = base()
    lec = LectorFalso(tiendas={u: _t(1) for u in (URL_TV, URL_AC, URL_GK)})
    lec.reinicios = 2
    assert 'Chrome se reabrió 2' in corrida.texto_resumen(correr(ss, lec, solo='perfiles'))


def test_evitar_suspension_no_rompe_fuera_de_windows():
    import scraper
    assert scraper._evitar_suspension() in (True, False)
