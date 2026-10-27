"""`sheets_io.upsert` con la misma clave dos veces en una tanda (dos eventos iguales): no debe armar el rango «ANone:LNone» (corrida del 23/10: la hoja devolvió 400 y se perdieron los eventos)."""
import sheets_io as sio
from fakes import WS

H = ['Fecha', 'Tipo', 'Referencia_ID', 'Entidad', 'Detalle']


def _d(det, tipo='Cambio', ref='R1'):
    return {'Fecha': '2026-10-27', 'Tipo': tipo, 'Referencia_ID': ref, 'Entidad': 'GEOTEK', 'Detalle': det}


def test_la_misma_clave_dos_veces_en_la_tanda_queda_una_sola_fila_la_ultima():
    ws = WS('Eventos_Competencia', [H])
    nuevas, act = sio.upsert(ws, H, [_d('a'), _d('b'), _d('c', ref='R2')], ['Fecha', 'Tipo', 'Referencia_ID', 'Entidad'])
    assert (nuevas, act) == (2, 0)
    assert [r[4] for r in ws.rows[1:]] == ['b', 'c']


def test_una_clave_que_ya_estaba_en_la_hoja_se_reemplaza_y_la_repetida_tambien():
    ws = WS('Eventos_Competencia', [H, ['2026-10-27', 'Cambio', 'R1', 'GEOTEK', 'viejo']])
    nuevas, act = sio.upsert(ws, H, [_d('x'), _d('y')], ['Fecha', 'Tipo', 'Referencia_ID', 'Entidad'])
    assert nuevas == 0 and act == 2 and ws.rows[1][4] == 'y' and len(ws.rows) == 2
