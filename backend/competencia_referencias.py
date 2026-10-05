"""Cambios masivos y REVERSIBLES sobre Referencias_Mercado (Etapa 2): desactivar todas las referencias de una entidad
(p. ej. 'GLOBAL ELECTRONICS GROUP': somos nosotros, no es competencia). Dry-run primero; la ejecución exige la cantidad
esperada (la que mostró el dry-run), deja registro de cada valor anterior en `Cambios_Referencias` y verifica al final."""
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
