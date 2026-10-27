"""Etapa A de Competidores ML: el panel de parámetros de margen vive en Análisis de Competencia (que ya no depende de la pantalla de Competidores)."""
import re

from test_front_analisis import INDEX


def pagina(s, nombre):
    i = s.index(f'<div id="page-{nombre}" class="page"')
    m = re.search(r'<div id="page-[a-z0-9-]+" class="page"', s[i + 10:])
    return s[i:i + 10 + m.start()]


def test_competidores_ml_esta_retirado_y_el_panel_de_parametros_ya_no_existe():
    s = open(INDEX, encoding='utf-8').read()
    an = pagina(s, 'analisis-competencia')
    assert 'id="page-competidores"' not in s and 'data-page="competidores"' not in s           # sin página y sin menú
    assert "if(page==='competidores'){page='analisis-competencia'" in s                         # su link viejo abre Análisis
    for fn in ("renderCompetidores", "loadCompetidores", "compModEcom", "compRefreshHistorial"):
        assert fn not in s, fn                                                                  # y no quedó código colgando
    for i in ("cfg-com", "cfg-iibb", "cfg-impch", "cfg-envio"):
        assert f'id="{i}"' not in s, i                                                          # ya no hay paneles de parámetros: los criterios viven en su página
    assert 'id="comp-criterios-txt"' in an and 'id="ac-tc"' in an and "irACriterios()" in an    # queda el resumen, el link y el TC


def test_los_criterios_de_ml_vienen_de_una_sola_fuente():
    s = open(INDEX, encoding='utf-8').read()
    assert "fetch(`${bu}/criterios/ml`)" in s and "function cargarTablasML(force){return criteriosMlCargar(force);}" in s
    assert "function cargarCostoFijoML(force){return criteriosMlCargar(force);}" in s and "function cargarCuotasML(force){return criteriosMlCargar(force);}" in s
    assert "comPct:CRIT_ML.comision,iibbPct:CRIT_ML.iibb,chequePct:CRIT_ML.cheque" in s          # Análisis calcula con los criterios
    assert "OFM.comisionGeneral=d.comision;OFM.iibbPct=d.iibb;OFM.impChequePct=d.cheque" in s    # y Ofertas ML también
    assert "ML_COSTO_ORDEN=d.orden" in s
    assert 'id="ofm-panel" class="cr-resumen"' in s and "OFM_CFG_VERSION=4" in s                 # el panel de Ofertas es solo un resumen (TC, umbral y tachado)


def test_cambiar_el_tc_o_los_criterios_vuelve_a_dibujar_la_pantalla_y_el_resumen():
    s = open(INDEX, encoding='utf-8').read()
    assert "function compParamResumen()" in s and 'compParamResumen();' in s[s.index('function acRender(){'):s.index('function acRender(){') + 160]
    assert "criteriosMlRefrescarPantallas" in s and "acRender()" in s.split("function criteriosMlRefrescarPantallas")[1][:400]
