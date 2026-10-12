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
import perfil_chrome
from errores import NavegadorCaido, es_error_de_sesion, es_timeout

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


# Cuántas publicaciones declara ML en el listado de la tienda ("1.234 resultados"). El selector es una SUPOSICIÓN (no pude abrir
# ML): se prueban los habituales y, si no, se busca el texto "N resultados" en la página. El modo prueba muestra los candidatos.
JS_DECLARADAS = r"""
const sels = ['.ui-search-search-result__quantity-results', '.ui-search-search-result__quantity-results span',
              '[class*="quantity-results"]', '[class*="search-result__quantity"]'];
let texto = '';
for (const s of sels) { const e = document.querySelector(s); if (e && (e.innerText || '').trim()) { texto = e.innerText.trim(); break; } }
if (!texto) { const m = (document.body.innerText || '').match(/[^\n]{0,40}\d[\d\.\,]*\s+resultados?[^\n]{0,20}/i); texto = m ? m[0].trim() : ''; }
const cand = Array.from(document.querySelectorAll('span, p, div, h1, h2')).filter(e => e.children.length === 0 && /\d\s+resultados?/i.test(e.innerText || ''))
  .slice(0, 5).map(e => ({clase: String(e.className || '').slice(0, 80), texto: (e.innerText || '').trim().slice(0, 80)}));
return {texto: texto, candidatos: cand};
"""


# Evidencia de paginación (para entender por qué una tienda queda INCOMPLETA): qué controles de "siguiente"/"ver más" hay.
JS_PAGINACION = r"""
const pag = document.querySelector('.andes-pagination');
return {
  url: location.href,
  paginacion_html: pag ? pag.outerHTML.slice(0, 900) : '',
  controles: Array.from(document.querySelectorAll('a, button')).filter(e => /siguiente|m[aá]s|next/i.test((e.innerText || '') + (e.getAttribute('aria-label') || '') + (e.title || '')))
    .slice(0, 8).map(e => ({tag: e.tagName, texto: (e.innerText || '').trim().slice(0, 40), aria: e.getAttribute('aria-label') || '', clase: String(e.className || '').slice(0, 70), href: (e.href || '').slice(0, 120)})),
  tarjetas: document.querySelectorAll('.poly-card, .ui-search-result').length,
  altura: document.body.scrollHeight
};
"""

# "Ver más" / "Mostrar más" / "Cargar más": algunas tiendas cargan el resto con un botón en vez de paginar.
JS_VER_MAS = r"""
const re = /^(ver|mostrar|cargar)\s+m[aá]s(\s+(resultados|productos|publicaciones))?$/i;
const el = Array.from(document.querySelectorAll('a, button, [role="button"]')).find(e => re.test((e.innerText || '').trim()));
if (!el) return false;
el.scrollIntoView({block: 'center'});
el.click();
return true;
"""


class LectorML:
    def __init__(self, perfil_dir=None, headless=False, log=print, api=None, esperar_humano_seg=0):
        self.perfil_dir, self.headless, self.log = perfil_dir or config.PERFIL_CHROME, headless, log
        self.esperar_humano_seg = esperar_humano_seg      # >0: corrida CON vos adelante: ante un captcha, esperar a que lo resuelvas
        self.api = api            # ml_api.ApiCatalogo (opcional)
        self._driver = None
        self._navs = 0            # navegaciones desde que se abrió Chrome (para reciclarlo antes de que se quede sin memoria)
        self.reinicios = 0        # cuántas veces se reabrió Chrome en esta corrida

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
            o.add_argument('--disable-dev-shm-usage')
            o.add_argument('--disable-background-timer-throttling')
            o.add_argument('--disable-renderer-backgrounding')         # corrida desatendida: que Chrome no se "duerma" en segundo plano
            o.add_experimental_option('excludeSwitches', ['enable-automation'])
            o.add_experimental_option('useAutomationExtension', False)
            if self.headless:
                o.add_argument('--headless=new')
            try:
                self._driver = webdriver.Chrome(options=o)    # Selenium Manager baja el chromedriver que corresponda solo
            except Exception as e:  # noqa: BLE001
                if not any(f in str(e).lower() for f in ('already in use', 'devtoolsactiveport', 'failed to start', 'session not created')):
                    raise
                # el perfil quedó tomado por un Chrome que se cayó a medias: se cierra solo ESE y se reintenta una vez
                self.log(f'  ⚠ Chrome no pudo abrir el perfil ({str(e).splitlines()[0][:90]}). Libero el perfil y reintento.')
                perfil_chrome.liberar_perfil(self.perfil_dir, self.log)
                self._driver = webdriver.Chrome(options=o)
            self._driver.set_page_load_timeout(config.TIMEOUT_PAGINA_SEG)
            self._driver.set_script_timeout(config.TIMEOUT_PAGINA_SEG)
            self._driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        return self._driver

    def cerrar(self):
        if self._driver is not None:
            try:
                self._driver.quit()
            except Exception:  # noqa: BLE001  (si Chrome ya murió, quit() también falla: no importa)
                pass
            finally:
                self._driver = None

    def reiniciar(self, motivo):
        """Cierra Chrome (esté como esté) y deja que se abra uno nuevo con el MISMO perfil: la sesión de ML sigue ahí."""
        self.reinicios += 1
        if self.reinicios > config.MAX_REINICIOS:
            raise NavegadorCaido(f'Chrome se reinició {self.reinicios - 1} veces en esta corrida ({motivo}): algo anda mal con el navegador o la PC.')
        self.log(f'  ↻ Reabriendo Chrome ({motivo}) · reinicio {self.reinicios}/{config.MAX_REINICIOS}')
        self.cerrar()
        self._navs = 0
        time.sleep(3)

    def _bloqueo_actual(self):
        d = self.driver()
        return pml.detectar_bloqueo(d.current_url, d.execute_script('return document.body ? document.body.innerText.slice(0,3000) : ""'))

    def _esperar_humano(self, tipo):
        """Corrida CON vos adelante (--esperar-captcha): avisa y espera hasta N minutos a que resuelvas el captcha/verificación en la
        ventana de Chrome. -> True si se resolvió. Sin esa opción (la tarea desatendida) no espera: el captcha se saltea."""
        if not self.esperar_humano_seg:
            return False
        self.log(f'  🔔 ML pidió {tipo}. Resolvelo en la ventana de Chrome: espero hasta {self.esperar_humano_seg // 60} min...')
        print('\a', end='')
        fin = time.time() + self.esperar_humano_seg
        while time.time() < fin:
            time.sleep(3)
            d = self.driver()
            if not pml.detectar_bloqueo(d.current_url, d.execute_script('return document.body ? document.body.innerText.slice(0,3000) : ""')):
                self.log('  ✓ Resuelto, sigo.')
                time.sleep(2)
                return True
        self.log('  (se acabó el tiempo de espera)')
        return False

    def _con_reintento(self, fn, fallo, *a, **k):
        """Ejecuta una LECTURA completa; si Chrome se cae a la mitad, lo reabre y la reintenta (hasta REINTENTOS_SESION veces).
        Si esa lectura sigue matando a Chrome, devuelve el resultado de `fallo` (se sigue con la próxima, no se corta todo)."""
        for intento in range(config.REINTENTOS_SESION + 1):
            try:
                return fn(*a, **k)
            except Exception as e:  # noqa: BLE001
                if not es_error_de_sesion(e):
                    raise
                self.log(f'  ⚠ El navegador se cayó ({str(e).splitlines()[0][:110]})')
                if intento >= config.REINTENTOS_SESION:
                    self.reiniciar('sesión caída')       # lo deja listo para la próxima lectura
                    return fallo(f'El navegador se cayó {intento + 1} veces leyendo esto')
                self.reiniciar('sesión caída')
        return fallo('El navegador no se pudo recuperar')

    def _ir(self, url, esperar_css=None, timeout=15):
        self._navs += 1
        if self._navs > config.RECICLAR_CADA_NAVEGACIONES:
            self.reiniciar('reciclado preventivo')       # una sesión de Chrome muy larga termina sin memoria
            self._navs = 1
        d = self.driver()
        try:
            d.get(url)
        except Exception as e:  # noqa: BLE001
            if es_error_de_sesion(e) or not es_timeout(e):
                raise
            try:
                d.execute_script('window.stop()')          # la página tardó demasiado: se usa lo que alcanzó a cargar
            except Exception:  # noqa: BLE001
                pass
        fin = time.time() + timeout
        while time.time() < fin:
            try:
                if d.execute_script('return document.readyState') == 'complete':
                    break
            except Exception as e:  # noqa: BLE001
                if es_error_de_sesion(e):
                    raise
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
            except Exception as e:  # noqa: BLE001
                if es_error_de_sesion(e):
                    raise
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
            if es_error_de_sesion(e):
                raise
            return {'encontrada': False, 'motivo': f'JS: {e}'}

    def _evidencia(self, wid):
        try:
            return self.driver().execute_script(JS_EVIDENCIA, wid)
        except Exception as e:  # noqa: BLE001
            if es_error_de_sesion(e):
                raise
            return {'error': str(e)}

    def _abrir_opciones(self):
        try:
            r = self.driver().execute_script(JS_ABRIR_OPCIONES) or {'clic': False}
        except Exception as e:  # noqa: BLE001
            if es_error_de_sesion(e):
                raise
            return {'clic': False, 'error': str(e)}
        if r.get('clic'):
            time.sleep(2.5)          # el listado de ofertas se arma con JS (modal o página nueva)
            self._ir(self.driver().current_url, '.andes-money-amount__fraction', timeout=8) if r.get('href') else None
        return r

    def leer_publicacion(self, url, esperado=None, diagnostico=False):
        fallo = lambda msg: {'estado': 'Error', 'precio': None, 'vendedor': '', 'detalle': msg, 'url_final': url}  # noqa: E731
        res = self._con_reintento(self._leer_publicacion_impl, fallo, url, esperado, diagnostico)
        if res.get('estado') == 'Bloqueado' and self.esperar_humano_seg and self._esperar_humano(res.get('bloqueo') or 'captcha'):
            res = self._con_reintento(self._leer_publicacion_impl, fallo, url, esperado, diagnostico)     # lo resolviste: se lee de nuevo
        return res

    def _leer_publicacion_impl(self, url, esperado=None, diagnostico=False):
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
            if es_error_de_sesion(e):
                raise
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
                    if es_error_de_sesion(e):
                        raise
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
                if es_error_de_sesion(e):
                    raise
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
            if es_error_de_sesion(e):
                raise
            res = {'estado': 'Error', 'precio': None, 'vendedor': '', 'detalle': f'Selenium: {e}', 'url_final': url}
        res['via'] = 'pagina_original' if res['estado'] == 'OK' else ''
        if diagnostico:
            res['pasos'] = [{'paso': 'pagina_original', 'estado': res['estado'], 'precio': res.get('precio'),
                             'vendedor': res.get('vendedor'), 'precio_ganador': res.get('precio_ganador'),
                             'url_final': res.get('url_final'), 'detalle': res.get('detalle')}]
        return res

    # ── tienda completa ──────────────────────────────────────────────────────
    def leer_tienda(self, url, max_paginas=40, diagnostico=False):
        return self._con_reintento(self._leer_tienda_impl,
                                   lambda msg: {'estado': 'error', 'items': [], 'detalle': msg, 'declaradas': None, 'paginas': 0,
                                                'fin': 'excepcion', 'completa': False, 'motivo': msg},
                                   url, max_paginas, diagnostico)

    def _leer_tienda_impl(self, url, max_paginas=40, diagnostico=False):
        """-> {'estado': 'ok'|'sin_resultados'|'bloqueado'|'error', 'items': [...], 'detalle': str,
               'declaradas': int|None, 'paginas': int, 'fin': str, 'completa': bool, 'motivo': str, 'via_paginacion': {...}}
        (+ 'evidencia_paginacion' si quedó incompleta o en diagnóstico).
        El link de cada tarjeta se guarda COMPLETO (con ?wid=...): el scraper viejo lo cortaba en '?' y perdía la
        identidad de las ofertas de catálogo. Se deduplica por identidad de publicación, no por título.
        `completa` (ver paginas_ml.evaluar_completitud) dice si se puede confiar en el conteo: sin bloqueo, llegó al final
        y leyó al menos COMPLETITUD_MIN_PCT% de lo que ML declara.
        Paginación: botón "Siguiente" (con clic normal y, si algo tapa el botón, clic por JavaScript) -> botón "Ver más" ->
        URL por offset (`_Desde_n`) cuando ML declara más publicaciones de las leídas."""
        items, vistos_pag, vistos_item, vias = [], set(), set(), {}
        declaradas, paginas, fin, evid, por_pagina, via_prev = None, 0, 'excepcion', {}, 0, None
        try:
            self._ir(url, '.poly-card, .ui-search-result')
            d = self.driver()
            b = self._bloqueo_actual()
            if b and self._esperar_humano(b):
                b = self._bloqueo_actual()
            if b:
                return {'estado': 'bloqueado', 'items': [], 'detalle': f'ML pidió {b} al abrir la tienda', 'bloqueo': b, 'declaradas': None,
                        'paginas': 0, 'fin': 'bloqueado', 'completa': False, 'motivo': f'ML pidió {b} al abrir la tienda', 'via_paginacion': {}}
            try:
                dec = d.execute_script(JS_DECLARADAS) or {}
                declaradas = pml.parse_declaradas(dec.get('texto'))
                if diagnostico:
                    evid = {'texto_declaradas': dec.get('texto'), 'candidatos': dec.get('candidatos')}
            except Exception as e:  # noqa: BLE001
                if es_error_de_sesion(e):
                    raise
                evid = {'error_declaradas': str(e)}
            fin = 'tope_paginas'
            for pagina in range(1, max_paginas + 1):
                d = self.driver()
                if via_prev != 'ver_mas' and d.current_url in vistos_pag:
                    fin = 'repetida'
                    break
                if pagina > 1:        # el captcha también puede aparecer AL PASAR de página (antes solo se miraba al abrir la tienda)
                    b = self._bloqueo_actual()
                    if b and self._esperar_humano(b):
                        b = self._bloqueo_actual()
                    if b:
                        motivo = f'ML pidió {b} en la página {pagina}: leyó {len(items)}' + (f' de {declaradas} declaradas' if declaradas else '')
                        return {'estado': 'bloqueado', 'items': items, 'detalle': motivo, 'bloqueo': b, 'declaradas': declaradas,
                                'paginas': pagina - 1, 'fin': 'bloqueado', 'completa': False, 'motivo': motivo, 'via_paginacion': vias}
                vistos_pag.add(d.current_url)
                self._scroll()
                tarjetas = d.execute_script(JS_TARJETAS) or []
                paginas = pagina
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
                if via_prev != 'ver_mas':
                    por_pagina = max(por_pagina, len(tarjetas))
                if not tarjetas:
                    fin = 'sin_tarjetas'
                    break
                if via_prev in ('desde_url', 'ver_mas') and nuevas == 0:
                    fin = 'sin_siguiente'              # la alternativa no trajo nada nuevo: se terminó
                    break
                via_prev = self._avanzar(url, pagina, por_pagina, len(items), declaradas)
                if via_prev is None:
                    fin = 'sin_siguiente'
                    break
                vias[via_prev] = vias.get(via_prev, 0) + 1
                time.sleep(1)
        except Exception as e:  # noqa: BLE001
            if es_error_de_sesion(e):
                raise
            ok_, motivo = pml.evaluar_completitud(len(items), declaradas, 'excepcion')
            return {'estado': 'error', 'items': items, 'detalle': f'Selenium: {e}', 'declaradas': declaradas, 'paginas': paginas,
                    'fin': 'excepcion', 'completa': False, 'motivo': motivo or f'Selenium: {e}', 'via_paginacion': vias}
        completa, motivo = pml.evaluar_completitud(len(items), declaradas, fin)
        if declaradas:
            self.log(f'    ML declara {declaradas} · leídas {len(items)} · {"completa" if completa else "INCOMPLETA: " + motivo}'
                     + (f' · paginación: {vias}' if vias else ''))
        out = {'estado': 'ok' if items else 'sin_resultados', 'items': items, 'detalle': '', 'declaradas': declaradas,
               'paginas': paginas, 'fin': fin, 'completa': completa, 'motivo': motivo, 'via_paginacion': vias}
        if diagnostico:
            out['evidencia'] = evid
        if diagnostico or not completa:
            try:   # qué controles de paginación hay en la página donde se frenó: es lo que hace falta para arreglarlo
                out['evidencia_paginacion'] = self.driver().execute_script(JS_PAGINACION)
            except Exception as e:  # noqa: BLE001
                if es_error_de_sesion(e):
                    raise
                out['evidencia_paginacion'] = {'error': str(e)}
        return out

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

    def _siguiente(self):
        """Clic en "Siguiente". Si algo tapa el botón (cartel de cookies, widget de chat, banner fijo) el clic normal falla con
        ElementClickIntercepted: antes eso se tomaba por "no hay más páginas"; ahora se reintenta con un clic por JavaScript."""
        d = self.driver()
        for sel in ('.andes-pagination__button--next a', 'a[title="Siguiente"]', 'a[aria-label="Siguiente"]'):
            try:
                el = d.find_element('css selector', sel)
            except Exception as e:  # noqa: BLE001  (no está ese selector: probar el siguiente)
                if es_error_de_sesion(e):
                    raise
                continue
            if 'disabled' in (el.find_element('xpath', '..').get_attribute('class') or ''):
                return False
            try:
                d.execute_script('arguments[0].scrollIntoView({block: "center"});', el)
                el.click()
            except Exception as e:  # noqa: BLE001
                if es_error_de_sesion(e):
                    raise
                d.execute_script('arguments[0].click();', el)     # lo tapa algo: clic directo sobre el elemento
            time.sleep(2)
            return True
        return False

    def _ver_mas(self):
        try:
            clic = self.driver().execute_script(JS_VER_MAS)
        except Exception as e:  # noqa: BLE001
            if es_error_de_sesion(e):
                raise
            return False
        if clic:
            time.sleep(2.5)
        return bool(clic)

    def _avanzar(self, url_base, pagina, por_pagina, leidas, declaradas):
        """Pasa a lo siguiente de la tienda. -> 'boton' | 'ver_mas' | 'desde_url' | None (no hay más).
        Los planes B solo se prueban si ML declara MÁS publicaciones de las que se leyeron."""
        if self._siguiente():
            return 'boton'
        if declaradas and leidas < declaradas * 0.98:
            if self._ver_mas():
                return 'ver_mas'
            nxt = pml.url_pagina_siguiente(url_base, pagina, por_pagina)
            if nxt:
                self.log(f'    sin botón "Siguiente" pero ML declara {declaradas} y van {leidas}: pruebo la URL por offset {nxt[-40:]}')
                self._ir(nxt, '.poly-card, .ui-search-result')
                return 'desde_url'
        return None


def configurar_login(perfil_dir=None):
    """Login manual de Mercado Libre. Abre un Chrome COMÚN (sin Selenium) con el perfil del scraper y espera a que escribas LISTO
    (perfil_chrome.configurar_login). Solo si no se encuentra chrome.exe usa Selenium, y aun así NO se cierra por un error ni por un ENTER suelto."""
    r = perfil_chrome.configurar_login(perfil_dir)
    if r != 'sin_chrome':
        return r
    print('No encontré chrome.exe (probá definir la variable CHROME_EXE). Uso el modo con Selenium.')
    perfil_chrome.liberar_perfil(perfil_dir or config.PERFIL_CHROME)
    lector = LectorML(perfil_dir, headless=False)
    try:
        d = lector.driver()
        try:
            d.get('https://www.mercadolibre.com.ar/')
        except Exception as e:  # noqa: BLE001  (una página que tarda o un captcha no tiene que cerrar la ventana)
            print(f'(la página no terminó de cargar: {str(e).splitlines()[0][:100]}; seguí a mano en la ventana de Chrome)')
        print('\nSe abrió Chrome con el perfil del scraper. Iniciá sesión, resolvé los captchas y confirmá que ves los precios.')
        perfil_chrome.esperar_listo()
    finally:
        lector.cerrar()
    return 'ok'
