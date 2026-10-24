"""Botón de la barra lateral (docs/index.html: sbEstado y el HTML del botón): aria-expanded / etiqueta según el ancho, y que el botón sea accesible. Node, sin datos; se saltea sin node."""
import json
import re
import shutil
import subprocess

import pytest

from test_front_analisis import INDEX, _fn

pytestmark = pytest.mark.skipif(not shutil.which('node'), reason='sin node')


def estado(angosto, oculta, abierta):
    s = open(INDEX, encoding='utf-8').read()
    js = _fn(s, 'sbEstado') + f"\nconsole.log(JSON.stringify(sbEstado({json.dumps(angosto)},{json.dumps(oculta)},{json.dumps(abierta)})));"
    return json.loads(subprocess.run(['node', '-e', js], capture_output=True, text=True, check=True).stdout)


def test_escritorio_expandido_si_no_esta_oculto():
    assert estado(False, False, False) == {'expandido': True, 'etiqueta': 'Ocultar el menú de módulos'}
    assert estado(False, True, False) == {'expandido': False, 'etiqueta': 'Mostrar el menú de módulos'}
    assert estado(False, True, True)['expandido'] is False                 # en escritorio manda «oculto», no «abierto»


def test_pantalla_angosta_expandido_si_esta_abierto():
    assert estado(True, False, False) == {'expandido': False, 'etiqueta': 'Mostrar el menú de módulos'}
    assert estado(True, False, True) == {'expandido': True, 'etiqueta': 'Ocultar el menú de módulos'}
    assert estado(True, True, True)['expandido'] is True                   # la preferencia de escritorio no pesa en pantalla angosta


def test_el_boton_es_un_button_con_aria_controls_expanded_y_nombre():
    s = open(INDEX, encoding='utf-8').read()
    b = re.search(r'<button[^>]*id="menu-toggle"[^>]*>', s).group(0)
    assert b.startswith('<button type="button"') and 'aria-controls="sidebar"' in b and 'aria-expanded="true"' in b and 'aria-label="Ocultar el menú de módulos"' in b
    assert 'id="sidebar"' in s and s.count('id="menu-toggle"') == 1       # el botón apunta a un elemento que existe; hay un solo botón (el mismo en ancho y angosto)


def test_la_eleccion_se_guarda_y_se_aplica_antes_de_pintar_sin_romper_si_el_storage_falla():
    s = open(INDEX, encoding='utf-8').read()
    assert "localStorage.getItem('erp_sidebar_oculta')==='1')document.body.classList.add('sb-oculta')" in s
    pre = s[s.index('<body>'):s.index('<header class="topbar">')]
    assert 'try{' in pre and 'catch(e){}' in pre                           # el script de arranque tolera localStorage bloqueado
    assert "try{localStorage.setItem(SB_KEY" in s
