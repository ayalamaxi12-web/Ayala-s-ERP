"""Precios de las planillas de los PM (docs/index.html): «9.089» es nueve mil ochenta y nueve pesos, no 9,089."""
import json
import shutil
import subprocess

import pytest

from test_front_analisis import INDEX, _fn

pytestmark = pytest.mark.skipif(not shutil.which('node'), reason='sin node')


def peso(valor):
    src = open(INDEX, encoding='utf-8').read()
    out = subprocess.run(['node', '-e', _fn(src, 'parseNum') + '\n' + _fn(src, 'parsePeso') + f'\nconsole.log(JSON.stringify(parsePeso({json.dumps(valor)})))'],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


@pytest.mark.parametrize('texto,esperado', [
    ('9.089', 9089), ('$9.089', 9089), ('$ 9.089', 9089), ('1.234.567', 1234567), ('9.089,00', 9089), ('$12.119,50', 12119.5),
    ('9089', 9089), ('12119,5', 12119.5), ('', 0), ('-', 0), ('45,5', 45.5), ('12.5', 12.5), ('1.5', 1.5),
])
def test_los_precios_en_pesos_se_leen_bien_con_o_sin_decimales(texto, esperado):
    assert peso(texto) == esperado
