"""Fase 2: Tiendas_Estado (publicaciones por tienda) y Nuevas/Desaparecidas en Tiendas_Conteo. Datos SINTÉTICOS."""
import corrida
import tiendas_conteo as tc
import tiendas_estado as te
from test_conteo import _items, _lector, correr, URL_TV, URL_AC, URL_GK
from test_scraper import base, tienda
from fakes import LectorFalso

HOY = '05/10/2026'


def _prev(*filas):
    return te.estado_de_tienda([te.ESTADO_HEADERS] + [list(f) for f in filas], 'E1')


def test_ident_texto():
    assert te.ident_texto(('P', 'MLA1', 'w2')) == 'P|MLA1|w2' and te.ident_texto(None) == ''


def test_siembra_no_cuenta_nuevas_ni_desaparecidas():
    filas, n, d, siembra = te.actualizar({}, 'E1', ['a', 'b'], True, HOY)
    assert siembra and n is None and d is None and {f['Ident'] for f in filas} == {'a', 'b'}
    assert all(f['Primera_Vez'] == HOY and f['Activa'] == 'Si' for f in filas)


def test_nuevas_desaparecidas_y_reaparecidas():
    prev = _prev(['E1', 'a', '01/10/2026', '04/10/2026', 'Si', ''], ['E1', 'b', '01/10/2026', '04/10/2026', 'Si', ''],
                 ['E1', 'c', '01/10/2026', '02/10/2026', 'No', '03/10/2026'])
    filas, n, d, siembra = te.actualizar(prev, 'E1', ['a', 'c', 'z'], True, HOY)       # b se fue, z es nueva, c vuelve
    por = {f['Ident']: f for f in filas}
    assert (n, d, siembra) == (1, 1, False)
    assert por['z']['Primera_Vez'] == HOY and por['b']['Activa'] == 'No' and por['b']['Desaparecida_Desde'] == HOY
    assert por['c']['Activa'] == 'Si' and por['c']['Desaparecida_Desde'] == '' and por['c']['Primera_Vez'] == '01/10/2026'


def test_lectura_incompleta_no_mueve_nada():
    assert te.actualizar(_prev(['E1', 'a', '01/10/2026', '04/10/2026', 'Si', '']), 'E1', [], False, HOY) == ([], None, None, False)


def test_idempotente_el_mismo_dia():
    prev = _prev(['E1', 'a', '01/10/2026', '04/10/2026', 'Si', ''], ['E1', 'b', '01/10/2026', '04/10/2026', 'Si', ''])
    f1, n1, d1, _ = te.actualizar(prev, 'E1', ['a', 'z'], True, HOY)
    prev2 = _prev(*[[f[c] for c in te.ESTADO_HEADERS] for f in f1] + [])
    f2, n2, d2, s2 = te.actualizar(prev2, 'E1', ['a', 'z'], True, HOY)
    assert (n1, d1) == (n2, d2) == (1, 1) and not s2


def test_la_corrida_siembra_y_al_dia_siguiente_cuenta():
    ss = base()
    correr(ss, _lector(), '05/10/2026')
    est = ss.tab(te.ESTADO_SHEET)
    assert est[0] == te.ESTADO_HEADERS and len(est) == 1 + 20 + 5 + 3
    fila_tv = next(f for f in ss.tab(tc.CONTEO_SHEET)[1:] if f[3] == 'TECNOVIBEARG')
    assert (fila_tv[9], fila_tv[10]) == ('', '')                                          # siembra: sin comparación
    # día 2: tecnovibe pierde 2 (t0, t1) y suma 3 (t20..t22)
    lec = LectorFalso(tiendas={URL_TV: dict(tienda(*_items(21, 2)[:18] + _items(3, 20)), declaradas=21, paginas=1, fin='sin_siguiente'),
                               URL_AC: dict(tienda(*_items(5, 500)), declaradas=5, paginas=1, fin='sin_siguiente'),
                               URL_GK: dict(tienda(*_items(3, 900)), declaradas=3, paginas=1, fin='sin_siguiente')}, pubs={})
    r = correr(ss, lec, '06/10/2026')
    fila_tv = next(f for f in ss.tab(tc.CONTEO_SHEET)[1:] if f[3] == 'TECNOVIBEARG' and f[0] == '06/10/2026')
    assert (fila_tv[9], fila_tv[10]) == (3, 2)
    assert next(f for f in r['tiendas'] if f['entidad'] == 'TECNOVIBEARG')['nuevas'] == 3
    assert '+3 nuevas / -2 desaparecidas' in corrida.texto_resumen(r)
    r = correr(ss, lec, '06/10/2026')                                                      # repetir el día no cambia el conteo
    fila_tv = next(f for f in ss.tab(tc.CONTEO_SHEET)[1:] if f[3] == 'TECNOVIBEARG' and f[0] == '06/10/2026')
    assert (fila_tv[9], fila_tv[10]) == (3, 2)


def test_tienda_incompleta_o_sin_escribir_no_toca_el_estado():
    ss = base()
    correr(ss, _lector(), '05/10/2026')
    tv = lambda: [list(f) for f in ss.tab(te.ESTADO_SHEET) if f[0] == 'ENT-000001']
    antes = tv()
    lec = _lector(n_tv=5, decl_tv=20)                                                      # 5 de 20 declaradas: incompleta
    correr(ss, lec, '06/10/2026')
    assert len(antes) == 20 and tv() == antes                                              # las otras tiendas (completas) sí avanzan
    f = next(f for f in ss.tab(tc.CONTEO_SHEET)[1:] if f[3] == 'TECNOVIBEARG' and f[0] == '06/10/2026')
    assert f[7] == 'No' and (f[9], f[10]) == ('', '')
    ss2 = base()
    correr(ss2, _lector(), '05/10/2026', escribir=False)
    assert te.ESTADO_SHEET not in {w.title for w in ss2.worksheets()}
