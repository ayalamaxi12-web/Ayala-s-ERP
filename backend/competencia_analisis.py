"""Datos de la pantalla "Análisis de Competencia" (Etapa 3): lógica pura sobre las filas de las pestañas, sin red ni Sheets.

Entra: Referencias_Mercado, Historial_Precios, Eventos_Competencia, Tiendas_Conteo y Categoria_Competidores (listas de filas con encabezado en la 1ª).
Sale: JSON compacto con, por referencia de competencia, el último precio, el anterior, desde cuándo rige, el precio ganador y la serie de los últimos N días.
No calcula márgenes (eso lo hace el front con las mismas fórmulas de Competidores) ni clasifica nada: categoría y PM se resuelven en el front por SKU."""
from datetime import date, datetime, timedelta

import competencia_db as cdb

DIAS_DEFAULT, DIAS_MAX = 30, 365
_ORDEN_ROL = {'Rey': 0, 'Media': 1, 'Barato': 2}
_SI = {'si', 'sí', 'true', '1', 'activo', 'x'}


def _dicts(filas):
    if not filas:
        return []
    h = [str(x).strip() for x in filas[0]]
    return [{h[i]: (str(f[i]).strip() if i < len(f) else '') for i in range(len(h)) if h[i]} for f in filas[1:] if any(str(c).strip() for c in f)]


def _fecha(v):
    """'dd/mm/aaaa[ hh:mm]' (o ISO) -> date | None."""
    s, _ = cdb.parse_fecha(v)
    return datetime.strptime(s, '%d/%m/%Y').date() if s else None


def _num(v):
    n = cdb.parse_precio(v)
    return n if n is not None and n > 0 else None


def _cant(v):
    """Cantidad que puede ser 0 ('' = no medido, None)."""
    n = cdb.parse_precio(v) if str(v).strip() != '0' else 0
    return n if n is not None and n >= 0 else None


def _iso(d):
    return d.isoformat() if d else ''


def _es_si(v):
    return str(v or '').strip().lower() in _SI


def construir(filas, dias=DIAS_DEFAULT, hoy=None):
    """filas = {'refs','hist','eventos','conteo','categorias'}: cada una, filas crudas de la pestaña (encabezado incluido)."""
    dias = max(1, min(int(dias or DIAS_DEFAULT), DIAS_MAX))
    hoy = hoy or date.today()
    desde = hoy - timedelta(days=dias)
    avisos = []

    refs = {}
    excluidas = {'inactivas': 0, 'otro_tipo': 0}
    for r in _dicts(filas.get('refs')):
        rid = r.get('Referencia_ID', '')
        if not rid:
            continue
        if cdb.norm_texto(r.get('Tipo')) != 'competencia':
            excluidas['otro_tipo'] += 1
            continue
        if not _es_si(r.get('Activo')):
            excluidas['inactivas'] += 1
            continue
        refs[rid] = {'id': rid, 'sku': r.get('SKU', ''), 'entidad_id': r.get('Entidad_ID', ''), 'entidad': r.get('Entidad_Nombre', ''),
                     'rol': r.get('Rol_Competidor', ''), 'link': r.get('Link_Publicacion', ''), 'cantidad': _num(r.get('Cantidad')) or 1,
                     'pvp_oficial': _num(r.get('PVP_Oficial'))}

    lect = {}          # rid -> [(fecha, hora, precio|None, fila)]
    mal_fecha = 0
    for h in _dicts(filas.get('hist')):
        rid = h.get('Referencia_ID', '')
        if rid not in refs:
            continue
        f, hora = cdb.parse_fecha((h.get('Fecha', '') + ' ' + h.get('Hora', '')).strip())
        if not f:
            mal_fecha += 1
            continue
        lect.setdefault(rid, []).append((datetime.strptime(f, '%d/%m/%Y').date(), hora, _num(h.get('Precio')), h))
    if mal_fecha:
        avisos.append(f'{mal_fecha} filas de Historial_Precios con fecha ilegible (ignoradas).')

    sin_lectura = 0
    for rid, r in refs.items():
        ls = sorted(lect.get(rid, []), key=lambda x: (x[0], x[1]))
        if not ls:
            sin_lectura += 1
            r.update(ultimo=None, anterior=None, delta_pct=None, desde=None, ganador=None, ultima_lectura=None, serie=[])
            continue
        f_ult, _, _, fila_ult = ls[-1]
        r['ultima_lectura'] = {'fecha': _iso(f_ult), 'estado': fila_ult.get('Estado', ''), 'dias': (hoy - f_ult).days}
        gan = _num(fila_ult.get('Precio_Ganador'))
        r['ganador'] = {'precio': gan, 'vendedor': fila_ult.get('Vendedor_Ganador', '')} if gan else None
        con_precio = [x for x in ls if x[2] is not None]
        por_dia = {}
        for f, hh, p, fila in con_precio:
            por_dia[f] = (p, fila)      # la última del día (están ordenadas)
        dias_ord = sorted(por_dia)
        if not dias_ord:
            r.update(ultimo=None, anterior=None, delta_pct=None, desde=None, serie=[])
            continue
        d_ult = dias_ord[-1]
        p_ult, fila_p = por_dia[d_ult]
        r['ultimo'] = {'fecha': _iso(d_ult), 'precio': p_ult, 'tachado': _num(fila_p.get('Precio_Tachado')), 'cuotas': fila_p.get('Cuotas', ''),
                       'metodo': fila_p.get('Metodo', '')}
        prev = dias_ord[-2] if len(dias_ord) > 1 else None
        r['anterior'] = {'fecha': _iso(prev), 'precio': por_dia[prev][0]} if prev else None
        r['delta_pct'] = round((p_ult - por_dia[prev][0]) / por_dia[prev][0] * 100, 2) if prev else None
        i = len(dias_ord) - 1
        while i > 0 and por_dia[dias_ord[i - 1]][0] == p_ult:
            i -= 1
        r['desde'] = _iso(dias_ord[i])
        r['serie'] = [[_iso(d), por_dia[d][0]] for d in dias_ord if d >= desde]
    if sin_lectura:
        avisos.append(f'{sin_lectura} referencias activas de competencia todavía sin ninguna lectura.')

    eventos = []
    for e in _dicts(filas.get('eventos')):
        f = _fecha(e.get('Fecha'))
        if f and f >= desde:
            eventos.append({'fecha': _iso(f), 'hora': e.get('Hora', ''), 'tipo': e.get('Tipo', ''), 'referencia_id': e.get('Referencia_ID', ''),
                            'sku': e.get('SKU', ''), 'entidad': e.get('Entidad', ''), 'rol': e.get('Rol', ''), 'anterior': _num(e.get('Valor_Anterior')),
                            'nuevo': _num(e.get('Valor_Nuevo')), 'variacion_pct': e.get('Variacion_Pct', ''), 'detalle': e.get('Detalle', ''),
                            'link': e.get('Link', '')})
    eventos.sort(key=lambda x: (x['fecha'], x['hora']), reverse=True)

    tiendas = {}
    for c in _dicts(filas.get('conteo')):
        f = _fecha(c.get('Fecha'))
        if not f:
            continue
        t = tiendas.setdefault(c.get('Entidad_ID', '') or c.get('Entidad', ''), {'entidad_id': c.get('Entidad_ID', ''), 'entidad': c.get('Entidad', ''), 'filas': []})
        t['filas'].append((f, c))
    lista_t = []
    for t in tiendas.values():
        t['filas'].sort(key=lambda x: x[0])
        f_u, c_u = t['filas'][-1]
        lista_t.append({'entidad_id': t['entidad_id'], 'entidad': t['entidad'],
                        'ultimo': {'fecha': _iso(f_u), 'leidas': _num(c_u.get('Leidas')), 'declaradas': _num(c_u.get('Declaradas_ML')),
                                   'completa': _es_si(c_u.get('Completa')), 'motivo': c_u.get('Motivo', ''), 'mediana_7d': _num(c_u.get('Mediana_7d')),
                                   'var_pct': c_u.get('Var_vs_Mediana_Pct', ''), 'estado_debilidad': c_u.get('Estado_Debilidad', ''),
                                   'nuevas': _cant(c_u.get('Nuevas')), 'desaparecidas': _cant(c_u.get('Desaparecidas'))},
                        'serie': [{'fecha': _iso(f), 'leidas': _num(c.get('Leidas')), 'completa': _es_si(c.get('Completa')),
                                   'nuevas': _cant(c.get('Nuevas')), 'desaparecidas': _cant(c.get('Desaparecidas'))} for f, c in t['filas'] if f >= desde]})
    lista_t.sort(key=lambda x: x['entidad'])

    cats = _dicts(filas.get('categorias'))
    fechas = [_fecha(c.get('Actualizado')) for c in cats]
    max_f = max((f for f in fechas if f), default=None)
    categorias = [{'subcategoria': c.get('Subcategoria', ''), 'rol': c.get('Rol', ''), 'entidad_id': c.get('Entidad_ID', ''), 'entidad': c.get('Entidad', ''),
                   'slug': c.get('Slug', ''), 'skus_nuestros': c.get('SKUs_Nuestros', ''), 'actualizado': _iso(f),
                   'desactualizada': bool(max_f and f and (max_f - f).days > 7)} for c, f in zip(cats, fechas)]
    if not categorias:
        avisos.append('Categoria_Competidores está vacía o no existe: correr el scraper actualizado para guardar el mapa de A-CATEGORIAS.')

    return {'hoy': _iso(hoy), 'dias': dias, 'referencias': sorted(refs.values(), key=lambda r: (r['sku'], _ORDEN_ROL.get(r['rol'], 9), r['entidad'])),
            'eventos': eventos, 'tiendas': lista_t, 'categorias': categorias, 'excluidas': excluidas, 'avisos': avisos}


class CacheAnalisis:
    """Caché de las filas leídas del Sheet (una sola lectura para todos los usuarios y todos los `dias`). `refrescar` fuerza una relectura,
    pero no más de una cada `min_refresco` segundos (cuota de la API de Sheets). Un error al releer NO borra lo cacheado."""

    def __init__(self, leer, ttl=600, min_refresco=30, reloj=None):
        import threading
        import time
        self.leer, self.ttl, self.min_refresco = leer, ttl, min_refresco
        self.reloj = reloj or time.time
        self.filas, self.t = None, 0.0
        self.lock = threading.Lock()

    def obtener(self, dias=DIAS_DEFAULT, refrescar=False, hoy=None):
        with self.lock:
            ahora = self.reloj()
            edad = ahora - self.t
            ignorado = False
            if self.filas is None or edad >= self.ttl or (refrescar and edad >= self.min_refresco):
                try:
                    self.filas, self.t = self.leer(), ahora
                except Exception:
                    if self.filas is None:
                        raise
                    ignorado = True          # relectura fallida: se sirve lo cacheado (y se avisa)
            elif refrescar:
                ignorado = True
            datos = construir(self.filas, dias, hoy)
            datos['cache'] = {'leido_hace_seg': int(self.reloj() - self.t), 'ttl_seg': self.ttl, 'refresco_ignorado': ignorado}
            return datos
