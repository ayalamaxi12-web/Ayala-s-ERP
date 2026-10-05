"""Migración de la base de competencia (Etapa 1): lectura del Sheet, respaldo, escritura y verificación.
Lo usan el script CLI (`scripts/migrar_competencia.py`) y el endpoint protegido de `main.py`
(`/competencia/migracion/run`). La lógica de planificación/cierre está en `competencia_db.py`."""
import json
import sys
import time

import competencia_db as cdb


class MigracionError(Exception):
    pass

ENT_HEADERS = ['Entidad_ID', 'Nombre', 'Tipo', 'Provincia', 'Localidad', 'Estado', 'Responsable',
               'Tolerancia_Default_Pct', 'Fecha_Alta', 'Fecha_Ultima_Revision', 'Observaciones', 'Link_ML', 'Seller_ID']
REF_HEADERS = ['Referencia_ID', 'SKU', 'Tipo', 'Entidad_ID', 'Entidad_Nombre', 'Link_Publicacion', 'PVP_Oficial',
               'PVP_Override', 'Tolerancia_Pct', 'Activo', 'Seller_ID_Esperado', 'Fecha_Alta', 'Origen', 'Observaciones']



def _valores(ss, nombre, titulos, reintentos=5):
    """Una pestaña que NO existe = vacía. Cualquier otro error (cuota, red) se reintenta y, si persiste, FALLA:
    leer mal una pestaña (p. ej. Referencias_Mercado) como vacía generaría duplicados al escribir."""
    if nombre not in titulos:
        return []
    for i in range(reintentos):
        try:
            return ss.worksheet(nombre).get_all_values()
        except Exception as e:
            if i == reintentos - 1:
                raise MigracionError(f'No se pudo leer la pestaña {nombre!r}: {e}')
            time.sleep(10 * (i + 1))


def leer_sheet(ss):
    titulos = {ws.title for ws in ss.worksheets()}
    v = lambda n: _valores(ss, n, titulos)  # noqa: E731
    f = {'refs': v('Referencias_Mercado'), 'ents': v('Entidades'), 'general': v('General'),
         'ml_competencia': v('ML Competencia'), 'hist_competidores': v(cdb.HIST_H2_NOMBRE),
         'monitor': v('Monitor_Lecturas'), 'historial_existente': v(cdb.HISTORIAL_SHEET),
         'huerfanos_existentes': v(cdb.HUERFANOS_SHEET), 'v_tabs': {}}
    for t in sorted(titulos):
        if t.startswith('V - '):
            f['v_tabs'][t] = v(t)
            time.sleep(0.5)  # cuota de la API de Sheets
    return f


def _append(ws, headers_hoja, dicts, headers_default):
    headers = headers_hoja or headers_default
    filas = [cdb.fila_desde_dict(headers, d) for d in dicts]
    for i in range(0, len(filas), 500):
        ws.append_rows(filas[i:i + 500], value_input_option='RAW')
        time.sleep(0.4)


def respaldar_historial_competidores(ss, filas, log=print, archivo_local=True):
    """Copia COMPLETA de 'Historial Competidores' (que se autoborra por el tope de 10 fechas) a una pestaña
    de respaldo + un JSON local, ANTES de escribir nada. Aborta si no queda idéntica en cantidad de filas."""
    if not filas:
        log('Respaldo: Historial Competidores está vacío, nada que respaldar.')
        return
    nombre = 'Respaldo_Hist_Competidores_' + time.strftime('%Y%m%d')
    local = f'respaldo_historial_competidores_{time.strftime("%Y%m%d_%H%M")}.json'
    if archivo_local:
        json.dump(filas, open(local, 'w', encoding='utf-8'), ensure_ascii=False)
    ws = cdb.asegurar_pestana(ss, nombre, filas[0], len(filas) + 10)
    if len(ws.get_all_values()) <= 1:
        for i in range(1, len(filas), 2000):
            ws.append_rows(filas[i:i + 2000], value_input_option='RAW')
            time.sleep(0.5)
    n = len(ws.get_all_values())
    if n != len(filas):
        raise MigracionError(f'RESPALDO NO CIERRA ({n} filas en {nombre} vs {len(filas)} de origen): no se migra nada.')
    log(f'Respaldo OK: {len(filas)} filas -> pestaña {nombre}' + (f' + archivo local {local}' if archivo_local else ''))


def ejecutar(ss, plan, fuentes, log=print, archivo_local=True):
    respaldar_historial_competidores(ss, fuentes.get('hist_competidores') or [], log, archivo_local)
    ent_ws = cdb.asegurar_pestana(ss, 'Entidades', ENT_HEADERS, 1000)
    ref_ws = cdb.asegurar_pestana(ss, 'Referencias_Mercado', REF_HEADERS, 1000)
    h_ws = cdb.asegurar_pestana(ss, cdb.HISTORIAL_SHEET, cdb.HISTORIAL_HEADERS, 20000)
    o_ws = cdb.asegurar_pestana(ss, cdb.HUERFANOS_SHEET, cdb.HUERFANOS_HEADERS, 5000)
    ref_h = ref_ws.row_values(1)
    if cdb.REFERENCIAS_COL_EXTRA not in ref_h:  # agrega 'Cantidad' al final: no mueve ninguna columna existente
        if len(ref_h) + 1 > ref_ws.col_count:
            ref_ws.add_cols(1)
        ref_ws.update_cell(1, len(ref_h) + 1, cdb.REFERENCIAS_COL_EXTRA)
        ref_h.append(cdb.REFERENCIAS_COL_EXTRA)
    _append(ent_ws, ent_ws.row_values(1), plan.entidades_nuevas, ENT_HEADERS)
    _append(ref_ws, ref_h, plan.refs_nuevas, REF_HEADERS)
    _append(h_ws, h_ws.row_values(1), plan.lecturas, cdb.HISTORIAL_HEADERS)
    _append(o_ws, o_ws.row_values(1), plan.huerfanos, cdb.HUERFANOS_HEADERS)


def verificar(ss):
    """Re-lee el Sheet y re-planifica: tras migrar, no debe quedar nada por escribir y el informe debe cerrar.
    Devuelve (ok, informe). `Historial_Precios` debe tener exactamente las lecturas con precio planificadas."""
    post = cdb.planificar(leer_sheet(ss))
    r = post.rep
    ok = (r['lecturas_a_escribir'] == 0 and r['referencias_nuevas'] == 0 and r['huerfanos_a_escribir'] == 0
          and r['cierra'] and r['totales']['nuevas'] == 0)
    return ok, r


def correr(ss, plan_hash=None, ejecutar_real=False, log=print, archivo_local=True):
    """Dry-run (default) o migración real. La real exige que el hash del plan calculado AHORA sea el aprobado:
    si los datos cambiaron desde el dry-run aprobado, no escribe y devuelve el informe nuevo."""
    fuentes = leer_sheet(ss)
    plan = cdb.planificar(fuentes)
    rep = plan.rep
    if not ejecutar_real:
        return {'modo': 'dry-run', 'ejecutado': False, 'informe': rep}
    if not rep['cierra']:
        raise MigracionError('El informe no cierra: no se ejecuta.')
    if not plan_hash or rep['plan_hash'] != plan_hash:
        return {'modo': 'ejecutar', 'ejecutado': False, 'motivo': 'plan_hash distinto: los datos cambiaron desde el '
                f"dry-run aprobado (hash actual {rep['plan_hash']}). No se escribió nada.", 'informe': rep}
    antes = {n: max(len(fuentes.get(k) or []) - 1, 0) for n, k in (
        (cdb.HISTORIAL_SHEET, 'historial_existente'), (cdb.HUERFANOS_SHEET, 'huerfanos_existentes'),
        ('Referencias_Mercado', 'refs'), ('Entidades', 'ents'))}
    ejecutar(ss, plan, fuentes, log, archivo_local)
    ok, post = verificar(ss)
    esperadas = {cdb.HISTORIAL_SHEET: antes[cdb.HISTORIAL_SHEET] + len(plan.lecturas),
                 cdb.HUERFANOS_SHEET: antes[cdb.HUERFANOS_SHEET] + len(plan.huerfanos),
                 'Referencias_Mercado': antes['Referencias_Mercado'] + len(plan.refs_nuevas),
                 'Entidades': antes['Entidades'] + len(plan.entidades_nuevas)}
    filas = {n: max(len(ss.worksheet(n).get_all_values()) - 1, 0) for n in esperadas}
    filas_ok = filas == esperadas
    log(f'Filas en las pestañas nuevas: {filas} (esperadas {esperadas}) -> ' + ('OK' if filas_ok else 'NO COINCIDEN'))
    log('VERIFICACIÓN post-migración: ' + ('OK, todo cerró exacto' if ok and filas_ok else 'NO CIERRA'))
    return {'modo': 'ejecutar', 'ejecutado': True, 'verificacion_ok': bool(ok and filas_ok), 'filas': filas,
            'filas_esperadas': esperadas, 'informe': rep, 'informe_post': post}
