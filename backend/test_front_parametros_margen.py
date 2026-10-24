"""Etapa A de Competidores ML: el panel de parámetros de margen vive en Análisis de Competencia (que ya no depende de la pantalla de Competidores)."""
import re

from test_front_analisis import INDEX


def pagina(s, nombre):
    i = s.index(f'<div id="page-{nombre}" class="page"')
    m = re.search(r'<div id="page-[a-z0-9-]+" class="page"', s[i + 10:])
    return s[i:i + 10 + m.start()]


IDS_PANEL = ('cfg-com', 'cfg-iibb', 'cfg-impch', 'cfg-envio', 'comp-costo-fijo-ml', 'comp-cuotas-ml', 'ac-tc', 'comp-desc-panel')


def test_los_campos_del_panel_estan_en_analisis_y_no_en_competidores():
    s = open(INDEX, encoding='utf-8').read()
    an, co = pagina(s, 'analisis-competencia'), pagina(s, 'competidores')
    for i in IDS_PANEL:
        assert f'id="{i}"' in an, i
        assert f'id="{i}"' not in co, i
    assert 'type="checkbox" checked onchange="COMPDESC.com=this.checked' in an and 'COMPDESC.' not in co      # las casillas (comisión, costo fijo, IVA, IIBB, cheque, envío) también se mudaron
    assert 'id="cfg-baja"' in co and 'id="cfg-baja"' not in an                                                # «Baja s/comp.» solo lo usa Competidores
    assert 'id="comp-tc"' not in s                                                                            # un solo TC: el del panel (ac-tc)


def test_cambiar_un_parametro_vuelve_a_dibujar_las_dos_pantallas_y_competidores_lee_el_tc_del_panel():
    s = open(INDEX, encoding='utf-8').read()
    panel = pagina(s, 'analisis-competencia')
    panel = panel[panel.index('id="comp-desc-panel"'):panel.index('id="ac-filtros"')]
    assert panel.count('renderCompetidores();acRender()') >= 9                                                 # 5 campos + 6 casillas: todas llaman a las dos
    assert "qs('ac-tc')" in s[s.index('const tcManual'):s.index('const tcManual') + 160]
    assert "function compParamResumen()" in s and 'compParamResumen();' in s[s.index('function renderCompetidores(){'):s.index('function renderCompetidores(){') + 80]
