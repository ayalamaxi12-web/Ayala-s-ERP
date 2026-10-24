"""Estilo «tienda web», PR 2: Motor de Precios, Precios & Márgenes, Verificar Ecom y Verificar Táctica (solo presentación)."""
import re

from test_front_analisis import INDEX


def html():
    return open(INDEX, encoding='utf-8').read()


def test_las_cuatro_paginas_estan_en_el_estilo_nuevo():
    s = html()
    lista = s[s.index('const PAGINAS_ESTILO_NUEVO'):][:200]
    for p in ('ayala-core', 'pricing', 'verificar-ecom', 'verificar-tactica', 'dashboard'):
        assert f"'{p}'" in lista, p


def test_el_bloque_del_pr2_solo_usa_tokens_y_no_toca_las_planillas_pm():
    s = html()
    bloque = s[s.index('<style id="estetica-tienda-web">'):s.index('</style>', s.index('<style id="estetica-tienda-web">'))]
    assert not re.findall(r'#[0-9A-Fa-f]{3,8}\b', bloque)
    assert 'PR 2: Motor de Precios' in bloque and '#pm-blocks input[id$="-id"]' in bloque
    for id_ in ('s-${k}-id', 's-${k}-tab', 'ss-${k}'):
        assert id_ in s, id_                                                                   # los ids que usa connectSheet siguen igual
