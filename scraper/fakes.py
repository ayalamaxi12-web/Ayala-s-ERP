"""Sheet y lector falsos para probar el scraper sin red (solo tests)."""
import re


def _a1(ref):
    m = re.fullmatch(r'([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?', ref)
    def col(s):
        n = 0
        for ch in s:
            n = n * 26 + ord(ch) - 64
        return n
    c1, r1 = col(m.group(1)), int(m.group(2))
    return r1, c1


class WS:
    def __init__(self, title, rows=()):
        self.title, self.rows, self.col_count = title, [list(r) for r in rows], 40

    def get_all_values(self): return [list(r) for r in self.rows]
    def row_values(self, n): return list(self.rows[n - 1]) if len(self.rows) >= n else []
    def col_values(self, n): return [r[n - 1] if len(r) >= n else '' for r in self.rows]
    def append_row(self, f): self.rows.append(list(f))
    def append_rows(self, filas, value_input_option=None): self.rows += [list(f) for f in filas]
    def add_cols(self, n): self.col_count += n

    def update_cell(self, r, c, v):
        while len(self.rows) < r:
            self.rows.append([])
        while len(self.rows[r - 1]) < c:
            self.rows[r - 1].append('')
        self.rows[r - 1][c - 1] = v

    def batch_update(self, data, **kw):
        for d in data:
            r, c = _a1(d['range'])
            for i, fila in enumerate(d['values']):
                for j, v in enumerate(fila):
                    self.update_cell(r + i, c + j, v)


class SS:
    def __init__(self, hojas):
        self.w = {n: WS(n, rows) for n, rows in hojas.items()}

    def worksheets(self): return list(self.w.values())

    def worksheet(self, n):
        if n not in self.w:
            raise KeyError(n)
        return self.w[n]

    def add_worksheet(self, title, rows, cols):
        self.w[title] = WS(title)
        return self.w[title]

    def tab(self, n): return self.w[n].rows

    def fetch_sheet_metadata(self, params=None):
        return {'sheets': [{'properties': {'title': n, 'gridProperties': {'rowCount': max(len(w.rows), 1), 'columnCount': w.col_count}}}
                           for n, w in self.w.items()]}


class LectorFalso:
    """tiendas: {url: {'estado':..., 'items':[...]}} · pubs: {url: dict resultado}. Cuenta las llamadas."""
    def __init__(self, tiendas=None, pubs=None):
        self.tiendas, self.pubs, self.llamadas = tiendas or {}, pubs or {}, []

    def leer_tienda(self, url, max_paginas=None, diagnostico=False):
        self.llamadas.append(('tienda', url))
        return self.tiendas.get(url, {'estado': 'error', 'items': [], 'detalle': 'no mockeada'})

    def leer_publicacion(self, url, esperado=None, diagnostico=False):
        self.llamadas.append(('pub', url))
        return self.pubs.get(url, {'estado': 'Error', 'detalle': 'no mockeada', 'precio': None, 'vendedor': ''})

    def cerrar(self): pass
