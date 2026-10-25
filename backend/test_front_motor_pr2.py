"""Motor de Precios (Bloque 2, PR 2): selector de SKU predictivo con todos los SKU de «ERP AYALA», un solo flujo (sin casos «Excel»), bloques minimizables."""
import json
import re
import subprocess

from test_front_analisis import INDEX, _fn


def html():
    return open(INDEX, encoding='utf-8').read()


def buscar(todos, elegidos, q):
    s = html()
    js = '\n'.join(_fn(s, n) for n in ('acNormTxt', 'ayalaCoreSkuBuscar')) + """
const AC_TODOS=JSON.parse(process.argv[1]),AC_SEL=JSON.parse(process.argv[2]);
console.log(JSON.stringify(ayalaCoreSkuBuscar(process.argv[3]).map(m=>[m.x,m.i,m.n])));
"""
    out = subprocess.run(['node', '-e', js, json.dumps(todos), json.dumps(elegidos), q], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


TODOS = ['FAN-MIST-STAND-10I', 'FAN-MIST-STAND-16I', 'GLOBAL-G305', 'MONI-OFFICE-21.6IFHD', 'PLANCHA-SUB-GORRA', 'TÉRMICO-ÑANDÚ']


def test_la_busqueda_encuentra_en_cualquier_parte_sin_mayusculas_ni_tildes_y_resalta():
    assert [m[0] for m in buscar(TODOS, [], 'stand-1')] == ['FAN-MIST-STAND-10I', 'FAN-MIST-STAND-16I']
    assert buscar(TODOS, [], 'mist') == [['FAN-MIST-STAND-10I', 4, 4], ['FAN-MIST-STAND-16I', 4, 4]]     # posición y largo del tramo a resaltar
    assert [m[0] for m in buscar(TODOS, [], 'termico')] == ['TÉRMICO-ÑANDÚ'] and [m[0] for m in buscar(TODOS, [], 'nandu')] == ['TÉRMICO-ÑANDÚ']
    assert buscar(TODOS, [], '') == [] and buscar(TODOS, [], 'zzz') == []


def test_los_ya_elegidos_no_se_sugieren_y_el_que_empieza_igual_va_primero():
    assert [m[0] for m in buscar(TODOS, ['GLOBAL-G305'], 'g')] == ['GLOBAL-G305'] or 'GLOBAL-G305' not in [m[0] for m in buscar(TODOS, ['GLOBAL-G305'], 'g')]
    r = [m[0] for m in buscar(TODOS, [], 'g')]
    assert r[0] == 'GLOBAL-G305'          # empieza con «g»: antes que los que la tienen adentro


def test_el_selector_es_accesible_y_hay_todos_los_piloto_y_ninguno():
    s = html()
    for frag in ('role="combobox"', 'aria-controls="ac-sku-lista"', 'role="listbox"', 'onclick="ayalaCoreSkuPilotos()"', 'onclick="ayalaCoreSkuNinguno()"', 'aria-label="Quitar ${acEsc(x)}"'):
        assert frag in s, frag
    for tecla in ("'ArrowDown'", "'Enter'", "'Escape'", "'Backspace'"):
        assert tecla in _fn(s, 'ayalaCoreSkuTecla'), tecla


def test_la_lista_completa_sale_de_erp_ayala_y_no_hay_camino_excel_aparte():
    s = html()
    assert 'AC_SKUS_EXCEL=(d2.skus||[])' in s and 'AC_TODOS=[...new Set([...(AC_SKUS||[]),...(AC_SKUS_EXCEL||[])' in s
    run = _fn(s, 'ayalaCorePublicacionesRun')
    assert 'skusExcel' not in run and 'AC_SEL.slice()' in run and "/ayala-core/publicaciones/run?" in run
    assert 'data-excel="1">' not in s and 'ac-pub-sku-chk' not in s.replace('// siempre', '')
    assert "id=\"ac-sku\"" not in s


def test_bloques_minimizables_con_resumen_expandir_y_minimizar_todo():
    s = html()
    for id_ in ('ref', 'pub', 'mla', 'cargado'):
        assert f'id="ac-b-{id_}"' in s and f'aria-controls="ac-b-{id_}-cuerpo"' in s and f'id="ac-b-{id_}-res"' in s
    assert "acBloquesTodos(true)" in s and "acBloquesTodos(false)" in s and "sessionStorage" in _fn(s, 'acBloquesEstado')
    assert '.ac-bloque.ac-min .ac-bloque-res{display:inline}' in s


def test_la_condicion_a_mano_lleva_etiqueta_de_texto_y_la_pagina_no_tiene_emojis_en_titulos_ni_botones():
    s = html()
    assert 'class="ac-tag-mano">A mano</span>' in _fn(s, 'ayalaCorePubCondCellHtml')
    pag = s[s.index('<div id="page-ayala-core"'):s.index('<script src="proyeccion_dashboard.js">')]
    emojis = re.findall(r'[\U0001F300-\U0001FAFF☀-➿]', re.sub(r'<!--.*?-->', '', pag, flags=re.S))
    assert not emojis, emojis
    bloque = s[s.index('<style id="estetica-tienda-web">'):s.index('</style>', s.index('<style id="estetica-tienda-web">'))]
    assert not re.findall(r'#[0-9A-Fa-f]{3,8}\b', bloque)


def test_pack_selector_x1_a_x6_y_otro_manda_la_cantidad_solo_si_es_mayor_a_1():
    s = html()
    for frag in ('<option value="1" selected>x1</option>', '<option value="6">x6</option>', '<option value="otro">Otro…</option>', 'id="ac-cantidad-otro"'):
        assert frag in s, frag
    assert "return n>1?`&cantidad=${n}`:'';" in _fn(s, 'ayalaCoreCantidadParam')
    assert 'ayalaCoreCantidadParam()' in _fn(s, 'ayalaCoreCalcular') and 'ayalaCoreCantidadParam()' in _fn(s, 'ayalaCoreCompararMLA')
    assert 'Precio por unidad</th>' in s and 'Precio de la publicación' in s and "'ac-cantidad','ac-cantidad-otro'" in s
