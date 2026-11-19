"""Carga de ofertas por Excel: las que ML no acepta tal cual se tildan en la pantalla (ajuste al precio que acepta ML), sin volver a subir el Excel."""
import json
import os
import subprocess

from scripts.paridad_margenes import extraer_funcion

SRC = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'docs', 'index.html'), encoding='utf-8').read()
FNS = ('ofxPendientes', 'ofxPuedeEn', 'ofxAjuste', 'ofxAcepta', 'ofxListas', 'ofxNecesitanAjuste')


def test_solo_se_suben_las_que_entran_tal_cual_y_las_ajustadas_que_se_tildaron():
    js = ("const OFX={sel:'C1'};" + '\n'.join(extraer_funcion(SRC, n) for n in FNS) + """
const mk=(mla,aj,ok)=>({mla,estado:null,bloqueos:[],ajOk:ok?{C1:true}:{},candidatas:[{id:'C1',ajuste:aj?{final:12000}:undefined}]});
OFX.filas=[mk('A',false,false),mk('B',true,false),mk('C',true,true),{...mk('D',false,false),candidatas:[{id:'OTRA'}]},{...mk('E',false,false),bloqueos:['x']},{...mk('F',false,false),estado:'ok'}];
console.log(JSON.stringify({listas:ofxListas('C1').map(f=>f.mla),ajuste:ofxNecesitanAjuste('C1').map(f=>f.mla)}));""")
    r = json.loads(subprocess.run(['node', '-e', js], capture_output=True, text=True, check=True).stdout)
    assert r == {'listas': ['A', 'C'], 'ajuste': ['B', 'C']}        # B necesita ajuste y no se tildó: queda pendiente; D no entra; E tiene bloqueo; F ya está aplicada
