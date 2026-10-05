"""Lector de Mercado Libre con Selenium + perfil de Chrome persistente (te logueás UNA vez a mano; después corre solo).
NO guarda usuario ni contraseña en ningún lado: la sesión vive en la carpeta del perfil (config.PERFIL_CHROME).

IMPORTANTE: los selectores de ML cambian y yo no pude probarlos contra el sitio real desde mi entorno. Por eso existe
el modo prueba (`scraper.py --probar 20`): lee ~20 links y NO escribe nada, y muestra qué vio en cada página.
La lógica de decisión está en paginas_ml.py (pura y con tests); acá solo se extrae el contenido de la página."""
import re
import time

import config
import competencia_db as cdb
import paginas_ml as pml

JS_PUBLICACION = r"""
const q = s => document.querySelector(s);
const t = e => e ? (e.innerText || '').trim() : '';
const primero = (...sels) => { for (const s of sels) { const v = t(q(s)); if (v) return v; } return ''; };
return {
  url: location.href,
  titulo: document.title,
  texto: (document.body.innerText || '').slice(0, 8000),
  precio: primero('.ui-pdp-price__second-line .andes-money-amount__fraction', '.ui-pdp-price .andes-money-amount__fraction',
                  '[class*="price"] .andes-money-amount__fraction'),
  tachado: primero('.ui-pdp-price__original-value .andes-money-amount__fraction',
                   's.andes-money-amount--previous .andes-money-amount__fraction'),
  descuento: primero('.ui-pdp-price__second-line__label', '.andes-money-amount__discount'),
  cuotas: primero('.ui-pdp-price__subtitles', '#pricing_price_subtitle'),
  vendedor: primero('.ui-pdp-seller__header__title', '.ui-pdp-seller__link-trigger', '.ui-pdp-seller__label-sold',
                    '[class*="seller"] a')
};
"""

JS_TARJETAS = r"""
const num = s => (s || '').replace(/[^\d]/g, '');
const out = [];
let cards = document.querySelectorAll('.poly-card');
if (!cards.length) cards = document.querySelectorAll('.ui-search-result__wrapper');
cards.forEach(c => {
  const g = s => { const e = c.querySelector(s); return e ? (e.innerText || '').trim() : ''; };
  const a = c.querySelector('a');
  let precio = num(g('.poly-price__current .andes-money-amount__fraction'));
  if (!precio) { const fr = c.querySelectorAll('.andes-money-amount__fraction'); if (fr.length) precio = num(fr[fr.length - 1].innerText); }
  out.push({
    title: g('.poly-component__title') || g('.ui-search-item__title'),
    link: a ? a.href : '',
    price: parseInt(precio || '0', 10),
    orig_price: parseInt(num(g('s.andes-money-amount--previous .andes-money-amount__fraction')) || '0', 10) || '',
    discount: g('.andes-money-amount__discount'),
    cuotas: g('.poly-price__installments') || g('.poly-component__installments')
  });
});
return out;
"""


class LectorML:
    def __init__(self, perfil_dir=None, headless=False, log=print):
        self.perfil_dir, self.headless, self.log = perfil_dir or config.PERFIL_CHROME, headless, log
        self._driver = None

    # ── navegador ────────────────────────────────────────────────────────────
    def driver(self):
        if self._driver is None:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            o = Options()
            o.add_argument(f'--user-data-dir={self.perfil_dir}')       # perfil PROPIO del scraper (no tu Chrome de todos los días)
            o.add_argument('--profile-directory=Default')
            o.add_argument('--no-first-run')
            o.add_argument('--no-default-browser-check')
            o.add_argument('--lang=es-AR')
            o.add_argument('--window-size=1366,900')
            o.add_argument('--disable-blink-features=AutomationControlled')
            o.add_experimental_option('excludeSwitches', ['enable-automation'])
            o.add_experimental_option('useAutomationExtension', False)
            if self.headless:
                o.add_argument('--headless=new')
            self._driver = webdriver.Chrome(options=o)    # Selenium Manager baja el chromedriver que corresponda solo
            self._driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        return self._driver

    def cerrar(self):
        if self._driver is not None:
            try:
                self._driver.quit()
            finally:
                self._driver = None

    def _ir(self, url, esperar_css=None, timeout=15):
        d = self.driver()
        d.get(url)
        fin = time.time() + timeout
        while time.time() < fin:
            try:
                if d.execute_script('return document.readyState') == 'complete':
                    break
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.4)
        # ML arma el precio con JS: espero a que aparezca (o a que la página diga que no existe)
        fin = time.time() + 8
        while time.time() < fin:
            try:
                if esperar_css and d.find_elements('css selector', esperar_css):
                    return
                cuerpo = (d.execute_script('return document.body ? document.body.innerText.slice(0, 4000) : ""') or '').lower()
                if pml.detectar_bloqueo(d.current_url, cuerpo) or any(f in cuerpo for f in pml.CAIDA_FRASES):
                    return
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.5)

    # ── publicación puntual ──────────────────────────────────────────────────
    def _snapshot(self, url):
        self._ir(url, '.andes-money-amount__fraction')
        return self.driver().execute_script(JS_PUBLICACION)

    def leer_publicacion(self, url, esperado=None, diagnostico=False):
        """-> dict de paginas_ml.clasificar_publicacion (+ 'intentos' en diagnóstico).
        Catálogo con wid: primero la URL tal cual; si no se puede atribuir, la página del ítem puntual de la oferta."""
        ids = cdb.extraer_ids(url)
        intentos = [(url, False)]
        if ids['product_id'] and ids['wid']:
            intentos.append((pml.url_item_directo(ids['wid']), True))
        hechos = []
        for u, directo in intentos:
            try:
                res = pml.clasificar_publicacion(self._snapshot(u), esperado, url, directo=directo)
            except Exception as e:  # noqa: BLE001
                res = {'estado': 'Error', 'precio': None, 'vendedor': '', 'detalle': f'Selenium: {e}', 'url_final': u}
            res['intento'] = 'directo' if directo else 'original'
            res['url_intentada'] = u
            hechos.append(res)
            if res['estado'] == 'Bloqueado' or (res['estado'] == 'OK' and not diagnostico):
                break
        orden = ['OK', 'Caida', 'Otro vendedor', 'Sin lectura', 'Error', 'Bloqueado']
        mejor = dict(sorted(hechos, key=lambda r: orden.index(r['estado']) if r['estado'] in orden else 9)[0])
        if any(r['estado'] == 'Bloqueado' for r in hechos):
            mejor = next(r for r in hechos if r['estado'] == 'Bloqueado')
        # Caída solo si TODOS los intentos dicen caída (un catálogo muerto en /p/ puede seguir vivo en el ítem)
        if mejor['estado'] == 'Caida' and not all(r['estado'] == 'Caida' for r in hechos):
            mejor = next(r for r in hechos if r['estado'] != 'Caida')
        if diagnostico:
            mejor['intentos'] = [{k: r.get(k) for k in ('intento', 'url_intentada', 'url_final', 'estado', 'precio',
                                                         'vendedor', 'detalle')} for r in hechos]
        return mejor

    # ── tienda completa ──────────────────────────────────────────────────────
    def leer_tienda(self, url, max_paginas=40):
        """-> {'estado': 'ok'|'sin_resultados'|'bloqueado'|'error', 'items': [...], 'detalle': str}.
        El link de cada tarjeta se guarda COMPLETO (con ?wid=...): el scraper viejo lo cortaba en '?' y perdía la
        identidad de las ofertas de catálogo. Se deduplica por identidad de publicación, no por título."""
        from selenium.webdriver.common.by import By
        d = self.driver()
        items, vistos_pag, vistos_item = [], set(), set()
        try:
            self._ir(url, '.poly-card, .ui-search-result')
            b = pml.detectar_bloqueo(d.current_url, d.execute_script('return document.body.innerText.slice(0,3000)'))
            if b:
                return {'estado': 'bloqueado', 'items': [], 'detalle': f'ML pidió {b} al abrir la tienda'}
            for pagina in range(1, max_paginas + 1):
                if d.current_url in vistos_pag:
                    break
                vistos_pag.add(d.current_url)
                self._scroll()
                tarjetas = d.execute_script(JS_TARJETAS) or []
                nuevas = 0
                for t in tarjetas:
                    if not (t['title'] and t['price']):
                        continue
                    k = (t['link'] and (cdb.clave_ref(t['link']) or t['link'])) or t['title']
                    if k in vistos_item:
                        continue
                    vistos_item.add(k)
                    items.append(t)
                    nuevas += 1
                self.log(f'    página {pagina}: {len(tarjetas)} tarjetas, {nuevas} nuevas (total {len(items)})')
                if not tarjetas or not self._siguiente(By):
                    break
                time.sleep(1)
        except Exception as e:  # noqa: BLE001
            return {'estado': 'error', 'items': items, 'detalle': f'Selenium: {e}'}
        return {'estado': 'ok' if items else 'sin_resultados', 'items': items, 'detalle': ''}

    def _scroll(self):
        d = self.driver()
        ultimo = d.execute_script('return document.body.scrollHeight')
        for _ in range(20):
            d.execute_script('window.scrollTo(0, document.body.scrollHeight);')
            time.sleep(1.2)
            nuevo = d.execute_script('return document.body.scrollHeight')
            if nuevo == ultimo:
                break
            ultimo = nuevo

    def _siguiente(self, By):
        d = self.driver()
        for sel in ('.andes-pagination__button--next a', 'a[title="Siguiente"]', 'a[aria-label="Siguiente"]'):
            try:
                el = d.find_element(By.CSS_SELECTOR, sel)
                if 'disabled' in (el.find_element(By.XPATH, '..').get_attribute('class') or ''):
                    return False
                el.click()
                time.sleep(2)
                return True
            except Exception:  # noqa: BLE001
                continue
        return False


def configurar_login(perfil_dir=None):
    """Abre Chrome VISIBLE con el perfil del scraper para que te loguees en Mercado Libre UNA vez. No se guarda
    ninguna contraseña: queda la sesión (cookies) en la carpeta del perfil."""
    lector = LectorML(perfil_dir, headless=False)
    d = lector.driver()
    d.get('https://www.mercadolibre.com.ar/')
    print('\nSe abrió Chrome con el perfil del scraper.')
    print('1) Iniciá sesión en Mercado Libre con tu cuenta (y resolvé cualquier verificación que te pida).')
    print('2) Abrí cualquier publicación para confirmar que ves los precios.')
    input('3) Cuando termines, volvé acá y apretá ENTER para cerrar Chrome y guardar la sesión... ')
    lector.cerrar()
