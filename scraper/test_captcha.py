"""Captcha / verificación de ML: se saltea la tienda (o publicación) afectada y se sigue; varios seguidos o un login cortan; el login
manual abre un Chrome común y NO se cierra solo. Sin red ni navegador."""
import sys
import types

import pytest

import config
import corrida
import eventos as ev
import ml_selenium as mls
import perfil_chrome as pc
import tiendas_conteo as tc
from errores import CorridaCortada
from fakes import LectorFalso
from test_scraper import HOY, L_ITEM, L_WID, L_WID2, base, maca, ok, tienda
from test_robustez import FD, LectorFD, cards

URL_TV = 'https://listado.mercadolibre.com.ar/tienda/tecnovibe'
URL_AC = 'https://listado.mercadolibre.com.ar/tienda/american-computers'
URL_GK = 'https://listado.mercadolibre.com.ar/tienda/geotek'


def _t(n, desde=0):
    return dict(tienda(*[(f't{i}', f'https://articulo.mercadolibre.com.ar/MLA-{400000000 + i}-x', 10 + i) for i in range(desde, desde + n)]),
                declaradas=n, paginas=1, fin='sin_siguiente')


def _captcha(items=0, declaradas=122):
    its = tienda(*[(f'g{i}', f'https://articulo.mercadolibre.com.ar/MLA-{500000000 + i}-x', 99) for i in range(items)])['items']
    return {'estado': 'bloqueado', 'bloqueo': 'captcha', 'items': its, 'detalle': 'ML pidió captcha en la página 2', 'declaradas': declaradas,
            'paginas': 1, 'fin': 'bloqueado', 'completa': False, 'motivo': f'ML pidió captcha en la página 2: leyó {items} de {declaradas} declaradas'}


def correr(ss, lec, dia=HOY, **kw):
    return corrida.correr(ss, maca(), lec, hoy=dia, pausa=False, log=lambda m: None, descubrir=False, **kw)


# ── la corrida: un captcha en UNA tienda no corta ─────────────────────────────────────────────────────────────
def test_captcha_en_una_tienda_se_saltea_y_la_corrida_sigue_con_las_demas():
    ss = base()
    lec = LectorFalso(tiendas={URL_TV: _t(20), URL_AC: _t(5, 500), URL_GK: _captcha(0)}, pubs={})
    r = correr(ss, lec, solo='perfiles')                                           # NO levanta excepción
    assert [b['entidad'] for b in r['perfiles']['bloqueadas']] == ['GEOTEK'] and r['perfiles']['ok'] == 2
    conteo = {f[3]: f for f in ss.tab(tc.CONTEO_SHEET)[1:]}
    assert conteo['GEOTEK'][7] == 'No' and 'captcha' in conteo['GEOTEK'][8] and conteo['TECNOVIBEARG'][7] == 'Si'
    assert r['eventos'] == {ev.TIENDA_BLOQUEADA: 1}
    txt = corrida.texto_resumen(r)
    assert 'Tiendas bloqueadas por captcha' in txt and 'GEOTEK: captcha' in txt


def test_lo_leido_antes_del_captcha_se_guarda_y_el_conteo_queda_incompleto():
    ss = base()
    lec = LectorFalso(tiendas={URL_TV: _t(20), URL_AC: _t(5, 500), URL_GK: _captcha(48)})
    r = correr(ss, lec, solo='perfiles')
    g = next(f for f in ss.tab(tc.CONTEO_SHEET)[1:] if f[3] == 'GEOTEK')
    assert (g[4], g[5], g[7]) == (48, 122, 'No') and '48 de 122' in g[8]               # leyó 48 de 122: INCOMPLETO (no cuenta para la línea base)
    assert r['perfiles']['items'] == 20 + 5 + 48


def test_un_captcha_aislado_no_corta_aunque_haya_otros_despues_si_hubo_una_tienda_buena_en_el_medio():
    ss = base()
    lec = LectorFalso(tiendas={URL_TV: _captcha(0), URL_AC: _t(5, 500), URL_GK: _captcha(0)})
    r = correr(ss, lec, solo='perfiles')                                               # captcha, ok, captcha: el contador se reinicia
    assert len(r['perfiles']['bloqueadas']) == 2 and r['perfiles']['ok'] == 1


def test_captcha_en_tiendas_seguidas_corta_la_corrida_porque_nos_frena_a_nosotros():
    ss = base()
    lec = LectorFalso(tiendas={URL_TV: _captcha(0), URL_AC: _captcha(0), URL_GK: _t(3, 900)})
    with pytest.raises(corrida.CorridaBloqueada) as e:
        correr(ss, lec, solo='perfiles')
    assert 'tiendas seguidas' in str(e.value) and ('tienda', URL_GK) not in lec.llamadas


def test_login_corta_de_inmediato():
    ss = base()
    lec = LectorFalso(tiendas={URL_TV: {'estado': 'bloqueado', 'bloqueo': 'login', 'items': [], 'detalle': 'ML pidió login'}, URL_AC: _t(5, 500)})
    with pytest.raises(corrida.CorridaBloqueada):
        correr(ss, lec, solo='perfiles')
    assert ('tienda', URL_AC) not in lec.llamadas


def _bloq(tipo='captcha'):
    return {'estado': 'Bloqueado', 'bloqueo': tipo, 'precio': None, 'vendedor': '', 'detalle': f'ML pidió {tipo}'}


def test_publicaciones_un_captcha_se_saltea_tres_seguidos_cortan_y_un_login_corta():
    ss = base()
    tiendas = {u: _t(1) for u in (URL_TV, URL_AC, URL_GK)}
    r = correr(ss, LectorFalso(tiendas=tiendas, pubs={L_WID: _bloq(), L_WID2: ok(3000, 'GEOTEK'), L_ITEM: ok(1000, 'GEOTEK')}), solo='publicaciones')
    assert r['publicaciones']['bloqueadas'] == 1 and r['publicaciones']['ok'] >= 1
    todas = {u: _bloq() for u in (L_WID, L_WID2, L_ITEM)}
    for u in list(todas) + ['https://articulo.mercadolibre.com.ar/MLA-1-x']:
        todas.setdefault(u, _bloq())
    pubs = {k: _bloq() for k in (L_WID, L_WID2, L_ITEM)}
    lec = LectorFalso(tiendas=tiendas, pubs={**{u: _bloq() for u in lec_urls(ss)}, **pubs})
    with pytest.raises(corrida.CorridaBloqueada) as e:
        correr(base(), lec, solo='publicaciones')
    assert 'publicaciones seguidas' in str(e.value)
    with pytest.raises(corrida.CorridaBloqueada):
        correr(base(), LectorFalso(tiendas=tiendas, pubs={L_WID: _bloq('login'), L_WID2: ok(3000), L_ITEM: ok(1)}), solo='publicaciones')


def lec_urls(ss):
    return [L_WID, L_WID2, L_ITEM]


# ── el lector: captcha al pasar de página y espera a un humano ────────────────────────────────────────────────
U = 'https://listado.mercadolibre.com.ar/tienda/geotek'


class FDCaptcha(FD):
    """La página 1 carga bien; al ir a la 2 aparece un captcha (que se 'resuelve' tras N consultas si hay un humano)."""
    def __init__(self, resuelve_tras=None):
        super().__init__({U: cards(48), U + '_Desde_49': cards(48, 48), U + '_Desde_97': cards(26, 96)}, '122 resultados')
        self.resuelve_tras, self.consultas = resuelve_tras, 0

    def execute_script(self, js, *a):
        if 'innerText.slice(0,3000)' in js:
            if self.current_url.endswith('_Desde_49'):
                self.consultas += 1
                if self.resuelve_tras is None or self.consultas <= self.resuelve_tras:
                    return 'Antes de continuar confirmá que no soy un robot'
            return 'texto normal'
        return super().execute_script(js, *a)


def test_captcha_al_pasar_de_pagina_devuelve_lo_leido_y_el_tipo_de_bloqueo():
    r = LectorFD(FDCaptcha()).leer_tienda(U)
    assert r['estado'] == 'bloqueado' and r['bloqueo'] == 'captcha' and len(r['items']) == 48 and r['completa'] is False
    assert '48 de 122' in r['motivo'] and 'página 2' in r['motivo']


def test_con_esperar_captcha_espera_a_que_lo_resuelvas_y_sigue(monkeypatch):
    monkeypatch.setattr(mls.time, 'time', iter(range(10 ** 6)).__next__)        # reloj simulado: no espera de verdad
    lec = LectorFD(FDCaptcha(resuelve_tras=3), esperar_humano_seg=600)
    r = lec.leer_tienda(U)
    assert r['estado'] == 'ok' and len(r['items']) == 122 and r['completa'] is True and r['via_paginacion'] == {'desde_url': 2}


def test_sin_esperar_captcha_no_espera_nada():
    lec = LectorFD(FDCaptcha(resuelve_tras=3))
    assert lec.esperar_humano_seg == 0 and lec._esperar_humano('captcha') is False


# ── login manual: Chrome común, no se cierra solo ─────────────────────────────────────────────────────────────
def test_buscar_chrome_rutas_y_variable():
    import os
    ruta = os.path.join('C:/PF', 'Google', 'Chrome', 'Application', 'chrome.exe')
    assert pc.buscar_chrome({'PROGRAMFILES': 'C:/PF'}, lambda r: r == ruta, lambda n: None) == ruta
    assert pc.buscar_chrome({'CHROME_EXE': 'D:/x/chrome.exe'}, lambda r: r == 'D:/x/chrome.exe', lambda n: None) == 'D:/x/chrome.exe'
    assert pc.buscar_chrome({}, lambda r: False, lambda n: None) is None


def test_el_comando_abre_chrome_comun_sin_banderas_de_automatizacion():
    cmd = pc.comando_chrome('chrome.exe', 'perfil', 'https://x')
    assert cmd[0] == 'chrome.exe' and any(c.startswith('--user-data-dir=') for c in cmd) and cmd[-1] == 'https://x'
    assert not any('automation' in c or 'remote-debugging' in c or 'headless' in c for c in cmd)


def test_un_enter_suelto_no_cierra_nada_hay_que_escribir_listo():
    respuestas = iter(['', '   ', 'no se', 'LISTO'])
    mensajes = []
    assert pc.esperar_listo(lambda p: next(respuestas), mensajes.append, vaciar=lambda: None) is True
    assert sum('no es LISTO' in m for m in mensajes) == 3                              # 3 respuestas que NO eran LISTO: siguió esperando
    assert pc.esperar_listo(lambda p: (_ for _ in ()).throw(EOFError()), lambda m: None, vaciar=lambda: None) is False


def test_configurar_login_abre_chrome_limpia_el_perfil_y_espera(tmp_path, monkeypatch):
    abiertos, liberados = [], []
    monkeypatch.setattr(pc, 'liberar_perfil', lambda perfil, log=print: liberados.append(perfil) or 0)
    r = pc.configurar_login(str(tmp_path / 'perfil'), input_fn=lambda p, r=iter(['', 'listo']): next(r), log=lambda m: None, popen=lambda cmd: abiertos.append(cmd),
                            chrome='chrome.exe', esperar_cierre_seg=0)
    assert r == 'ok' and len(abiertos) == 1 and len(liberados) == 1                    # se abrió UNA vez y se limpió el perfil antes


def test_sin_chrome_instalado_devuelve_sin_chrome(monkeypatch):
    monkeypatch.setattr(pc, 'buscar_chrome', lambda *a, **k: None)
    assert pc.configurar_login('x', log=lambda m: None) == 'sin_chrome'


def test_liberar_perfil_cierra_solo_los_chrome_de_ese_perfil():
    llamadas = []

    class R:
        stdout = '111\n222\n'

    def ejecutar(cmd, **kw):
        llamadas.append(cmd)
        return R()
    n = pc.liberar_perfil('C:\\perfil', lambda m: None, ejecutar, es_windows=True)
    assert n == 2 and any(c[0] == 'taskkill' and c[1:3] == ['/PID', '111'] for c in llamadas)
    assert 'Contains' in llamadas[0][-1] and 'C:\\perfil' in llamadas[0][-1]            # filtra por la carpeta del perfil: tu Chrome diario no se toca
    assert pc.pids_del_perfil('C:\\perfil', ejecutar, es_windows=False) == []           # fuera de Windows no hace nada


def test_si_chrome_no_abre_el_perfil_porque_quedo_tomado_se_libera_y_se_reintenta(monkeypatch):
    intentos, liberados = [], []

    class Chrome:
        def __init__(self, options=None):
            intentos.append(1)
            if len(intentos) == 1:
                raise Exception('session not created: DevToolsActivePort file doesn\'t exist; user data directory is already in use')

        def set_page_load_timeout(self, s): pass
        def set_script_timeout(self, s): pass
        def execute_script(self, js, *a): return None

    class Options:
        def add_argument(self, a): pass
        def add_experimental_option(self, k, v): pass
    sel, wd, ch, op = (types.ModuleType(n) for n in ('selenium', 'selenium.webdriver', 'selenium.webdriver.chrome', 'selenium.webdriver.chrome.options'))
    wd.Chrome, op.Options, sel.webdriver, wd.chrome, ch.options = Chrome, Options, wd, ch, op
    for n, m in (('selenium', sel), ('selenium.webdriver', wd), ('selenium.webdriver.chrome', ch), ('selenium.webdriver.chrome.options', op)):
        monkeypatch.setitem(sys.modules, n, m)
    monkeypatch.setattr(mls.perfil_chrome, 'liberar_perfil', lambda perfil, log=print: liberados.append(perfil) or 1)
    lec = mls.LectorML(perfil_dir='perfil_x', log=lambda m: None)
    assert lec.driver() is not None and len(intentos) == 2 and liberados == ['perfil_x']
