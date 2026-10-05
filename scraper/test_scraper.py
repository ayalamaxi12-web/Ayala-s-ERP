"""Tests del scraper de competencia (Etapa 2) con datos que replican la estructura REAL de la planilla de Maca
(encabezados en la fila 3, COMP2 sin encabezado en A, stock con rótulo en la fila 2 y basura numérica en la fila 3,
SKU repetidos, guiones, links de catálogo con y sin wid). Sin red."""
import pytest

import config
import competencia_db as cdb
import corrida
import eventos as ev
import paginas_ml as pml
import planilla_maca as pm
import sincronizar as sy
from fakes import SS, LectorFalso

L_ITEM = 'https://articulo.mercadolibre.com.ar/MLA-1111111111-camara-wifi'
L_WID = 'https://www.mercadolibre.com.ar/camara-x/p/MLA555?pdp_filters=a&wid=MLA999999999'
L_WID2 = 'https://www.mercadolibre.com.ar/camara-y/p/MLA556?wid=MLA888888888'
L_SINWID = 'https://www.mercadolibre.com.ar/toner/p/MLA777'
PERFIL_TV = 'https://www.mercadolibre.com.ar/tienda/tecnovibe?item_id=MLA1949492648&category_id=MLA1648&official_store_id=1'
PERFIL_AC = 'https://www.mercadolibre.com.ar/tienda/american-computers#client=SEARCH&component_id=header_logo'
PERFIL_GE = 'https://www.mercadolibre.com.ar/tienda/global-electronics-group'
PERFIL_NEW = 'https://www.mercadolibre.com.ar/tienda/geotek?item_id=MLA2022536754'

HOY = '05/10/2026'


def hoja_a():
    return [['PASO 1 — Los 3 mejores vendedores'], [],
            ['#', 'Subcategoría', 'SKUs nuestros', 'COMP1 — El Rey (perfil)', '', 'COMP3 — El Barato (perfil)', 'Notas'],
            ['1', 'Cartucho De Toner', '548', PERFIL_TV, PERFIL_AC, PERFIL_GE],
            ['2', 'Textil', '338'],
            ['3', 'Cámara Wifi', '6', PERFIL_NEW, '-', '']]


def hoja_b():
    hdr = ['SKU', 'Subcategoría', 'PM', '35091', 'COMP1 — El Rey (publi)', 'Cuotas', 'COMP2 — La Media (publi)', '',
           'COMP3 — El Barato (publi)', '', 'Notas', 'Ventas 30 Dias', 'Maximo Historico']
    return [['PASO 2 — Los 3 competidores'], ['', '', '', 'Stock'], hdr,
            ['CAM-1', 'Cámara Wifi', 'Cristian', '21777', L_ITEM, '', L_WID, '', '-', '', '', '0', '-'],
            ['CAM-2', 'Cámara Wifi', 'Cristian', '3', L_WID2, '', '', '', L_SINWID, '', '', '1', '-'],
            ['CAM-1', 'Cámara Wifi', 'Cristian', '21777', L_ITEM, '', L_WID, '', '-', '', '', '0', '-'],   # repetido
            ['SIN-LINKS', 'Textil', 'Laura', '', '', '', '', '', '', '', '', '', '']]


ENT_H = ['Entidad_ID', 'Nombre', 'Tipo', 'Link_ML']
REF_H = ['Referencia_ID', 'SKU', 'Tipo', 'Entidad_ID', 'Entidad_Nombre', 'Link_Publicacion', 'Activo', 'Origen']


def base(extra_refs=()):
    return SS({
        'Entidades': [ENT_H, ['ENT-000001', 'TECNOVIBEARG', 'Competencia', ''],
                      ['ENT-000002', 'AMERICANCOMPUTERS', 'Competencia', 'https://ya.puesto'],
                      ['ENT-000003', 'GLOBAL ELECTRONICS GROUP', 'Competencia', '']],
        'Referencias_Mercado': [REF_H] + [list(r) for r in extra_refs],
    })


def maca():
    return {'A': hoja_a(), 'B': hoja_b()}


def ok(precio, vendedor='', **kw):
    return dict({'estado': 'OK', 'precio': precio, 'tachado': None, 'descuento': '', 'cuotas': '', 'vendedor': vendedor,
                 'detalle': ''}, **kw)


# ── planilla_maca ─────────────────────────────────────────────────────────────
def test_perfiles_normaliza_url_y_toma_comp2_sin_encabezado():
    p, av = pm.leer_perfiles(hoja_a())
    assert any('COMP2 sin encabezado' in a for a in av)
    assert [(x['rol_nombre'], x['slug']) for x in p if x['subcategoria'] == 'Cartucho De Toner'] == [
        ('Rey', 'tecnovibe'), ('Media', 'american-computers'), ('Barato', 'global-electronics-group')]
    assert p[0]['url_listado'] == 'https://listado.mercadolibre.com.ar/tienda/tecnovibe'   # sin ?item_id=...
    assert pm.normalizar_perfil('https://www.mercadolibre.com.ar/pagina/distribuidoraromico')[1].endswith('/pagina/distribuidoraromico')
    assert pm.normalizar_perfil('https://google.com/x') is None


def test_skus_encabezado_partido_repetidos_y_guiones():
    skus, av, res = pm.leer_skus(hoja_b())
    d = {x['sku']: x for x in skus}
    assert res == {'skus': 3, 'filas_repetidas': 1, 'skus_con_links': 2, 'links': 4}   # CAM-1 repetido: unido, no duplicado
    assert d['CAM-1']['stock'] == 21777                       # 'Stock' viene del rótulo de la fila 2, no del 35091
    assert [(l['rol_nombre']) for l in d['CAM-1']['links']] == ['Rey', 'Media']      # el '-' de COMP3 se ignora
    assert d['SIN-LINKS']['links'] == []


def test_planilla_con_columna_faltante_falla_fuerte():
    mala = hoja_b()
    mala[2][8] = 'OTRA COSA'      # desaparece COMP3
    with pytest.raises(pm.PlanillaError):
        pm.leer_skus(mala)
    with pytest.raises(pm.PlanillaError):
        pm.leer_perfiles([['x'], []])


def test_acepta_celdas_con_hipervinculo_del_export():
    celdas = [[{'v': c, 'h': ''} for c in f] for f in hoja_a()]
    celdas[3][3] = {'v': 'ver perfil', 'h': PERFIL_TV}        # texto distinto del link real
    p, _ = pm.leer_perfiles(celdas)
    assert p[0]['slug'] == 'tecnovibe'


# ── sincronizar ───────────────────────────────────────────────────────────────
def test_sync_alias_entidades_nuevas_refs_y_exclusion():
    ss = base()
    p, _ = pm.leer_perfiles(hoja_a()); s, _, _ = pm.leer_skus(hoja_b())
    plan = sy.planificar_sync(p, s, ss.tab('Entidades'), ss.tab('Referencias_Mercado'), hoy=HOY)
    assert [e['Nombre'] for e in plan.entidades_nuevas] == ['GEOTEK']                  # las demás mapean por alias
    assert {x['Entidad_ID'] for x in plan.entidades_link} == {'ENT-000001'}   # solo Link_ML vacíos, y nunca el de una excluida
    assert plan.report['perfiles_excluidos'] == ['GLOBAL ELECTRONICS GROUP']
    assert len(plan.refs_nuevas) == 4
    assert {r['Rol_Competidor'] for r in plan.refs_nuevas} == {'Rey', 'Media', 'Barato'}
    assert all(r['Origen'] == sy.ORIGEN_B and r['Entidad_ID'] == '' for r in plan.refs_nuevas)   # entidad se completa al leer


def test_sync_reusa_mismo_sku_completa_rol_e_informa_otro_sku():
    ss = base([('REF-000010', 'CAM-1', 'Competencia', 'ENT-000001', 'TECNOVIBEARG', L_ITEM, 'Si', 'Migracion V-*'),
               ('REF-000011', 'OTRO', 'Competencia', '', '', L_WID, 'Si', 'Migracion V-*')])
    p, _ = pm.leer_perfiles(hoja_a()); s, _, _ = pm.leer_skus(hoja_b())
    plan = sy.planificar_sync(p, s, ss.tab('Entidades'), ss.tab('Referencias_Mercado'), hoy=HOY)
    assert {'Referencia_ID': 'REF-000010', 'Rol': 'Rey'} in plan.rol_updates              # rol vacío: se completa
    assert all(r['Link_Publicacion'] != L_ITEM for r in plan.refs_nuevas)                    # mismo SKU+link: se reutiliza
    assert plan.report['diferencias_sku'][0]['referencias_existentes'] == [{'id': 'REF-000011', 'sku': 'OTRO'}]
    assert any(r['Link_Publicacion'] == L_WID and r['SKU'] == 'CAM-1' for r in plan.refs_nuevas)   # y se crea la del SKU de Maca
    assert plan.refs_nuevas[0]['Referencia_ID'] == 'REF-000012'                              # la secuencia continúa


# ── eventos / páginas ─────────────────────────────────────────────────────────
def test_eventos_precio_caida_y_stock():
    assert ev.evento_precio(1000, 900)['Tipo'] == 'Bajo' and ev.evento_precio(1000, 900)['Variacion_Pct'] == -10.0
    assert ev.evento_precio(1000, 1001)['Tipo'] == 'Subio'                  # cualquier cambio
    assert ev.evento_precio(1000, 1000) is None and ev.evento_precio(None, 5) is None
    assert ev.transicion_caida(None, False, True) == 'Publicacion_caida'
    assert ev.transicion_caida('Publicacion_caida', False, True) is None     # no se repite todos los días
    assert ev.transicion_caida('Publicacion_caida', True, False) == 'Reaparecio'
    assert ev.transicion_caida(None, True, False) is None
    assert ev.evento_stock_bajo(2) is None                                   # DESACTIVADO por config
    assert ev.evento_stock_bajo(2, activo=True)['Tipo'] == 'Stock_bajo'
    assert ev.evento_stock_bajo(5, activo=True) is None and ev.evento_stock_bajo(None, activo=True) is None
    assert config.STOCK_ALERTAS_ACTIVAS is False


def test_clasificar_publicacion():
    snap = {'url': L_ITEM, 'texto': 'x', 'precio': '$ 12.345', 'vendedor': 'Vendido por TECNOVIBEARG'}
    assert pml.clasificar_publicacion(snap, 'TECNOVIBEARG')['estado'] == 'OK'
    assert pml.clasificar_publicacion(snap, 'ELEPHANT CARTDRIGE')['estado'] == 'Otro vendedor'
    caida = {'url': L_ITEM, 'texto': 'Esta publicación ya no está disponible', 'precio': ''}
    assert pml.clasificar_publicacion(caida)['estado'] == 'Caida'
    assert pml.clasificar_publicacion({'url': L_ITEM, 'texto': 'cargando', 'precio': ''})['estado'] == 'Error'   # no es caída
    assert pml.clasificar_publicacion({'url': 'https://www.mercadolibre.com/jms/mla/lgz/login', 'texto': '', 'precio': ''})['estado'] == 'Bloqueado'
    cat = {'url': L_WID, 'texto': 'x', 'precio': '100', 'vendedor': ''}
    assert pml.clasificar_publicacion(cat, 'GEOTEK', L_WID)['estado'] == 'Sin lectura'      # catálogo sin vendedor visible
    assert pml.clasificar_publicacion(dict(cat, vendedor='GEOTEK'), None, L_SINWID)['estado'] == 'Sin lectura'
    assert pml.clasificar_publicacion(dict(cat, vendedor='Geotek'), 'GEOTEK', L_WID)['estado'] == 'OK'
    # ítem puntual de la oferta (wid): identifica la oferta aunque aún no sepamos quién es; si ML redirige y se pierde el wid, no
    directo = {'url': 'https://articulo.mercadolibre.com.ar/MLA-999999999-x', 'texto': 'x', 'precio': '100', 'vendedor': 'GEOTEK'}
    assert pml.clasificar_publicacion(directo, None, L_WID, directo=True)['estado'] == 'OK'
    assert pml.clasificar_publicacion(dict(directo, url='https://www.mercadolibre.com.ar/p/MLA555'), None, L_WID, directo=True)['estado'] == 'Sin lectura'
    assert pml.coincide_vendedor('tecnovibe', 'TECNOVIBEARG') and not pml.coincide_vendedor('otro', 'TECNOVIBEARG')
    assert pml.url_item_directo('MLA3334869990') == 'https://articulo.mercadolibre.com.ar/MLA-3334869990'


# ── corrida completa ──────────────────────────────────────────────────────────
def tienda(*items):
    return {'estado': 'ok', 'items': [{'title': t, 'link': l, 'price': p, 'orig_price': '', 'discount': '', 'cuotas': ''}
                                      for t, l, p in items]}


def test_corrida_completa_escribe_lecturas_eventos_descubrimiento_y_es_idempotente():
    ss = base()
    # 1ª corrida: perfil de tecnovibe trae el item de CAM-1 y una publicación que NO es referencia
    lector = LectorFalso(
        tiendas={'https://listado.mercadolibre.com.ar/tienda/tecnovibe': tienda(('Cámara', L_ITEM, 1000), ('Otra cosa', 'https://articulo.mercadolibre.com.ar/MLA-9999999999-x', 50)),
                 'https://listado.mercadolibre.com.ar/tienda/american-computers': {'estado': 'sin_resultados', 'items': []},
                 'https://listado.mercadolibre.com.ar/tienda/geotek': tienda()},
        pubs={L_WID: ok(2000, 'GEOTEK'), L_WID2: ok(3000, 'GEOTEK'), L_SINWID: {'estado': 'Sin lectura', 'precio': None, 'detalle': 'catálogo'}})
    r1 = corrida.correr(ss, maca(), lector, hoy=HOY, pausa=False, log=lambda m: None)
    hist = ss.tab('Historial_Precios')
    n_refs = len(ss.tab('Referencias_Mercado'))
    assert {f[4] for f in ss.tab('Referencias_Mercado')[1:] if f[1] == 'CAM-1'} == {'TECNOVIBEARG', 'GEOTEK'}   # entidad aprendida al leer
    assert len(hist) == 1 + 3 and r1['lecturas'] == 3                  # item (perfil) + WID + WID2 (publicación); sin-wid no
    assert ('tienda', 'https://listado.mercadolibre.com.ar/tienda/global-electronics-group') not in lector.llamadas   # propia: no se scrapea
    assert r1['perfiles'] == {'leidos': 3, 'ok': 1, 'sin_resultados': 2, 'error': 0, 'items': 2}
    assert r1['eventos'] == {'Vendedor_sin_resultados': 2}               # american-computers y geotek (tienda vacía)
    assert r1['descubrimiento_nuevas'] == 1 and len(ss.tab('Discovery_Sugerencias')) == 2
    assert r1['publicaciones']['sin_lectura'] == 1 and r1['pendientes_stock'].startswith('Stock bajo DESACTIVADO')
    refs = {r[1]: r for r in ss.tab('Referencias_Mercado')[1:]}
    assert 'Rol_Competidor' in ss.tab('Referencias_Mercado')[0]
    # la entidad de las refs nuevas se completó al leer: GEOTEK ya existe (perfil nuevo) y TECNOVIBEARG por perfil
    ents = {r[1]: r for r in ss.tab('Entidades')[1:]}
    assert 'GEOTEK' in ents and ents['TECNOVIBEARG'][3] == 'https://listado.mercadolibre.com.ar/tienda/tecnovibe'
    assert ents['AMERICANCOMPUTERS'][3] == 'https://ya.puesto'          # no se pisa lo existente
    # 2ª corrida el MISMO día con otro precio: reemplaza la fila (no duplica) y genera el evento de cambio
    lector.tiendas['https://listado.mercadolibre.com.ar/tienda/tecnovibe'] = tienda(('Cámara', L_ITEM, 900))
    r2 = corrida.correr(ss, maca(), lector, hoy=HOY, pausa=False, log=lambda m: None)
    hist2 = ss.tab('Historial_Precios')
    assert len(hist2) == len(hist) and any(f[5] == 900 for f in hist2[1:]) and not any(f[5] == 1000 for f in hist2[1:])
    assert len(ss.tab('Referencias_Mercado')) == n_refs                                   # sin refs duplicadas
    assert r2['sync']['refs_nuevas'] == 0 and r2['descubrimiento_nuevas'] == 0


def test_corrida_dia_siguiente_eventos_de_precio_y_caida_sin_repetirse():
    ss = base()
    lector = LectorFalso(
        tiendas={},
        pubs={L_WID: ok(2000, 'GEOTEK'), L_WID2: ok(3000, 'GEOTEK'), L_SINWID: {'estado': 'Sin lectura', 'precio': None}})
    lector.tiendas = {f'https://listado.mercadolibre.com.ar/tienda/{s}': tienda(('x', L_ITEM, 1000)) for s in ('tecnovibe', 'american-computers', 'geotek')}
    corrida.correr(ss, maca(), lector, hoy='05/10/2026', pausa=False, log=lambda m: None)
    # día siguiente: sube un precio, se cae una publicación
    lector.pubs[L_WID] = ok(2200, 'GEOTEK')
    lector.pubs[L_WID2] = {'estado': 'Caida', 'precio': None, 'detalle': 'finalizada'}
    r = corrida.correr(ss, maca(), lector, hoy='06/10/2026', pausa=False, log=lambda m: None)
    assert r['eventos'].get('Subio') == 1 and r['eventos'].get('Publicacion_caida') == 1
    r = corrida.correr(ss, maca(), lector, hoy='07/10/2026', pausa=False, log=lambda m: None)
    assert r['eventos'].get('Publicacion_caida') is None                 # ya estaba caída: no se repite
    lector.pubs[L_WID2] = ok(3100, 'GEOTEK')
    r = corrida.correr(ss, maca(), lector, hoy='08/10/2026', pausa=False, log=lambda m: None)
    assert r['eventos'].get('Reaparecio') == 1


def test_sin_escribir_no_toca_el_sheet_y_filtro_por_vendedor():
    ss = base()
    antes = {k: [list(f) for f in v.rows] for k, v in ss.w.items()}
    lector = LectorFalso(tiendas={'https://listado.mercadolibre.com.ar/tienda/geotek': tienda()}, pubs={})
    r = corrida.correr(ss, maca(), lector, hoy=HOY, pausa=False, escribir=False, vendedor='geotek', solo='perfiles', log=lambda m: None)
    assert {k: v.rows for k, v in ss.w.items()} == antes and set(ss.w) == {'Entidades', 'Referencias_Mercado'}
    assert lector.llamadas == [('tienda', 'https://listado.mercadolibre.com.ar/tienda/geotek')]
    assert r['perfiles']['leidos'] == 1


def test_bloqueo_corta_la_corrida_pero_escribe_lo_leido():
    ss = base()
    lector = LectorFalso(
        tiendas={'https://listado.mercadolibre.com.ar/tienda/tecnovibe': tienda(('Cámara', L_ITEM, 1000)),
                 'https://listado.mercadolibre.com.ar/tienda/american-computers': {'estado': 'bloqueado', 'items': [], 'detalle': 'ML pidió login'}})
    with pytest.raises(corrida.CorridaBloqueada):
        corrida.correr(ss, maca(), lector, hoy=HOY, pausa=False, log=lambda m: None)
    assert len(ss.tab('Historial_Precios')) == 2                      # lo leído antes del bloqueo quedó guardado
    assert ('pub', L_WID) not in lector.llamadas                       # y no siguió con las publicaciones


def test_referencias_inactivas_y_de_global_no_se_leen():
    ss = base([('REF-000020', 'GE-1', 'Competencia', 'ENT-000003', 'GLOBAL ELECTRONICS GROUP', L_WID2, 'Si', 'Migracion V-*'),
               ('REF-000021', 'CAM-1', 'Competencia', 'ENT-000001', 'TECNOVIBEARG', L_ITEM, 'No', 'Migracion V-*')])
    lector = LectorFalso(tiendas={f'https://listado.mercadolibre.com.ar/tienda/{s}': tienda(('x', L_ITEM, 1000), ('y', L_WID2, 5)) for s in ('tecnovibe', 'american-computers', 'geotek')},
                         pubs={})
    corrida.correr(ss, maca(), lector, hoy=HOY, pausa=False, log=lambda m: None, solo='perfiles')
    ids = {f[0] for f in ss.tab('Historial_Precios')[1:]}
    assert 'REF-000020' not in ids and 'REF-000021' not in ids         # Global (excluida) e inactiva: sin lecturas


# ── modo prueba ───────────────────────────────────────────────────────────────
def test_modo_prueba_no_escribe_y_cubre_cada_tipo_de_link():
    import prueba
    lector = LectorFalso(
        tiendas={'https://listado.mercadolibre.com.ar/tienda/tecnovibe': tienda(('x', L_ITEM, 10))},
        pubs={L_ITEM: ok(10), L_WID: dict(ok(20, 'GEOTEK'), intentos=[{'intento': 'original'}, {'intento': 'directo'}])})
    inf = prueba.correr_prueba(maca(), lector, n=20, log=lambda m: None)
    tipos = {p['tipo'] for p in inf['publicaciones']}
    assert tipos == {'item', 'catalogo_con_wid', 'catalogo_sin_wid'}
    assert [t['slug'] for t in inf['tiendas']][0] == 'tecnovibe' and 'global-electronics-group' not in [t['slug'] for t in inf['tiendas']]
    assert all(c[0] in ('tienda', 'pub') for c in lector.llamadas)       # solo lee: el lector falso ni siquiera recibe hojas
    assert 'RESULTADO DEL MODO PRUEBA' in prueba.resumen_texto(inf)


def test_modo_prueba_se_corta_si_ml_bloquea():
    import prueba
    lector = LectorFalso(tiendas={'https://listado.mercadolibre.com.ar/tienda/tecnovibe': {'estado': 'bloqueado', 'items': [], 'detalle': 'login'}})
    inf = prueba.correr_prueba(maca(), lector, n=20, log=lambda m: None)
    assert len(lector.llamadas) == 1 and inf['publicaciones'] == []
