"""3.2 Histórico por SKU (docs/index.html: acHist*): serie por competidor, último cambio y eventos. Lógica y HTML extraídos del HTML y corridos en node
con datos SINTÉTICOS; se saltea sin node."""
import json
import re
import shutil
import subprocess

import pytest

from test_front_analisis import INDEX, _fn

pytestmark = pytest.mark.skipif(not shutil.which('node'), reason='sin node')
FUNS = ('acIsoMas', 'acHistHoy', 'acHistSeries', 'acHistCambio', 'acHistEventos', 'acHistSvg', 'acHistHtml', 'acHistFilaHtml', 'acEsc', 'acFechaCorta', 'fmt$')
HOY = '2026-10-20'


def _src():
    s = open(INDEX, encoding='utf-8').read()
    consts = [re.search(p, s).group(0) for p in (r"const AC_HIST_COLORES=\[.*?\];", r"const AC_EV_TXT=\{.*?\};")]
    return '\n'.join(_fn(s, n) for n in FUNS) + '\n' + '\n'.join(consts)


def js(cuerpo, datos):
    codigo = _src() + "\nconst X=JSON.parse(process.argv[1]);\nglobal.normSku=s=>String(s||'').trim().toLowerCase();\n" + cuerpo
    return json.loads(subprocess.run(['node', '-e', codigo, json.dumps(datos)], capture_output=True, text=True, check=True).stdout)


def r(i, ent, rol, serie, cant=1, ant=None, desde=None, precio=None):
    return {'id': i, 'sku': 'PV-1', 'entidad': ent, 'rol': rol, 'cantidad': cant, 'serie': serie, 'precio': precio if precio is not None else (serie[-1][1] if serie else None),
            'ultimo': {'fecha': serie[-1][0], 'precio': serie[-1][1]} if serie else None,
            'anterior': {'fecha': '2026-10-18', 'precio': ant} if ant else None, 'desde': desde,
            'delta_pct': round((serie[-1][1] - ant) / ant * 100, 2) if ant and serie else None,
            'ultima_lectura': {'fecha': serie[-1][0], 'estado': 'OK', 'dias': 0} if serie else None}


A = r('A', 'GEOTEK', 'Rey', [['2026-08-01', 1000], ['2026-10-05', 900], ['2026-10-18', 800], ['2026-10-20', 800]], ant=900, desde='2026-10-18')
B = r('B', 'TECNO', 'Barato', [['2026-10-19', 1200]], cant=2)          # kit ×2 de 1.200 = 600 por unidad


def test_series_ventana_ancla_el_precio_vigente_y_usa_precio_por_unidad():
    s = js("console.log(JSON.stringify([acHistSeries(X.refs,7,X.hoy),acHistSeries(X.refs,90,X.hoy),acHistHoy({referencias:X.refs})]))", {'refs': [A, B], 'hoy': HOY})
    s7, s90, hoy = s
    a7 = next(x for x in s7 if x['id'] == 'A')
    assert a7['pasos'][0] == ['2026-10-13', 900] and a7['reales'] == [['2026-10-18', 800], ['2026-10-20', 800]]   # el 900 de la lectura del 5/10 sigue vigente al inicio
    assert next(x for x in s7 if x['id'] == 'B')['pasos'] == [['2026-10-19', 600]]                              # por unidad
    assert len(next(x for x in s90 if x['id'] == 'A')['reales']) == 4 and hoy == '2026-10-20'


def test_referencia_sin_serie_no_aparece():
    s = js("console.log(JSON.stringify(acHistSeries(X.refs,30,X.hoy)))", {'refs': [r('Z', 'X', 'Rey', [])], 'hoy': HOY})
    assert s == []


def test_ultimo_cambio_y_eventos_del_sku():
    out = js("console.log(JSON.stringify([acHistCambio(X.a),acHistCambio(X.b),acHistEventos(X.D,'pv-1',30,X.hoy,normSku)]))",
             {'a': A, 'b': B, 'hoy': HOY, 'D': {'eventos': [
                 {'fecha': '2026-10-18', 'sku': 'PV-1', 'tipo': 'Bajo'}, {'fecha': '2026-10-18', 'sku': 'PV-2', 'tipo': 'Bajo'},
                 {'fecha': '2026-08-01', 'sku': 'PV-1', 'tipo': 'Subio'}]}})
    assert out[0] == {'fecha': '2026-10-18', 'de': 900, 'a': 800, 'pct': -11.11} and out[1] is None
    assert [e['fecha'] for e in out[2]] == ['2026-10-18'] and out[2][0]['sku'] == 'PV-1'      # otro SKU y fuera de ventana quedan afuera


def test_svg_escalon_puntos_y_linea_del_pm():
    svg = js("console.log(JSON.stringify(acHistSvg(acHistSeries(X.refs,30,X.hoy),X.pm,30,X.hoy)))", {'refs': [A, B], 'hoy': HOY, 'pm': 1000})
    assert svg.startswith('<svg') and svg.count('<path') == 2 and svg.count('<circle') == 3 + 1    # A: 3 lecturas en 30 d, B: 1
    assert 'stroke-dasharray' in svg and ' V' in svg and 'NaN' not in svg
    sin = js("console.log(JSON.stringify(acHistSvg([],0,30,X.hoy)))", {'hoy': HOY})
    assert sin == ''


def test_html_completo_con_cambio_eventos_y_sin_datos():
    D = {'referencias': [A, B], 'eventos': [{'fecha': '2026-10-18', 'sku': 'PV-1', 'tipo': 'Bajo', 'entidad': 'GEOTEK', 'anterior': 900, 'nuevo': 800}]}
    h = js("global.AC={data:X.D,histAb:{'pv-1':30},keys:['pv-1']};const f={key:'pv-1',sku:'PV-1',pmML:1000,refs:X.D.referencias};global.acFilaCompleta=()=>f;"
           "console.log(JSON.stringify([acHistHtml(f,30),acHistFilaHtml(f),acHistHtml(f,7)]))", {'D': D})
    assert 'GEOTEK' in h[0] and '▼ 11.1%' in h[0] and '▼ Bajó' in h[0] and 'acHistDias(0,7)' in h[0] and '×2' in h[0]
    assert h[1].startswith('<tr class="ac-ctx-row">') and '<svg' in h[1]
    assert h[2].count('<svg') == 1
    vacio = js("global.AC={data:{referencias:[],eventos:[]},histAb:{},keys:[]};const f={key:'k',sku:'K',pmML:0,refs:[]};console.log(JSON.stringify([acHistHtml(f,30),acHistFilaHtml(f)]))", {})
    assert 'Sin lecturas con precio' in vacio[0] and 'Sin eventos' in vacio[0] and vacio[1] == ''
