"""Motor de Precios (Bloque 2, PR 4): selector de mercado con logos, panel de descuentos comunes, avisos de configuración en un solo lugar, parámetros del pedido."""
import json
import os
import re
import subprocess

from test_front_analisis import INDEX, _fn

RAIZ = os.path.dirname(os.path.abspath(INDEX))   # docs/


def html():
    return open(INDEX, encoding='utf-8').read()


def params(mercado, usa, comunes, valores, def_usa=None, recargo='', r18='', r24=''):
    s = html()
    js = '\n'.join(_fn(s, n) for n in ('ayalaCoreMercadoParams',)) + """
const A=JSON.parse(process.argv[1]);let AC_MERCADO=A.m;const AC_MK_USA={[A.m]:A.usa};
const AC_MK={comunes:A.comunes,mercados:{[A.m]:{usa_por_defecto:A.def}}};
function ayalaCoreMkInfo(m){return AC_MK.mercados[m];}
const V=A.valores;function qs(id){return {value:V[id]!==undefined?V[id]:''};}
console.log(ayalaCoreMercadoParams());
"""
    a = {'m': mercado, 'usa': usa, 'comunes': comunes, 'valores': valores, 'def': def_usa or {'orden': mercado != 'ml', 'cheque': True, 'iibb': True}}
    return subprocess.run(['node', '-e', js, json.dumps(a)], capture_output=True, text=True, check=True).stdout.strip()


COM = {'costo_orden': 149.12, 'cheque_pct': 1.2, 'iibb_pct': 5, 'recargo_cuotas': 20}
VAL = {'ac-costo-orden': '149.12', 'ac-cheque': '1.2', 'ac-iibb': '5', 'ac-recargo': '20', 'ac-renta-18': '24', 'ac-renta-24': '24'}


def test_ml_sin_cambios_no_manda_nada_de_mercado_para_que_el_pedido_sea_el_de_siempre():
    assert params('ml', {'orden': False, 'cheque': True, 'iibb': True}, COM, VAL) == ''


def test_ml_con_un_cambio_manda_solo_ese_cambio():
    assert params('ml', {'orden': True, 'cheque': True, 'iibb': True}, COM, VAL) == '&usar_costo_orden=true'
    assert params('ml', {'orden': False, 'cheque': True, 'iibb': True}, COM, {**VAL, 'ac-cheque': '2'}) == '&cheque_pct=2'


def test_otro_mercado_manda_mercado_y_los_tres_interruptores_y_solo_los_valores_cambiados():
    q = params('fravega', {'orden': True, 'cheque': True, 'iibb': False}, COM, {**VAL, 'ac-costo-orden': '200'})
    assert q == '&mercado=fravega&usar_costo_orden=true&usar_cheque=true&usar_iibb=false&costo_orden=200'


def test_la_web_manda_recargo_y_las_rentas_de_18_y_24():
    q = params('web', {'orden': True, 'cheque': True, 'iibb': True}, COM, {**VAL, 'ac-recargo': '0', 'ac-renta-18': '22'})
    assert q.startswith('&mercado=web') and '&recargo_cuotas=0' in q and '&renta_18=22&renta_24=24' in q


def test_selector_accesible_con_logos_reales_y_sin_nombres_escritos_con_fuente():
    s = html()
    g = s[s.index('id="ac-mercados"'):s.index('id="ac-config"')]
    assert 'role="radiogroup"' in s and g.count('role="radio"') == 6 and 'aria-checked="true"' in g
    for logo in ('mercadolibre-isotipo.png', 'fravega.svg', 'oncity.png', 'megatone.png', 'global-celeste.png'):
        assert f'assets/logos/{logo}' in g and os.path.exists(os.path.join(RAIZ, 'assets', 'logos', logo)), logo
    for nombre in ('Frávega', 'OnCity', 'Megatone'):                      # el nombre va como imagen (alt), nunca como texto en el botón
        assert f'alt="{nombre}"' in g and f'<span>{nombre}</span>' not in g
    assert os.path.exists(os.path.join(RAIZ, 'assets', 'logos', 'oncity-blanco.png'))
    assert "'ArrowRight'" in _fn(s, 'ayalaCoreMercadoTecla')


def test_identidad_solo_en_el_selector_con_tokens_y_sin_hex_sueltos():
    s = html()
    bloque = s[s.index('<style id="estetica-tienda-web">'):s.index('</style>', s.index('<style id="estetica-tienda-web">'))]
    assert not re.findall(r'#[0-9A-Fa-f]{3,8}\b', bloque)
    raiz = s[:s.index('</style>', s.index('<style id="estetica-tokens">'))]
    definidos = {'--mk-fravega-violeta': '#440099', '--mk-fravega-magenta': '#D30098', '--mk-fravega-link': '#801DD9', '--mk-fravega-azul': '#006AFD', '--mk-fravega-verde': '#208041',
                 '--mk-oncity-azul': '#064FD3', '--mk-oncity-turquesa': '#05F2D4', '--mk-oncity-chip': '#CDFBF5', '--mk-megatone-naranja': '#E53308', '--mk-megatone-rojo': '#E31E25',
                 '--mk-megatone-verde': '#008A45', '--mk-megatone-verde-texto': '#00783C', '--mk-megatone-gris': '#E6E6E6', '--mk-megatone-texto': '#2A2A28'}
    for tok, hexa in definidos.items():
        assert f'{tok}:{hexa}' in raiz, tok                               # los colores de marca viven como tokens, una sola vez
    for tok in ('--mk-fravega-violeta', '--mk-oncity-azul', '--mk-oncity-chip', '--mk-megatone-rojo', '--mk-megatone-gris'):
        assert f'var({tok})' in bloque, tok


def test_descuentos_comunes_y_avisos_en_un_solo_lugar():
    s = html()
    for id_ in ('ac-costo-orden', 'ac-cheque', 'ac-iibb', 'ac-recargo', 'ac-usa-orden', 'ac-usa-cheque', 'ac-usa-iibb', 'ac-config'):
        assert s.count(f'id="{id_}"') == 1, id_
    assert 'a confirmar' in s[s.index('id="ac-recargo-box"'):][:400]
    f = _fn(s, 'ayalaCoreConfigRender')
    assert 'Tarifas: ' in f and 'Actualizar' in f and 'avisos_por_mercado' in f and 'Crear pestañas Mercados y Envios' in f


def test_las_tablas_de_otros_mercados_no_llevan_manual_usar_y_muestran_los_datos_que_faltan():
    f = _fn(html(), 'ayalaCoreTablaHtml')
    assert "ml?'<th style=\"text-align:right\">Manual</th>" in f and 'ayalaCoreFilaErrorHtml' in f and 'ayalaCoreComisionDetalleHtml' in f


def test_impacto_costo_orden_en_ml_junto_al_interruptor():
    """Junto a «Aplicar en este mercado» se muestra cuánto sube el contado de ML con el costo por orden (SKU barato y caro), sin cambiar el default."""
    html = INDEX.read_text(encoding="utf-8") if hasattr(INDEX, "read_text") else open(INDEX, encoding="utf-8").read()
    assert 'id="ac-orden-impacto"' in html and "async function ayalaCoreImpactoOrden" in html
    assert "usar_costo_orden=false" in html and "usar_costo_orden=true" in html
