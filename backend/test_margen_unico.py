"""Margen único de Mercado Libre: Ofertas ML, Análisis de Competencia y el backend (`ml_ofertas.calcular_margen_oferta`) dan el MISMO margen (decisión de Maxi, 27/10)."""
import json
import shutil
import subprocess
from decimal import Decimal as D

import pytest

import ml_ofertas as mo
from test_front_jugar import INDEX, pm

pytestmark = pytest.mark.skipif(not shutil.which('node'), reason='sin node')
FUNS = ('cfgN', 'ofmPorTramo', 'mlEnvioRegla', 'mlMargenUnico', 'ofmMargenAt')
CASOS = [(9000, 1.21, 3000, None), (20000, 1.21, 8000, 6), (28000, 1.105, 12000, 3), (33000, 1.21, 15000, None), (80000, 1.105, 40000, 12)]


def _js_ofm(casos, orden=True, envio_real=None):
    src = open(INDEX, encoding='utf-8').read()
    fns = '\n'.join(pm.extraer_funcion(src, n) for n in FUNS)
    tramos = [[None if t is None else float(t), float(m)] for t, m in mo.COSTO_FIJO_TRAMOS_DEFAULT]
    cuotas = {int(k): float(v) for k, v in mo.CUOTAS_PCT_DEFAULT.items()}
    js = (f"global.qs=()=>null;global.S={{shippingThreshold:33000}};const ML_COSTO_ORDEN=149.12;const ML_COSTO_FIJO={{tramos:{json.dumps([[t, m] for t, m in tramos])}}};"
          f"const ML_CUOTAS={{planes:{json.dumps(cuotas)}}};const OFM={{comisionGeneral:15.5,iibbPct:5,impChequePct:1.2,usarComision:true,usarCostoFijo:true,usarCuotas:true,usarEnvio:true,usarImpCheque:true,usarIibb:true,usarOrden:{str(orden).lower()}}};\n"
          + fns + f"\nconsole.log(JSON.stringify({json.dumps(casos)}.map(c=>ofmMargenAt(c[0],c[1],c[2],null,c[3],{json.dumps(envio_real)}).margen)));")
    return json.loads(subprocess.run(['node', '-e', js], capture_output=True, text=True, check=True).stdout)


def _py(caso, **kw):
    precio, iva, costo, cuotas = caso
    return float(mo.calcular_margen_oferta(D(str(precio)), D(str(iva)), D(costo), None, cuotas, mo.ParametrosMargen(**kw), envio_real=kw.pop('envio_real', None)).margen)


def test_ofertas_js_da_el_mismo_margen_que_el_backend():
    for js, caso in zip(_js_ofm(CASOS), CASOS):
        assert abs(js - _py(caso)) < 0.01, caso


def test_el_costo_por_orden_baja_el_margen_en_149_12_y_se_puede_apagar():
    con, sin = _js_ofm(CASOS), _js_ofm(CASOS, orden=False)
    for c, s in zip(con, sin):
        assert abs((s - c) - 149.12) < 1e-6


def test_con_el_envio_real_se_usa_ese_y_no_la_regla():
    regla, real = _js_ofm(CASOS), _js_ofm(CASOS, envio_real=6123)
    for caso, r0, r1 in zip(CASOS, regla, real):
        esperado = 8500 if caso[0] >= 33000 else 0
        assert abs((r0 - r1) - (6123 - esperado)) < 1e-6
