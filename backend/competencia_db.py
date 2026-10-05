"""Base de datos de competencia unificada (Etapa 1 del módulo de competencia,
docs/business/MODULO_COMPETENCIA_SPEC.md).

Un solo registro de links (`Referencias_Mercado`, Tipo=Competencia, con el SKU
resuelto una vez) y un solo histórico en formato largo (`Historial_Precios`,
una fila por lectura). Este módulo es lógica pura (sin red, sin FastAPI):
recibe/entrega listas de filas, así se testea sin Google y lo usan tanto
`main.py` (escritura en vivo) como `scripts/migrar_competencia.py`.

Reglas: la categoría NO se toca (la define Maca a mano en el Excel); no se
adivina SKU por título; nada se borra ni se edita de lo existente."""
import hashlib
import json
import re
import time
from datetime import datetime

HISTORIAL_SHEET = 'Historial_Precios'
HUERFANOS_SHEET = 'Migracion_Huerfanos'
HISTORIAL_HEADERS = ['Referencia_ID', 'SKU', 'Entidad', 'Fecha', 'Hora', 'Precio', 'Precio_Tachado',
                     'Descuento', 'Cuotas', 'Estado', 'Metodo', 'Fuente', 'Link']
HUERFANOS_HEADERS = ['Fuente', 'Pestana_Origen', 'Fila_Origen', 'Detalle', 'Motivo', 'Fecha_Migracion', 'Dato_Original']
REFERENCIAS_COL_EXTRA = 'Cantidad'  # unidades por publicación (kits); se agrega al final de Referencias_Mercado

F_V = 'V-*'
F_GENERAL = 'General'
F_MLCOMP = 'ML Competencia'
F_H2 = 'Historial Competidores'
F_H3 = 'Monitor_Lecturas'
F_VIVO = 'En vivo'

# ── Identidad de publicación (misma lógica que main._monitor_extract_ids) ─────
_PATH_ITEM = re.compile(r'/(ML[A-Z]+-?\d{8,})')
_PATH_P = re.compile(r'/p/(ML[A-Z]+-?\d+)', re.I)
_PATH_UP = re.compile(r'/up/(ML[A-Z]+-?\d+)', re.I)
_PARAM_ITEM = re.compile(r'item_id:(ML[A-Z]+-?\d+)', re.I)
_PARAM_WID = re.compile(r'[?&#]wid=(ML[A-Z]+-?\d+)', re.I)


def _norm_id(raw):
    return re.sub(r'[^A-Z0-9]', '', raw.upper())


def extraer_ids(link):
    s = str(link or '')
    cut = min([i for i in (s.find('?'), s.find('#')) if i != -1] or [len(s)])
    path = s[:cut]
    product_id = None
    for pat in (_PATH_P, _PATH_UP):
        m = pat.search(path)
        if m:
            product_id = _norm_id(m.group(1)); break
    wid = None
    m = _PARAM_WID.search(s)
    if m:
        wid = _norm_id(m.group(1))
    item_id = None
    if not product_id:
        m = _PATH_ITEM.search(path) or _PARAM_ITEM.search(s)
        if m:
            item_id = _norm_id(m.group(1))
        elif wid:
            item_id = wid
    return {'product_id': product_id, 'wid': wid, 'item_id': item_id}


def norm_texto(s):
    return re.sub(r'\s+', ' ', str(s or '').strip().lower())


def clave_ref(link, entidad='', item_id=''):
    """Identidad estable de una publicación de un vendedor. Catálogo con wid =
    (producto, oferta); catálogo SIN wid no distingue vendedor, así que se
    desambigua por entidad; ítem individual = su MLA. None si no hay identificador."""
    ids = extraer_ids(link)
    if ids['product_id'] and ids['wid']:
        return ('P', ids['product_id'], ids['wid'])
    if ids['product_id']:
        return ('Pn', ids['product_id'], norm_texto(entidad))
    if ids['item_id']:
        return ('I', ids['item_id'])
    if item_id:
        return ('I', _norm_id(str(item_id)))
    return None


def es_catalogo_sin_wid(link):
    ids = extraer_ids(link)
    return bool(ids['product_id'] and not ids['wid'])


# ── Parseo de valores de Sheets ───────────────────────────────────────────────
def parse_fecha(v):
    """-> (fecha 'dd/mm/aaaa', hora 'HH:MM' o '') o (None, '') si no se entiende."""
    s = str(v or '').strip()
    if not s:
        return None, ''
    for fmt, tiene_hora in (('%d/%m/%Y %H:%M', True), ('%d/%m/%Y %H:%M:%S', True), ('%d/%m/%Y', False),
                            ('%Y-%m-%d %H:%M:%S', True), ('%Y-%m-%d %H:%M', True), ('%Y-%m-%d', False),
                            ('%d-%m-%Y', False)):
        try:
            d = datetime.strptime(s, fmt)
            return d.strftime('%d/%m/%Y'), (d.strftime('%H:%M') if tiene_hora else '')
        except ValueError:
            continue
    return None, ''


def parse_precio(v):
    """'$ 1.234.567' / '1234,50' / 1234 -> float; vacío o no numérico -> None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r'[^\d.,-]', '', str(v))
    if not s or not re.search(r'\d', s):
        return None
    if '.' in s and ',' in s:
        s = s.replace('.', '').replace(',', '.')
    elif ',' in s:
        s = s.replace(',', '.') if re.fullmatch(r'-?\d+,\d{1,2}', s) else s.replace(',', '')
    elif '.' in s and re.fullmatch(r'-?\d{1,3}(\.\d{3})+', s):
        s = s.replace('.', '')
    try:
        return float(s)
    except ValueError:
        return None


def _num_out(p):
    if p is None:
        return ''
    return int(p) if float(p).is_integer() else round(float(p), 2)


_SKU_VACIO = {'-', '--', '—', '–', 'n/a', 'na', 's/d', 'sin sku', 'null', 'none'}


def limpiar_sku(v):
    """'-' y similares son 'sin SKU' en las planillas: no son un SKU real (no generan conflictos)."""
    v = str(v or '').strip()
    return '' if v.lower() in _SKU_VACIO else v


def _celda(fila, i):
    return str(fila[i]).strip() if i is not None and i < len(fila) else ''


def _idx_headers(headers):
    return {str(h).strip(): i for i, h in enumerate(headers)}


# ── Planificación de la migración ─────────────────────────────────────────────
def _hash_fila(fila):
    return hashlib.sha1(json.dumps(list(fila), ensure_ascii=False).encode()).hexdigest()[:10]


class Plan:
    def __init__(self):
        self.entidades_nuevas = []   # dicts
        self.refs_nuevas = []        # dicts
        self.lecturas = []           # dicts a escribir (ya deduplicadas y sin las existentes)
        self.huerfanos = []          # dicts a escribir
        self.rep = {}                # informe


def _split_bloques_v(headers):
    """Devuelve (base, bloques, no_reconocidas). base: idx de columnas sin fecha;
    bloques: {fecha: {precio,tachado,desc,cuotas}}; no_reconocidas: headers que no encajan."""
    base, bloques, raros = {}, {}, []
    for i, h in enumerate(headers):
        h = str(h).strip()
        hl = h.lower()
        if not h:
            continue
        m = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', h)
        campo = None
        if 'tachado' in hl:
            campo = 'tachado'
        elif hl.startswith('precio'):
            campo = 'precio'
        elif hl.startswith('desc'):
            campo = 'desc'
        elif 'cuota' in hl:
            campo = 'cuotas'
        if m and campo:
            f, _ = parse_fecha(m.group(1))
            f = f or m.group(1)
            # misma fecha repetida (ej. dos scrapes el mismo día): bloque aparte, no se pisa el anterior
            k, n = f, 1
            while campo in bloques.get(k, {}):
                n += 1
                k = f'{f}#{n}'
            bloques.setdefault(k, {})[campo] = i
        elif not m and campo and campo not in base:
            base[campo] = i
        elif hl in ('titulo', 'título', 'title') and 'titulo' not in base:
            base['titulo'] = i
        elif 'link' in hl and 'link' not in base:
            base['link'] = i
        elif hl == 'sku':
            base['sku'] = i
        elif 'cantidad' in hl:
            base['cantidad'] = i
        elif hl in ('ventas',):
            base['ventas'] = i
        else:
            raros.append(h)
    return base, bloques, raros


def planificar(fuentes, hoy=None):
    """fuentes: dict con listas de filas (la primera es el header):
      refs, ents, v_tabs {nombre_pestaña: filas}, general, ml_competencia, hist_competidores,
      monitor, historial_existente (opcional), huerfanos_existentes (opcional).
    No toca nada: devuelve un Plan con el informe de conteos."""
    hoy = hoy or datetime.now().strftime('%d/%m/%Y')
    plan = Plan()
    rep = plan.rep = {'fuentes': {}, 'notas': [], 'conflictos_sku': [], 'sku_completables': [],
                      'columnas_no_reconocidas': {}, 'links_sin_identificador': 0}

    def fuente(nombre):
        return rep['fuentes'].setdefault(nombre, {'origen': 0, 'nuevas': 0, 'fusionadas': 0,
                                                  'ya_existian': 0, 'huerfanas': 0})

    # --- Entidades y referencias existentes ---
    ents = fuentes.get('ents') or [[]]
    eh = _idx_headers(ents[0]) if ents else {}
    ent_por_nombre, ent_ids = {}, []
    ent_nombre_por_id = {}
    for r in ents[1:]:
        nombre, eid = _celda(r, eh.get('Nombre')), _celda(r, eh.get('Entidad_ID'))
        if eid:
            ent_ids.append(eid)
            ent_nombre_por_id[eid] = nombre
        if nombre and _celda(r, eh.get('Tipo')) == 'Competencia':
            ent_por_nombre.setdefault(norm_texto(nombre), eid)
    refs = fuentes.get('refs') or [[]]
    rh = _idx_headers(refs[0]) if refs else {}
    ref_ids = []
    ref_por_clave = {}   # solo Tipo=Competencia (se reutilizan)
    ref_por_id = {}
    refs_distrib = {}    # (entidad_norm, sku_norm, link) -> ref_id
    for r in refs[1:]:
        rid = _celda(r, rh.get('Referencia_ID'))
        if not rid:
            continue
        ref_ids.append(rid)
        tipo = _celda(r, rh.get('Tipo'))
        link = _celda(r, rh.get('Link_Publicacion'))
        sku = _celda(r, rh.get('SKU'))
        ent = _celda(r, rh.get('Entidad_Nombre'))
        sku = limpiar_sku(sku)
        ref_por_id[rid] = {'id': rid, 'sku': sku, 'entidad': ent, 'link': link, 'tipo': tipo}
        if tipo == 'Competencia':
            k = clave_ref(link, ent)
            if k:
                ref_por_clave.setdefault(k, rid)
        elif tipo == 'Distribuidor':
            refs_distrib[(norm_texto(ent), norm_texto(sku), link)] = rid

    def siguiente(prefijo, ids):
        n = 0
        for v in ids:
            m = re.fullmatch(prefijo + r'-(\d+)', str(v).strip())
            if m:
                n = max(n, int(m.group(1)))
        return n

    seq = {'ENT': siguiente('ENT', ent_ids), 'REF': siguiente('REF', ref_ids)}

    def entidad(nombre):
        nombre = str(nombre or '').strip()
        if not nombre:
            return '', ''
        k = norm_texto(nombre)
        if k not in ent_por_nombre:
            seq['ENT'] += 1
            eid = f'ENT-{seq["ENT"]:06d}'
            ent_por_nombre[k] = eid
            plan.entidades_nuevas.append({'Entidad_ID': eid, 'Nombre': nombre, 'Tipo': 'Competencia',
                                          'Fecha_Alta': hoy})
        return ent_por_nombre[k], nombre

    def asegurar_ref(link, nombre_ent, sku, cantidad, origen, item_id=''):
        """-> referencia (dict) o None si el link no tiene identificador ML."""
        k = clave_ref(link, nombre_ent, item_id)
        if k is None:
            return None
        sku, cantidad = limpiar_sku(sku), str(cantidad or '').strip()
        if k in ref_por_clave:
            r = ref_por_id.get(ref_por_clave[k])
            if r is not None:
                if sku and r['sku'] and norm_texto(sku) != norm_texto(r['sku']):
                    rep['conflictos_sku'].append({'referencia': r['id'], 'sku_existente': r['sku'],
                                                  'sku_nuevo': sku, 'link': link})
                elif sku and not r['sku']:
                    rep['sku_completables'].append({'referencia': r['id'], 'sku': sku, 'link': link})
            return r
        eid, enombre = entidad(nombre_ent)
        seq['REF'] += 1
        rid = f'REF-{seq["REF"]:06d}'
        r = {'id': rid, 'sku': sku, 'entidad': enombre, 'link': link, 'tipo': 'Competencia'}
        ref_por_clave[k] = rid
        ref_por_id[rid] = r
        plan.refs_nuevas.append({
            'Referencia_ID': rid, 'SKU': sku, 'Tipo': 'Competencia', 'Entidad_ID': eid, 'Entidad_Nombre': enombre,
            'Link_Publicacion': link, 'Activo': 'Si', 'Fecha_Alta': hoy, 'Origen': origen,
            'Cantidad': cantidad or '1'})
        return r

    # --- General: link -> sku/cantidad/vendedor ---
    gen_map = {}
    gen = fuentes.get('general') or []
    for r in gen[1:]:
        link = _celda(r, 0)
        if link:
            d = {'sku': _celda(r, 1), 'cantidad': _celda(r, 2), 'vendedor': _celda(r, 3)}
            gen_map.setdefault(link, d)
            gen_map.setdefault(link.split('?')[0], d)

    candidatas = []  # lecturas crudas antes de deduplicar: dict + fuente + pestaña + fila

    def huerfano(fte, pestana, fila_n, detalle, motivo, fila):
        fuente(fte)['origen'] += 1
        fuente(fte)['huerfanas'] += 1
        plan.huerfanos.append({'Fuente': fte, 'Pestana_Origen': pestana, 'Fila_Origen': fila_n, 'Detalle': detalle,
                               'Motivo': motivo, 'Fecha_Migracion': hoy,
                               'Dato_Original': json.dumps(list(fila), ensure_ascii=False)})

    def lectura(fte, ref, fecha, hora, precio, tachado, desc, cuotas, estado, metodo, link):
        fuente(fte)['origen'] += 1
        candidatas.append({'fuente': fte, 'ref': ref, 'fecha': fecha, 'hora': hora, 'precio': precio,
                           'tachado': tachado, 'desc': desc, 'cuotas': cuotas, 'estado': estado,
                           'metodo': metodo, 'link': link})

    # --- V-*: registro de links + bloques de lecturas ---
    for tab, filas in sorted((fuentes.get('v_tabs') or {}).items()):
        if len(filas) < 2:
            continue
        vendedor = re.sub(r'^V - ', '', tab)
        base, bloques, raros = _split_bloques_v(filas[0])
        if raros:
            rep['columnas_no_reconocidas'][tab] = raros
        for n, f in enumerate(filas[1:], start=2):
            link = _celda(f, base.get('link'))
            sku = _celda(f, base.get('sku'))
            g = gen_map.get(link) or gen_map.get(link.split('?')[0]) or {}
            sku = sku or g.get('sku', '')
            cantidad = g.get('cantidad') or _celda(f, base.get('cantidad')) or '1'
            ref = asegurar_ref(link, vendedor, sku, cantidad, 'Migracion V-*') if link else None
            lecs = []  # (detalle, fecha, precio, tachado, desc, cuotas)
            for fecha_k, b in bloques.items():
                fecha = fecha_k.split('#')[0]
                p = _celda(f, b.get('precio'))
                d = _celda(f, b.get('desc'))
                if p or 'no encontr' in d.lower():
                    lecs.append((fecha_k, fecha, p, _celda(f, b.get('tachado')), d, _celda(f, b.get('cuotas'))))
            if _celda(f, base.get('precio')):
                lecs.append(('base (sin fecha)', None, _celda(f, base['precio']), _celda(f, base.get('tachado')),
                             _celda(f, base.get('desc')), _celda(f, base.get('cuotas'))))
            if link and ref is None:
                rep['links_sin_identificador'] += 1
            for detalle, fecha, p, t, d, c in lecs:
                if not link:
                    huerfano(F_V, tab, n, detalle, 'Fila sin link', f)
                elif ref is None:
                    huerfano(F_V, tab, n, detalle, 'Link sin identificador ML', f)
                elif fecha is None:
                    huerfano(F_V, tab, n, detalle, 'Lectura base sin fecha (primer scrape): falta decidir fecha', f)
                else:
                    pn = parse_precio(p)
                    estado = 'OK' if pn else 'No encontrado'
                    lectura(F_V, ref, fecha, '', pn, parse_precio(t), d, c, estado, 'Scraping vitrina', link)

    # --- General: links que no estaban en ninguna pestaña V-* (registro, sin lecturas) ---
    for r in gen[1:]:
        link = _celda(r, 0)
        if link:
            asegurar_ref(link, _celda(r, 3), _celda(r, 1), _celda(r, 2) or '1', 'Migracion General')

    # --- ML Competencia: link + última lectura ---
    mc = fuentes.get('ml_competencia') or []
    for n, f in enumerate(mc[1:], start=2):
        link = _celda(f, 0)
        if not link:
            continue
        ref = asegurar_ref(link, _celda(f, 2), (gen_map.get(link) or {}).get('sku', ''),
                           (gen_map.get(link) or {}).get('cantidad', ''), 'Migracion ML Competencia')
        precio = parse_precio(_celda(f, 3))
        if precio is None:
            continue  # '❌ Sin datos' o fila sin leer: no hay lectura
        if ref is None:
            rep['links_sin_identificador'] += 1
            huerfano(F_MLCOMP, 'ML Competencia', n, 'ultima lectura', 'Link sin identificador ML', f)
            continue
        fecha, hora = parse_fecha(_celda(f, 7))
        if not fecha:
            huerfano(F_MLCOMP, 'ML Competencia', n, 'ultima lectura', 'Sin fecha interpretable (Último Update)', f)
            continue
        lectura(F_MLCOMP, ref, fecha, hora, precio, parse_precio(_celda(f, 4)), _celda(f, 5), _celda(f, 6),
                'OK', 'API', link)

    # --- H2: Historial Competidores ---
    h2 = fuentes.get('hist_competidores') or []
    if h2:
        hx = _idx_headers(h2[0])
        for n, f in enumerate(h2[1:], start=2):
            if not any(str(c).strip() for c in f):
                continue
            link = _celda(f, hx.get('Link'))
            vend = _celda(f, hx.get('Vendedor'))
            item_id = _celda(f, hx.get('Item ID'))
            sku = _celda(f, hx.get('SKU'))
            ref = asegurar_ref(link, vend, sku, _celda(f, hx.get('Cantidad')), 'Migracion Historial Competidores',
                               item_id) if (link or item_id) else None
            fecha, hora = parse_fecha(_celda(f, hx.get('Fecha Refresh')))
            if not link and not item_id:
                huerfano(F_H2, HIST_H2_NOMBRE, n, '', 'Fila sin link ni Item ID', f)
            elif ref is None:
                huerfano(F_H2, HIST_H2_NOMBRE, n, '', 'Link sin identificador ML', f)
            elif not fecha:
                huerfano(F_H2, HIST_H2_NOMBRE, n, '', 'Sin fecha interpretable (Fecha Refresh)', f)
            else:
                pn = parse_precio(_celda(f, hx.get('Precio ($)')))
                lectura(F_H2, ref, fecha, hora, pn, parse_precio(_celda(f, hx.get('Precio Tachado ($)'))),
                        _celda(f, hx.get('Descuento')), _celda(f, hx.get('Cuotas')),
                        'OK' if pn else 'Sin precio', 'API', link or item_id)

    # --- H3: Monitor_Lecturas ---
    h3 = fuentes.get('monitor') or []
    if h3:
        hx = _idx_headers(h3[0])
        for n, f in enumerate(h3[1:], start=2):
            if not any(str(c).strip() for c in f):
                continue
            link = _celda(f, hx.get('Link'))
            ent = _celda(f, hx.get('Entidad')) or _celda(f, 0)
            rid = _celda(f, hx.get('Referencia_ID'))
            ref = ref_por_id.get(rid) if rid else None
            if ref is None:
                rid2 = refs_distrib.get((norm_texto(ent), norm_texto(_celda(f, hx.get('SKU'))), link))
                ref = ref_por_id.get(rid2) if rid2 else None
            if ref is None:
                k = clave_ref(link, ent)
                if k and k in ref_por_clave:
                    ref = ref_por_id.get(ref_por_clave[k])
            fecha, hora = parse_fecha(_celda(f, hx.get('Fecha_Hora')))
            if ref is None:
                huerfano(F_H3, F_H3, n, '', 'Sin referencia en Referencias_Mercado (¿falta correr el bridge?)', f)
            elif not fecha:
                huerfano(F_H3, F_H3, n, '', 'Sin fecha interpretable (Fecha_Hora)', f)
            else:
                pn = parse_precio(_celda(f, hx.get('Precio_Detectado')))
                lectura(F_H3, ref, fecha, hora, pn, None, '', '', _celda(f, hx.get('Estado')) or ('OK' if pn else 'Error'),
                        _celda(f, hx.get('Metodo')), link)

    # Diagnóstico del lector 'refresh' (¿403 en publicaciones ajenas?): lecturas sin precio por fuente.
    rep['sin_precio_por_fuente'] = {}
    for c in candidatas:
        if c['precio'] is None:
            rep['sin_precio_por_fuente'][c['fuente']] = rep['sin_precio_por_fuente'].get(c['fuente'], 0) + 1

    # --- Deduplicar entre históricos y contra lo ya existente ---
    ya = set()
    he = fuentes.get('historial_existente') or []
    if he:
        hx = _idx_headers(he[0])
        for f in he[1:]:
            ya.add((_celda(f, hx.get('Referencia_ID')), _celda(f, hx.get('Fecha')),
                    _num_out(parse_precio(_celda(f, hx.get('Precio')))), _celda(f, hx.get('Estado'))))
    grupos = {}
    for c in candidatas:
        k = (c['ref']['id'], c['fecha'], _num_out(c['precio']), c['estado'])
        if k in ya:
            fuente(c['fuente'])['ya_existian'] += 1
        elif k in grupos:
            fuente(c['fuente'])['fusionadas'] += 1
            g = grupos[k]
            if c['fuente'] not in g['fuentes']:
                g['fuentes'].append(c['fuente'])
            for campo in ('hora', 'tachado', 'desc', 'cuotas', 'metodo'):
                if not g[campo] and c[campo]:
                    g[campo] = c[campo]
        else:
            fuente(c['fuente'])['nuevas'] += 1
            grupos[k] = dict(c, fuentes=[c['fuente']])
    por_dia = {}
    for k, g in grupos.items():
        por_dia.setdefault((k[0], k[1]), []).append(g)
    conflictos = []
    for gs in por_dia.values():
        con_precio = [g for g in gs if g['precio'] is not None]
        if len({_num_out(g['precio']) for g in con_precio}) > 1:
            conflictos.append(con_precio)
    rep['lecturas_sin_precio_a_escribir'] = sum(1 for g in grupos.values() if g['precio'] is None)
    rep['conflictos_precio_mismo_dia'] = len(conflictos)
    rep['conflictos_precio_entre_fuentes'] = sum(
        1 for gs in conflictos if len({fte for g in gs for fte in g['fuentes']}) > 1)
    for g in grupos.values():
        r = g['ref']
        plan.lecturas.append({
            'Referencia_ID': r['id'], 'SKU': r['sku'], 'Entidad': r['entidad'], 'Fecha': g['fecha'],
            'Hora': g['hora'], 'Precio': _num_out(g['precio']), 'Precio_Tachado': _num_out(g['tachado']),
            'Descuento': g['desc'], 'Cuotas': g['cuotas'], 'Estado': g['estado'], 'Metodo': g['metodo'],
            'Fuente': '+'.join(g['fuentes']), 'Link': g['link']})

    # --- Huérfanos ya existentes (idempotencia) ---
    ho = fuentes.get('huerfanos_existentes') or []
    hoy_keys = set()
    if ho:
        hx = _idx_headers(ho[0])
        for f in ho[1:]:
            hoy_keys.add((_celda(f, hx.get('Pestana_Origen')), _celda(f, hx.get('Fila_Origen')),
                          _celda(f, hx.get('Detalle')), _celda(f, hx.get('Motivo'))))
    nuevos, vistos = [], set()
    for h in plan.huerfanos:
        k = (h['Pestana_Origen'], str(h['Fila_Origen']), h['Detalle'], h['Motivo'])
        if k in hoy_keys or k in vistos:
            fuente(h['Fuente'])['huerfanas'] -= 1
            fuente(h['Fuente'])['ya_existian'] += 1
            continue
        vistos.add(k)
        nuevos.append(h)
    plan.huerfanos = nuevos

    # --- Cierre exacto ---
    tot = {'origen': 0, 'nuevas': 0, 'fusionadas': 0, 'ya_existian': 0, 'huerfanas': 0}
    for d in rep['fuentes'].values():
        for k in tot:
            tot[k] += d[k]
    rep['totales'] = tot
    rep['cierra'] = tot['origen'] == tot['nuevas'] + tot['fusionadas'] + tot['ya_existian'] + tot['huerfanas']
    rep['entidades_nuevas'] = len(plan.entidades_nuevas)
    rep['referencias_nuevas'] = len(plan.refs_nuevas)
    rep['lecturas_a_escribir'] = len(plan.lecturas)
    rep['huerfanos_a_escribir'] = len(plan.huerfanos)
    rep['motivos_huerfanos'] = {}
    for h in plan.huerfanos:
        key = f"{h['Fuente']} — {h['Motivo']}"
        rep['motivos_huerfanos'][key] = rep['motivos_huerfanos'].get(key, 0) + 1
    rep['plan_hash'] = hashlib.sha1(json.dumps(
        [rep['totales'], rep['entidades_nuevas'], rep['referencias_nuevas'], rep['lecturas_a_escribir'],
         rep['huerfanos_a_escribir']], sort_keys=True).encode()).hexdigest()[:12]
    return plan


HIST_H2_NOMBRE = 'Historial Competidores'


# ── Escritura en vivo (un lector por link, un histórico) ──────────────────────
def asegurar_pestana(ss, nombre, headers, filas=2000):
    try:
        return ss.worksheet(nombre)
    except Exception:
        ws = ss.add_worksheet(title=nombre, rows=filas, cols=max(len(headers), 10))
        ws.append_row(headers)
        return ws


def fila_desde_dict(headers, d):
    return [d.get(h, '') for h in headers]


def normalizar_resultado(res, link):
    """Resultado de main.leer_precio_publicacion -> (estado, ¿se guarda?). Un link de catálogo sin wid
    no se puede leer hasta la Etapa 2: es 'Sin lectura' y NO se guarda una fila por día (no aporta dato)."""
    if res.get('precio'):
        return 'OK', True
    if es_catalogo_sin_wid(link) and 'sin wid' in str(res.get('detalle_error', '')):
        return 'Sin lectura', False
    return 'Error', True


def mapa_referencias(ss):
    """clave_ref -> {id, sku, entidad} de las referencias de Competencia/Distribuidor/etc. (lectura en vivo)."""
    filas = ss.worksheet('Referencias_Mercado').get_all_values()
    if not filas:
        return {}
    h = _idx_headers(filas[0])
    out = {}
    for f in filas[1:]:
        rid = _celda(f, h.get('Referencia_ID'))
        link = _celda(f, h.get('Link_Publicacion'))
        ent = _celda(f, h.get('Entidad_Nombre'))
        k = clave_ref(link, ent)
        if rid and k:
            out.setdefault(k, {'id': rid, 'sku': _celda(f, h.get('SKU')), 'entidad': ent})
    return out


def registrar_lecturas(ss, lecturas, fuente):
    """Agrega lecturas a Historial_Precios. Cada lectura: {link, entidad, precio, tachado, descuento,
    cuotas, estado, metodo, [referencia_id]}. Idempotente por (Referencia_ID, Fecha): correr dos veces el
    mismo día no duplica. Links sin referencia se cuentan y se omiten (no se inventan referencias en vivo).
    Devuelve {'escritas', 'duplicadas', 'sin_referencia'}."""
    ws = asegurar_pestana(ss, HISTORIAL_SHEET, HISTORIAL_HEADERS, 20000)
    refs = mapa_referencias(ss)
    existentes = set(zip(ws.col_values(1)[1:], ws.col_values(4)[1:]))
    ahora = datetime.now()
    fecha, hora = ahora.strftime('%d/%m/%Y'), ahora.strftime('%H:%M')
    filas, dup, sin_ref = [], 0, 0
    for l in lecturas:
        r = refs.get(clave_ref(l.get('link'), l.get('entidad', '')))
        if r is None:
            sin_ref += 1
            continue
        if (r['id'], fecha) in existentes:
            dup += 1
            continue
        existentes.add((r['id'], fecha))
        filas.append(fila_desde_dict(HISTORIAL_HEADERS, {
            'Referencia_ID': r['id'], 'SKU': r['sku'], 'Entidad': r['entidad'], 'Fecha': fecha, 'Hora': hora,
            'Precio': _num_out(parse_precio(l.get('precio'))), 'Precio_Tachado': _num_out(parse_precio(l.get('tachado'))),
            'Descuento': l.get('descuento', ''), 'Cuotas': l.get('cuotas', ''), 'Estado': l.get('estado', 'OK'),
            'Metodo': l.get('metodo', ''), 'Fuente': fuente, 'Link': l.get('link', '')}))
    for i in range(0, len(filas), 500):
        ws.append_rows(filas[i:i + 500], value_input_option='RAW')
        time.sleep(0.3)
    return {'escritas': len(filas), 'duplicadas': dup, 'sin_referencia': sin_ref}


def registrar_lecturas_seguro(ss, lecturas, fuente, log=None):
    """Doble escritura NO bloqueante: si falla, el flujo viejo (que el front todavía lee) sigue intacto."""
    try:
        res = registrar_lecturas(ss, lecturas, fuente)
        if log is not None:
            log.append(f"📚 Historial_Precios ({fuente}): {res['escritas']} nuevas · {res['duplicadas']} ya del día · "
                       f"{res['sin_referencia']} sin referencia")
        return res
    except Exception as e:
        if log is not None:
            log.append(f"⚠ Historial_Precios ({fuente}): no se pudo registrar: {e}")
        return None
