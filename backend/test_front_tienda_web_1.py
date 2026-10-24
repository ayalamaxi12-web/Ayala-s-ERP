"""Estilo «tienda web», PR 1: Ventas & Rentabilidad con la consulta en vivo tras una bandera, y fuente/barra lateral para todo el ERP."""
import re

from test_front_analisis import INDEX


def html():
    return open(INDEX, encoding='utf-8').read()


def test_la_consulta_en_vivo_y_la_pestana_estan_tras_una_bandera_apagada_y_el_codigo_sigue_ahi():
    s = html()
    assert 'const VENTAS_EN_VIVO=false;' in s
    assert "(page==='dashboard'&&VENTAS_EN_VIVO)?'block':'none'" in s and "(page==='dashboard'&&VENTAS_EN_VIVO)?'flex':'none'" in s
    for id_ in ('rent-query-bar', 'ventas-tab-btn-vivo', 'rent-btn-consultar', 'page-dashboard-vivo'):
        assert f'id="{id_}"' in s, id_                                                         # no se borró nada


def test_cierres_guardados_y_liquidacion_fravega_viven_fuera_de_la_consulta_en_vivo():
    s = html()
    barra = s[s.index('<div id="rent-query-bar"'):s.index('<div id="dash-cab"')]
    for id_ in ('rent-btn-historicos', 'rent-btn-liq-fravega', 'rent-liq-fravega-file', 'rent-status', 'rent-historicos-panel'):
        assert f'id="{id_}"' not in barra, id_                                                 # ya no dependen de la barra que se oculta
        assert s.count(f'id="{id_}"') == 1, id_
    cab = s[s.index('<div id="dash-cab"'):s.index('<div id="ventas-tabs-bar"')]
    assert 'Cierres guardados' in cab and 'Cargar liquidación Frávega' in cab and 'rentCargarLiquidacionFravega(this)' in cab


def test_una_sola_fuente_montserrat_sin_mono_ni_mayusculas_con_espaciado_ni_hex_sueltos_en_el_bloque_nuevo():
    s = html()
    assert "--fuente:'Montserrat'" in s and 'family=Montserrat' in s and 'DM+Mono' not in s and 'family=Figtree' not in s
    bloque = s[s.index('<style id="estetica-tienda-web">'):s.index('</style>', s.index('<style id="estetica-tienda-web">'))]
    assert not re.findall(r'#[0-9A-Fa-f]{3,8}\b', bloque), 'el bloque nuevo solo usa tokens'
    assert 'var(--fuente)!important' in bloque and 'text-transform:none!important' in bloque
    assert 'dashboard' in s[s.index('const PAGINAS_ESTILO_NUEVO'):][:120]


def test_los_graficos_leen_los_colores_del_sistema():
    s = html()
    i0, i1 = s.index('function mapVentaTacticaOut'), s.index('function renderBrasil')
    assert not re.findall(r"'#[0-9a-fA-F]{6}[0-9a-fA-F]{0,2}'", s[i0:i1])
    assert "PALETTE=[1,2,3,4,5,6,7,8,9,10,11,12].map(i=>cssv('--grafico-'+i))" in s
