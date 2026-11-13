"""Filtro «Aging» de Ventas & Rentabilidad (docs/index.html): antigüedad de la venta = días desde su fecha hasta hoy, en tramos."""
import json
import os
import re
import shutil
import subprocess

import pytest

from scripts.paridad_margenes import extraer_funcion

INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'docs', 'index.html')
pytestmark = pytest.mark.skipif(not shutil.which('node'), reason='sin node')


def js(cuerpo, datos):
    src = open(INDEX, encoding='utf-8').read()
    tramos = re.search(r'^const AGING_TRAMOS=.*$', src, re.M).group(0)
    cod = tramos + '\n' + '\n'.join(extraer_funcion(src, n) for n in ('agingHoy', 'agingDias', 'agingTramoDe')) + '\nconst D=JSON.parse(process.argv[1]);\n' + cuerpo
    return json.loads(subprocess.run(['node', '-e', cod, json.dumps(datos)], capture_output=True, text=True, check=True).stdout)


HOY = '2026-11-13'


def test_tramos_en_los_bordes():
    casos = {'2026-11-13': '0-7 días', '2026-11-06': '0-7 días', '2026-11-05': '8-15 días', '2026-10-29': '8-15 días', '2026-10-28': '16-30 días',
             '2026-10-14': '16-30 días', '2026-10-13': '31-60 días', '2026-09-14': '31-60 días', '2026-09-13': '61-90 días', '2026-08-15': '61-90 días',
             '2026-08-14': 'Más de 90 días', '2025-01-01': 'Más de 90 días'}
    r = js('console.log(JSON.stringify(Object.keys(D.c).map(f=>agingTramoDe(f,D.h))))', {'c': casos, 'h': HOY})
    assert r == list(casos.values())


def test_dias_hora_en_la_fecha_futuras_y_vacias():
    r = js('console.log(JSON.stringify([agingDias("2026-11-10 15:30:00",D.h),agingDias("2026-11-20",D.h),agingTramoDe("2026-11-20",D.h),agingTramoDe("",D.h),agingTramoDe(null,D.h),agingTramoDe("basura",D.h)]))', {'h': HOY})
    assert r == [3, 0, '0-7 días', None, None, None]                                   # con hora se toma solo el día; futuras = 0; sin fecha no entra en ningún tramo


def test_los_tramos_quedan_en_orden_y_cubren_todo():
    r = js('console.log(JSON.stringify(AGING_TRAMOS.map(t=>t[0])))', {})
    assert r == ['0-7 días', '8-15 días', '16-30 días', '31-60 días', '61-90 días', 'Más de 90 días']


def test_agingHoy_es_una_fecha_aaaa_mm_dd():
    r = js('console.log(JSON.stringify(agingHoy()))', {})
    assert re.match(r'^\d{4}-\d{2}-\d{2}$', r)
