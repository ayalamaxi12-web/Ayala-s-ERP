from datetime import date

import competencia_analisis as ca

HOY = date(2026, 10, 10)
REFS = [['Referencia_ID', 'SKU', 'Tipo', 'Entidad_ID', 'Entidad_Nombre', 'Link_Publicacion', 'PVP_Oficial', 'Activo', 'Rol_Competidor', 'Cantidad'],
        ['R1', 'PV-1', 'Competencia', 'E1', 'GEOTEK', 'https://x/1', '', 'Si', 'Rey', '2'],
        ['R2', 'PV-1', 'Competencia', 'E2', 'TECNO', 'https://x/2', '', 'Si', 'Barato', ''],
        ['R3', 'PV-2', 'Competencia', 'E1', 'GEOTEK', 'https://x/3', '', 'No', 'Rey', ''],
        ['R4', 'PV-3', 'Distribuidor', 'E3', 'DIST', 'https://x/4', '', 'Si', '', ''],
        ['R5', 'PV-4', 'Competencia', 'E1', 'GEOTEK', 'https://x/5', '', 'Si', 'Media', '']]
H = ['Referencia_ID', 'SKU', 'Entidad', 'Fecha', 'Hora', 'Precio', 'Precio_Tachado', 'Descuento', 'Cuotas', 'Estado', 'Metodo', 'Fuente', 'Link', 'Precio_Ganador', 'Vendedor_Ganador']


def h(rid, fecha, precio, hora='17:30', estado='OK', gan='', vg=''):
    return [rid, 'S', 'E', fecha, hora, precio, '', '', '', estado, 'api', 'Scraper', '', gan, vg]


HIST = [H,
        h('R1', '01/10/2026', '1000'), h('R1', '02/10/2026', '1000'), h('R1', '03/10/2026', '1200'), h('R1', '04/10/2026', '1200'),
        h('R1', '09/10/2026', '$ 1.100', gan='1050', vg='OTRO'),
        h('R2', '09/10/2026', '500'), h('R2', '10/10/2026', '', estado='Publicacion caida'),
        h('R3', '09/10/2026', '1'), h('R4', '09/10/2026', '2'), h('ZZ', '09/10/2026', '3'), h('R1', 'basura', '5')]


def armar(**k):
    return ca.construir(dict({'refs': REFS, 'hist': HIST, 'eventos': [], 'conteo': [], 'categorias': []}, **k), dias=30, hoy=HOY)


def test_solo_competencia_activa_y_cuenta_lo_excluido():
    r = armar()
    assert [x['id'] for x in r['referencias']] == ['R1', 'R2', 'R5'] and r['excluidas'] == {'inactivas': 1, 'otro_tipo': 1}


def test_ultimo_anterior_delta_desde_y_ganador():
    r1 = next(x for x in armar()['referencias'] if x['id'] == 'R1')
    assert r1['ultimo']['precio'] == 1100 and r1['ultimo']['fecha'] == '2026-10-09'
    assert r1['anterior'] == {'fecha': '2026-10-04', 'precio': 1200} and r1['delta_pct'] == -8.33
    assert r1['desde'] == '2026-10-09'                                   # el precio actual rige desde la última lectura (cambió)
    assert r1['ganador'] == {'precio': 1050, 'vendedor': 'OTRO'} and r1['cantidad'] == 2
    assert [p for _, p in r1['serie']] == [1000, 1000, 1200, 1200, 1100]


def test_desde_es_el_inicio_de_la_racha_con_el_mismo_precio():
    hist = [H, h('R1', '01/10/2026', '900'), h('R1', '02/10/2026', '1000'), h('R1', '03/10/2026', '1000'), h('R1', '04/10/2026', '1000')]
    r1 = armar(hist=hist)['referencias'][0]
    assert r1['desde'] == '2026-10-02' and r1['delta_pct'] == 0.0


def test_lectura_sin_precio_no_pisa_el_ultimo_precio_pero_se_informa():
    r2 = next(x for x in armar()['referencias'] if x['id'] == 'R2')
    assert r2['ultimo']['precio'] == 500 and r2['ultima_lectura'] == {'fecha': '2026-10-10', 'estado': 'Publicacion caida', 'dias': 0}


def test_referencia_sin_lecturas_y_avisos():
    r = armar()
    r5 = next(x for x in r['referencias'] if x['id'] == 'R5')
    assert r5['ultimo'] is None and r5['serie'] == []
    assert any('1 referencias activas' in a for a in r['avisos']) and any('fecha ilegible' in a for a in r['avisos'])
    assert any('Categoria_Competidores' in a for a in r['avisos'])


def test_la_serie_respeta_la_ventana_de_dias():
    r = ca.construir({'refs': REFS, 'hist': HIST, 'eventos': [], 'conteo': [], 'categorias': []}, dias=3, hoy=HOY)
    assert [f for f, _ in next(x for x in r['referencias'] if x['id'] == 'R1')['serie']] == ['2026-10-09']


def test_eventos_ventana_y_orden():
    ev = [['Fecha', 'Hora', 'Tipo', 'Referencia_ID', 'SKU', 'Entidad', 'Rol', 'Valor_Anterior', 'Valor_Nuevo', 'Variacion_Pct', 'Detalle', 'Link'],
          ['05/10/2026', '17:30', 'Bajo', 'R1', 'PV-1', 'GEOTEK', 'Rey', '1200', '1100', '-8.3', '', ''],
          ['09/10/2026', '17:30', 'Subio', 'R2', 'PV-1', 'TECNO', 'Barato', '400', '500', '25', '', ''],
          ['01/01/2026', '17:30', 'Bajo', 'R1', 'PV-1', 'GEOTEK', 'Rey', '1', '1', '', '', '']]
    e = armar(eventos=ev)['eventos']
    assert [(x['tipo'], x['fecha']) for x in e] == [('Subio', '2026-10-09'), ('Bajo', '2026-10-05')] and e[0]['nuevo'] == 500


def test_tiendas_conteo_y_categorias_desactualizadas():
    cont = [['Fecha', 'Hora', 'Entidad_ID', 'Entidad', 'Leidas', 'Declaradas_ML', 'Paginas', 'Completa', 'Motivo', 'Nuevas', 'Desaparecidas', 'Mediana_7d', 'Var_vs_Mediana_Pct', 'Estado_Debilidad', 'Fuente'],
            ['08/10/2026', '', 'E1', 'GEOTEK', '120', '122', '3', 'Si', '', '', '', '', '', '', 'Scraper'],
            ['09/10/2026', '', 'E1', 'GEOTEK', '48', '122', '1', 'No', 'captcha', '', '', '118', '', '', 'Scraper'],
            ['08/10/2026', '', 'E2', 'TECNO', '30', '30', '1', 'Si', '', '0', '4', '', '', '', 'Scraper']]
    cat = [['Subcategoria', 'Rol', 'Entidad_ID', 'Entidad', 'Slug', 'SKUs_Nuestros', 'Actualizado'],
           ['Toner', 'Rey', 'E1', 'GEOTEK', 'geotek', 'PV-1', '10/10/2026'], ['Tinta', 'Barato', 'E2', 'TECNO', 'tecno', '', '01/09/2026']]
    r = armar(conteo=cont, categorias=cat)
    t = r['tiendas'][0]
    assert (t['ultimo']['nuevas'], t['ultimo']['desaparecidas']) == (None, None)             # '' = no medido (lectura incompleta)
    t2 = r['tiendas'][1]
    assert (t2['ultimo']['nuevas'], t2['ultimo']['desaparecidas']) == (0, 4) and t2['serie'][0]['nuevas'] == 0    # 0 es un dato, no 'sin dato'
    assert t['ultimo']['leidas'] == 48 and t['ultimo']['completa'] is False and t['ultimo']['mediana_7d'] == 118 and len(t['serie']) == 2
    assert [c['desactualizada'] for c in r['categorias']] == [False, True]
    assert not any('Categoria_Competidores' in a for a in r['avisos'])


def test_cache_lee_una_vez_respeta_ttl_y_min_refresco_y_sobrevive_a_un_error():
    t, lecturas, falla = [1000.0], [], [False]

    def leer():
        lecturas.append(1)
        if falla[0]:
            raise RuntimeError('cuota')
        return {'refs': REFS, 'hist': HIST, 'eventos': [], 'conteo': [], 'categorias': []}
    c = ca.CacheAnalisis(leer, ttl=600, min_refresco=30, reloj=lambda: t[0])
    c.obtener(30, hoy=HOY); c.obtener(7, hoy=HOY)
    assert len(lecturas) == 1                                    # dos consultas, una lectura del Sheet
    t[0] += 10
    assert c.obtener(30, refrescar=True, hoy=HOY)['cache']['refresco_ignorado'] and len(lecturas) == 1     # muy pronto
    t[0] += 30
    assert not c.obtener(30, refrescar=True, hoy=HOY)['cache']['refresco_ignorado'] and len(lecturas) == 2
    t[0] += 700; falla[0] = True
    r = c.obtener(30, hoy=HOY)                                   # TTL vencido y el Sheet falla: se sirve lo cacheado
    assert r['cache']['refresco_ignorado'] and r['referencias']
    c2 = ca.CacheAnalisis(leer, reloj=lambda: t[0])
    try:
        c2.obtener(30, hoy=HOY)
        assert False
    except RuntimeError:
        pass


def test_aviso_cuando_tiendas_estado_supera_el_umbral(monkeypatch):
    base = {'refs': REFS, 'hist': HIST, 'eventos': [], 'conteo': [], 'categorias': []}
    sin = lambda **k: [a for a in ca.construir(dict(base, **k), dias=30, hoy=HOY)['avisos'] if 'Tiendas_Estado' in a]
    assert sin() == [] and sin(estado_filas=ca.TIENDAS_ESTADO_AVISO_FILAS) == []            # en el umbral todavía no avisa
    a = sin(estado_filas=ca.TIENDAS_ESTADO_AVISO_FILAS + 1)
    assert len(a) == 1 and '100.001 filas' in a[0] and 'podar' in a[0] and '90 días' in a[0]
    monkeypatch.setattr(ca, 'TIENDAS_ESTADO_AVISO_FILAS', 10)
    assert len(sin(estado_filas=11)) == 1
