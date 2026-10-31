"""Reglas de precio del Cyber (docs/index.html: cyberDecidirPrecio): la lógica REAL de la página corrida en node con filas sintéticas. Se saltea sin node."""
import json
import os
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scripts'))
import paridad_margenes as pm  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which('node'), reason='sin node')
SRC = open(pm.INDEX, encoding='utf-8').read()
FUNS = '\n'.join(pm.extraer_funcion(SRC, n) for n in ('cpTramoFijo', 'cpMargenLocal', 'cyberReglas', 'cyberGrupo', 'cyberMargenA', 'cyberPrecioParaMargen', 'cyberDecidirPrecio'))
# Criterios de ML vigentes: comisión 15,5 %, cuotas (3: 8,5 %), cheque 1,2 %, IIBB 5 %, costo fijo por tramo, envío desde $33.000 por precio de lista
M = {'iva_cargos': 0, 'comision': 0.155, 'cheque': 0.012, 'iibb': 0.05, 'umbral_envio': 33000, 'cuotas': {'3': 0.085, '6': 0.129},
     'tramos_costo_fijo': [{'desde': 0, 'hasta': 15000, 'valor': 1330}, {'desde': 15000, 'hasta': 24000, 'valor': 2740}, {'desde': 24000, 'hasta': 33000, 'valor': 3320}, {'desde': 33000, 'hasta': None, 'valor': 0}]}


def decidir(fila, rango=None, otro=None):
    js = ("const f=JSON.parse(process.argv[1]);const ctx=JSON.parse(process.argv[2]);" + FUNS +
          "\nconst r=cyberDecidirPrecio(f,ctx);r.margen_check=f.calc?cyberMargenA(f,ctx.M,ctx.tc,'3',r.precio):null;"
          "r.margen_un_peso_menos=f.calc?cyberMargenA(f,ctx.M,ctx.tc,'3',r.precio-1):null;console.log(JSON.stringify(r));")
    return json.loads(subprocess.run(['node', '-e', js, json.dumps(fila), json.dumps({'M': M, 'tc': 1500, 'rango': rango, 'otro': otro})], capture_output=True, text=True, check=True).stdout)


def fila(orig=100000, prop=80000, pm_=None, clase='MEDIO', costo=40000, calc=True):
    return {'precio_original': orig, '_prop': prop, 'precio_cliente': prop, 'precio_pm': pm_, 'clase': clase, 'meli_monto': 0,
            'calc': {'costo': costo, 'costo_usd': None, 'iva': 1.21, 'envio': 0, 'comision': 0.155} if calc else None}


def test_la_propuesta_de_ml_se_toma_tal_cual_si_la_publicacion_no_esta_sobre_el_pm():
    r = decidir(fila(pm_=100000, costo=20000))           # publicación = PM
    assert r['precio'] == 80000 and r['estado'] == 'ok' and r['regla'] == 'Propuesta de ML' and r['grupo'] == 'medio' and r['participa']
    assert decidir(fila(pm_=120000, costo=20000))['precio'] == 80000   # publicación MÁS BARATA que el PM: directo el de ML


def test_si_la_publicacion_esta_sobre_el_pm_se_parte_del_pm_con_el_descuento_de_ml_mas_5_puntos():
    r = decidir(fila(orig=100000, prop=80000, pm_=80000, costo=20000))     # ML sugiere 20 %: 80.000 × (1 − 25 %) = 60.000
    assert r['precio'] == 60000 and 'Publicación sobre el PM' in r['regla'] and r['estado'] == 'ok'


def test_liquidar_va_al_precio_de_ml_sin_piso_aunque_quede_bajo_el_costo():
    r = decidir(fila(prop=30000, costo=60000, clase='REVENTAR'))
    assert r['precio'] == 30000 and r['grupo'] == 'liquidar' and r['margen'] < 0 and r['estado'] == 'ok' and r['participa']


def test_medio_sube_al_piso_de_10_por_ciento_en_3_cuotas_y_ni_un_peso_menos():
    r = decidir(fila(prop=60000, costo=45000))            # a $60.000 el margen en 3 cuotas queda bajo 10 %
    assert r['estado'] == 'sube_a_piso' and r['piso'] == 10 and r['precio'] > 60000
    assert r['margen_check'] >= 10 and r['margen_un_peso_menos'] < 10


def test_rey_exige_20_por_ciento_y_si_no_se_alcanza_baja_a_18_y_si_tampoco_no_participa():
    r = decidir(fila(prop=70000, costo=25000, clase='REY'))
    assert r['grupo'] == 'rey' and r['piso'] == 20 and r['margen_check'] >= 20
    alt = decidir(fila(prop=70000, costo=25000, clase='REY'), rango={'min': 50000, 'max': 62000})     # con ese tope el 20 % no se alcanza
    assert alt['piso'] in (18, 20) and (alt['estado'] != 'no_participa' or alt['piso'] == 20)
    no = decidir(fila(prop=70000, costo=60000, clase='REY'), rango={'min': 50000, 'max': 70000})
    assert no['estado'] == 'no_participa' and not no['participa'] and 'OK de Maxx' in no['regla']


def test_medio_de_ticket_alto_usa_5_por_ciento_de_piso():
    r = decidir(fila(orig=200000, prop=170000, costo=60000))
    assert r['piso'] == 5 and r['margen_check'] >= 5


def test_bajar_mas_de_lo_que_ml_permite_va_al_minimo_en_liquidar_y_medio_pero_no_en_reyes():
    medio = decidir(fila(orig=100000, prop=40000, costo=10000), rango={'min': 55000, 'max': 90000})
    assert medio['precio'] == 55000 and medio['estado'] == 'tope_ml' and medio['participa']
    liq = decidir(fila(orig=100000, prop=40000, costo=10000, clase='REVENTAR'), rango={'min': 55000, 'max': 90000})
    assert liq['precio'] == 55000 and liq['estado'] == 'tope_ml'
    rey = decidir(fila(orig=100000, prop=40000, costo=10000, clase='REY'), rango={'min': 55000, 'max': 90000})
    assert rey['estado'] == 'no_participa' and not rey['participa'] and 'revisalo vos' in rey['regla']


def test_sin_costo_el_precio_actual_menos_10_por_ciento_dentro_del_rango_de_ml():
    r = decidir(fila(calc=False))
    assert r['precio'] == 90000 and r['estado'] == 'sin_costo' and r['margen'] is None and r['participa']
    assert decidir(fila(calc=False), rango={'min': 92000, 'max': 99000})['precio'] == 92000       # no baja más de lo que ML permite


def test_mismo_precio_en_las_dos_cuentas_se_toma_el_mas_alto_dentro_del_rango():
    r = decidir(fila(prop=80000, costo=20000), otro=85000)
    assert r['precio'] == 85000 and 'igualado' in r['regla']
    assert decidir(fila(prop=80000, costo=20000), otro=70000)['precio'] == 80000                    # el de la otra cuenta es más bajo: queda el propio
    assert decidir(fila(prop=80000, costo=20000), rango={'min': 50000, 'max': 82000}, otro=95000)['precio'] == 82000   # respeta el máximo de ML


def test_si_no_llega_al_piso_entra_con_pm_menos_3_por_ciento_tambien_los_reyes():
    for clase in ('REY', 'MEDIO'):
        r = decidir(fila(prop=70000, costo=90000, clase=clase, pm_=100000), rango={'min': 50000, 'max': 100000})
        assert r['estado'] == 'piso_pm' and r['precio'] == 97000 and r['participa'], clase


def test_pm_menos_3_respeta_el_rango_de_ml_y_sin_pm_sigue_sin_participar():
    r = decidir(fila(prop=70000, costo=90000, clase='REY', pm_=100000), rango={'min': 50000, 'max': 90000})
    assert r['estado'] == 'piso_pm' and r['precio'] == 90000 and 'ajustado al rango' in r['regla']
    assert decidir(fila(prop=70000, costo=90000, clase='REY', pm_=None), rango={'min': 50000, 'max': 100000})['estado'] == 'no_participa'
