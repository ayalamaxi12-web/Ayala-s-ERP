"""Lectura/escritura de Google Sheets para el scraper. Funciones chicas sobre gspread (se prueban con un Sheet falso).
Regla: nunca pisar datos existentes salvo la fila de la MISMA lectura/evento del día (upsert) y rellenar vacíos."""
import time

import config  # noqa: F401
import competencia_db as cdb


def col_letra(n):
    s = ''
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def leer(ss, nombre, titulos=None, reintentos=5):
    """Pestaña inexistente = []. Cualquier otro error se reintenta y, si persiste, FALLA (nunca se lee como vacía)."""
    if titulos is None:
        titulos = {w.title for w in ss.worksheets()}
    if nombre not in titulos:
        return []
    for i in range(reintentos):
        try:
            return ss.worksheet(nombre).get_all_values()
        except Exception as e:  # noqa: BLE001
            if i == reintentos - 1:
                raise RuntimeError(f'No se pudo leer la pestaña {nombre!r}: {e}')
            time.sleep(10 * (i + 1))


def asegurar_columnas(ws, nombres):
    """Agrega al final de la fila 1 las columnas que falten (no mueve ninguna existente). -> encabezados."""
    h = ws.row_values(1)
    faltan = [n for n in nombres if n not in h]
    if faltan:
        if len(h) + len(faltan) > ws.col_count:
            ws.add_cols(len(h) + len(faltan) - ws.col_count)
        for n in faltan:
            h.append(n)
            ws.update_cell(1, len(h), n)
    return h


def agregar(ws, headers, dicts, trozo=500):
    filas = [cdb.fila_desde_dict(headers, d) for d in dicts]
    for i in range(0, len(filas), trozo):
        ws.append_rows(filas[i:i + trozo], value_input_option='RAW')
        time.sleep(0.3)
    return len(filas)


def actualizar_celdas(ws, headers, cambios, trozo=200):
    """cambios: [(fila 1-based, nombre_columna, valor)]."""
    data = [{'range': f'{col_letra(headers.index(c) + 1)}{f}', 'values': [[v]]} for f, c, v in cambios if c in headers]
    for i in range(0, len(data), trozo):
        ws.batch_update(data[i:i + trozo])
        time.sleep(0.5)
    return len(data)


def upsert(ws, headers, dicts, claves, trozo=200):
    """Inserta o REEMPLAZA (por las columnas `claves`) la fila de la misma lectura/evento. -> (insertadas, actualizadas)."""
    existentes = ws.get_all_values()
    idx = {h: i for i, h in enumerate(headers)}
    pos = {}
    for n, f in enumerate(existentes[1:], start=2):
        pos[tuple(str(f[idx[c]]).strip() if idx[c] < len(f) else '' for c in claves)] = n
    nuevas, data = [], []
    ultima = col_letra(len(headers))
    for d in dicts:
        k = tuple(str(d.get(c, '')).strip() for c in claves)
        fila = cdb.fila_desde_dict(headers, d)
        if k in pos:
            data.append({'range': f'A{pos[k]}:{ultima}{pos[k]}', 'values': [fila]})
        else:
            nuevas.append(d)
            pos[k] = None
    for i in range(0, len(data), trozo):
        ws.batch_update(data[i:i + trozo])
        time.sleep(0.5)
    agregar(ws, headers, nuevas)
    return len(nuevas), len(data)
