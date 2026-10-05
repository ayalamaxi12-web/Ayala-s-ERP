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


# Busca en la página la TARJETA de una oferta puntual (el wid): cualquier elemento del <body> con un atributo (href, data-*,
# id...) que contenga los dígitos del wid; sube hasta el ancestro más chico que tenga un precio y devuelve ese precio y el
# texto de la tarjeta. Descarta <link>/<meta>/<script> (la URL canónica de la propia página trae el wid). Si el ancestro
# con precio tiene demasiados montos distintos es ambiguo (no es una tarjeta): no se acepta.
JS_OFERTA_POR_WID = r"""
const wid = String(arguments[0] || '').replace(/\D/g, '');
if (!wid) return {encontrada: false, candidatos: [], motivo: 'sin wid'};
const SKIP = new Set(['SCRIPT', 'STYLE', 'LINK', 'META', 'NOSCRIPT', 'HEAD', 'TITLE']);
const montosDe = root => Array.from(root.querySelectorAll('.andes-money-amount'))
  .filter(m => !m.classList.contains('andes-money-amount--previous') && !m.closest('s'));
const precioDe = root => {
  const ms = montosDe(root);
  for (const m of ms) { const f = m.querySelector('.andes-money-amount__fraction'); if (f && (f.innerText || '').trim()) return {txt: f.innerText.trim(), n: ms.length}; }
  return null;
};
const candidatos = [];
const vistos = new Set();
for (const e of document.body.querySelectorAll('*')) {
  if (SKIP.has(e.tagName)) continue;
  let hit = false;
  for (const a of e.attributes) { if (a.value && a.value.indexOf(wid) >= 0) { hit = true; break; } }
  if (!hit) continue;
  let n = e, prof = 0;
  while (n && n !== document.body && prof < 8) {
    const p = precioDe(n);
    if (p) {
      if (!vistos.has(n)) { vistos.add(n); candidatos.push({precio: p.txt, montos: p.n, prof: prof, tag: n.tagName, texto: (n.innerText || '').trim().slice(0, 500)}); }
      break;
    }
    n = n.parentElement; prof++;
  }
}
const buenos = candidatos.filter(c => c.montos <= 3).sort((a, b) => a.montos - b.montos || a.prof - b.prof);
if (!buenos.length) return {encontrada: false, candidatos: candidatos.slice(0, 5), motivo: candidatos.length ? 'ancestro ambiguo' : 'el wid no aparece en la página'};
return {encontrada: true, precio: buenos[0].precio, texto: buenos[0].texto, via: 'tarjeta_wid', candidatos: candidatos.slice(0, 5)};
"""

# Hace clic en "Más opciones de compra" / "Otros vendedores" (lo que haya) para que se listen las demás ofertas.
JS_ABRIR_OPCIONES = r"""
const re = /(m[aá]s|otras|ver)\s+(las\s+)?opciones\s+de\s+compra|ver\s+todas\s+las\s+ofertas|otros\s+vendedores|m[aá]s\s+vendedores|ver\s+m[aá]s\s+ofertas/i;
const els = Array.from(document.querySelectorAll('a, button, [role="button"]'));
const el = els.find(e => re.test((e.innerText || '').trim()) && (e.innerText || '').trim().length < 80);
if (!el) return {clic: false};
const href = el.href || '';
el.scrollIntoView({block: 'center'});
el.click();
return {clic: true, texto: (el.innerText || '').trim().slice(0, 80), href: href};
"""

# Evidencia para el modo prueba: lo que necesito ver para afinar la lectura de catálogo.
JS_EVIDENCIA = r"""
const wid = String(arguments[0] || '').replace(/\D/g, '');
const txt = e => (e.innerText || '').trim();
const html = document.documentElement.outerHTML;
const ctx = [];
for (let i = wid ? html.indexOf(wid) : -1; i >= 0 && ctx.length < 4; i = html.indexOf(wid, i + 1)) ctx.push(html.slice(Math.max(0, i - 160), i + 160));
return {
  url: location.href,
  opciones: Array.from(document.querySelectorAll('a[href], button')).filter(e => /opciones de compra|otros vendedores|m[aá]s vendedores|m[aá]s ofertas/i.test(txt(e))).slice(0, 8)
    .map(e => ({tag: e.tagName, texto: txt(e).slice(0, 80), href: e.href || ''})),
  wid_en_html: ctx,
  wid_veces_en_html: wid ? html.split(wid).length - 1 : 0,
  secciones: Array.from(document.querySelectorAll('h2, h3')).map(txt).filter(Boolean).slice(0, 25),
  ld_json: Array.from(document.querySelectorAll('script[type="application/ld+json"]')).slice(0, 3).map(s => (s.textContent || '').slice(0, 500))
};
"""


class LectorML:
    def __init__(self, perfil_dir=None, headless=False, log=print, api=None):
        self.perfil_dir, self.headless, self.log = perfil_dir or config.PERFIL_CHROME, headless, log
        self.api = api            # ml_api.ApiCatalogo (opcional)
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

    def _snapshot_actual(self):
        return self.driver().execute_script(JS_PUBLICACION)

    def _buscar_oferta(self, wid):
        try:
            return self.driver().execute_script(JS_OFERTA_POR_WID, wid) or {'encontrada': False}
        except Exception as e:  # noqa: BLE001
            return {'encontrada': False, 'motivo': f'JS: {e}'}

    def _evidencia(self, wid):
        try:
            return self.driver().execute_script(JS_EVIDENCIA, wid)
        except Exception as e:  # noqa: BLE001
            return {'error': str(e)}

    def _abrir_opciones(self):
        try:
            r = self.driver().execute_script(JS_ABRIR_OPCIONES) or {'clic': False}
        except Exception as e:  # noqa: BLE001
            return {'clic': False, 'error': str(e)}
        if r.get('clic'):
            time.sleep(2.5)          # el listado de ofertas se arma con JS (modal o página nueva)
            self._ir(self.driver().current_url, '.andes-money-amount__fraction', timeout=8) if r.get('href') else None
        return r

    def leer_publicacion(self, url, esperado=None, diagnostico=False):
        """-> dict de paginas_ml (estado OK|Caida|Error|Sin lectura|Otro vendedor|Bloqueado, precio, vendedor,
        precio_ganador, vendedor_ganador, via, ...). En diagnóstico agrega 'pasos' y 'evidencia' (qué se intentó y qué vio).
        - Ítem directo: la página del ítem.
        - Catálogo CON wid (la oferta que sigue Maca): la página de catálogo muestra a la GANADORA; la oferta del wid se busca
          (1) en la propia página, (2) abriendo 'Más opciones de compra', (3) por API si está configurada, (4) en la página
          del ítem (/MLA-<wid>) que solo existe si la oferta NO es una publicación de catálogo.
        - Catálogo SIN wid: no hay forma de saber de quién es la oferta; se guarda solo el precio de la ganadora."""
        ids = cdb.extraer_ids(url)
        if not (ids['product_id'] and ids['wid']):
            return self._leer_simple(url, esperado, diagnostico)
        wid, pasos, evid = ids['wid'], [], {}
        digitos = re.sub(r'\D', '', wid)

        def paso(nombre, res, extra=None):
            pasos.append(dict({'paso': nombre, 'estado': res.get('estado'), 'precio': res.get('precio'),
                               'vendedor': res.get('vendedor'), 'precio_ganador': res.get('precio_ganador'),
                               'url_final': res.get('url_final'), 'detalle': res.get('detalle')}, **(extra or {})))

        try:
            snap = self._snapshot(url)
        except Exception as e:  # noqa: BLE001
            return {'estado': 'Error', 'precio': None, 'vendedor': '', 'detalle': f'Selenium: {e}', 'url_final': url}
        oferta = self._buscar_oferta(digitos)
        res = pml.clasificar_oferta_en_catalogo(snap, oferta, esperado, url)
        paso('pagina_original', res, {'oferta': {k: oferta.get(k) for k in ('encontrada', 'precio', 'motivo', 'via')}})
        ganador = {k: res.get(k) for k in ('precio_ganador', 'vendedor_ganador')}
        if diagnostico:
            evid['original'] = self._evidencia(digitos)
            evid['original']['candidatos'] = oferta.get('candidatos')
        if res['estado'] == 'Bloqueado':
            return self._cerrar(res, ganador, pasos, evid, diagnostico)

        if res['estado'] != 'OK' or diagnostico:
            clic = self._abrir_opciones()
            if clic.get('clic'):
                try:
                    snap2 = self._snapshot_actual()
                    oferta2 = self._buscar_oferta(digitos)
                    res2 = pml.clasificar_oferta_en_catalogo(snap2, oferta2, esperado, url)
                    res2['via'] = 'opciones_de_compra' if res2.get('estado') == 'OK' else res2.get('via')
                    paso('opciones_de_compra', res2, {'clic': clic, 'oferta': {k: oferta2.get(k) for k in ('encontrada', 'precio', 'motivo')}})
                    if diagnostico:
                        evid['opciones'] = self._evidencia(digitos)
                        evid['opciones']['candidatos'] = oferta2.get('candidatos')
                    if res['estado'] != 'OK' and res2['estado'] == 'OK':
                        res = dict(res2, precio_ganador=ganador['precio_ganador'], vendedor_ganador=ganador['vendedor_ganador'])
                except Exception as e:  # noqa: BLE001
                    paso('opciones_de_compra', {'estado': 'Error', 'detalle': f'Selenium: {e}'}, {'clic': clic})
            else:
                paso('opciones_de_compra', {'estado': 'Sin lectura', 'detalle': 'No encontré el botón de más opciones de compra'}, {'clic': clic})

        if self.api and self.api.disponible() and (res['estado'] != 'OK' or diagnostico):
            a = self.api.leer(ids['product_id'], wid)
            paso('api', {'estado': a['estado'], 'precio': a.get('precio'), 'detalle': a.get('detalle'),
                         'precio_ganador': a.get('precio_ganador')}, {'http': a.get('http'), 'ofertas': a.get('ofertas')})
            if res['estado'] != 'OK' and a['estado'] == 'OK':
                res = dict(res, estado='OK', precio=a['precio'], vendedor=f"seller {a.get('seller_id')}", via='api', detalle='',
                           precio_ganador=ganador['precio_ganador'] or a.get('precio_ganador'))
            if not ganador['precio_ganador'] and a.get('precio_ganador'):
                ganador['precio_ganador'] = a['precio_ganador']

        if res['estado'] != 'OK' or diagnostico:
            directo_url = pml.url_item_directo(wid)
            try:
                rd = pml.clasificar_publicacion(self._snapshot(directo_url), esperado, url, directo=True)
            except Exception as e:  # noqa: BLE001
                rd = {'estado': 'Error', 'precio': None, 'vendedor': '', 'detalle': f'Selenium: {e}', 'url_final': directo_url}
            paso('item_directo', rd, {'url_intentada': directo_url})
            if res['estado'] != 'OK' and rd['estado'] == 'OK':
                res = dict(rd, via='item_directo', precio_ganador=ganador['precio_ganador'], vendedor_ganador=ganador['vendedor_ganador'])
            elif res['estado'] == 'Sin lectura' and rd['estado'] == 'Caida':
                pass   # la página de catálogo vive: no es una caída
        res.setdefault('via', 'pagina_original' if res['estado'] == 'OK' else '')
        return self._cerrar(res, ganador, pasos, evid, diagnostico)

    def _cerrar(self, res, ganador, pasos, evid, diagnostico):
        res = dict(res)
        for k, v in ganador.items():
            if v is not None and not res.get(k):
                res[k] = v
        if diagnostico:
            res['pasos'], res['evidencia'] = pasos, evid
        return res

    def _leer_simple(self, url, esperado, diagnostico):
        """Ítem directo o catálogo sin wid: una sola página."""
        try:
            res = pml.clasificar_publicacion(self._snapshot(url), esperado, url)
        except Exception as e:  # noqa: BLE001
            res = {'estado': 'Error', 'precio': None, 'vendedor': '', 'detalle': f'Selenium: {e}', 'url_final': url}
        res['via'] = 'pagina_original' if res['estado'] == 'OK' else ''
        if diagnostico:
            res['pasos'] = [{'paso': 'pagina_original', 'estado': res['estado'], 'precio': res.get('precio'),
                             'vendedor': res.get('vendedor'), 'precio_ganador': res.get('precio_ganador'),
                             'url_final': res.get('url_final'), 'detalle': res.get('detalle')}]
        return res

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
