"""Cambios masivos y REVERSIBLES sobre Referencias_Mercado (Etapa 2): desactivar todas las referencias de una entidad
(p. ej. 'GLOBAL ELECTRONICS GROUP': somos nosotros, no es competencia). Dry-run primero; la ejecución exige la cantidad
esperada (la que mostró el dry-run), deja registro de cada valor anterior en `Cambios_Referencias` y verifica al final."""
import re
import time
import uuid
from datetime import datetime

import competencia_db as cdb

CAMBIOS_SHEET = 'Cambios_Referencias'
CAMBIOS_HEADERS = ['Lote', 'Fecha', 'Referencia_ID', 'Campo', 'Valor_Anterior', 'Valor_Nuevo', 'Motivo', 'Operador']
_INACTIVO = {'no', 'false', '0', 'inactivo'}


class CambioError(Exception):
    pass


def _letra(n):
    s = ''
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _es_activa(v):
    return str(v or '').strip().lower() not in _INACTIVO


def _leer_refs(ss):
    try:
        ws = ss.worksheet('Referencias_Mercado')
    except Exception:
        raise CambioError('No existe la pestaña Referencias_Mercado')
    filas = ws.get_all_values()
    if not filas:
        raise CambioError('Referencias_Mercado está vacía')
    h = {x: i for i, x in enumerate(filas[0])}
    for c in ('Referencia_ID', 'Entidad_Nombre', 'Activo'):
        if c not in h:
            raise CambioError(f'Referencias_Mercado no tiene la columna {c!r}')
    return ws, filas, h


def _coinciden(filas, h, entidad):
    objetivo = cdb.norm_texto(entidad)
    out = []
    for n, f in enumerate(filas[1:], start=2):
        nombre = f[h['Entidad_Nombre']] if h['Entidad_Nombre'] < len(f) else ''
        if cdb.norm_texto(nombre) == objetivo:
            out.append((n, f))
    return out


def _celda(f, h, col):
    i = h.get(col)
    return f[i] if i is not None and i < len(f) else ''


def desactivar_entidad(ss, entidad, ejecutar=False, esperado=None, operador='', log=print):
    """Dry-run (default): cuenta qué tocaría. Real: exige `esperado` == referencias hoy activas de esa entidad."""
    if not str(entidad or '').strip():
        raise CambioError('Falta la entidad')
    ws, filas, h = _leer_refs(ss)
    todas = _coinciden(filas, h, entidad)
    activas = [(n, f) for n, f in todas if _es_activa(_celda(f, h, 'Activo'))]
    por_tipo = {}
    for _, f in activas:
        t = _celda(f, h, 'Tipo') or '(sin tipo)'
        por_tipo[t] = por_tipo.get(t, 0) + 1
    info = {'entidad': entidad, 'coinciden': len(todas), 'activas_a_desactivar': len(activas),
            'ya_inactivas': len(todas) - len(activas), 'activas_por_tipo': por_tipo,
            'muestra': [_celda(f, h, 'Referencia_ID') for _, f in activas[:5]]}
    if not ejecutar:
        return dict(info, ejecutado=False)
    if esperado is None or int(esperado) != len(activas):
        return dict(info, ejecutado=False,
                    motivo=f'`esperado` ({esperado}) no coincide con las activas actuales ({len(activas)}). No se tocó nada.')
    lote = 'LOTE-' + datetime.now().strftime('%Y%m%d%H%M%S') + '-' + uuid.uuid4().hex[:4]
    hoy = datetime.now().strftime('%d/%m/%Y %H:%M')
    motivo = f'Desactivar referencias de {entidad} (no es competencia)'
    cws = cdb.asegurar_pestana(ss, CAMBIOS_SHEET, CAMBIOS_HEADERS, 5000)
    # 1) primero el registro (si algo falla después, queda constancia de qué se iba a tocar)
    reg = [[lote, hoy, _celda(f, h, 'Referencia_ID'), 'Activo', _celda(f, h, 'Activo'), 'No', motivo, operador]
           for _, f in activas]
    for i in range(0, len(reg), 500):
        cws.append_rows(reg[i:i + 500], value_input_option='RAW')
        time.sleep(0.3)
    # 2) los cambios, celda por celda en lotes
    col = _letra(h['Activo'] + 1)
    data = [{'range': f'{col}{n}', 'values': [['No']]} for n, _ in activas]
    for i in range(0, len(data), 300):
        ws.batch_update(data[i:i + 300])
        time.sleep(0.5)
    # 3) verificación: re-leer
    _, filas2, h2 = _leer_refs(ss)
    todas2 = _coinciden(filas2, h2, entidad)
    quedan = [1 for _, f in todas2 if _es_activa(_celda(f, h2, 'Activo'))]
    ok = len(todas2) == len(todas) and not quedan and len(filas2) == len(filas)
    log(f'{lote}: {len(activas)} referencias de {entidad} -> Activo=No · verificación ' + ('OK' if ok else 'NO CIERRA'))
    return dict(info, ejecutado=True, lote=lote, verificacion_ok=ok, quedan_activas=len(quedan))


def revertir_lote(ss, lote, ejecutar=False, log=print):
    """Devuelve Activo a su valor anterior SOLO donde el valor actual sigue siendo el que puso ese lote."""
    try:
        cws = ss.worksheet(CAMBIOS_SHEET)
    except Exception:
        raise CambioError(f'No existe la pestaña {CAMBIOS_SHEET}')
    reg = cws.get_all_values()
    ch = {x: i for i, x in enumerate(reg[0])}
    del_lote = [f for f in reg[1:] if _celda(f, ch, 'Lote') == lote]
    if not del_lote:
        raise CambioError(f'No hay cambios registrados para el lote {lote!r}')
    ws, filas, h = _leer_refs(ss)
    fila_de = {_celda(f, h, 'Referencia_ID'): n for n, f in enumerate(filas[1:], start=2)}
    actual = {_celda(f, h, 'Referencia_ID'): _celda(f, h, 'Activo') for f in filas[1:]}
    a_revertir, conflictos = [], 0
    for f in del_lote:
        rid = _celda(f, ch, 'Referencia_ID')
        if rid in fila_de and actual.get(rid) == _celda(f, ch, 'Valor_Nuevo'):
            a_revertir.append((fila_de[rid], _celda(f, ch, 'Valor_Anterior')))
        else:
            conflictos += 1       # alguien lo cambió a mano después: no se pisa
    info = {'lote': lote, 'en_el_lote': len(del_lote), 'a_revertir': len(a_revertir), 'cambiadas_despues': conflictos}
    if not ejecutar:
        return dict(info, ejecutado=False)
    col = _letra(h['Activo'] + 1)
    data = [{'range': f'{col}{n}', 'values': [[v]]} for n, v in a_revertir]
    for i in range(0, len(data), 300):
        ws.batch_update(data[i:i + 300])
        time.sleep(0.5)
    log(f'{lote}: {len(a_revertir)} referencias revertidas')
    return dict(info, ejecutado=True)


# ── Limpieza: lecturas de una entidad en Historial_Precios y pestañas de respaldo ─────────────────────────────────
PATRON_RESPALDO = re.compile(r'^Respaldo_Hist_Competidores_\d{8}$')


def _registrar_cambio(ss, lote, referencia, campo, anterior, nuevo, motivo, operador):
    cws = cdb.asegurar_pestana(ss, CAMBIOS_SHEET, CAMBIOS_HEADERS, 5000)
    cws.append_row([lote, datetime.now().strftime('%d/%m/%Y %H:%M'), referencia, campo, anterior, nuevo, motivo, operador])


def _tandas(filas):
    """[3,4,5,9,10] -> [(3,5),(9,10)] (números de fila 1-based, consecutivos)."""
    out = []
    for n in sorted(filas):
        if out and n == out[-1][1] + 1:
            out[-1] = (out[-1][0], n)
        else:
            out.append((n, n))
    return out


def borrar_lecturas_entidad(ss, entidad, ejecutar=False, esperado=None, operador='', log=print):
    """Borra de Historial_Precios TODAS las lecturas cuya `Entidad` es esa (p. ej. GLOBAL ELECTRONICS GROUP: somos nosotros).
    IRREVERSIBLE (se puede reconstruir desde las V-* con la migración, mientras existan). Dry-run primero; la real exige `esperado`
    = cantidad del dry-run, borra por tandas de filas consecutivas (de abajo hacia arriba) y verifica al final.
    No correr mientras el scraper está escribiendo."""
    if not str(entidad or '').strip():
        raise CambioError('Falta la entidad')
    try:
        ws = ss.worksheet(cdb.HISTORIAL_SHEET)
    except Exception:
        raise CambioError(f'No existe la pestaña {cdb.HISTORIAL_SHEET}')
    filas = ws.get_all_values()
    if not filas or 'Entidad' not in filas[0]:
        raise CambioError('Historial_Precios no tiene la columna Entidad')
    ie = filas[0].index('Entidad')
    objetivo = cdb.norm_texto(entidad)
    nums = [n for n, f in enumerate(filas[1:], start=2) if cdb.norm_texto(f[ie] if ie < len(f) else '') == objetivo]
    info = {'entidad': entidad, 'filas_con_datos': len(filas) - 1, 'a_borrar': len(nums), 'tandas': len(_tandas(nums))}
    if not ejecutar:
        return dict(info, ejecutado=False)
    if esperado is None or int(esperado) != len(nums):
        return dict(info, ejecutado=False,
                    motivo=f'`esperado` ({esperado}) no coincide con las filas a borrar ({len(nums)}). No se tocó nada.')
    if not nums:
        return dict(info, ejecutado=False, motivo='No hay filas de esa entidad.')
    lote = 'LOTE-' + datetime.now().strftime('%Y%m%d%H%M%S') + '-' + uuid.uuid4().hex[:4]
    _registrar_cambio(ss, lote, f'({cdb.HISTORIAL_SHEET})', 'filas_borradas', len(nums), 0,
                      f'Borrar lecturas de {entidad} (no es competencia)', operador)    # primero el registro
    reqs = [{'deleteDimension': {'range': {'sheetId': ws.id, 'dimension': 'ROWS', 'startIndex': a - 1, 'endIndex': b}}}
            for a, b in reversed(_tandas(nums))]                                          # de abajo hacia arriba: los índices no se corren
    for i in range(0, len(reqs), 100):
        ss.batch_update({'requests': reqs[i:i + 100]})
        time.sleep(0.5)
    despues = ws.get_all_values()
    quedan = sum(1 for f in despues[1:] if cdb.norm_texto(f[ie] if ie < len(f) else '') == objetivo)
    ok = quedan == 0 and len(despues) == len(filas) - len(nums)
    log(f'{lote}: {len(nums)} lecturas de {entidad} borradas de Historial_Precios · verificación ' + ('OK' if ok else 'NO CIERRA'))
    return dict(info, ejecutado=True, lote=lote, verificacion_ok=ok, quedan=quedan, filas_con_datos_despues=len(despues) - 1)


def borrar_pestana_respaldo(ss, nombre, ejecutar=False, confirmar=None, operador='', log=print):
    """Borra UNA pestaña de respaldo (solo nombres `Respaldo_Hist_Competidores_AAAAMMDD`: no sirve para ninguna otra).
    Dry-run: cuántas celdas libera. Real: exige `confirmar` == el nombre exacto."""
    if not PATRON_RESPALDO.fullmatch(str(nombre or '')):
        raise CambioError('Solo se pueden borrar pestañas con nombre Respaldo_Hist_Competidores_AAAAMMDD')
    try:
        ws = ss.worksheet(nombre)
    except Exception:
        raise CambioError(f'No existe la pestaña {nombre}')
    info = {'pestana': nombre, 'filas_con_datos': len(ws.get_all_values()), 'celdas_liberadas': ws.row_count * ws.col_count}
    if not ejecutar:
        return dict(info, ejecutado=False)
    if confirmar != nombre:
        return dict(info, ejecutado=False, motivo='`confirmar` debe ser el nombre exacto de la pestaña. No se tocó nada.')
    lote = 'LOTE-' + datetime.now().strftime('%Y%m%d%H%M%S') + '-' + uuid.uuid4().hex[:4]
    _registrar_cambio(ss, lote, '(pestaña)', 'pestaña', f"{nombre} ({info['filas_con_datos']} filas)", 'borrada',
                      'Respaldo de la migración de la Etapa 1: ya cumplió (copia en competencia_export.json)', operador)
    ss.del_worksheet(ws)
    ok = nombre not in {w.title for w in ss.worksheets()}
    log(f'{lote}: pestaña {nombre} borrada ({info["celdas_liberadas"]} celdas liberadas) · verificación ' + ('OK' if ok else 'NO CIERRA'))
    return dict(info, ejecutado=True, lote=lote, verificacion_ok=ok)
