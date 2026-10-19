"""Orquestación de una corrida del scraper: sincroniza la planilla de Maca, lee perfiles y publicaciones, escribe las
lecturas a Historial_Precios y detecta eventos. El lector (Selenium) y las hojas se INYECTAN: así se prueba entero
sin red. Reglas de la Etapa 1: una fila por lectura, solo con precio, idempotente por referencia y día."""
import random
import re
import time
from datetime import datetime

import config
import competencia_db as cdb
import categorias_competidores as cc
import eventos as ev
import planilla_maca as pm
import sheets_io as sio
import sincronizar as sy
import paginas_ml as pml
import celdas as cel
import tiendas_conteo as tc
import tiendas_estado as te
import errores
from errores import CorridaCortada, NavegadorCaido

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
def _refs_con_lectura_hoy(filas_hist, hoy):
    if not filas_hist:
        return set()
    h = {x: i for i, x in enumerate(filas_hist[0])}
    if 'Referencia_ID' not in h or 'Fecha' not in h:
        return set()
    return {f[h['Referencia_ID']] for f in filas_hist[1:] if len(f) > max(h['Referencia_ID'], h['Fecha']) and f[h['Fecha']].strip() == hoy}


def _tiendas_completas_hoy(filas_conteo, hoy):
    if not filas_conteo:
        return set()
    h = {x: i for i, x in enumerate(filas_conteo[0])}
    try:
        return {f[h['Entidad_ID']] for f in filas_conteo[1:]
                if f[h['Fecha']].strip() == hoy and str(f[h['Completa']]).strip().lower() in ('si', 'sí')}
    except (KeyError, IndexError):
        return set()


def _evidencia_corta(ev_):
    """Una línea con lo esencial de la evidencia de paginación (el detalle completo queda en el JSON de la corrida)."""
    if not ev_ or 'error' in ev_:
        return ''
    ctl = ev_.get('controles') or []
    return (f"{len(ctl)} controles de siguiente/más en la página " + str([c.get('texto') or c.get('aria') for c in ctl][:4])
            + f" · {ev_.get('tarjetas')} tarjetas · hay paginador: {'sí' if ev_.get('paginacion_html') else 'NO'}")


def correr(ss, filas_maca, lector, *, vendedor=None, solo=None, escribir=True, descubrir=True, hoy=None, ahora=None,
           log=print, pausa=True, reanudar=False, max_minutos=None):
    """ss: Spreadsheet del ERP. filas_maca: {'A': filas, 'B': filas}. lector: ver ml_selenium.LectorML.
    -> resumen (dict). Si ML bloquea, escribe lo que haya y levanta CorridaBloqueada."""
    ahora = ahora or datetime.now()
    t_inicio = time.time()
    limite_seg = (config.DURACION_MAXIMA_MIN if max_minutos is None else max_minutos) * 60

    def tiempo_agotado():
        return limite_seg and (time.time() - t_inicio) > limite_seg
    hoy = hoy or ahora.strftime('%d/%m/%Y')
    hora = ahora.strftime('%H:%M')
    R = {'fecha': hoy, 'escribir': escribir, 'vendedor': vendedor or 'todos', 'solo': solo or 'todo',
         'sync': {}, 'perfiles': {'leidos': 0, 'ok': 0, 'sin_resultados': 0, 'error': 0, 'items': 0, 'saltados_reanudar': 0, 'bloqueadas': []},
         'publicaciones': {'leidas': 0, 'ok': 0, 'caidas': 0, 'sin_lectura': 0, 'otro_vendedor': 0, 'error': 0,
                           'saltadas_por_perfil': 0, 'via': {}, 'solo_precio_ganador': 0, 'catalogo_sin_wid': 0, 'ya_hechas': 0, 'bloqueadas': 0},
         'para_completar_en_la_planilla': [], 'tiendas': [], 'celdas': None, 'reanudar': reanudar, 'corte': None,
         'navegador_reinicios': 0,
         'lecturas': 0, 'eventos': {}, 'descubrimiento_nuevas': 0, 'avisos': [], 'pendientes_stock': None}

    titulos = {w.title for w in ss.worksheets()}
    ents_f, refs_f = sio.leer(ss, 'Entidades', titulos), sio.leer(ss, 'Referencias_Mercado', titulos)
    hist_f, ev_f = sio.leer(ss, cdb.HISTORIAL_SHEET, titulos), sio.leer(ss, ev.EVENTOS_SHEET, titulos)
    disc_f = sio.leer(ss, DISCOVERY_SHEET, titulos)
    conteo_f = sio.leer(ss, tc.CONTEO_SHEET, titulos)
    estado_f = sio.leer(ss, te.ESTADO_SHEET, titulos)

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
    lecturas, eventos, disc_nuevas, conteos, estados = {}, [], [], [], []
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

    bloqueo, corte = None, None
    bloq_tiendas = bloq_pubs = 0      # bloqueos (captcha/verificación) SEGUIDOS: uno aislado se saltea; varios seguidos cortan la corrida
    ya_hoy = _refs_con_lectura_hoy(hist_f, hoy) if reanudar else set()
    tiendas_ok_hoy = _tiendas_completas_hoy(conteo_f, hoy) if reanudar else set()
    try:
        # 3) Perfiles de tienda
        if solo in (None, 'perfiles'):
            vistos_perfil = set()
            for p in plan.perfiles:
                if p['slug'] in vistos_perfil or p['excluida'] or not _coincide_filtro(p['entidad_nombre'], vendedor):
                    continue
                if tiempo_agotado():
                    corte = f'Se alcanzó el tiempo máximo de la corrida ({limite_seg // 60} min)'
                    break
                vistos_perfil.add(p['slug'])
                if reanudar and p['entidad_id'] in tiendas_ok_hoy:
                    R['perfiles']['saltados_reanudar'] += 1      # esta tienda ya se leyó COMPLETA hoy
                    continue
                R['perfiles']['leidos'] += 1
                log(f"Perfil {p['entidad_nombre']}: {p['url_listado']}")
                try:
                    t = lector.leer_tienda(p['url_listado'])
                except NavegadorCaido as e:
                    corte = f'Chrome se cayó demasiadas veces: {e}'
                    break
                except Exception as e:  # noqa: BLE001  (un error inesperado en una tienda no corta las demás)
                    R['perfiles']['error'] += 1
                    R['avisos'].append(f"Perfil {p['entidad_nombre']}: {type(e).__name__}: {str(e)[:120]}")
                    continue
                # Conteo diario de la tienda (Fase 1): también el día que no se pudo leer (queda como Completa=No)
                n_leidas = len(t.get('items') or [])
                completa, motivo_c = t.get('completa'), t.get('motivo', '')
                if completa is None:
                    completa, motivo_c = pml.evaluar_completitud(n_leidas, t.get('declaradas'), t.get('fin', 'sin_siguiente'),
                                                                 t['estado'] == 'bloqueado')
                previas = tc.validas_previas(conteo_f, p['entidad_id'], hoy)
                fila_c = tc.fila_conteo(hoy, hora, p['entidad_id'], p['entidad_nombre'], n_leidas, t.get('declaradas'),
                                        t.get('paginas'), completa, motivo_c, previas)
                # Fase 2: Nuevas / Desaparecidas contra el estado guardado (solo con lectura completa y sin bloqueo)
                f_est, nuevas_t, desap_t, siembra_t = te.actualizar(
                    te.estado_de_tienda(estado_f, p['entidad_id']), p['entidad_id'],
                    [te.ident_texto(sy.ident_publicacion(it['link'])) for it in (t.get('items') or [])],
                    bool(completa) and t['estado'] != 'bloqueado', hoy)
                estados += f_est
                fila_c['Nuevas'], fila_c['Desaparecidas'] = ('' if nuevas_t is None else nuevas_t), ('' if desap_t is None else desap_t)
                conteos.append(fila_c)
                R['tiendas'].append({'entidad': p['entidad_nombre'], 'leidas': n_leidas, 'declaradas': t.get('declaradas'),
                                     'completa': completa, 'motivo': motivo_c, 'mediana': fila_c['Mediana_7d'],
                                     'nuevas': fila_c['Nuevas'], 'desaparecidas': fila_c['Desaparecidas'], 'siembra': siembra_t,
                                     'var': fila_c['Var_vs_Mediana_Pct'], 'via_paginacion': t.get('via_paginacion'),
                                     'evidencia_paginacion': t.get('evidencia_paginacion')})
                if not completa and t['estado'] != 'bloqueado':
                    R['avisos'].append(f"{p['entidad_nombre']}: lectura INCOMPLETA ({motivo_c}). " + _evidencia_corta(t.get('evidencia_paginacion')))
                if t['estado'] == 'bloqueado':
                    tipo_b = t.get('bloqueo') or 'captcha'
                    if tipo_b == 'login':      # sesión vencida: afecta a TODO, no tiene sentido seguir
                        bloqueo = t.get('detalle', 'ML pidió login')
                        break
                    # captcha/verificación en ESTA tienda: se saltea y se sigue con las demás
                    R['perfiles']['bloqueadas'].append({'entidad': p['entidad_nombre'], 'tipo': tipo_b, 'leidas': n_leidas, 'motivo': motivo_c})
                    bloq_tiendas += 1
                    emitir({'Tipo': ev.TIENDA_BLOQUEADA, 'Detalle': f'ML pidió {tipo_b}: {motivo_c}'}, entidad=p['entidad_nombre'], link=p['url_listado'])
                    R['avisos'].append(f"{p['entidad_nombre']}: ML pidió {tipo_b} ({motivo_c}). Se saltea; hoy no hay conteo completo de esa tienda.")
                    if bloq_tiendas >= config.MAX_BLOQUEOS_SEGUIDOS_TIENDAS:
                        bloqueo = f'ML pidió {tipo_b} en {bloq_tiendas} tiendas seguidas: nos está frenando a nosotros, no a una tienda'
                        break
                    if pausa:
                        time.sleep(config.PAUSA_TRAS_CAPTCHA_SEG)       # enfriamiento antes de la próxima tienda
                    if not t['items']:
                        continue
                    # lo leído ANTES del captcha son lecturas válidas: se guardan (el conteo ya quedó como INCOMPLETO)
                else:
                    bloq_tiendas = 0
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
                if t['estado'] == 'ok':
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
        if bloqueo is None and corte is None and solo in (None, 'publicaciones'):
            tareas = {}   # url -> [refs]
            for d in skus:
                for l in d['links']:
                    ident = sy.ident_publicacion(l['url'])
                    for r in por_ident.get(ident, []) if ident else []:
                        if r['sku'] and cdb.norm_texto(r['sku']) == cdb.norm_texto(d['sku']) and r['rol']:
                            tareas.setdefault(l['url'], []).append(r)
            for url, rs in tareas.items():
                if tiempo_agotado():
                    corte = f'Se alcanzó el tiempo máximo de la corrida ({limite_seg // 60} min)'
                    break
                rs = list({x['id']: x for x in rs}.values())
                if vendedor:   # "actualizar un vendedor": solo las referencias YA atribuidas a ese vendedor
                    rs = [r for r in rs if r['entidad'] and _coincide_filtro(r['entidad'], vendedor)]
                if not rs:
                    continue
                if reanudar:      # lo que ya tiene lectura de HOY no se vuelve a abrir
                    rs_f = [r for r in rs if r['id'] not in ya_hoy]
                    if not rs_f:
                        R['publicaciones']['ya_hechas'] += 1
                        continue
                    rs = rs_f
                pendientes = [r for r in rs if r['id'] not in leidas_por_perfil]
                if not pendientes:
                    R['publicaciones']['saltadas_por_perfil'] += 1
                    continue
                esperado = next((r['entidad'] for r in pendientes if r['entidad']), None)
                ident_u = sy.ident_publicacion(url)
                if ident_u and ident_u[0] == 'Pn' and not esperado:
                    # Catálogo SIN wid y sin vendedor conocido: no hay forma de saber cuál es la oferta del competidor.
                    # No se abre (no es un error ni una lectura fallida): se lista para que Maca complete el wid.
                    R['publicaciones']['catalogo_sin_wid'] += 1
                    for r in pendientes:
                        R['para_completar_en_la_planilla'].append({'sku': r['sku'], 'rol': r['rol'], 'link': url,
                                                                   'falta': 'el wid de la oferta (link de catálogo sin ?wid=)'})
                    continue
                R['publicaciones']['leidas'] += 1
                try:
                    res = lector.leer_publicacion(url, esperado)
                except NavegadorCaido as e:
                    corte = f'Chrome se cayó demasiadas veces: {e}'
                    break
                except Exception as e:  # noqa: BLE001  (una publicación que falla no corta las demás)
                    res = {'estado': 'Error', 'precio': None, 'vendedor': '', 'detalle': f'{type(e).__name__}: {str(e)[:120]}'}
                est = res['estado']
                if est == 'Bloqueado':
                    tipo_b = res.get('bloqueo') or 'captcha'
                    R['publicaciones']['bloqueadas'] += 1
                    if tipo_b == 'login':
                        bloqueo = res.get('detalle', 'ML pidió login')
                        break
                    bloq_pubs += 1
                    if bloq_pubs >= config.MAX_BLOQUEOS_SEGUIDOS_PUBLICACIONES:
                        bloqueo = f'ML pidió {tipo_b} en {bloq_pubs} publicaciones seguidas: nos está frenando a nosotros'
                        break
                    if pausa:
                        time.sleep(config.PAUSA_TRAS_CAPTCHA_SEG)
                    continue
                bloq_pubs = 0
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
        R['navegador_reinicios'] = getattr(lector, 'reinicios', 0)
        if escribir:
            _escribir(ss, titulos, plan, ents_nuevas_por_lectura, cambios_ref, lecturas, eventos, disc_nuevas, conteos, estados, R, log)
        R['celdas'] = cel.medir(ss)
    if bloqueo:
        R['bloqueo'] = bloqueo
        e = CorridaBloqueada(bloqueo)
        e.resumen = R
        raise e
    if corte:
        R['corte'] = corte
        e = CorridaCortada(corte)
        e.resumen = R
        raise e
    return R


def _escribir(ss, titulos, plan, ents_extra, cambios_ref, lecturas, eventos, disc_nuevas, conteos, estados, R, log):
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
    if plan.perfiles:
        nuevas, act = cc.registrar(ss, plan.perfiles, R['fecha'])
        R['categoria_competidores'] = {'nuevas': nuevas, 'actualizadas': act}
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
    if conteos:
        ins, act, _ = tc.registrar(ss, conteos)
        R['conteos_escritos'] = {'nuevos': ins, 'reemplazados': act}
    if estados:
        ins, act = te.registrar(ss, estados)
        R['estado_tiendas_escrito'] = {'nuevas': ins, 'actualizadas': act}
    log('Escritura al Sheet terminada.')


def texto_resumen(R):
    """Resumen legible de una corrida (lo que se imprime al final y queda en el log)."""
    pl, pu, sy_ = R['perfiles'], R['publicaciones'], R['sync']
    plan = sy_.get('planilla', {})
    L = ['', f"=== RESUMEN {R['fecha']} · vendedor={R['vendedor']} · solo={R['solo']} · {'ESCRIBIÓ' if R['escribir'] else 'SIN escribir'} ===",
         f"Planilla de Maca: {plan.get('skus', 0)} SKU · {plan.get('skus_con_links', 0)} con competidores cargados "
         f"({plan.get('links', 0)} links) · {plan.get('skus_sin_competidor_cargado', 0)} SKU sin competidor cargado todavía "
         f"(celdas con guion: {plan.get('celdas_con_guion', 0)}, vacías: {plan.get('celdas_vacias', 0)}) · {plan.get('perfiles', 0)} perfiles",
         f"Base: entidades nuevas {sy_.get('entidades_nuevas', [])} · referencias nuevas {sy_.get('refs_nuevas', 0)} · "
         f"roles completados {sy_.get('roles_a_completar', 0)} · Link_ML completados {sy_.get('link_ml_a_completar', 0)}",
         f"Perfiles de tienda: {pl['leidos']} leídos · {pl['ok']} ok ({pl['items']} publicaciones) · {pl['sin_resultados']} sin resultados · {pl['error']} con error"
         + (f" · {pl['items_sin_identidad']} tarjetas sin identidad ML" if pl.get('items_sin_identidad') else ''),
         f"Publicaciones puntuales: {pu['leidas']} leídas · {pu['ok']} ok {pu['via'] or ''} · {pu['caidas']} caídas · "
         f"{pu['sin_lectura']} sin lectura · {pu['otro_vendedor']} de otro vendedor · {pu['error']} con error · "
         f"{pu['saltadas_por_perfil']} ya leídas por el perfil",
         f"Lecturas a Historial_Precios: {R['lecturas']}" + (f" {R['lecturas_escritas']}" if R.get('lecturas_escritas') else ''),
         f"Eventos: {R['eventos'] or 'ninguno'}",
         f"Descubrimiento (publicaciones de tienda que no son referencias): {R['descubrimiento_nuevas']} nuevas"]
    if pl.get('bloqueadas'):
        L.append('Tiendas bloqueadas por captcha/verificación (se saltearon; el resto siguió):')
        L += [f"   - {b['entidad']}: {b['tipo']} · {b['motivo']}" for b in pl['bloqueadas']]
    if pu.get('bloqueadas'):
        L.append(f"Publicaciones bloqueadas por captcha/verificación: {pu['bloqueadas']}")
    if R.get('reanudar'):
        L.append(f"MODO REANUDAR: {pl.get('saltados_reanudar', 0)} tiendas y {pu.get('ya_hechas', 0)} publicaciones ya estaban hechas hoy y no se repitieron.")
    if R.get('navegador_reinicios'):
        L.append(f"Chrome se reabrió {R['navegador_reinicios']} vez/veces durante la corrida (reciclado preventivo o caída).")
    if R.get('corte'):
        L.append(f"⚠ CORRIDA CORTADA: {R['corte']}. Lo leído hasta acá se escribió; con --reanudar se retoma lo que falta.")
    if R.get('tiendas'):
        L.append('Conteo por tienda (Tiendas_Conteo):')
        for t in R['tiendas']:
            dec = f" / {t['declaradas']} declaradas" if t['declaradas'] else ''
            med = f" · mediana {t['mediana']} ({t['var']:+}%)" if t['mediana'] != '' and t['var'] != '' else (f" · mediana {t['mediana']}" if t['mediana'] != '' else ' · línea base en construcción')
            via = f" · paginación {t['via_paginacion']}" if t.get('via_paginacion') else ''
            cambio = ('' if t.get('nuevas', '') == '' else f" · +{t['nuevas']} nuevas / -{t['desaparecidas']} desaparecidas") + (' · estado sembrado hoy (sin comparación)' if t.get('siembra') else '')
            L.append(f"   - {t['entidad']}: {t['leidas']} leídas{dec} · " + ('completa' if t['completa'] else f"INCOMPLETA ({t['motivo']})") + med + cambio + via)
    if R.get('celdas'):
        L.append(cel.texto(R['celdas']))
    if pu['catalogo_sin_wid']:
        L.append(f"Para completar en la planilla ({pu['catalogo_sin_wid']} links de catálogo sin wid, NO se leyeron):")
        L += [f"   - {x['sku']} ({x['rol']}): {x['link'][:90]}" for x in R['para_completar_en_la_planilla'][:15]]
    if sy_.get('diferencias_sku'):
        L.append(f"Mismo link con otro SKU en la base (informativo): {len(sy_['diferencias_sku'])}")
    if R.get('pendientes_stock'):
        L.append(R['pendientes_stock'])
    if R['avisos']:
        L.append(f"Avisos ({len(R['avisos'])}):")
        L += [f'   - {a}' for a in R['avisos'][:15]]
    return '\n'.join(L)
