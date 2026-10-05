"""Orquestación de una corrida del scraper: sincroniza la planilla de Maca, lee perfiles y publicaciones, escribe las
lecturas a Historial_Precios y detecta eventos. El lector (Selenium) y las hojas se INYECTAN: así se prueba entero
sin red. Reglas de la Etapa 1: una fila por lectura, solo con precio, idempotente por referencia y día."""
import random
import re
import time
from datetime import datetime

import config
import competencia_db as cdb
import eventos as ev
import planilla_maca as pm
import sheets_io as sio
import sincronizar as sy
import paginas_ml as pml

# Historial_Precios + las 2 columnas del precio de la oferta GANADORA del catálogo (se agregan al final de la hoja).
HISTORIAL_HEADERS_V2 = cdb.HISTORIAL_HEADERS + ['Precio_Ganador', 'Vendedor_Ganador']
DISCOVERY_SHEET = 'Discovery_Sugerencias'
DISCOVERY_HEADERS = ['Sugerencia_ID', 'Entidad_Origen', 'Titulo_Detectado', 'Link_Detectado', 'Precio_Detectado',
                     'SKU_Sugerido', 'Fecha_Deteccion', 'Estado_Revision', 'Referencia_ID_Generada']
ENT_HEADERS = ['Entidad_ID', 'Nombre', 'Tipo', 'Provincia', 'Localidad', 'Estado', 'Responsable',
               'Tolerancia_Default_Pct', 'Fecha_Alta', 'Fecha_Ultima_Revision', 'Observaciones', 'Link_ML', 'Seller_ID']
REF_HEADERS = ['Referencia_ID', 'SKU', 'Tipo', 'Entidad_ID', 'Entidad_Nombre', 'Link_Publicacion', 'PVP_Oficial',
               'PVP_Override', 'Tolerancia_Pct', 'Activo', 'Seller_ID_Esperado', 'Fecha_Alta', 'Origen', 'Observaciones']
_TRUE = {'si', 'sí', 'true', '1', 'activo'}


class CorridaBloqueada(Exception):
    """ML pidió login/verificación/captcha: se corta la corrida (no hay nadie para resolverlo)."""


def es_activo(v):
    v = str(v or '').strip().lower()
    return True if not v else v in _TRUE


def _fecha_orden(s):
    f, _ = cdb.parse_fecha(s)
    if not f:
        return None
    d, m, y = f.split('/')
    return (int(y), int(m), int(d))


def _pausa(rango):
    time.sleep(random.uniform(*rango))


# ── Estado de la base en memoria ──────────────────────────────────────────────
def _refs_desde_filas(filas):
    out = []
    if not filas:
        return out
    h = {x: i for i, x in enumerate(filas[0])}
    g = lambda f, c: str(f[h[c]]).strip() if c in h and h[c] < len(f) else ''  # noqa: E731
    for n, f in enumerate(filas[1:], start=2):
        rid = g(f, 'Referencia_ID')
        if rid:
            out.append({'id': rid, 'sku': cdb.limpiar_sku(g(f, 'SKU')), 'tipo': g(f, 'Tipo'), 'link': g(f, 'Link_Publicacion'),
                        'entidad_id': g(f, 'Entidad_ID'), 'entidad': g(f, 'Entidad_Nombre'), 'activo': g(f, 'Activo'),
                        'rol': g(f, sy.COL_ROL), 'fila': n})
    return out


def _ents_desde_filas(filas):
    out = []
    if not filas:
        return out
    h = {x: i for i, x in enumerate(filas[0])}
    g = lambda f, c: str(f[h[c]]).strip() if c in h and h[c] < len(f) else ''  # noqa: E731
    for n, f in enumerate(filas[1:], start=2):
        if g(f, 'Entidad_ID'):
            out.append({'id': g(f, 'Entidad_ID'), 'nombre': g(f, 'Nombre'), 'tipo': g(f, 'Tipo'),
                        'link': g(f, 'Link_ML'), 'fila': n})
    return out


def _ultimos_precios(filas_hist, hoy):
    """{Referencia_ID: precio} de la última lectura ANTERIOR a hoy con precio (la de hoy se reemplaza)."""
    if not filas_hist:
        return {}
    h = {x: i for i, x in enumerate(filas_hist[0])}
    mejor = {}
    for f in filas_hist[1:]:
        try:
            rid, fe, pr = f[h['Referencia_ID']], f[h['Fecha']], f[h['Precio']]
        except (KeyError, IndexError):
            continue
        fo, p = _fecha_orden(fe), cdb.parse_precio(pr)
        if not rid or fo is None or p is None or fe.strip() == hoy:
            continue
        if rid not in mejor or fo >= mejor[rid][0]:
            mejor[rid] = (fo, p)
    return {k: v[1] for k, v in mejor.items()}


def _coincide_filtro(nombre, filtro):
    if not filtro:
        return True
    a, b = re.sub(r'[^a-z0-9]', '', cdb.norm_texto(nombre)), re.sub(r'[^a-z0-9]', '', cdb.norm_texto(filtro))
    return bool(a and b and (b in a or a in b))


# ── Corrida ───────────────────────────────────────────────────────────────────
def correr(ss, filas_maca, lector, *, vendedor=None, solo=None, escribir=True, descubrir=True, hoy=None, ahora=None,
           log=print, pausa=True):
    """ss: Spreadsheet del ERP. filas_maca: {'A': filas, 'B': filas}. lector: ver ml_selenium.LectorML.
    -> resumen (dict). Si ML bloquea, escribe lo que haya y levanta CorridaBloqueada."""
    ahora = ahora or datetime.now()
    hoy = hoy or ahora.strftime('%d/%m/%Y')
    hora = ahora.strftime('%H:%M')
    R = {'fecha': hoy, 'escribir': escribir, 'vendedor': vendedor or 'todos', 'solo': solo or 'todo',
         'sync': {}, 'perfiles': {'leidos': 0, 'ok': 0, 'sin_resultados': 0, 'error': 0, 'items': 0},
         'publicaciones': {'leidas': 0, 'ok': 0, 'caidas': 0, 'sin_lectura': 0, 'otro_vendedor': 0, 'error': 0,
                           'saltadas_por_perfil': 0, 'via': {}, 'solo_precio_ganador': 0},
         'lecturas': 0, 'eventos': {}, 'descubrimiento_nuevas': 0, 'avisos': [], 'pendientes_stock': None}

    titulos = {w.title for w in ss.worksheets()}
    ents_f, refs_f = sio.leer(ss, 'Entidades', titulos), sio.leer(ss, 'Referencias_Mercado', titulos)
    hist_f, ev_f = sio.leer(ss, cdb.HISTORIAL_SHEET, titulos), sio.leer(ss, ev.EVENTOS_SHEET, titulos)
    disc_f = sio.leer(ss, DISCOVERY_SHEET, titulos)

    # 1) Planilla de Maca -> perfiles y SKU
    perfiles, av1 = pm.leer_perfiles(filas_maca['A'])
    skus, av2, resumen_b = pm.leer_skus(filas_maca['B'])
    R['avisos'] += av1 + av2
    R['sync']['planilla'] = dict(resumen_b, perfiles=len(perfiles))

    # 2) Sincronizar con la base
    plan = sy.planificar_sync(perfiles, skus, ents_f, refs_f, hoy=hoy)
    R['sync'].update({'entidades_nuevas': [e['Nombre'] for e in plan.entidades_nuevas],
                      'link_ml_a_completar': len(plan.entidades_link), 'refs_nuevas': len(plan.refs_nuevas),
                      'roles_a_completar': len(plan.rol_updates),
                      'diferencias_sku': plan.report['diferencias_sku'],
                      'links_no_reconocidos': plan.report['links_no_reconocidos']})
    refs, ents = _refs_desde_filas(refs_f), _ents_desde_filas(ents_f)
    for e in plan.entidades_nuevas:
        ents.append({'id': e['Entidad_ID'], 'nombre': e['Nombre'], 'tipo': 'Competencia', 'link': e['Link_ML'], 'fila': None})
    for r in plan.refs_nuevas:
        refs.append({'id': r['Referencia_ID'], 'sku': r['SKU'], 'tipo': 'Competencia', 'link': r['Link_Publicacion'],
                     'entidad_id': '', 'entidad': '', 'activo': 'Si', 'rol': r[sy.COL_ROL], 'fila': None})
    por_id = {r['id']: r for r in refs}
    for u in plan.rol_updates:
        if u['Referencia_ID'] in por_id:
            por_id[u['Referencia_ID']]['rol'] = u['Rol']
    ent_por_id = {e['id']: e for e in ents}
    cambios_ref = []   # (ref_id, columna, valor) a escribir en refs YA existentes (rellenar vacíos)
    ents_nuevas_por_lectura = []

    def asignar_entidad(ref, eid, nombre):
        """Completa la entidad de una referencia SOLO si estaba vacía."""
        if ref['entidad_id'] or ref['entidad']:
            return
        ref['entidad_id'], ref['entidad'] = eid, nombre
        if ref['fila'] is not None:
            cambios_ref.append((ref['fila'], 'Entidad_ID', eid))
            cambios_ref.append((ref['fila'], 'Entidad_Nombre', nombre))
        else:  # referencia nueva de esta corrida: se escribe ya con su entidad
            for d in plan.refs_nuevas:
                if d['Referencia_ID'] == ref['id']:
                    d['Entidad_ID'], d['Entidad_Nombre'] = eid, nombre

    def entidad_por_nombre(nombre):
        for e in ents:
            if e['tipo'] == 'Competencia' and (cdb.norm_texto(e['nombre']) == cdb.norm_texto(nombre)
                                               or pml.coincide_vendedor(nombre, e['nombre'])):
                return e
        return None

    def excluida(ref):
        e = ent_por_id.get(ref['entidad_id'])
        return sy.es_excluida(ref['entidad']) or (e is not None and sy.es_excluida(e['nombre']))

    def vigente(ref):
        return ref['tipo'] == 'Competencia' and es_activo(ref['activo']) and not excluida(ref)

    por_ident = {}
    for r in refs:
        if vigente(r):
            i = sy.ident_publicacion(r['link'])
            if i:
                por_ident.setdefault(i, []).append(r)

    previos = _ultimos_precios(hist_f, hoy)
    ultimo_caida = ev.ultimo_tipo_por_referencia(ev_f)
    lecturas, eventos, disc_nuevas = {}, [], []
    leidas_por_perfil = set()
    disc_existentes = set()
    if disc_f:
        h = {x: i for i, x in enumerate(disc_f[0])}
        for f in disc_f[1:]:
            k = (f[h['Entidad_Origen']] if 'Entidad_Origen' in h and h['Entidad_Origen'] < len(f) else '',
                 sy.ident_publicacion(f[h['Link_Detectado']] if 'Link_Detectado' in h and h['Link_Detectado'] < len(f) else ''))
            disc_existentes.add(k)
    sug_seq = len(disc_f) - 1 if disc_f else 0

    def emitir(tipo_dato, ref=None, entidad='', link='', **campos):
        fila = {'Fecha': hoy, 'Hora': hora, 'Tipo': tipo_dato['Tipo'], 'Referencia_ID': ref['id'] if ref else '',
                'SKU': ref['sku'] if ref else '', 'Entidad': ref['entidad'] if ref else entidad,
                'Rol': ref['rol'] if ref else '', 'Valor_Anterior': tipo_dato.get('Valor_Anterior', ''),
                'Valor_Nuevo': tipo_dato.get('Valor_Nuevo', ''), 'Variacion_Pct': tipo_dato.get('Variacion_Pct', ''),
                'Detalle': tipo_dato.get('Detalle', ''), 'Link': link}
        eventos.append(fila)
        R['eventos'][fila['Tipo']] = R['eventos'].get(fila['Tipo'], 0) + 1

    def registrar_lectura(ref, res, fuente, link):
        precio = res['precio']
        lecturas[ref['id']] = {
            'Referencia_ID': ref['id'], 'SKU': ref['sku'], 'Entidad': ref['entidad'], 'Fecha': hoy, 'Hora': hora,
            'Precio': precio if not float(precio).is_integer() else int(precio),
            'Precio_Tachado': (res.get('tachado') or ''), 'Descuento': res.get('descuento') or '',
            'Cuotas': res.get('cuotas') or '', 'Estado': 'OK', 'Metodo': 'Selenium', 'Fuente': fuente, 'Link': link,
            # lo que ML muestra primero en el catálogo (la ganadora): dato aparte; el evento de precio NO lo mira
            'Precio_Ganador': res.get('precio_ganador') or '', 'Vendedor_Ganador': res.get('vendedor_ganador') or ''}
        d = ev.evento_precio(previos.get(ref['id']), precio)
        if d:
            emitir(d, ref, link=link)
        t = ev.transicion_caida(ultimo_caida.get(ref['id']), True, False)
        if t:
            emitir({'Tipo': t, 'Detalle': 'La publicación volvió a tener precio'}, ref, link=link)
            ultimo_caida[ref['id']] = t

    bloqueo = None
    try:
        # 3) Perfiles de tienda
        if solo in (None, 'perfiles'):
            vistos_perfil = set()
            for p in plan.perfiles:
                if p['slug'] in vistos_perfil or p['excluida'] or not _coincide_filtro(p['entidad_nombre'], vendedor):
                    continue
                vistos_perfil.add(p['slug'])
                R['perfiles']['leidos'] += 1
                log(f"Perfil {p['entidad_nombre']}: {p['url_listado']}")
                t = lector.leer_tienda(p['url_listado'])
                if t['estado'] == 'bloqueado':
                    bloqueo = t.get('detalle', 'ML pidió login/verificación')
                    break
                if t['estado'] == 'error':
                    R['perfiles']['error'] += 1
                    R['avisos'].append(f"Perfil {p['entidad_nombre']}: {t.get('detalle', 'error de lectura')}")
                    continue
                if t['estado'] == 'sin_resultados' or not t['items']:
                    R['perfiles']['sin_resultados'] += 1
                    subs = sorted({x['subcategoria'] for x in plan.perfiles if x['slug'] == p['slug']})
                    emitir({'Tipo': ev.SIN_RESULTADOS, 'Detalle': 'La tienda cargó y no trajo publicaciones (' + ', '.join(subs) + ')'},
                           entidad=p['entidad_nombre'], link=p['url_listado'])
                    continue
                R['perfiles']['ok'] += 1
                R['perfiles']['items'] += len(t['items'])
                for it in t['items']:
                    ident = sy.ident_publicacion(it['link'])
                    cands = [r for r in por_ident.get(ident, []) if ident and (ident[0] != 'Pn' or r['entidad_id'] in ('', p['entidad_id']))]
                    if cands:
                        for r in cands:
                            asignar_entidad(r, p['entidad_id'], p['entidad_nombre'])
                            registrar_lectura(r, {'precio': it['price'], 'tachado': it.get('orig_price'),
                                                  'descuento': it.get('discount'), 'cuotas': it.get('cuotas')},
                                              'Scraper perfil', it['link'])
                            leidas_por_perfil.add(r['id'])
                    elif not ident:
                        R['perfiles']['items_sin_identidad'] = R['perfiles'].get('items_sin_identidad', 0) + 1   # p. ej. links de tracking
                    elif descubrir and ident:
                        k = (p['entidad_nombre'], ident)
                        if k not in disc_existentes:
                            disc_existentes.add(k)
                            sug_seq += 1
                            disc_nuevas.append({'Sugerencia_ID': f'SUG-{sug_seq:06d}', 'Entidad_Origen': p['entidad_nombre'],
                                                'Titulo_Detectado': it['title'], 'Link_Detectado': it['link'],
                                                'Precio_Detectado': it['price'], 'SKU_Sugerido': '',
                                                'Fecha_Deteccion': hoy, 'Estado_Revision': 'Pendiente',
                                                'Referencia_ID_Generada': ''})
                if pausa:
                    _pausa(config.PAUSA_ENTRE_PAGINAS)

        # 4) Publicaciones puntuales (links de B-SKU) que el perfil de hoy no cubrió
        if bloqueo is None and solo in (None, 'publicaciones'):
            tareas = {}   # url -> [refs]
            for d in skus:
                for l in d['links']:
                    ident = sy.ident_publicacion(l['url'])
                    for r in por_ident.get(ident, []) if ident else []:
                        if r['sku'] and cdb.norm_texto(r['sku']) == cdb.norm_texto(d['sku']) and r['rol']:
                            tareas.setdefault(l['url'], []).append(r)
            for url, rs in tareas.items():
                rs = list({x['id']: x for x in rs}.values())
                if vendedor:   # "actualizar un vendedor": solo las referencias YA atribuidas a ese vendedor
                    rs = [r for r in rs if r['entidad'] and _coincide_filtro(r['entidad'], vendedor)]
                if not rs:
                    continue
                pendientes = [r for r in rs if r['id'] not in leidas_por_perfil]
                if not pendientes:
                    R['publicaciones']['saltadas_por_perfil'] += 1
                    continue
                esperado = next((r['entidad'] for r in pendientes if r['entidad']), None)
                R['publicaciones']['leidas'] += 1
                res = lector.leer_publicacion(url, esperado)
                est = res['estado']
                if est == 'Bloqueado':
                    bloqueo = res.get('detalle', 'ML pidió login/verificación')
                    break
                if est == 'OK':
                    vend = res.get('vendedor', '')
                    if vend and sy.es_excluida(vend):
                        R['avisos'].append(f'{url[:70]}: el vendedor de la página es propio ({vend}): se omite.')
                        continue
                    R['publicaciones']['ok'] += 1
                    via = res.get('via') or 'pagina_original'
                    R['publicaciones']['via'][via] = R['publicaciones']['via'].get(via, 0) + 1
                    for r in pendientes:
                        if not r['entidad_id'] and vend:
                            e = entidad_por_nombre(vend)
                            if e is None:
                                nid = max([int(re.sub(r'\D', '', x['id']) or 0) for x in ents] + [0]) + 1
                                eid = f'ENT-{nid:06d}'
                                e = {'id': eid, 'nombre': vend.upper(), 'tipo': 'Competencia', 'link': '', 'fila': None}
                                ents.append(e)
                                ent_por_id[eid] = e
                                ents_nuevas_por_lectura.append({'Entidad_ID': eid, 'Nombre': e['nombre'], 'Tipo': 'Competencia',
                                                                'Fecha_Alta': hoy, 'Observaciones': 'Creada al leer una publicación de la planilla de Maca'})
                            asignar_entidad(r, e['id'], e['nombre'])
                        registrar_lectura(r, res, 'Scraper publicación', url)
                elif est == 'Caida':
                    R['publicaciones']['caidas'] += 1
                    for r in pendientes:
                        t = ev.transicion_caida(ultimo_caida.get(r['id']), False, True)
                        if t:
                            emitir({'Tipo': t, 'Detalle': res.get('detalle', '')}, r, link=url)
                            ultimo_caida[r['id']] = t
                elif est == 'Otro vendedor':
                    R['publicaciones']['otro_vendedor'] += 1
                    R['avisos'].append(f'{url[:70]}: {res.get("detalle", "")}')
                elif est == 'Sin lectura':
                    R['publicaciones']['sin_lectura'] += 1
                    if res.get('precio_ganador'):      # se vio al ganador pero no la oferta que sigue Maca: no se guarda fila
                        R['publicaciones']['solo_precio_ganador'] += 1
                else:
                    R['publicaciones']['error'] += 1
                    R['avisos'].append(f'{url[:70]}: {res.get("detalle", "error de lectura")}')
                if pausa:
                    _pausa(config.PAUSA_ENTRE_PUBLICACIONES)

        # 5) Stock bajo: lógica lista, DESACTIVADA hasta que la columna tenga el dato real
        if config.STOCK_ALERTAS_ACTIVAS:
            for d in skus:
                if not d['links']:
                    continue
                dd = ev.evento_stock_bajo(d['stock'])
                if dd:
                    rr = next((r for r in refs if cdb.norm_texto(r['sku']) == cdb.norm_texto(d['sku']) and vigente(r)), None)
                    emitir(dd, rr, entidad='', link='')
        else:
            R['pendientes_stock'] = 'Stock bajo DESACTIVADO: la columna de stock de B-SKU todavía no tiene el dato real.'
    finally:
        R['lecturas'] = len(lecturas)
        R['descubrimiento_nuevas'] = len(disc_nuevas)
        if escribir:
            _escribir(ss, titulos, plan, ents_nuevas_por_lectura, cambios_ref, lecturas, eventos, disc_nuevas, R, log)
    if bloqueo:
        R['bloqueo'] = bloqueo
        raise CorridaBloqueada(bloqueo)
    return R


def _escribir(ss, titulos, plan, ents_extra, cambios_ref, lecturas, eventos, disc_nuevas, R, log):
    ent_ws = cdb.asegurar_pestana(ss, 'Entidades', ENT_HEADERS, 1000)
    ref_ws = cdb.asegurar_pestana(ss, 'Referencias_Mercado', REF_HEADERS, 1000)
    ent_h = sio.asegurar_columnas(ent_ws, ENT_HEADERS)
    ref_h = sio.asegurar_columnas(ref_ws, REF_HEADERS + [cdb.REFERENCIAS_COL_EXTRA, sy.COL_ROL])
    sio.agregar(ent_ws, ent_h, plan.entidades_nuevas + ents_extra)
    sio.agregar(ref_ws, ref_h, plan.refs_nuevas)
    if plan.entidades_link:
        filas = {r[0]: n for n, r in enumerate(ent_ws.get_all_values(), start=1) if r}
        sio.actualizar_celdas(ent_ws, ent_h, [(filas[x['Entidad_ID']], 'Link_ML', x['Link_ML'])
                                              for x in plan.entidades_link if x['Entidad_ID'] in filas])
    if plan.rol_updates or cambios_ref:
        filas = {r[0]: n for n, r in enumerate(ref_ws.get_all_values(), start=1) if r}
        celdas = [(filas[u['Referencia_ID']], sy.COL_ROL, u['Rol']) for u in plan.rol_updates if u['Referencia_ID'] in filas]
        sio.actualizar_celdas(ref_ws, ref_h, celdas + list(cambios_ref))
    if lecturas:
        ws = cdb.asegurar_pestana(ss, cdb.HISTORIAL_SHEET, HISTORIAL_HEADERS_V2, 20000)
        hh = sio.asegurar_columnas(ws, HISTORIAL_HEADERS_V2)
        ins, act = sio.upsert(ws, hh, list(lecturas.values()), ['Referencia_ID', 'Fecha'])
        R['lecturas_escritas'] = {'nuevas': ins, 'reemplazadas': act}
    if eventos:
        ws = cdb.asegurar_pestana(ss, ev.EVENTOS_SHEET, ev.EVENTOS_HEADERS, 5000)
        sio.upsert(ws, ev.EVENTOS_HEADERS, eventos, ['Fecha', 'Tipo', 'Referencia_ID', 'Entidad'])
    if disc_nuevas:
        ws = cdb.asegurar_pestana(ss, DISCOVERY_SHEET, DISCOVERY_HEADERS, 5000)
        sio.agregar(ws, DISCOVERY_HEADERS, disc_nuevas)
    log('Escritura al Sheet terminada.')
