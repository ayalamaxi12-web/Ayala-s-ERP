"""Etapa A de Competidores ML: el panel de parámetros de margen vive en Análisis de Competencia (que ya no depende de la pantalla de Competidores)."""
import re

from test_front_analisis import INDEX


def pagina(s, nombre):
    i = s.index(f'<div id="page-{nombre}" class="page"')
    m = re.search(r'<div id="page-[a-z0-9-]+" class="page"', s[i + 10:])
    return s[i:i + 10 + m.start()]


IDS_PANEL = ('cfg-com', 'cfg-iibb', 'cfg-impch', 'cfg-envio', 'comp-costo-fijo-ml', 'comp-cuotas-ml', 'ac-tc', 'comp-desc-panel')


def test_competidores_ml_esta_retirado_y_los_campos_del_panel_viven_en_analisis():
    s = open(INDEX, encoding='utf-8').read()
    an = pagina(s, 'analisis-competencia')
    assert 'id="page-competidores"' not in s and 'data-page="competidores"' not in s           # sin página y sin menú
    assert "if(page==='competidores'){page='analisis-competencia'" in s                         # su link viejo abre Análisis
    for fn in ("renderCompetidores", "loadCompetidores", "compModEcom", "compRefreshHistorial"):
        assert fn not in s, fn                                                                  # y no quedó código colgando
    for i in IDS_PANEL:
        assert f'id="{i}"' in an, i
    assert 'type="checkbox" checked onchange="COMPDESC.com=this.checked' in an
    assert 'id="comp-tc"' not in s                                                              # un solo TC: el del panel (ac-tc)


def test_cambiar_un_parametro_vuelve_a_dibujar_la_pantalla_y_el_resumen():
    s = open(INDEX, encoding='utf-8').read()
    panel = pagina(s, 'analisis-competencia')
    panel = panel[panel.index('id="comp-desc-panel"'):panel.index('id="ac-filtros"')]
    assert panel.count('acRender()') >= 9                                                      # 5 campos + 6 casillas: todas redibujan
    assert "function compParamResumen()" in s and 'compParamResumen();' in s[s.index('function acRender(){'):s.index('function acRender(){') + 160]
