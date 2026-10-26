"""Pantalla del Motor: base de la renta, «Ver cuenta», encabezados con IVA y aviso de porcentajes raros. Funciones JS extraídas de docs/index.html y corridas con node."""
import json
import subprocess

from test_front_analisis import INDEX, _fn

SRC = open(INDEX, encoding="utf-8").read()


def _node(js):
    return subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout


def test_precio_js_con_iva_es_el_de_siempre_y_sin_iva_cambia_solo_el_termino_de_renta():
    consts = "const AC_IVA_SERVICIOS_ML=1.21,AC_COMISION_PCT=15.32,AC_IIBB_PCT=5,AC_IMPCH_PCT=1.2;let AC_RENTA_BASE='con_iva';"
    js = consts + _fn(SRC, "ayalaCoreCalcularPrecioJS") + """
const a=ayalaCoreCalcularPrecioJS(20925,1.105,0,6.8,10), b=ayalaCoreCalcularPrecioJS(20925,1.105,0,6.8,10,'con_iva'), c=ayalaCoreCalcularPrecioJS(20925,1.105,0,6.8,10,'sin_iva');
const num=20925, den=(1/1.105)-(15.32/100)/1.21-(5/100)/1.105-(1.2/100)-(6.8/100)-(10/100);
console.log(JSON.stringify([a,b,c,Math.round(num/den)]));"""
    a, b, c, antes = json.loads(_node(js))
    assert a == b == antes and c < a   # la misma renta nominal sobre el neto son menos pesos


def test_aviso_marca_el_valor_que_se_aparta_y_no_los_defaults():
    js = _fn(SRC, "ayalaCoreRentaAvisoCalc") + "const AC_RENTA_DESVIO_PP=10;" + """
const v=(a)=>a.map((n,i)=>({id:'x'+i,n}));
console.log(JSON.stringify([
 ayalaCoreRentaAvisoCalc(v([10,10,32.279,10,10,10])).map(x=>x.id),
 ayalaCoreRentaAvisoCalc(v([32,32,30,28,26,24])).map(x=>x.id),
 ayalaCoreRentaAvisoCalc(v([10,10,10,150,10])).map(x=>x.id),
 ayalaCoreRentaAvisoCalc(v([null,10,10])).map(x=>x.id)]));"""
    assert json.loads(_node(js)) == [["x2"], [], ["x3"], []]


def test_la_pantalla_tiene_el_interruptor_la_columna_cuenta_y_los_encabezados():
    assert 'role="radiogroup" aria-label="Base del porcentaje de renta"' in SRC
    assert SRC.count("(con IVA; en la cuenta se resta sin IVA)") == 1 and "AC_NOTA_IVA" in SRC
    assert "Comisión${AC_NOTA_IVA}" in SRC and "Envío${AC_NOTA_IVA}" in SRC
    assert "aria-expanded" in _fn(SRC, "ayalaCoreVerCuentaBtn") and "renta_base=${AC_RENTA_BASE}" in _fn(SRC, "ayalaCoreRentaQueryParams")
    # con «con IVA» no se manda nada: el pedido es idéntico al de antes
    assert "&renta_base=${AC_RENTA_BASE}" in _fn(SRC, "ayalaCoreRentaQueryParams")      # siempre se manda explícita
    assert "let AC_RENTA_BASE='sin_iva'" in SRC                                          # Maxi (27/10): renta = margen ÷ precio sin IVA por defecto
    assert 'aria-checked="true" class="ac-mk ac-rb" data-rb="sin_iva"' in SRC
