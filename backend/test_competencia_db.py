"""Tests de `competencia_db.py` — sin red ni Google. Cubren la migración (dry-run), el cierre exacto,
la idempotencia y la escritura en vivo con un Spreadsheet falso."""
import competencia_db as cdb

L1 = 'https://articulo.mercadolibre.com.ar/MLA-1111111111-algo?tracking=x'
L2 = 'https://articulo.mercadolibre.com.ar/MLA-2222222222-otro'
LCAT = 'https://www.mercadolibre.com.ar/p/MLA555?wid=MLA999999999'
LCAT_SIN_WID = 'https://www.mercadolibre.com.ar/p/MLA777'
ROTO = 'https://example.com/nada'

V_HDR = ['Titulo', 'Precio ($)', 'Precio Tachado ($)', 'Descuento', 'Cuotas', 'Ventas', 'Link', 'SKU', 'Cantidad',
         'Precio ($) 01/10/2026', 'Tachado ($) 01/10/2026', 'Desc 01/10/2026', 'Cuotas 01/10/2026',
         'Precio ($) 02/10/2026', 'Tachado ($) 02/10/2026', 'Desc 02/10/2026', 'Cuotas 02/10/2026']
REF_HDR = ['Referencia_ID', 'SKU', 'Tipo', 'Entidad_ID', 'Entidad_Nombre', 'Link_Publicacion', 'Activo']
ENT_HDR = ['Entidad_ID', 'Nombre', 'Tipo']
H2_HDR = ['Vendedor', 'Titulo', 'Precio ($)', 'Precio Tachado ($)', 'Descuento', 'Cuotas', 'Link', 'SKU', 'Cantidad',
          'Fecha Refresh', 'Item ID', 'Estado Identidad']
H3_HDR = ['Distribuidor', 'SKU', 'Link', 'Precio_Detectado', 'Fecha_Hora', 'Estado', 'Metodo', 'Detalle_Error',
          'Seller_ID', 'Official_Store_ID', 'Referencia_ID', 'Tipo', 'Entidad']


def fuentes_base():
    return {
        'ents': [ENT_HDR], 'refs': [REF_HDR],
        'general': [['Link', 'SKU', 'Cantidad', 'Vendedor'], [L2, 'SKU-2', '3', 'Rival']],
        'v_tabs': {'V - Rival': [
            V_HDR,
            ['t1', '1000', '', '', '', '', L1, 'SKU-1', '1', '1.200', '', '', '', '1.100', '1.500', '26% OFF', ''],
            ['t2', '2000', '', '', '', '', L2, '', '', '', '', '', '', '2.100', '', '', ''],
            ['t3', '3000', '', '', '', '', ROTO, '', '', '3.000', '', '', '', '', '', '', ''],
            ['t4', '', '', '', '', '', LCAT_SIN_WID, '', '', '', '', '', '', '4.000', '', '', ''],
        ]},
        'ml_competencia': [['Link', 'T', 'Vendedor', 'Precio', 'Tach', 'Desc', 'Cuotas', 'Upd'],
                           [L1, 't1', 'Rival', '1100', '', '', '', '02/10/2026 08:00'],
                           [LCAT, 'x', 'Otro', '❌ Sin datos', '', '', '', '']],
        'hist_competidores': [H2_HDR,
                              ['Rival', 't1', '1100', '', '', '', L1, 'SKU-1', '1', '02/10/2026', 'MLA1111111111', 'OK'],
                              ['Rival', 't1', '900', '', '', '', L1, 'SKU-1', '1', '03/10/2026', 'MLA1111111111', 'OK']],
        'monitor': [H3_HDR,
                    ['Rival', 'SKU-1', L1, '1100', '02/10/2026 09:15', 'OK', 'API', '', '', '', '', 'Competencia', 'Rival'],
                    ['Rival', 'SKU-1', L1, '1150', '03/10/2026 09:15', 'OK', 'API', '', '', '', '', 'Competencia', 'Rival'],
                    ['Fantasma', 'SKU-9', 'https://x.com/y', '10', '03/10/2026 09:15', 'OK', 'API', '', '', '', '', '', '']],
    }


def test_parse_precio_y_fecha():
    assert cdb.parse_precio('$ 1.234.567') == 1234567.0
    assert cdb.parse_precio('1234,50') == 1234.5
    assert cdb.parse_precio('1.234,50') == 1234.5
    assert cdb.parse_precio('') is None and cdb.parse_precio('❌ Sin datos') is None
    assert cdb.parse_fecha('02/10/2026 08:00') == ('02/10/2026', '08:00')
    assert cdb.parse_fecha('2026-10-02') == ('02/10/2026', '')
    assert cdb.parse_fecha('basura') == (None, '')


def test_clave_ref_catalogo_y_item():
    assert cdb.clave_ref(L1) == ('I', 'MLA1111111111')
    assert cdb.clave_ref(LCAT) == ('P', 'MLA555', 'MLA999999999')
    # catálogo sin wid se desambigua por vendedor
    assert cdb.clave_ref(LCAT_SIN_WID, 'A') != cdb.clave_ref(LCAT_SIN_WID, 'B')
    assert cdb.clave_ref(ROTO) is None
    assert cdb.es_catalogo_sin_wid(LCAT_SIN_WID) and not cdb.es_catalogo_sin_wid(LCAT)


def test_dry_run_cierra_exacto_y_no_pierde_nada():
    plan = cdb.planificar(fuentes_base(), hoy='04/10/2026')
    rep = plan.rep
    assert rep['cierra']
    # V-*: t1 (2 fechas + base) + t2 (1 + base) + t3/ROTO (1 + base, huérfanas) + t4 (1) = 8
    v = rep['fuentes'][cdb.F_V]
    assert v['origen'] == 8
    motivos = rep['motivos_huerfanos']
    assert motivos[f'{cdb.F_V} — Lectura base sin fecha (primer scrape): falta decidir fecha'] == 2  # t1,t2 (la de ROTO cae por link sin identificador)
    assert any('Link sin identificador ML' in k for k in motivos)
    # el SKU de L2 se resolvió desde General, y la cantidad también; nunca por título
    ref2 = next(r for r in plan.refs_nuevas if r['Link_Publicacion'] == L2)
    assert ref2['SKU'] == 'SKU-2' and ref2['Cantidad'] == '3' and ref2['Tipo'] == 'Competencia'
    # categoría no se toca: no hay columna de categoría en lo que se escribe
    assert all('Categoria' not in r for r in plan.refs_nuevas)
    # la entidad se crea una sola vez aunque aparezca en varias fuentes (case-insensitive)
    assert [e['Nombre'] for e in plan.entidades_nuevas].count('Rival') == 1


def test_fusion_entre_historicos_y_conflicto_de_precio():
    plan = cdb.planificar(fuentes_base(), hoy='04/10/2026')
    ref1 = next(r for r in plan.refs_nuevas if r['Link_Publicacion'] == L1)['Referencia_ID']
    del_dia2 = [l for l in plan.lecturas if l['Referencia_ID'] == ref1 and l['Fecha'] == '02/10/2026']
    precios = sorted(l['Precio'] for l in del_dia2)
    # 02/10: V dice 1100, ML Competencia 1100, H2 1100, H3 1100 -> se fusionan en UNA fila con las 4 fuentes
    assert precios == [1100]
    assert del_dia2[0]['Fuente'].count('+') == 3
    # 03/10: H2 dice 900 y H3 dice 1150 -> se conservan ambas y se informa el conflicto
    assert sorted(l['Precio'] for l in plan.lecturas if l['Referencia_ID'] == ref1 and l['Fecha'] == '03/10/2026') == [900, 1150]
    assert plan.rep['conflictos_precio_entre_fuentes'] == 1


def test_idempotente_segunda_corrida_no_escribe():
    f = fuentes_base()
    plan = cdb.planificar(f, hoy='04/10/2026')
    # simula el Sheet después de migrar
    f['ents'] += [[e['Entidad_ID'], e['Nombre'], e['Tipo']] for e in plan.entidades_nuevas]
    for r in plan.refs_nuevas:
        f['refs'].append([r['Referencia_ID'], r['SKU'], r['Tipo'], r['Entidad_ID'], r['Entidad_Nombre'],
                          r['Link_Publicacion'], r['Activo']])
    f['historial_existente'] = [cdb.HISTORIAL_HEADERS] + [[l.get(h, '') for h in cdb.HISTORIAL_HEADERS] for l in plan.lecturas]
    f['huerfanos_existentes'] = [cdb.HUERFANOS_HEADERS] + [[h.get(c, '') for c in cdb.HUERFANOS_HEADERS] for h in plan.huerfanos]
    post = cdb.planificar(f, hoy='04/10/2026')
    r = post.rep
    assert r['cierra'] and r['referencias_nuevas'] == 0 and r['entidades_nuevas'] == 0
    assert r['lecturas_a_escribir'] == 0 and r['huerfanos_a_escribir'] == 0 and r['totales']['nuevas'] == 0


def test_no_edita_ref_existente_y_reporta_conflicto_de_sku():
    f = fuentes_base()
    f['refs'].append(['REF-000007', 'OTRO-SKU', 'Competencia', 'ENT-000001', 'Rival', L1, 'Si'])
    plan = cdb.planificar(f, hoy='04/10/2026')
    assert all(r['Link_Publicacion'] != L1 for r in plan.refs_nuevas)  # se reutiliza, no se duplica
    assert plan.rep['conflictos_sku'][0]['referencia'] == 'REF-000007'
    assert plan.refs_nuevas[0]['Referencia_ID'] == 'REF-000008'      # secuencia continúa


def test_normalizar_resultado_catalogo_sin_wid_es_sin_lectura():
    res = {'precio': None, 'detalle_error': 'Link de catálogo sin wid= — no se puede identificar la oferta'}
    assert cdb.normalizar_resultado(res, LCAT_SIN_WID) == ('Sin lectura', False)
    assert cdb.normalizar_resultado({'precio': 10}, L1) == ('OK', True)
    assert cdb.normalizar_resultado({'precio': None, 'detalle_error': 'API 403'}, L1) == ('Error', False)  # sin precio no se guarda


class _WS:
    def __init__(self, rows): self.rows = rows
    def get_all_values(self): return [list(r) for r in self.rows]
    def col_values(self, n): return [r[n - 1] if len(r) >= n else '' for r in self.rows]
    def append_rows(self, filas, value_input_option=None): self.rows += [list(f) for f in filas]
    def append_row(self, f): self.rows.append(list(f))


class _SS:
    def __init__(self): self.w = {'Referencias_Mercado': _WS([REF_HDR, ['REF-000001', 'SKU-1', 'Competencia', 'E', 'Rival', L1, 'Si']])}
    def worksheet(self, n):
        if n not in self.w: raise KeyError(n)
        return self.w[n]
    def add_worksheet(self, title, rows, cols):
        self.w[title] = _WS([]); return self.w[title]


def test_registrar_lecturas_en_vivo_idempotente_por_dia():
    ss = _SS()
    lec = [{'link': L1, 'entidad': 'Rival', 'precio': 1234, 'estado': 'OK', 'metodo': 'API'},
           {'link': L2, 'entidad': 'Rival', 'precio': 5, 'estado': 'OK', 'metodo': 'API'}]
    r1 = cdb.registrar_lecturas(ss, lec, 'test')
    assert r1 == {'escritas': 1, 'duplicadas': 0, 'sin_referencia': 1, 'sin_precio': 0}
    r2 = cdb.registrar_lecturas(ss, lec, 'test')
    assert r2 == {'escritas': 0, 'duplicadas': 1, 'sin_referencia': 1, 'sin_precio': 0}
    assert len(ss.w[cdb.HISTORIAL_SHEET].rows) == 2  # header + 1


def test_bloque_de_fecha_repetido_no_se_pisa_y_sku_guion_es_vacio():
    hdr = ['Titulo', 'Precio ($)', 'Precio Tachado ($)', 'Descuento', 'Cuotas', 'Ventas', 'Link', 'SKU', 'Cantidad',
           'Precio ($) 25/06/2026', 'Tachado ($) 25/06/2026', 'Desc 25/06/2026', 'Cuotas 25/06/2026',
           'Precio ($) 25/06/2026', 'Tachado ($) 25/06/2026', 'Desc 25/06/2026', 'Cuotas 25/06/2026']
    f = {'ents': [ENT_HDR], 'refs': [REF_HDR], 'v_tabs': {'V - R': [
        hdr, ['t', '', '', '', '', '', L1, '-', '1', '100', '', '', '', '200', '', '', '']]}}
    plan = cdb.planificar(f, hoy='04/10/2026')
    assert sorted(l['Precio'] for l in plan.lecturas) == [100, 200]  # ambos scrapes del 25/06 se conservan
    assert plan.refs_nuevas[0]['SKU'] == ''
    assert plan.rep['conflictos_precio_mismo_dia'] == 1


def test_lecturas_sin_precio_no_se_migran_se_cuentan_y_el_informe_cierra():
    f = fuentes_base()
    f['hist_competidores'] += [['Rival', 't1', '', '', '', '', L1, 'SKU-1', '1', '04/10/2026', 'MLA1111111111', 'OK']] * 3
    plan = cdb.planificar(f, hoy='04/10/2026')
    assert plan.rep['fuentes'][cdb.F_H2]['sin_precio'] == 3
    assert plan.rep['cierra'] and all(l['Precio'] != '' for l in plan.lecturas)
    # en vivo tampoco se guardan
    ss = _SS()
    r = cdb.registrar_lecturas(ss, [{'link': L1, 'entidad': 'Rival', 'precio': None, 'estado': 'Error'}], 'test')
    assert r['sin_precio'] == 1 and r['escritas'] == 0
