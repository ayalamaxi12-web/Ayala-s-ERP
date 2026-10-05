"""Tests de la migración (`competencia_migracion.py`) con un Spreadsheet falso, y del endpoint protegido."""
import pytest

import competencia_db as cdb
import competencia_migracion as mig
from test_competencia_db import fuentes_base


class _WS:
    def __init__(self, title, rows):
        self.title, self.rows, self.col_count = title, [list(r) for r in rows], 30

    def get_all_values(self): return [list(r) for r in self.rows]
    def col_values(self, n): return [r[n - 1] if len(r) >= n else '' for r in self.rows]
    def row_values(self, n): return list(self.rows[n - 1]) if len(self.rows) >= n else []
    def append_row(self, f): self.rows.append(list(f))
    def append_rows(self, filas, value_input_option=None): self.rows += [list(f) for f in filas]
    def add_cols(self, n): self.col_count += n

    def update_cell(self, r, c, v):
        while len(self.rows[r - 1]) < c:
            self.rows[r - 1].append('')
        self.rows[r - 1][c - 1] = v


class _SS:
    def __init__(self, fuentes):
        m = {'refs': 'Referencias_Mercado', 'ents': 'Entidades', 'general': 'General',
             'ml_competencia': 'ML Competencia', 'hist_competidores': 'Historial Competidores',
             'monitor': 'Monitor_Lecturas'}
        self.w = {n: _WS(n, fuentes[k]) for k, n in m.items() if fuentes.get(k)}
        for t, rows in fuentes['v_tabs'].items():
            self.w[t] = _WS(t, rows)

    def worksheets(self): return list(self.w.values())

    def worksheet(self, n):
        if n not in self.w:
            raise KeyError(n)
        return self.w[n]

    def add_worksheet(self, title, rows, cols):
        self.w[title] = _WS(title, [])
        return self.w[title]


def _fuentes_con_h2_sin_precio():
    f = fuentes_base()
    f['hist_competidores'] += [['Rival', 't1', '', '', '', '', f['v_tabs']['V - Rival'][1][6], 'SKU-1', '1',
                                '04/10/2026', 'MLA1111111111', 'OK']] * 4
    return f


def test_flujo_completo_hash_respaldo_verificacion_e_idempotencia(monkeypatch):
    monkeypatch.setattr(mig.time, 'sleep', lambda s: None)
    ss = _SS(_fuentes_con_h2_sin_precio())
    seco = mig.correr(ss)
    assert seco['ejecutado'] is False and seco['informe']['cierra']
    h = seco['informe']['plan_hash']
    assert 'Historial_Precios' not in ss.w            # el dry-run no escribe nada
    # hash equivocado: no escribe nada y devuelve el hash vigente
    malo = mig.correr(ss, 'deadbeef', True, log=lambda m: None, archivo_local=False)
    assert malo['ejecutado'] is False and h in malo['motivo'] and 'Historial_Precios' not in ss.w
    # hash correcto
    r = mig.correr(ss, h, True, log=lambda m: None, archivo_local=False)
    assert r['ejecutado'] and r['verificacion_ok']
    assert r['filas'] == r['filas_esperadas']
    assert r['filas']['Historial_Precios'] == seco['informe']['lecturas_a_escribir']
    assert all(row[5] != '' for row in ss.w['Historial_Precios'].rows[1:])   # solo lecturas con precio
    assert any(n.startswith('Respaldo_Hist_Competidores_') for n in ss.w)    # respaldo hecho antes
    assert 'Cantidad' in ss.w['Referencias_Mercado'].rows[0]
    # segunda corrida: nada nuevo
    seg = mig.correr(ss)
    assert seg['informe']['lecturas_a_escribir'] == 0 and seg['informe']['referencias_nuevas'] == 0


def test_lectura_fallida_de_una_pestana_aborta_en_vez_de_leerla_vacia(monkeypatch):
    monkeypatch.setattr(mig.time, 'sleep', lambda s: None)
    ss = _SS(fuentes_base())
    ss.w['General'].get_all_values = lambda: (_ for _ in ()).throw(RuntimeError('429'))
    with pytest.raises(mig.MigracionError):
        mig.leer_sheet(ss)


def test_endpoint_falla_cerrado_y_exige_clave(monkeypatch):
    from fastapi.testclient import TestClient
    import main
    c = TestClient(main.app)
    monkeypatch.delenv('ERP_API_KEY', raising=False)
    assert c.post('/competencia/migracion/run', json={}).status_code == 503      # sin clave en el servidor: no corre
    monkeypatch.setenv('ERP_API_KEY', 'secreta')
    assert c.post('/competencia/migracion/run', json={}).status_code == 401
    assert c.post('/competencia/migracion/run', json={}, headers={'X-ERP-Key': 'otra'}).status_code == 401
    assert c.get('/competencia/migracion/status/x').status_code == 401
    h = {'X-ERP-Key': 'secreta'}
    assert c.post('/competencia/migracion/run', json={'ejecutar': True}, headers=h).status_code == 400  # sin plan_hash
    assert c.get('/competencia/migracion/status/x', headers=h).json() == {'status': 'not_found'}


def test_endpoint_dry_run_en_hilo_y_un_solo_job_a_la_vez(monkeypatch):
    import threading
    from fastapi.testclient import TestClient
    import main
    monkeypatch.setenv('ERP_API_KEY', 'secreta')
    liberar = threading.Event()
    monkeypatch.setattr(main, 'get_gs', lambda: type('G', (), {'open_by_key': lambda self, k: object()})())
    monkeypatch.setattr(mig, 'correr', lambda ss, plan_hash=None, ejecutar_real=False, log=print, archivo_local=True:
                        (liberar.wait(5), {'ejecutado': False, 'informe': {'plan_hash': 'abc'}})[1])
    c, h = TestClient(main.app), {'X-ERP-Key': 'secreta'}
    r = c.post('/competencia/migracion/run', json={}, headers=h)
    assert r.status_code == 200 and r.json()['modo'] == 'dry-run'
    assert c.post('/competencia/migracion/run', json={}, headers=h).status_code == 409   # ya hay uno corriendo
    liberar.set()
    import time
    for _ in range(50):
        st = c.get('/competencia/migracion/status/' + r.json()['job_id'], headers=h).json()
        if st['status'] != 'running':
            break
        time.sleep(0.1)
    assert st['status'] == 'done' and st['resultado']['informe']['plan_hash'] == 'abc'
