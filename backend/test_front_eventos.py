"""Vista «Eventos» de Análisis de Competencia (docs/index.html: acEv*): lista, baja fuerte con umbral configurable y CSV. Lógica extraída del HTML y corrida
en node con datos SINTÉTICOS; se saltea sin node."""
import json
import re
import shutil
import subprocess

import pytest

from test_front_analisis import INDEX, _fn

pytestmark = pytest.mark.skipif(not shutil.which('node'), reason='sin node')
FUNS = ('acUmbralLeer', 'acUmbralGuardar', 'acEvPct', 'acEvFiltrar', 'acEvResumen', 'acCsvCelda', 'acEvCsv', 'acEvHtml', 'acIsoMas', 'acEsc', 'acFechaCorta', 'fmt$')
HOY = '2026-10-20'


def js(cuerpo, datos, ls='{}'):
    s = open(INDEX, encoding='utf-8').read()
    consts = '\n'.join(re.search(p, s).group(0) for p in (r"const AC_EV_TIPOS=\{.*?\};", r"const AC_UMBRAL_DEFAULT=10,AC_UMBRAL_KEY='[a-z_]+';"))
    src = consts + '\n' + '\n'.join(_fn(s, n) for n in FUNS)
    pre = "const X=JSON.parse(process.argv[1]);const norm=s=>String(s||'').trim().toLowerCase();const LS=JSON.parse(process.argv[2]);global.localStorage={getItem:k=>(k in LS?LS[k]:null),setItem:(k,v)=>{LS[k]=v;}};\n"
    return json.loads(subprocess.run(['node', '-e', src + '\n' + pre + cuerpo, json.dumps(datos), ls], capture_output=True, text=True, check=True).stdout)


def ev(fecha, tipo, sku, ent, ant=None, nuevo=None, pct='', rol='Rey', hora='17:30', detalle='', link=''):
    return {'fecha': fecha, 'hora': hora, 'tipo': tipo, 'sku': sku, 'entidad': ent, 'rol': rol, 'anterior': ant, 'nuevo': nuevo, 'variacion_pct': pct, 'detalle': detalle, 'link': link}


EVS = [ev('2026-10-19', 'Bajo', 'SKU-9001', 'TIENDA A', 1000, 850, '-15'), ev('2026-10-18', 'Bajo', 'SKU-9002', 'TIENDA B', 2000, 1900, ''), ev('2026-10-17', 'Subio', 'SKU-9001', 'TIENDA B', 900, 990, '10', rol='Media'),
       ev('2026-10-10', 'Publicacion_caida', 'SKU-9003', 'TIENDA A', detalle='no responde', link='https://ejemplo.invalid/x'), ev('2026-08-15', 'Bajo', 'SKU-9001', 'TIENDA A', 1, 1, '-50')]
INFO = {'sku-9001': {'cat': 'Cat 1', 'pm': 'PM 1'}, 'sku-9002': {'cat': 'Cat 2', 'pm': 'PM 2'}}


def filtrar(**kw):
    fl = dict({'dias': 30, 'hoy': HOY, 'tipos': [], 'vend': [], 'search': '', 'soloFuertes': False, 'umbral': 10, 'cats': None, 'pms': None, 'info': INFO}, **kw)
    return js("const f=X.fl;f.tipos=new Set(f.tipos);f.vend=new Set(f.vend);f.norm=norm;console.log(JSON.stringify(acEvFiltrar({eventos:X.evs},f).map(e=>[e.sku,e.entidad,e.tipoTxt,e.pct,e.fuerte])))", {'fl': fl, 'evs': EVS})


def test_ventana_orden_porcentaje_y_baja_fuerte_con_umbral():
    r = filtrar()
    assert [x[:2] for x in r] == [['SKU-9001', 'TIENDA A'], ['SKU-9002', 'TIENDA B'], ['SKU-9001', 'TIENDA B'], ['SKU-9003', 'TIENDA A']]    # el de agosto (66 d) queda fuera de la ventana de 30 d; el más nuevo primero
    assert r[0][3] == -15 and r[0][4] is True and r[1][3] == -5 and r[1][4] is False and r[2][4] is False        # sin variacion_pct se calcula de anterior/nuevo (-5 %); una suba nunca es baja fuerte
    assert [x[4] for x in filtrar(umbral=5)][:2] == [True, True] and [x[4] for x in filtrar(umbral=20)][:2] == [False, False]   # el umbral cambia qué es «fuerte»
    assert len(filtrar(dias=90)) == 5 and len(filtrar(dias=7)) == 3


def test_filtros_tipo_vendedor_buscador_fuertes_categoria_y_pm():
    assert [x[0] for x in filtrar(tipos=['Subio'])] == ['SKU-9001']
    assert [x[1] for x in filtrar(vend=['TIENDA B'])] == ['TIENDA B', 'TIENDA B']
    assert [x[0] for x in filtrar(search='9003')] == ['SKU-9003'] and [x[0] for x in filtrar(search='ejemplo.invalid')] == ['SKU-9003'] and [x[0] for x in filtrar(search='no responde')] == ['SKU-9003']
    assert [x[0] for x in filtrar(soloFuertes=True)] == ['SKU-9001']
    assert {x[0] for x in filtrar(cats=['Cat 2'])} == {'SKU-9002'} and {x[0] for x in filtrar(pms=['PM 1'])} == {'SKU-9001'}
    assert {x[0] for x in filtrar(cats=['Sin categoría'])} == {'SKU-9003'}                                          # SKU que no está en la pantalla: «Sin categoría»


def test_resumen_y_csv():
    out = js("const f={dias:30,hoy:X.hoy,tipos:new Set(),vend:new Set(),search:'',soloFuertes:false,umbral:10,cats:null,pms:null,info:{},norm};const r=acEvFiltrar({eventos:X.evs},f);"
             "console.log(JSON.stringify([acEvResumen(r),acEvCsv(r)]))", {'hoy': HOY, 'evs': EVS + [ev('2026-10-19', 'Bajo', 'SKU,9', 'TIENDA "Q"', 10, 5, '-50', detalle='línea\ndos')]})
    assert out[0] == {'total': 5, 'bajaron': 3, 'subieron': 1, 'fuertes': 2, 'otros': 1}                       # 3 bajas (una con comillas), 1 suba y 1 publicación caída (otro); fuertes: -15 % y -50 %
    lineas = out[1].split('\n')
    assert out[1].startswith('﻿Fecha,Hora,Tipo,SKU,Competidor,Rol,Precio anterior,Precio nuevo,Variacion %,Baja fuerte,Detalle,Link')
    assert '"SKU,9"' in out[1] and '"TIENDA ""Q"""' in out[1] and '"línea\ndos"' in out[1]                         # comas, comillas y saltos de línea bien escapados
    assert any(l.startswith('2026-10-19,17:30,Bajó,SKU-9001,TIENDA A,Rey,1000,850,-15,Si') for l in lineas)


def test_umbral_guardado_valido_invalido_o_sin_storage():
    assert js("console.log(JSON.stringify([acUmbralLeer()]))", {}, '{}') == [10]
    assert js("acUmbralGuardar(15);console.log(JSON.stringify([acUmbralLeer(),LS]))", {}, '{}') == [15, {'ac_umbral_baja_fuerte': '15'}]
    assert js("console.log(JSON.stringify([acUmbralLeer()]))", {}, '{"ac_umbral_baja_fuerte":"abc"}') == [10]
    assert js("console.log(JSON.stringify([acUmbralLeer()]))", {}, '{"ac_umbral_baja_fuerte":"500"}') == [10]
    assert js("global.localStorage={getItem(){throw new Error('x')},setItem(){throw new Error('x')}};acUmbralGuardar(20);console.log(JSON.stringify([acUmbralLeer()]))", {}) == [10]   # storage bloqueado: no rompe


def test_html_con_chips_umbral_kpis_y_sin_datos():
    h = js("const f={dias:30,hoy:X.hoy,tipos:new Set(['Bajo']),vend:new Set(),search:'',soloFuertes:true,umbral:10,cats:null,pms:null,info:{},norm};const r=acEvFiltrar({eventos:X.evs},f);"
           "console.log(JSON.stringify([acEvHtml(r,acEvResumen(r),{dias:30,umbral:10,tipos:f.tipos,fuertes:true,max:200},['Bajo','Subio']),acEvHtml([],acEvResumen([]),{dias:7,umbral:12,tipos:new Set(),fuertes:false,max:200},[])]))", {'hoy': HOY, 'evs': EVS})
    assert 'acEvDias(7)' in h[0] and "acEvTipo('Bajo')" in h[0] and 'aria-pressed="true"' in h[0] and 'value="10"' in h[0] and 'checked' in h[0] and 'baja fuerte' in h[0] and 'Bajas fuertes (≥ 10%)' in h[0]
    assert '−15,0%' in h[0] and '→' in h[0] and '$850' in h[0]
    assert 'Sin eventos con esos filtros' in h[1] and 'sin eventos' in h[1] and 'value="12"' in h[1]
