"""Paridad de márgenes: `compMargenAt` (docs/index.html, el que usan Competidores/Ofertas y usará la pantalla nueva) vs el motor oficial
`rentabilidad/motor_precios.precio_a_margen` con los parámetros del seed. Mismo precio, costo e IVA -> mismo margen (CRITERIOS_MARGEN).
Uso (desde backend/):  python scripts/paridad_margenes.py [--tolerancia 0.0001]   (necesita node). Sale con 1 si algún caso difiere."""
import argparse
import json
import os
import re
import subprocess
import sys
from decimal import Decimal

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, '..'))
from rentabilidad import seed  # noqa: E402
from rentabilidad.motor_precios import EntradaMotor, ParametrosMotor, Tramo, precio_a_margen, tramos_costo_fijo_ml  # noqa: E402

INDEX = os.path.join(AQUI, '..', '..', 'docs', 'index.html')
PRECIOS = [5000, 15999, 16000, 23999, 24000, 32999, 33000, 45000, 120000, 300000]
CASOS_IVA_COSTO = [(1.21, 0.55), (1.105, 0.55), (1.21, 0.85)]   # (iva, costo como fracción del neto)


def extraer_funcion(src, nombre):
    i = src.index(f'function {nombre}(')
    j = src.index('{', i)
    n = 0
    for k in range(j, len(src)):
        n += (src[k] == '{') - (src[k] == '}')
        if n == 0:
            return src[i:k + 1]
    raise ValueError(nombre)


def margenes_js(casos):
    src = open(INDEX, encoding='utf-8').read()
    fn = '\n'.join(extraer_funcion(src, n) for n in ('cfgN', 'compExtraFijo', 'compMargenAt'))
    # El front toma los tramos del endpoint /rentabilidad/pricing/ml-costo-fijo: acá se le pasa la misma respuesta (desde la tabla del seed)
    tramos = [[float(t['hasta']), float(t['valor'])] for t in tramos_costo_fijo_ml(parametros_seed()) if t['hasta'] is not None] + [[None, 0]]
    js = ("global.window={};global.qs=()=>null;global.S={shippingThreshold:33000,shippingCost:8500};const ML_COSTO_FIJO={tramos:" + json.dumps(tramos) + "};\n" + fn +
          "\nconst c=JSON.parse(process.argv[1]);console.log(JSON.stringify(c.map(x=>compMargenAt(x[0],x[1],x[2],0).m)));")
    out = subprocess.run(['node', '-e', js, json.dumps(casos)], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def costo_fijo_ofertas_js(precios):
    src = open(INDEX, encoding='utf-8').read()
    tramos = [[float(t['hasta']), float(t['valor'])] for t in tramos_costo_fijo_ml(parametros_seed()) if t['hasta'] is not None] + [[None, 0]]
    js = ("const ML_COSTO_FIJO={tramos:" + json.dumps(tramos) + "};\n" + extraer_funcion(src, 'ofmPorTramo') +
          "\nconsole.log(JSON.stringify(JSON.parse(process.argv[1]).map(p=>ofmPorTramo(p,ML_COSTO_FIJO.tramos))));")
    return json.loads(subprocess.run(['node', '-e', js, json.dumps(precios)], capture_output=True, text=True, check=True).stdout)


def parametros_seed():
    valores = {(c, k): Decimal(v) for c, k, v, *_ in seed.PRICING_PARAMETROS}
    tramos = {}
    for t in seed.PRICING_TRAMOS:
        tramos.setdefault(t['tabla'], []).append(Tramo(Decimal(t['desde']), None if t['hasta'] is None else Decimal(t['hasta']), Decimal(t['valor']), t['unidad']))
    return ParametrosMotor(valores=valores, tramos=tramos)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tolerancia', type=float, default=0.0001)
    a = ap.parse_args()
    casos = [(p, iva, round(p / iva * frac, 2)) for p in PRECIOS for iva, frac in CASOS_IVA_COSTO]
    js = margenes_js(casos)
    par = parametros_seed()
    malos = 0
    print(f"{'precio':>8} {'iva':>6} {'costo':>10} {'JS %':>9} {'motor %':>9} {'dif pp':>8}")
    for (p, iva, costo), mj in zip(casos, js):
        d = precio_a_margen(Decimal(p), EntradaMotor(canal='ML', costo=Decimal(str(costo)), iva_factor=Decimal(str(iva)), envio=Decimal(8500)), par)
        mm = float(d.margen)
        dif = (mj - mm) * 100
        malos += abs(mj - mm) > a.tolerancia
        print(f'{p:>8} {iva:>6} {costo:>10.2f} {mj * 100:>9.2f} {mm * 100:>9.2f} {dif:>+8.2f}{"  <<<" if abs(mj - mm) > a.tolerancia else ""}')
    # Ofertas ML (ofmMargenAt) usa su propia cuenta de envío/cuotas; acá se verifica solo el costo fijo, que ahora sale de la misma fuente.
    cf_js = costo_fijo_ofertas_js(PRECIOS)
    for p, cj in zip(PRECIOS, cf_js):
        cm = float(precio_a_margen(Decimal(p), EntradaMotor(canal='ML', costo=Decimal(1000), iva_factor=Decimal('1.21'), envio=Decimal(0)), par).cargos['costo_fijo'])
        malos += abs(cj - cm) > 0.005
        print(f'costo fijo Ofertas @ {p:>7}: JS {cj:>7.2f} · motor {cm:>7.2f}{"  <<<" if abs(cj - cm) > 0.005 else ""}')
    print(f'\n{len(casos)} casos de Competidores + {len(PRECIOS)} de costo fijo de Ofertas, {malos} fuera de tolerancia ({a.tolerancia * 100:.2f} pp).')
    sys.exit(1 if malos else 0)


if __name__ == '__main__':
    main()
