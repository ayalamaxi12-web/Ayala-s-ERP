"""Lector de la planilla de Maca (pestañas A-CATEGORIAS y B-SKU-COMPETENCIA). Lógica pura, sin red.

Acepta filas como listas de strings (gspread) o de celdas {'v': texto, 'h': hipervínculo} (export del navegador).
Los encabezados reales están en la FILA 3 (no la 1). Las columnas se ubican por NOMBRE, no por posición:
si falta una esperada, falla fuerte (PlanillaError) en vez de leer cualquier cosa.
La categoría/competidores los define Maca: acá no se clasifica nada."""
import re
import unicodedata
from urllib.parse import urlparse

import config  # noqa: F401  (agrega backend/ al path)
import competencia_db as cdb

FILA_ENCABEZADO = 2   # índice 0 => fila 3
ROLES = ('COMP1', 'COMP2', 'COMP3')
NOMBRE_ROL = {'COMP1': 'Rey', 'COMP2': 'Media', 'COMP3': 'Barato'}


class PlanillaError(Exception):
    pass


def _sin_acentos(s):
    return ''.join(c for c in unicodedata.normalize('NFD', str(s)) if unicodedata.category(c) != 'Mn')


def _n(s):
    return cdb.norm_texto(_sin_acentos(s))


def _v(c):
    return str(c.get('v', '') if isinstance(c, dict) else c if c is not None else '').strip()


def _url(c):
    """URL de una celda: el hipervínculo si lo hay; si no, el texto (en la planilla el texto ES la URL)."""
    if isinstance(c, dict):
        return (c.get('h') or c.get('v') or '').strip()
    return _v(c)


def _cel(fila, i):
    return fila[i] if i is not None and 0 <= i < len(fila) else ''


def es_link(u):
    return str(u).lower().startswith('http')


def _encabezados(filas, extra_arriba=True):
    """Encabezado efectivo por columna: el de la fila 3; si está vacío o es un número suelto (basura pegada,
    p. ej. el '35091' sobre la columna de stock), el rótulo de la fila 2."""
    if len(filas) <= FILA_ENCABEZADO:
        raise PlanillaError('La pestaña tiene menos de 3 filas: no encuentro los encabezados (fila 3).')
    h3, h2 = filas[FILA_ENCABEZADO], (filas[FILA_ENCABEZADO - 1] if extra_arriba else [])
    n = max(len(h3), len(h2))
    out = []
    for i in range(n):
        a = _v(_cel(h3, i))
        if (not a or re.fullmatch(r'[\d.,]+', a)) and extra_arriba:
            b = _v(_cel(h2, i))
            a = b or a
        out.append(a)
    return out


def _buscar(hs, *nombres, obligatorio=True, prefijo=False):
    for i, h in enumerate(hs):
        hn = _n(h)
        for nom in nombres:
            if hn == _n(nom) or (prefijo and hn.startswith(_n(nom))):
                return i
    if obligatorio:
        raise PlanillaError(f'No encuentro la columna {nombres[0]!r} en los encabezados: {[h for h in hs if h]}')
    return None


def _cols_roles(hs, avisos):
    """Posición de COMP1/COMP2/COMP3. COMP2 puede venir SIN encabezado en A-CATEGORIAS (Maxx confirmó
    2026-10-05 que la columna sin nombre entre COMP1 y COMP3 es COMP2)."""
    c1 = _buscar(hs, 'COMP1', prefijo=True)
    c3 = _buscar(hs, 'COMP3', prefijo=True)
    c2 = _buscar(hs, 'COMP2', prefijo=True, obligatorio=False)
    if c2 is None:
        if c3 - c1 == 2 and not hs[c1 + 1]:
            c2 = c1 + 1
            avisos.append('COMP2 sin encabezado: se toma la columna entre COMP1 y COMP3.')
        else:
            raise PlanillaError('No encuentro COMP2 (ni como columna sin nombre entre COMP1 y COMP3).')
    return {'COMP1': c1, 'COMP2': c2, 'COMP3': c3}


# ── Perfiles de tienda (A-CATEGORIAS) ─────────────────────────────────────────
def normalizar_perfil(url):
    """URL de perfil/tienda de la planilla -> (slug, url_listado, tipo) o None si no se reconoce.
    La planilla trae links de tienda con parámetros de seguimiento (?item_id=..&category_id=.., #client=..):
    se descartan y se arma la URL de listado (la que usaba el scraper viejo)."""
    try:
        p = urlparse(url.strip())
    except Exception:
        return None
    host, partes = (p.netloc or '').lower(), [x for x in p.path.split('/') if x]
    if 'mercadolibre' not in host or len(partes) < 2:
        return None
    if partes[0] in ('tienda', 'pagina'):
        slug = partes[1].lower()
        return slug, f'https://listado.mercadolibre.com.ar/{partes[0]}/{slug}', partes[0]
    if partes[0] == 'perfil':
        return partes[1].lower(), f'https://www.mercadolibre.com.ar/perfil/{partes[1]}', 'perfil'
    return None


def leer_perfiles(filas):
    """-> (lista de {subcategoria, skus_nuestros, rol, rol_nombre, url_original, slug, url_listado, tipo},
           avisos). Un perfil por celda con link; las celdas vacías o '-' se ignoran."""
    avisos = []
    hs = _encabezados(filas, extra_arriba=False)
    c_sub = _buscar(hs, 'Subcategoría', 'Subcategoria')
    c_skus = _buscar(hs, 'SKUs nuestros', obligatorio=False)
    roles = _cols_roles(hs, avisos)
    out = []
    for n, f in enumerate(filas[FILA_ENCABEZADO + 1:], start=FILA_ENCABEZADO + 2):
        sub = _v(_cel(f, c_sub))
        if not sub:
            continue
        for rol, ci in roles.items():
            u = _url(_cel(f, ci))
            if not u or u == '-':
                continue
            if not es_link(u):
                avisos.append(f'Fila {n} ({sub}) {rol}: "{u[:40]}" no es un link, se ignora.')
                continue
            r = normalizar_perfil(u)
            if r is None:
                avisos.append(f'Fila {n} ({sub}) {rol}: no reconozco el perfil {u[:80]}')
                continue
            slug, listado, tipo = r
            out.append({'subcategoria': sub, 'skus_nuestros': _v(_cel(f, c_skus)), 'rol': rol,
                        'rol_nombre': NOMBRE_ROL[rol], 'url_original': u, 'slug': slug,
                        'url_listado': listado, 'tipo': tipo, 'fila': n})
    return out, avisos


# ── Publicaciones por SKU (B-SKU-COMPETENCIA) ─────────────────────────────────
def _stock(v):
    s = re.sub(r'[^\d-]', '', str(v))
    return int(s) if s and s != '-' else None


def leer_skus(filas):
    """-> (lista de {sku, subcategoria, pm, stock, links:[{rol, rol_nombre, url}], fila}, avisos, resumen).
    Un SKU repetido en varias filas (error de carga, confirmado por Maxx) se trata como el mismo SKU: se unen sus
    links sin duplicar. 'Stock' puede venir con el rótulo en la fila 2 y basura numérica en la fila 3."""
    avisos = []
    hs = _encabezados(filas, extra_arriba=True)
    c_sku = _buscar(hs, 'SKU')
    c_sub = _buscar(hs, 'Subcategoría', 'Subcategoria')
    c_pm = _buscar(hs, 'PM', obligatorio=False)
    c_stock = _buscar(hs, 'Stock', obligatorio=False)
    roles = _cols_roles(hs, avisos)
    por_sku, orden, repetidas, filas_con_link = {}, [], 0, 0
    guiones = vacias = 0     # celdas de competidor con '-' (a propósito) o vacías: no son competidores cargados todavía
    for n, f in enumerate(filas[FILA_ENCABEZADO + 1:], start=FILA_ENCABEZADO + 2):
        sku = cdb.limpiar_sku(_v(_cel(f, c_sku)))
        if not sku:
            continue
        if sku in por_sku:
            repetidas += 1
        else:
            por_sku[sku] = {'sku': sku, 'subcategoria': _v(_cel(f, c_sub)), 'pm': _v(_cel(f, c_pm)),
                            'stock': _stock(_cel(f, c_stock)) if c_stock is not None else None,
                            'links': [], 'fila': n}
            orden.append(sku)
        d = por_sku[sku]
        tuvo = False
        for rol, ci in roles.items():
            u = _url(_cel(f, ci))
            if not u:
                vacias += 1
                continue
            if u == '-':
                guiones += 1
                continue
            if not es_link(u):
                avisos.append(f'Fila {n} ({sku}) {rol}: "{u[:40]}" no es un link, se ignora.')
                continue
            tuvo = True
            if not any(l['url'] == u and l['rol'] == rol for l in d['links']):
                d['links'].append({'rol': rol, 'rol_nombre': NOMBRE_ROL[rol], 'url': u})
        filas_con_link += tuvo
    out = [por_sku[s] for s in orden]
    resumen = {'skus': len(out), 'filas_repetidas': repetidas, 'skus_con_links': sum(1 for d in out if d['links']),
               'links': sum(len(d['links']) for d in out), 'skus_sin_competidor_cargado': sum(1 for d in out if not d['links']),
               'celdas_con_guion': guiones, 'celdas_vacias': vacias}
    return out, avisos, resumen
