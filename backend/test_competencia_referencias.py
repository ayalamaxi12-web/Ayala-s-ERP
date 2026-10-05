"""Tests de competencia_referencias.py (desactivar referencias de una entidad, con registro y reversión) y de sus endpoints."""
import pytest

import re

import competencia_referencias as cr


class _WS:
    def __init__(self, title, rows=()):
        self.title, self.rows, self.col_count = title, [list(r) for r in rows], 30

    def get_all_values(self): return [list(r) for r in self.rows]
    def append_row(self, f): self.rows.append(list(f))
    def append_rows(self, filas, value_input_option=None): self.rows += [list(f) for f in filas]

    def batch_update(self, data, **kw):
        for d in data:
            m = re.fullmatch(r'([A-Z]+)(\d+)', d['range'])
            col = 0
            for ch in m.group(1):
                col = col * 26 + ord(ch) - 64
            r = int(m.group(2))
            while len(self.rows[r - 1]) < col:
                self.rows[r - 1].append('')
            self.rows[r - 1][col - 1] = d['values'][0][0]


class _SS:
    def __init__(self, hojas): self.w = {n: _WS(n, r) for n, r in hojas.items()}
    def worksheets(self): return list(self.w.values())

    def worksheet(self, n):
        if n not in self.w:
            raise KeyError(n)
        return self.w[n]

    def add_worksheet(self, title, rows, cols):
        self.w[title] = _WS(title)
        return self.w[title]


@pytest.fixture(autouse=True)
def _sin_pausas(monkeypatch):
    monkeypatch.setattr(cr.time, 'sleep', lambda s: None)


def hoja(n_global=5, n_otra=3, inactivas_global=1):
    h = ['Referencia_ID', 'SKU', 'Tipo', 'Entidad_ID', 'Entidad_Nombre', 'Link_Publicacion', 'Activo']
    filas = [h]
    for i in range(n_global):
        filas.append([f'REF-G{i}', 'S', 'Competencia', 'ENT-3', 'GLOBAL ELECTRONICS GROUP', f'l{i}', 'No' if i < inactivas_global else 'Si'])
    for i in range(n_otra):
        filas.append([f'REF-O{i}', 'S', 'Competencia', 'ENT-1', 'TECNOVIBEARG', f'o{i}', 'Si'])
    return filas


def ss_con(filas):
    return _SS({'Referencias_Mercado': filas})


def test_dry_run_no_toca_nada_y_cuenta_solo_las_activas():
    ss = ss_con(hoja())
    antes = [list(f) for f in ss.w['Referencias_Mercado'].rows]
    r = cr.desactivar_entidad(ss, 'global electronics group')           # normalizado: no importa mayúsculas
    assert r['ejecutado'] is False and r['coinciden'] == 5 and r['activas_a_desactivar'] == 4 and r['ya_inactivas'] == 1
    assert ss.w['Referencias_Mercado'].rows == antes and cr.CAMBIOS_SHEET not in ss.w


def test_ejecutar_exige_la_cantidad_esperada_y_verifica():
    ss = ss_con(hoja())
    mal = cr.desactivar_entidad(ss, 'GLOBAL ELECTRONICS GROUP', ejecutar=True, esperado=99)
    assert mal['ejecutado'] is False and 'no coincide' in mal['motivo'] and cr.CAMBIOS_SHEET not in ss.w
    r = cr.desactivar_entidad(ss, 'GLOBAL ELECTRONICS GROUP', ejecutar=True, esperado=4, log=lambda m: None)
    assert r['ejecutado'] and r['verificacion_ok'] and r['quedan_activas'] == 0
    filas = {f[0]: f[6] for f in ss.w['Referencias_Mercado'].rows[1:]}
    assert all(filas[f'REF-G{i}'] == 'No' for i in range(5))
    assert all(filas[f'REF-O{i}'] == 'Si' for i in range(3))              # las demás entidades no se tocan
    reg = ss.w[cr.CAMBIOS_SHEET].rows
    assert len(reg) == 1 + 4 and {f[4] for f in reg[1:]} == {'Si'} and {f[5] for f in reg[1:]} == {'No'}


def test_revertir_solo_lo_que_sigue_como_lo_dejo_el_lote():
    ss = ss_con(hoja())
    r = cr.desactivar_entidad(ss, 'GLOBAL ELECTRONICS GROUP', ejecutar=True, esperado=4, log=lambda m: None)
    ws = ss.w['Referencias_Mercado']
    ws.rows[3][6] = 'Si'                                                    # alguien reactivó REF-G2 a mano
    seco = cr.revertir_lote(ss, r['lote'])
    assert seco == {'lote': r['lote'], 'en_el_lote': 4, 'a_revertir': 3, 'cambiadas_despues': 1, 'ejecutado': False}
    cr.revertir_lote(ss, r['lote'], ejecutar=True, log=lambda m: None)
    assert [f[6] for f in ws.rows[1:6]] == ['No', 'Si', 'Si', 'Si', 'Si']   # la 1ª ya estaba inactiva antes: sigue 'No'
    with pytest.raises(cr.CambioError):
        cr.revertir_lote(ss, 'LOTE-inexistente')


def test_endpoints_protegidos_y_dry_run(monkeypatch):
    from fastapi.testclient import TestClient
    import main
    import competencia_referencias
    c = TestClient(main.app)
    monkeypatch.delenv('ERP_API_KEY', raising=False)
    assert c.post('/competencia/referencias/desactivar-entidad', json={'entidad': 'X'}).status_code == 503   # falla cerrado
    monkeypatch.setenv('ERP_API_KEY', 'k')
    assert c.post('/competencia/referencias/desactivar-entidad', json={'entidad': 'X'}).status_code == 401
    h = {'X-ERP-Key': 'k'}
    assert c.post('/competencia/referencias/desactivar-entidad', json={'entidad': 'X', 'ejecutar': True}, headers=h).status_code == 400
    assert c.post('/competencia/referencias/revertir-lote', json={}, headers=h).status_code == 400
    ss = ss_con(hoja())
    monkeypatch.setattr(main, 'get_gs', lambda: type('G', (), {'open_by_key': lambda self, k: ss})())
    r = c.post('/competencia/referencias/desactivar-entidad', json={'entidad': 'GLOBAL ELECTRONICS GROUP'}, headers=h)
    assert r.status_code == 200 and r.json()['activas_a_desactivar'] == 4 and r.json()['ejecutado'] is False
    r = c.post('/competencia/referencias/revertir-lote', json={'lote': 'nada'}, headers=h)
    assert r.status_code == 400
