"""Fase 2 del diseño B: estado por publicación de cada tienda (`Tiendas_Estado`) para contar Nuevas / Desaparecidas por tienda y día
(se escriben en `Tiendas_Conteo`). Es lo que la vista "por categoría" muestra junto al conteo de publicaciones. Lógica pura + escritura.

Una fila por (Entidad_ID, Ident). Reglas:
  - Solo una lectura COMPLETA mueve el estado: una incompleta no puede decir qué desapareció ni qué es nuevo (Nuevas/Desaparecidas quedan vacías).
  - Primera lectura completa de la tienda = siembra: todo queda Activa con Primera_Vez = hoy y NO se cuenta como nuevo (no hay con qué comparar).
  - Idempotente por día: se cuenta contra el estado de ANTES de hoy (Primera_Vez == hoy es nueva de hoy; Desaparecida_Desde == hoy, desaparecida de hoy),
    así que correr dos veces el mismo día da el mismo resultado.
  - Una publicación que vuelve a aparecer se reactiva (Activa = Si) y no cuenta como nueva.
Pensado para Postgres: clave (entidad_id, ident)."""
import config  # noqa: F401
import competencia_db as cdb
import sheets_io as sio

ESTADO_SHEET = 'Tiendas_Estado'
ESTADO_HEADERS = ['Entidad_ID', 'Ident', 'Primera_Vez', 'Ultima_Vez', 'Activa', 'Desaparecida_Desde']


def ident_texto(ident):
    """('P', producto, wid) -> 'P|producto|wid'. None si no hay identidad."""
    return '|'.join(str(x) for x in ident) if ident else ''


def _es_si(v):
    return str(v).strip().lower() in ('si', 'sí')


def estado_de_tienda(filas_estado, entidad_id):
    """{ident: dict de la fila} de la tienda, desde la hoja leída (con encabezado)."""
    if not filas_estado:
        return {}
    h = {x: i for i, x in enumerate(filas_estado[0])}
    out = {}
    for f in filas_estado[1:]:
        if len(f) > h['Ident'] and f[h['Entidad_ID']] == entidad_id and f[h['Ident']]:
            out[f[h['Ident']]] = {c: (f[h[c]] if c in h and len(f) > h[c] else '') for c in ESTADO_HEADERS}
    return out


def actualizar(previo, entidad_id, idents_hoy, completa, hoy):
    """previo: estado_de_tienda(...). idents_hoy: iterable de textos de ident leídos hoy.
    -> (filas a escribir [dict], nuevas | None, desaparecidas | None, siembra: bool). Si la lectura no es completa no hay cambios."""
    if not completa:
        return [], None, None, False
    vistas = {i for i in idents_hoy if i}
    siembra = not any(r['Primera_Vez'] != hoy for r in previo.values())
    cambios = {}
    for i in vistas:
        r = previo.get(i)
        if r is None:
            cambios[i] = {'Entidad_ID': entidad_id, 'Ident': i, 'Primera_Vez': hoy, 'Ultima_Vez': hoy, 'Activa': 'Si', 'Desaparecida_Desde': ''}
        else:
            cambios[i] = dict(r, Ultima_Vez=hoy, Activa='Si', Desaparecida_Desde='')
    for i, r in previo.items():
        if i not in vistas and _es_si(r['Activa']):
            cambios[i] = dict(r, Activa='No', Desaparecida_Desde=hoy)
    final = {i: cambios.get(i, r) for i, r in previo.items()}
    final.update({i: c for i, c in cambios.items() if i not in final})
    if siembra:
        return list(cambios.values()), None, None, True
    nuevas = sum(1 for i in vistas if final[i]['Primera_Vez'] == hoy)
    desap = sum(1 for r in final.values() if r['Desaparecida_Desde'] == hoy and not _es_si(r['Activa']))
    return list(cambios.values()), nuevas, desap, False


def registrar(ss, filas):
    """Upsert por (Entidad_ID, Ident). -> (insertadas, actualizadas)."""
    if not filas:
        return 0, 0
    ws = cdb.asegurar_pestana(ss, ESTADO_SHEET, ESTADO_HEADERS, 5000)
    h = sio.asegurar_columnas(ws, ESTADO_HEADERS)
    return sio.upsert(ws, h, filas, ['Entidad_ID', 'Ident'])
