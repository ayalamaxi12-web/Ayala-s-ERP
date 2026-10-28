"""Campañas ML con propuestas de ML (docs/index.html): filtros por PM/categoría/ticket/participación. Lógica pura en node."""
import json
import shutil
import subprocess

import pytest

from test_front_analisis import INDEX, _fn

pytestmark = pytest.mark.skipif(not shutil.which('node'), reason='sin node')

FILAS = [
    {'fila': 6, 'sku': 'A', 'item_id': 'MLA1', 'pm': 'Veronica', 'categoria': 'Insumo', 'precio_cliente': 9000, 'participa': True},
    {'fila': 7, 'sku': 'B', 'item_id': 'MLA2', 'pm': 'Laura', 'categoria': 'Cocina', 'precio_cliente': 25000, 'participa': True},
    {'fila': 8, 'sku': 'C', 'item_id': 'MLA3', 'pm': 'Veronica', 'categoria': 'Insumo', 'precio_cliente': 60000, 'participa': False},
]


def filtrar(fl):
    src = open(INDEX, encoding='utf-8').read()
    cuerpo = (_fn(src, 'cpModificada') + '\n' + _fn(src, 'cpMargen') + '\n' + _fn(src, 'cpFiltrar') +
              f"\nconsole.log(JSON.stringify(cpFiltrar({json.dumps(FILAS)},{json.dumps(fl)},{{}}).map(f=>f.fila)))")
    return json.loads(subprocess.run(['node', '-e', cuerpo], capture_output=True, text=True, check=True).stdout)


def test_filtros_por_pm_categoria_participacion_y_ticket():
    assert filtrar({}) == [6, 7, 8]
    assert filtrar({'pm': 'Veronica'}) == [6, 8]
    assert filtrar({'cat': 'Cocina'}) == [7]
    assert filtrar({'part': 'si'}) == [6, 7] and filtrar({'part': 'no'}) == [8]
    assert filtrar({'pmin': 10000, 'pmax': 30000}) == [7]                     # ticket por precio final
    assert filtrar({'pm': 'Veronica', 'part': 'si', 'pmax': 9500}) == [6]
