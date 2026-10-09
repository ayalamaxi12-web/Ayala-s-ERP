"""Conteo diario por tienda (Fase 1 del diseño B): una fila por tienda y día en `Tiendas_Conteo`. Es la base de la detección de
debilidad (Fase 3): hace falta una línea base de varios días, por eso se empieza a guardar YA. Lógica pura + escritura.

Pensado para Postgres: clave (Fecha, Entidad_ID); mismas columnas que tendría la tabla `comp_tienda_conteo`."""
import statistics

import config  # noqa: F401
import competencia_db as cdb
import sheets_io as sio

CONTEO_SHEET = 'Tiendas_Conteo'
CONTEO_HEADERS = ['Fecha', 'Hora', 'Entidad_ID', 'Entidad', 'Leidas', 'Declaradas_ML', 'Paginas', 'Completa', 'Motivo',
                  'Nuevas', 'Desaparecidas', 'Mediana_7d', 'Var_vs_Mediana_Pct', 'Estado_Debilidad', 'Fuente']
# Nuevas/Desaparecidas se completan en la Fase 2 (Tiendas_Estado) y Estado_Debilidad en la Fase 3.
FUENTE_SCRAPER, FUENTE_SEMILLA = 'Scraper', 'V-* (historico)'


def orden_fecha(f):
    s, _ = cdb.parse_fecha(f)
    if not s:
        return None
    d, m, y = s.split('/')
    return (int(y), int(m), int(d))


def validas_previas(filas_conteo, entidad_id, antes_de):
    """Lecturas COMPLETAS de la tienda anteriores a `antes_de` (dd/mm/aaaa), de la más vieja a la más nueva:
    [(orden, leidas)]. Las incompletas no cuentan para la línea base."""
    if not filas_conteo:
        return []
    h = {x: i for i, x in enumerate(filas_conteo[0])}
    lim = orden_fecha(antes_de)
    out = []
    for f in filas_conteo[1:]:
        try:
            if f[h['Entidad_ID']] != entidad_id or str(f[h['Completa']]).strip().lower() not in ('si', 'sí'):
                continue
            o, n = orden_fecha(f[h['Fecha']]), cdb.parse_precio(f[h['Leidas']])
        except (KeyError, IndexError):
            continue
        if o is not None and n is not None and (lim is None or o < lim):
            out.append((o, n))
    return sorted(out)


def mediana_y_variacion(previas, leidas, completa):
    """Mediana de las últimas N lecturas completas previas (si hay al menos CONTEO_MEDIANA_MIN) y cuánto se aleja hoy."""
    ult = [n for _, n in previas[-config.CONTEO_MEDIANA_DIAS:]]
    if len(ult) < config.CONTEO_MEDIANA_MIN:
        return '', ''
    med = statistics.median(ult)
    med_out = int(med) if float(med).is_integer() else round(med, 1)
    if not completa or not med:
        return med_out, ''
    return med_out, round((leidas - med) / med * 100, 1)


def fila_conteo(fecha, hora, entidad_id, entidad, leidas, declaradas, paginas, completa, motivo, previas, fuente=FUENTE_SCRAPER):
    med, var = mediana_y_variacion(previas, leidas, completa)
    return {'Fecha': fecha, 'Hora': hora, 'Entidad_ID': entidad_id, 'Entidad': entidad, 'Leidas': leidas,
            'Declaradas_ML': declaradas if declaradas is not None else '', 'Paginas': paginas if paginas is not None else '',
            'Completa': 'Si' if completa else 'No', 'Motivo': motivo or '', 'Nuevas': '', 'Desaparecidas': '',
            'Mediana_7d': med, 'Var_vs_Mediana_Pct': var, 'Estado_Debilidad': '', 'Fuente': fuente}


def registrar(ss, filas, solo_nuevas=False):
    """Escribe en Tiendas_Conteo (upsert por Fecha+Entidad_ID: correr dos veces el mismo día REEMPLAZA la fila).
    solo_nuevas=True (siembra): no pisa lo que ya existe. -> (insertadas, reemplazadas, omitidas)."""
    if not filas:
        return 0, 0, 0
    ws = cdb.asegurar_pestana(ss, CONTEO_SHEET, CONTEO_HEADERS, 3000)
    h = sio.asegurar_columnas(ws, CONTEO_HEADERS)
    omitidas = 0
    if solo_nuevas:
        ex = ws.get_all_values()
        ix = {x: i for i, x in enumerate(h)}
        claves = {(f[ix['Fecha']], f[ix['Entidad_ID']]) for f in ex[1:] if len(f) > max(ix['Fecha'], ix['Entidad_ID'])}
        nuevas = [f for f in filas if (f['Fecha'], f['Entidad_ID']) not in claves]
        omitidas, filas = len(filas) - len(nuevas), nuevas
    ins, act = sio.upsert(ws, h, filas, ['Fecha', 'Entidad_ID'])
    return ins, act, omitidas


# ── Línea base desde las pestañas V-* (scraper viejo) ─────────────────────────
def sembrar_desde_v(v_tabs, ents_rows, permitidas):
    """Cuenta, por cada fecha de scrape de las pestañas `V - <tienda>`, cuántas publicaciones tenían precio. Solo para las
    tiendas permitidas (las de A-CATEGORIAS que ya existen en la base). Son fechas sueltas, no diarias, y no se puede
    verificar si cada scrape viejo fue completo: se marcan con Fuente 'V-* (historico)'. -> (filas, avisos)."""
    perm = {cdb.norm_texto(x) for x in permitidas}
    h = {x: i for i, x in enumerate(ents_rows[0])} if ents_rows else {}
    ids = {cdb.norm_texto(f[h['Nombre']]): f[h['Entidad_ID']] for f in (ents_rows or [])[1:]
           if len(f) > max(h.get('Nombre', 0), h.get('Entidad_ID', 0))} if h else {}
    filas, avisos = [], []
    for tab, rows in sorted(v_tabs.items()):
        nombre = tab[4:] if tab.startswith('V - ') else tab
        k = cdb.norm_texto(nombre)
        if k not in perm:
            continue
        eid = ids.get(k)
        if not eid:
            avisos.append(f'{tab}: no existe la entidad {nombre!r} en Entidades: no se siembra.')
            continue
        if not rows:
            continue
        _, bloques, _ = cdb._split_bloques_v(rows[0])
        col = {}
        for kf, b in bloques.items():            # una sola columna de precio por fecha (si la fecha está repetida, la primera)
            f = kf.split('#')[0]
            if f not in col and 'precio' in b:
                col[f] = b['precio']
        previas = []
        for f in sorted(col, key=orden_fecha):
            n = sum(1 for r in rows[1:] if len(r) > col[f] and cdb.parse_precio(r[col[f]]))
            if not n:
                continue
            fila = fila_conteo(f, '', eid, nombre, n, None, None, True, 'Sembrado desde V-*: completitud no verificable',
                               previas, FUENTE_SEMILLA)
            filas.append(fila)
            previas.append((orden_fecha(f), n))
    return filas, avisos
