"""Sincronización planilla de Maca -> base de competencia (Entidades + Referencias_Mercado). Lógica pura.

- Perfiles (A): cada tienda es una entidad de Competencia (alias confirmados en config.ALIAS_TIENDAS; las demás se
  crean). Se guarda la URL de listado en Entidades.Link_ML solo si estaba vacía.
- Publicaciones (B): una referencia por (SKU, publicación) con Rol_Competidor (Rey/Media/Barato) y
  Origen='Planilla Maca B-SKU'. Un link que ya existe con el MISMO SKU se reutiliza (solo se completa el rol si
  estaba vacío); con OTRO SKU se crea la referencia del SKU de Maca y se informa la diferencia.
- Nada se pisa: solo se completan vacíos. No se clasifica nada (categoría/competidores los define Maca)."""
import re
from datetime import datetime

import config
import competencia_db as cdb

ORIGEN_B = 'Planilla Maca B-SKU'
COL_ROL = 'Rol_Competidor'


def ident_publicacion(link):
    """Identidad de la publicación SIN la entidad (a diferencia de cdb.clave_ref): ('P', producto, wid) |
    ('Pn', producto) | ('I', item) | None."""
    ids = cdb.extraer_ids(link)
    if ids['product_id'] and ids['wid']:
        return ('P', ids['product_id'], ids['wid'])
    if ids['product_id']:
        return ('Pn', ids['product_id'])
    if ids['item_id']:
        return ('I', ids['item_id'])
    return None


def es_excluida(nombre):
    n = cdb.norm_texto(nombre)
    return bool(n) and any(cdb.norm_texto(x) in n for x in config.EXCLUIR_ENTIDADES)


def nombre_desde_slug(slug):
    return re.sub(r'[-_]+', ' ', slug).upper().strip()


def _idx(filas):
    return {h: i for i, h in enumerate(filas[0])} if filas else {}


def _c(f, h, col):
    i = h.get(col)
    return str(f[i]).strip() if i is not None and i < len(f) else ''


class SyncPlan:
    def __init__(self):
        self.entidades_nuevas = []     # dicts (Entidad_ID, Nombre, Tipo, ...)
        self.entidades_link = []       # {'Entidad_ID', 'Link_ML'} (solo vacíos)
        self.refs_nuevas = []          # dicts de Referencias_Mercado
        self.rol_updates = []          # {'Referencia_ID', 'Rol'} (solo vacíos)
        self.perfiles = []             # perfiles resueltos: + entidad_id, entidad_nombre, excluida
        self.report = {'diferencias_sku': [], 'links_no_reconocidos': [], 'perfiles_excluidos': []}


def planificar_sync(perfiles, skus, ents_rows, refs_rows, hoy=None):
    hoy = hoy or datetime.now().strftime('%d/%m/%Y')
    plan = SyncPlan()
    eh, rh = _idx(ents_rows), _idx(refs_rows)

    # --- entidades existentes ---
    ent_por_nombre, ent_ids, ent_link = {}, [], {}
    for f in (ents_rows or [])[1:]:
        eid, nom = _c(f, eh, 'Entidad_ID'), _c(f, eh, 'Nombre')
        if eid:
            ent_ids.append(eid)
            ent_link[eid] = _c(f, eh, 'Link_ML')
        if nom and _c(f, eh, 'Tipo') == 'Competencia':
            ent_por_nombre.setdefault(cdb.norm_texto(nom), (eid, nom))

    def n_seq(prefijo, ids):
        m = 0
        for v in ids:
            g = re.fullmatch(prefijo + r'-(\d+)', str(v).strip())
            if g:
                m = max(m, int(g.group(1)))
        return m
    seq = {'ENT': n_seq('ENT', ent_ids), 'REF': 0}

    # --- referencias existentes (índice SIN entidad) ---
    ref_ids, por_sku_ident, por_ident = [], {}, {}
    for f in (refs_rows or [])[1:]:
        rid = _c(f, rh, 'Referencia_ID')
        if not rid:
            continue
        ref_ids.append(rid)
        sku = cdb.limpiar_sku(_c(f, rh, 'SKU'))
        ident = ident_publicacion(_c(f, rh, 'Link_Publicacion'))
        if not ident:
            continue
        rol = _c(f, rh, COL_ROL)
        por_sku_ident.setdefault((cdb.norm_texto(sku), ident), []).append((rid, rol))
        por_ident.setdefault(ident, []).append((rid, sku))
    seq['REF'] = n_seq('REF', ref_ids)

    # --- perfiles -> entidades ---
    for p in perfiles:
        nombre = config.ALIAS_TIENDAS.get(p['slug']) or nombre_desde_slug(p['slug'])
        excl = es_excluida(nombre)
        k = cdb.norm_texto(nombre)
        if k not in ent_por_nombre and not excl:
            seq['ENT'] += 1
            eid = f'ENT-{seq["ENT"]:06d}'
            ent_por_nombre[k] = (eid, nombre)
            plan.entidades_nuevas.append({'Entidad_ID': eid, 'Nombre': nombre, 'Tipo': 'Competencia',
                                          'Fecha_Alta': hoy, 'Link_ML': p['url_listado'],
                                          'Observaciones': 'Creada desde la planilla de Maca (A-CATEGORIAS)'})
            ent_link[eid] = p['url_listado']
        eid, nom = ent_por_nombre.get(k, ('', nombre))
        if eid and not excl and not ent_link.get(eid) and p['url_listado']:
            ent_link[eid] = p['url_listado']
            plan.entidades_link.append({'Entidad_ID': eid, 'Link_ML': p['url_listado']})
        plan.perfiles.append(dict(p, entidad_id=eid, entidad_nombre=nom, excluida=excl))
        if excl:
            plan.report['perfiles_excluidos'].append(nombre)

    # --- publicaciones por SKU -> referencias ---
    vistos = set()
    for d in skus:
        for l in d['links']:
            ident = ident_publicacion(l['url'])
            if ident is None:
                plan.report['links_no_reconocidos'].append({'sku': d['sku'], 'rol': l['rol'], 'url': l['url']})
                continue
            clave = (cdb.norm_texto(d['sku']), ident)
            if clave in vistos:
                continue
            vistos.add(clave)
            existentes = por_sku_ident.get(clave)
            if existentes:
                for rid, rol in existentes:
                    if not rol:
                        plan.rol_updates.append({'Referencia_ID': rid, 'Rol': l['rol_nombre']})
                continue
            otros = [(rid, s) for rid, s in por_ident.get(ident, []) if cdb.norm_texto(s) != clave[0]]
            if otros:
                plan.report['diferencias_sku'].append({'sku_planilla': d['sku'], 'link': l['url'],
                                                       'referencias_existentes': [{'id': r, 'sku': s} for r, s in otros]})
            seq['REF'] += 1
            rid = f'REF-{seq["REF"]:06d}'
            plan.refs_nuevas.append({'Referencia_ID': rid, 'SKU': d['sku'], 'Tipo': 'Competencia', 'Entidad_ID': '',
                                     'Entidad_Nombre': '', 'Link_Publicacion': l['url'], 'Activo': 'Si',
                                     'Fecha_Alta': hoy, 'Origen': ORIGEN_B, 'Cantidad': '1', COL_ROL: l['rol_nombre']})
            por_sku_ident.setdefault(clave, []).append((rid, l['rol_nombre']))
            por_ident.setdefault(ident, []).append((rid, d['sku']))
    return plan
