"""Motor de Precios (Bloque 2, PR 5): vista «Todos», una tarjeta por mercado con su identidad (logo, color, tipografía)."""
import json
import os
import re
import subprocess

from test_front_analisis import INDEX, _fn

RAIZ = os.path.dirname(os.path.abspath(INDEX))


def html():
    return open(INDEX, encoding='utf-8').read()


def tarjeta(mercado, lote):
    s = html()
    fns = '\n'.join(_fn(s, n) for n in ('acEsc', 'ayalaCoreConds', 'ayalaCoreFmt', 'ayalaCoreFmt2', 'ayalaCoreTarjetaMercadoHtml'))
    const = re.search(r"const AC_TARJETA=\{.*?\n\};", s, re.S).group(0) + "\n" + re.search(r"const AC_COND_LABEL=\{[^}]*\};", s).group(0) + "\nconst AC_COND_ORDEN=['contado','reducida','3','6','9','12'];"
    js = const + '\n' + fns + "\nconsole.log(ayalaCoreTarjetaMercadoHtml(process.argv[1],JSON.parse(process.argv[2])));"
    return subprocess.run(['node', '-e', js, mercado, json.dumps(lote)], capture_output=True, text=True, check=True).stdout


def res(sku, conds, precios, cantidad=1, **extra):
    return {"sku": sku, "cantidad": cantidad, "condiciones": conds, "precios": precios, "precios_unitarios": {k: round(v / cantidad, 2) for k, v in precios.items()},
            "etiqueta_contado": extra.pop("etiqueta", "Simple"), "parametros": {"comision_pct": 15.5, "costo_orden": 149.12}, "errores_condicion": extra.pop("errores", {}), **extra}


def test_hay_una_tarjeta_por_mercado_con_su_logo_y_el_nombre_de_frabega_como_imagen():
    c = tarjeta('fravega', {"resultados": [res("A", ["contado", "3"], {"contado": 100000, "3": 110000})], "calculado_con": {"avisos_mercado": []}})
    assert 'src="assets/logos/fravega.svg" alt="Frávega"' in c and '<h3 class="ac-sr">Frávega</h3>' in c and 'Ver en Frávega' in c and 'data-mk="fravega"' in c
    ml = tarjeta('ml', {"resultados": [res("A", ["contado", "reducida"], {"contado": 1, "reducida": 2}, etiqueta="Contado")], "calculado_con": {}})
    assert '<h3>Mercado Libre</h3>' in ml and 'mercadolibre-isotipo.png' in ml and 'a confirmar' not in ml and 'Reducida' in ml
    on = tarjeta('oncity', {"resultados": [res("A", ["contado"], {"contado": 1})], "calculado_con": {}})
    assert 'oncity-blanco.png' in on and 'a confirmar' not in on      # lo pendiente va en el resumen de configuración, no en cada tarjeta


def test_frabega_marca_las_cuotas_sin_interes_y_los_otros_mercados_no():
    lote = {"resultados": [res("A", ["contado", "3", "6"], {"contado": 1, "3": 2, "6": 3})], "calculado_con": {}}
    fr = tarjeta('fravega', lote)
    assert fr.count('class="ac-sin-interes"') == 2 and fr.count('sin interés') == 2 and '>Simple<' in fr
    assert 'sin interés' not in tarjeta('megatone', lote) and 'sin interés' not in tarjeta('web', lote)


def test_pack_muestra_precio_de_la_publicacion_y_por_unidad_y_un_dato_faltante_se_dice():
    lote = {"resultados": [res("A", ["contado", "12"], {"contado": 200000}, cantidad=2, errores={"12": "falta dato: tarifa de 12 cuotas de OnCity"})], "calculado_con": {}}
    c = tarjeta('oncity', lote)
    assert 'por unidad $100.000,00' in c and 'Pack x2' in c and 'falta dato: tarifa de 12 cuotas de OnCity' in c


def test_sin_datos_para_ningun_sku_la_tarjeta_lo_dice():
    c = tarjeta('web', {"resultados": [{"sku": "A", "error": "SIN_COSTO para SKU 'A'"}], "calculado_con": {}})
    assert 'SIN_COSTO' in c and 'Ver en la Web' in c


def test_la_identidad_vive_solo_en_selector_y_tarjetas_con_tokens_y_tipografias_cargadas_al_usar_todos():
    s = html()
    bloque = s[s.index('<style id="estetica-tienda-web">'):s.index('</style>', s.index('<style id="estetica-tienda-web">'))]
    assert not re.findall(r'#[0-9A-Fa-f]{3,8}\b', bloque)
    for fam, tok in (('Roboto', '--fuente-mk-fravega'), ('Outfit', '--fuente-mk-oncity'), ('Rubik', '--fuente-mk-megatone'), ('Nunito Sans', '--fuente-mk-ml')):
        assert f"{tok}:'{fam}'" in s, fam
    for m in ('ml', 'fravega', 'oncity', 'megatone'):
        assert f'.ac-tk[data-mk={m}] *{{font-family:var(--fuente-mk-{m})!important}}' in bloque, m   # gana contra el «*{font-family:var(--fuente)!important}» global
    # esas familias NO se cargan con la página: solo al elegir «Todos»
    assert 'family=Rubik' not in s[:s.index('</head>')] and 'family=Rubik' in _fn(s, 'ayalaCoreCargarFuentes')
    # nada de la identidad se filtra al resto del módulo
    resto = bloque.replace(bloque[bloque.index('.ac-todos{'):], '')
    assert '--mk-fravega' not in resto.split('.ac-mk')[0] and '.ac-tk' not in resto


def test_logos_y_encabezados_no_usan_header_ni_footer_de_la_app():
    s = html()
    f = _fn(s, 'ayalaCoreTarjetaMercadoHtml')
    assert '<header' not in f and '<footer' not in f           # esas etiquetas heredan los estilos de la barra de la app
    for logo in ('mercadolibre-isotipo.png', 'fravega.svg', 'oncity-blanco.png', 'megatone.png', 'global-blanco.png'):
        assert logo in s and os.path.exists(os.path.join(RAIZ, 'assets', 'logos', logo)), logo


def test_el_selector_tiene_todos_y_pide_un_lote_por_mercado():
    s = html()
    assert 'data-mk="todos"' in s and "const AC_MK_ORDEN=['todos','ml','fravega','oncity','megatone','web']" in s
    f = _fn(s, 'ayalaCoreCalcularTodos')
    assert 'Promise.all(AC_MK_REALES.map' in f and 'ayalaCoreMercadoParams(m)' in f and 'ayalaCoreCargarFuentes()' in f
    assert "return '';" in _fn(s, 'ayalaCoreMercadoParams')[:200]


def test_comision_de_ml_en_la_tarjeta_es_la_real_y_las_tablas_no_se_estiran():
    ml = tarjeta('ml', {"resultados": [dict(res("A", ["contado"], {"contado": 1}, etiqueta="Contado"), parametros=None, comision_pct=15.32)], "calculado_con": {}})
    assert re.search(r"Comisión base 15[.,]32 %", ml)
    src = open(INDEX, encoding="utf-8").read()
    assert ".ac-tk table{width:auto" in src and ".ac-tk th:first-child{position:sticky;left:0" in src
    assert "tw.style.display=AC_MERCADO==='todos'?'grid':'none'" in src      # con «block» las tarjetas quedaban una debajo de otra


def test_avisos_de_configuracion_un_resumen_plegado_y_lo_informativo_aparte():
    f = _fn(html(), 'ayalaCoreConfigRender')
    assert '<details class="ac-config-av"><summary>' in f and "open" not in f.split("<details")[1].split(">")[0]
    assert "usando los valores iniciales del código" in f and 'class="ac-config-nota"' in f      # información y notas, fuera del conteo de avisos
