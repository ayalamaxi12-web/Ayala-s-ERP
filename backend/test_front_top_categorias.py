"""Top Categorías de Ventas & Rentabilidad (docs/index.html): trae el margen en pesos ($) además del %, por período, en la categoría y en cada SKU."""
import json
import os
import shutil
import subprocess

import pytest

from scripts.paridad_margenes import extraer_funcion

INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'docs', 'index.html')
pytestmark = pytest.mark.skipif(not shutil.which('node'), reason='sin node')
FNS = ('fmt$', 'groupSum', '_margenPesosColor', '_rentBadgeClass', '_rentInlineColor', 'buildTopCatsHTML')


def html(comparar):
    src = open(INDEX, encoding='utf-8').read()
    cod = ('\n'.join(extraer_funcion(src, n) for n in FNS) + '''
const v=(cat,sku,pf,sin,rent)=>({categoria:cat,skus:[sku],precioFinal:pf,precioSinIva:sin,rentabilidad:rent});
const p1=[v("Electro","A1",1210,1000,250),v("Electro","A2",605,500,-300),v("Audio","B1",121,100,12)];
const p2=[v("Electro","A1",1210,1000,40)];
const rm=(arr)=>{const m={};arr.forEach(d=>{m[d.categoria]=(m[d.categoria]||0)+d.rentabilidad;});return m;};
const tops=Object.entries(groupSum(p1,"categoria","precioFinal"));
console.log(JSON.stringify(buildTopCatsHTML(tops,p1,''' + ('p2' if comparar else 'null') + ',' + ('true' if comparar else 'false') + ',3000,rm(p1),rm(p2),"hist")));')
    return json.loads(subprocess.run(['node', '-e', cod], capture_output=True, text=True, check=True).stdout)


def test_sin_comparar_muestra_margen_en_pesos_de_categorias_y_skus():
    h = html(False)
    assert h.count('Margen $') == 3                                       # 1 en la tabla de categorías + 1 en la tabla de SKUs de cada una de las 2 categorías
    assert '$-50' in h and 'var(--red)' in h                              # Electro: 250 − 300 = −50 → pérdida en rojo
    assert '$12' in h and 'var(--green)' in h                             # Audio: +12
    assert '$250' in h and '$-300' in h                                   # por SKU: A1 +250, A2 −300


def test_comparando_periodos_muestra_margen_en_pesos_p1_y_p2():
    h = html(True)
    assert h.count('Margen $ P1') == 3 and h.count('Margen $ P2') == 3
    assert '$40' in h                                                     # P2 de Electro (SKU A1): +40
