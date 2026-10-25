"""Estilo «tienda web», PR 3: Inteligencia Comercial, Compras (Proyección 2027), Distribución y Sistema (solo presentación)."""
import re

from test_front_analisis import INDEX


def html():
    return open(INDEX, encoding='utf-8').read()


def test_las_ocho_paginas_estan_en_el_estilo_nuevo():
    s = html()
    lista = s[s.index('const PAGINAS_ESTILO_NUEVO'):][:420]
    for p in ('intel-entidades', 'intel-referencias', 'intel-mix', 'distribucion', 'proyeccion', 'config', 'reglas', 'mltools'):
        assert f"'{p}'" in lista, p


def test_la_proyeccion_se_monta_en_claro_y_sus_graficos_leen_los_colores_del_sistema():
    s = html()
    assert "ProyeccionDashboard.mount(root,d,{theme:'light'})" in s and "theme:'dark'" not in s
    j = open(INDEX.replace('index.html', 'proyeccion_dashboard.js'), encoding='utf-8').read()
    assert "cv('--pd-g1'" in j and 'C.ac' in j
    cuerpo = j[j.index('var C = {'):]
    assert not re.findall(r"color: '#[0-9a-fA-F]{3,6}'", cuerpo[cuerpo.index('\n'):]), 'los gráficos no llevan hex sueltos (solo el respaldo de C)'
    assert "--pd-g1:var(--grafico-1)" in s


def test_el_bloque_del_pr3_sigue_sin_hex_y_conserva_los_ids():
    s = html()
    bloque = s[s.index('<style id="estetica-tienda-web">'):s.index('</style>', s.index('<style id="estetica-tienda-web">'))]
    assert not re.findall(r'#[0-9A-Fa-f]{3,8}\b', bloque) and 'PR 3: Inteligencia Comercial' in bloque
    for id_ in ('mix-input', 'btn-mix-procesar', 'mix-table-wrap', 'distribucion-stats-wrap', 'proy-root', 'entidades-table-wrap'):
        assert s.count(f'id="{id_}"') == 1, id_
    mix = s[s.index('id="page-intel-mix"'):s.index('id="page-distribucion"')]
    assert mix.count('<div') == mix.count('</div>')
