"""Contexto propio por SKU en Análisis de Competencia (docs/index.html: acCtx*): stock + ventas desde los Sheets, cruce madre→variante, filtro y orden."""
import json
import os
import shutil
import subprocess

import pytest

from scripts.paridad_margenes import extraer_funcion

INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'docs', 'index.html')
pytestmark = pytest.mark.skipif(not shutil.which('node'), reason='sin node')
FNS = ('_parseNumEsAR', 'normSku', 'acColIdx', 'acCtxNum', 'acCtxSinAcento', 'acCtxFilaTitulos', 'acCtxColVar', 'acCtxLeerStock', 'acCtxLeerVentas',
       'acCtxArmar', 'acCtxBuscar', 'acCtxResumen', 'acFiltrar', 'acOrdenar')


def js(cuerpo, datos):
    src = open(INDEX, encoding='utf-8').read()
    cod = 'const CTX_DIAS_STOCK_BAJO=15;\n' + '\n'.join(extraer_funcion(src, n) for n in FNS) + '\nconst D=JSON.parse(process.argv[1]);\n' + cuerpo
    return json.loads(subprocess.run(['node', '-e', cod, json.dumps(datos)], capture_output=True, text=True, check=True).stdout)


def fila_stock(sku, var, e, f, g):
    return [sku, var, '', '', e, f, g]


def fila_ventas(sku, var, d7, d30, d90, d180, mx):
    r = [''] * 55
    r[0], r[1] = sku, var
    r[50:55] = [d7, d30, d90, d180, mx]
    return r


STOCK = [['sku', 'sku variante', '', '', 'Táctica', 'Ecom', 'Total'], fila_stock('SEW-MINI', 'SEW-MINI-N', '200', '100', '300'), fila_stock('SEW-MINI', 'SEW-MINI-R', '218', '73', '291'),
         fila_stock('SEW-MINI', 'SEW-MINI-R', '218', '73', '291'), fila_stock('AGOTADO', 'AGOTADO-1', '0', '0', '0'), fila_stock('PV-9', '', '1.000', '5', '1.005')]
VENTAS = [['SKU madre', 'SKU Variante'] + [''] * 48 + ['7 d', '30 d', '90 d', '180 d', 'Máx mensual'], fila_ventas('SEW-MINI', 'SEW-MINI-N', '1', '14', '60', '200', '30'),
          fila_ventas('SEW-MINI', 'SEW-MINI-R', '0', '10', '40', '131', '25'), fila_ventas('SEW-MINI', 'SEW-MINI-R', '0', '10', '40', '131', '25'),
          fila_ventas('MADRE-X', 'COLOR-AZUL', '2', '5', '9', '20', '7')]
ARMAR = 'const s=acCtxLeerStock(D.s),v=acCtxLeerVentas(D.v),c=acCtxArmar(s.filas,v.filas);'


def test_suma_variantes_y_deduplica():
    r = js(ARMAR + 'const e=c.madres[normSku("SEW-MINI")];console.log(JSON.stringify({st:e.stock,ve:e.ventas,n:e.vars.length,av:[...s.avisos,...v.avisos]}))', {'s': STOCK, 'v': VENTAS})
    assert r['st'] == {'tactica': 418, 'ecom': 173, 'total': 591}          # los números que Maxx confirmó para SEW-MINI
    assert r['ve'] == {'d7': 1, 'd30': 24, 'd90': 100, 'd180': 331, 'max': 55}   # BC = suma de máximos de variante
    assert r['n'] == 2 and r['av'] == []                                    # la fila repetida no suma dos veces


def test_numeros_es_ar_y_total_vacio():
    r = js(ARMAR + 'console.log(JSON.stringify(acCtxBuscar(c,"pv-9").e.stock))', {'s': STOCK, 'v': VENTAS})
    assert r == {'tactica': 1000, 'ecom': 5, 'total': 1005}


def test_busca_por_variante_y_prefijo_pv():
    r = js(ARMAR + 'const a=acCtxBuscar(c,"COLOR-AZUL"),b=acCtxBuscar(c,"pv-SEW-MINI"),n=acCtxBuscar(c,"NOEXISTE");console.log(JSON.stringify({a:[a.via,a.madre,a.e.ventas.d30,a.e.stock],b:b.via,n}))', {'s': STOCK, 'v': VENTAS})
    assert r['a'] == ['variante', 'MADRE-X', 5, None] and r['b'] == 'madre' and r['n'] is None


def test_resumen_dias_de_stock():
    r = js(ARMAR + 'console.log(JSON.stringify([acCtxResumen(c.madres.agotado),acCtxResumen(c.madres["sew-mini"]),acCtxResumen(c.madres["madre-x"])]))', {'s': STOCK, 'v': VENTAS})
    assert r[0]['sinStock'] is True
    assert r[1]['dias'] == pytest.approx(591 / (24 / 30)) and r[1]['bajo'] is False
    assert r[2]['total'] is None and r[2]['sinStock'] is False and r[2]['dias'] is None   # sin dato de stock no es "sin stock"


def test_avisa_si_cambia_el_encabezado_pero_lee_igual():
    s = [['sku', 'x', '', '', 'Otra cosa', 'Ecom', 'Total'], fila_stock('A', 'A1', '1', '2', '3')]
    r = js('const s=acCtxLeerStock(D);console.log(JSON.stringify(s))', s)
    assert len(r['avisos']) == 1 and 'columna E' in r['avisos'][0] and r['filas'][0]['g'] == 3


def test_filtro_sin_stock_y_orden_por_ventas():
    cuerpo = ARMAR + """const fn=sku=>{const r=acCtxBuscar(c,sku);return r?r.e:null;};
const filas=['SEW-MINI','AGOTADO','NOEXISTE','MADRE-X'].map(s=>({sku:s,key:s,_hayCambio:true,_ganan:true}));
console.log(JSON.stringify({o:acOrdenar(filas,'ventas30',fn).map(f=>f.sku)}));"""
    assert js(cuerpo, {'s': STOCK, 'v': VENTAS})['o'][:2] == ['SEW-MINI', 'MADRE-X']       # 24 > 5; los sin dato de ventas van al final
