"""Categoria_Competidores: el mapa subcategoría -> tienda Rey/Media/Barato de A-CATEGORIAS se guarda en el Sheet del ERP (upsert, sin borrar)."""
import categorias_competidores as cc
import corrida
from fakes import LectorFalso
from test_scraper import HOY, base, maca

URL = {u: {'estado': 'sin_resultados', 'items': [], 'declaradas': 0, 'paginas': 1, 'fin': 'sin_siguiente'} for u in (
    'https://listado.mercadolibre.com.ar/tienda/tecnovibe', 'https://listado.mercadolibre.com.ar/tienda/american-computers',
    'https://listado.mercadolibre.com.ar/tienda/geotek')}


def _perfil(sub, rol, slug, **k):
    return dict({'subcategoria': sub, 'rol_nombre': rol, 'slug': slug, 'entidad_id': 'E-' + slug, 'entidad_nombre': slug.upper(),
                 'skus_nuestros': 'PV-1', 'excluida': False}, **k)


def test_filas_dedupe_y_excluye_a_global():
    p = [_perfil('Toner', 'Rey', 'geotek'), _perfil('Toner', 'Rey', 'geotek'), _perfil('Toner', 'Barato', 'global', excluida=True)]
    f = cc.filas(p, HOY)
    assert [(x['Subcategoria'], x['Rol'], x['Slug'], x['Actualizado']) for x in f] == [('Toner', 'Rey', 'geotek', HOY)]


def test_registrar_crea_la_pestana_actualiza_y_no_borra():
    ss = base()
    assert cc.registrar(ss, [_perfil('Toner', 'Rey', 'geotek'), _perfil('Toner', 'Media', 'tecnovibe')], '01/10/2026') == (2, 0)
    assert cc.registrar(ss, [_perfil('Toner', 'Rey', 'geotek', skus_nuestros='PV-1, PV-2')], '05/10/2026') == (0, 1)
    h = ss.tab(cc.CATEGORIAS_SHEET)
    assert h[0] == cc.CATEGORIAS_HEADERS and len(h) == 3
    por = {(f[0], f[1]): f for f in h[1:]}
    assert por[('Toner', 'Rey')][5] == 'PV-1, PV-2' and por[('Toner', 'Rey')][6] == '05/10/2026'
    assert por[('Toner', 'Media')][6] == '01/10/2026'          # la que ya no vino NO se borra ni se toca


def test_la_corrida_escribe_el_mapa_y_en_sin_escribir_no():
    ss = base()
    r = corrida.correr(ss, maca(), LectorFalso(tiendas=URL, pubs={}), hoy=HOY, pausa=False, log=lambda m: None, descubrir=False, solo='perfiles')
    filas = ss.tab(cc.CATEGORIAS_SHEET)[1:]
    assert filas and r['categoria_competidores']['nuevas'] == len(filas)
    assert all(f[6] == HOY for f in filas)
    ss2 = base()
    corrida.correr(ss2, maca(), LectorFalso(tiendas=URL, pubs={}), hoy=HOY, pausa=False, log=lambda m: None, descubrir=False, solo='perfiles', escribir=False)
    assert cc.CATEGORIAS_SHEET not in ss2.w
