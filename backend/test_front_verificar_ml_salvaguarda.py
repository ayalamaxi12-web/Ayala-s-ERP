"""Salvaguarda de Verificar ML: con la bandera VERIFICAR_ML_ESCRIBE en false no se escribe ningún precio en ML (ni «Corregir todos» ni el ✓ sin precio manual)."""
import re

from test_front_analisis import INDEX


def test_la_bandera_esta_apagada_y_cada_escritura_la_consulta_antes_de_llamar_a_mlput():
    s = open(INDEX, encoding='utf-8').read()
    assert 'const VERIFICAR_ML_ESCRIBE=false' in s
    fix_all = s[s.index('async function fixAllML(){'):s.index('function exportML(')]
    assert fix_all.index('if(!VERIFICAR_ML_ESCRIBE)') < fix_all.index('mlPut(')          # «Corregir todos»: la guarda va antes
    fila = s[s.index("tbody.querySelectorAll('.ml-fix-btn')"):s.index('async function fixAllML(){')]
    assert fila.index('if(!VERIFICAR_ML_ESCRIBE)') < fila.index('mlPut(')                  # ✓ de cada fila
    assert len(re.findall(r'\bmlPut\(', s)) == 3                                          # definición + los dos usos: ningún otro camino escribe


def test_el_cartel_y_el_boton_deshabilitado_se_aplican_al_dibujar_la_tabla():
    s = open(INDEX, encoding='utf-8').read()
    assert 'En revisión: la escritura está desactivada' in s and 'id="ml-revision-aviso"' in s and 'role="status"' in s.split('id="ml-revision-aviso"')[1][:80]
    assert s[s.index('function renderML(){'):].lstrip().split('\n')[1].strip() == 'mlRevisionAplicar();'
