"""Clasificación de páginas de Mercado Libre. LÓGICA PURA sobre un "snapshot" (dict con el texto/DOM ya extraído),
así se prueba sin navegador. El extractor real (Selenium) vive en ml_selenium.py.

Principio: ante la duda NO se inventa un precio ni una caída. Timeout, login, captcha o un layout que no entendemos
son 'Bloqueado'/'Error', jamás 'Caida'."""
import re

import config
import competencia_db as cdb

CAIDA_FRASES = (
    'publicación finalizada', 'publicacion finalizada', 'esta publicación ya no está disponible',
    'esta publicación está pausada', 'publicación pausada', 'publicación no disponible',
    'la publicación que buscás no existe', 'no encontramos la página', 'ya no está disponible',
)
BLOQUEO_URL = ('/login', 'account-verification', 'verification', 'captcha', 'security', '/gz/account')
BLOQUEO_TEXTO = ('ingresá tu e-mail', 'ingresa tu e-mail', 'no soy un robot', 'verificá tu cuenta',
                 'verifica tu cuenta', 'confirmá que sos una persona', 'iniciar sesión para continuar')


def detectar_bloqueo(url, texto):
    """-> 'login'|'verificacion'|'captcha'|None. Si ML pide login/verificación, el scraper NO sigue (a las 17:30 no
    hay nadie para resolverlo): se corta la corrida y se avisa en el log."""
    u, t = str(url or '').lower(), str(texto or '').lower()[:3000]
    if 'captcha' in u or 'no soy un robot' in t or 'confirmá que sos una persona' in t:
        return 'captcha'
    if 'account-verification' in u or 'verification' in u or 'verificá tu cuenta' in t or 'verifica tu cuenta' in t:
        return 'verificacion'
    if '/login' in u or 'ingresá tu e-mail' in t or 'ingresa tu e-mail' in t or 'iniciar sesión para continuar' in t:
        return 'login'
    return None


def _vendedor_de(snap):
    v = str(snap.get('vendedor') or '').strip()
    if not v:
        m = re.search(r'vendido por\s+([^\n|]+)', str(snap.get('texto') or ''), re.I)
        v = m.group(1).strip() if m else ''
    v = re.sub(r'^(vendido por|tienda oficial de|tienda oficial|vendedor:?)\s*', '', v, flags=re.I).strip()
    return v


def vendedor_de_texto(texto):
    """Vendedor a partir del texto suelto de una tarjeta de oferta ('Vendido por X', 'Tienda oficial X', 'Por X')."""
    t = str(texto or '')
    for pat in (r'vendido por\s+([^\n|]+)', r'tienda oficial(?: de)?\s+([^\n|]+)', r'(?:^|\n)por\s+([^\n|]{2,60})'):
        m = re.search(pat, t, re.I)
        if m:
            return m.group(1).strip()
    return ''


def coincide_vendedor(visto, esperado):
    """¿El vendedor de la página es el esperado? Igualdad/contención normalizada, más los alias de tienda
    confirmados (p. ej. tienda 'tecnovibe' <-> entidad TECNOVIBEARG)."""
    a, b = re.sub(r'[^a-z0-9]', '', cdb.norm_texto(visto)), re.sub(r'[^a-z0-9]', '', cdb.norm_texto(esperado))
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    for slug, nombre in config.ALIAS_TIENDAS.items():
        s, n = re.sub(r'[^a-z0-9]', '', slug), re.sub(r'[^a-z0-9]', '', cdb.norm_texto(nombre))
        if n == b and (s in a or a in s):
            return True
        if n == a and (s in b or b in s):
            return True
    return False


def _digitos_wid(url):
    m = re.search(r'wid=ML[A-Z]-?(\d+)', str(url or ''), re.I) or re.search(r'/ML[A-Z]-?(\d{8,})', str(url or ''), re.I)
    return m.group(1) if m else ''


def clasificar_publicacion(snap, esperado=None, url_original=None, directo=False):
    """snap: {url, texto, precio, tachado, descuento, cuotas, vendedor}. -> dict con 'estado':
    OK | Caida | Error | Sin lectura | Otro vendedor | Bloqueado (+ precio, tachado, descuento, cuotas, vendedor, detalle).
    En catálogo (/p/) sin el vendedor visible NO se acepta el precio: sería el de la oferta ganadora, no la de ese
    vendedor (queda 'Sin lectura'). Excepción: `directo=True` = se abrió la página del ítem puntual de la oferta (el
    `wid`) y la URL final conserva ese id: ahí el wid ya identifica la oferta, aunque no sepamos aún quién es."""
    url_original = url_original or snap.get('url', '')
    base = {'url_final': snap.get('url', ''), 'vendedor': _vendedor_de(snap), 'precio': None, 'tachado': None,
            'descuento': '', 'cuotas': '', 'detalle': ''}
    bloqueo = detectar_bloqueo(snap.get('url'), snap.get('texto'))
    if bloqueo:
        return dict(base, estado='Bloqueado', detalle=f'ML pidió {bloqueo}')
    precio = cdb.parse_precio(snap.get('precio'))
    texto = str(snap.get('texto') or '').lower()
    if not precio:
        if any(f in texto for f in CAIDA_FRASES):
            return dict(base, estado='Caida', detalle='La página dice que la publicación ya no está disponible')
        return dict(base, estado='Error', detalle='No se encontró el precio (¿cambió el diseño de la página o no cargó?)')
    out = dict(base, precio=precio, tachado=cdb.parse_precio(snap.get('tachado')),
               descuento=str(snap.get('descuento') or '').strip(), cuotas=str(snap.get('cuotas') or '').strip())
    ids = cdb.extraer_ids(url_original)
    es_catalogo = bool(ids['product_id'])
    vendedor = base['vendedor']
    if es_catalogo and not directo:
        # La página de catálogo muestra a la oferta GANADORA (buy box): es el "Precio_Ganador", aunque no sea la que seguimos.
        out['precio_ganador'], out['vendedor_ganador'] = precio, vendedor
    if directo:
        wid = ids['wid'] or ids['item_id'] or ''
        if _digitos_wid(snap.get('url')) != re.sub(r'\D', '', wid):
            return dict(out, estado='Sin lectura', precio=None,
                        detalle='Al abrir el ítem de la oferta ML me llevó a otra página (no conserva el wid)')
        es_catalogo = False
    if es_catalogo:
        if not esperado:
            return dict(out, estado='Sin lectura', precio=None,
                        detalle=f'Catálogo: no sé de quién es la oferta (la página muestra a {vendedor or "?"})')
        if not vendedor:
            return dict(out, estado='Sin lectura', precio=None, detalle='Catálogo: no pude leer el vendedor de la página')
    if esperado and vendedor and not coincide_vendedor(vendedor, esperado):
        return dict(out, estado='Otro vendedor', precio=None,
                    detalle=f'La página muestra a {vendedor}, se esperaba {esperado}')
    return dict(out, estado='OK')


def url_item_directo(wid):
    """wid 'MLA3334869990' -> 'https://articulo.mercadolibre.com.ar/MLA-3334869990' (la oferta puntual)."""
    m = re.fullmatch(r'(ML[A-Z])(\d+)', str(wid or '').upper())
    return f'https://articulo.mercadolibre.com.ar/{m.group(1)}-{m.group(2)}' if m else ''


def clasificar_oferta_en_catalogo(snap, oferta, esperado=None, url_original=''):
    """Catálogo con wid. `snap` = la página de catálogo (muestra a la GANADORA); `oferta` = lo que encontró el extractor
    buscando en esa página la tarjeta de la oferta del wid ({'encontrada', 'precio', 'texto', ...}) o None.
    El wid identifica la oferta (no hace falta saber de antemano quién es el vendedor). Siempre devuelve el
    precio/vendedor ganador de la página para guardarlos aparte."""
    res = clasificar_publicacion(snap, None, url_original)
    if res['estado'] in ('Bloqueado', 'Caida', 'Error'):
        return res
    if oferta and oferta.get('encontrada'):
        p = cdb.parse_precio(oferta.get('precio'))
        v = vendedor_de_texto(oferta.get('texto'))
        if p:
            if esperado and v and not coincide_vendedor(v, esperado):
                return dict(res, estado='Otro vendedor', precio=None, vendedor=v,
                            detalle=f'La tarjeta del wid es de {v}, se esperaba {esperado}')
            gan_p, gan_v = res.get('precio_ganador'), res.get('vendedor_ganador')
            return dict(res, estado='OK', precio=p, vendedor=v, via=oferta.get('via', 'tarjeta_wid'), detalle='',
                        tachado=None, descuento='', cuotas='', precio_ganador=gan_p, vendedor_ganador=gan_v)
    return dict(res, detalle=(res.get('detalle') or '') + ' | no encontré la tarjeta de la oferta del wid en la página')
