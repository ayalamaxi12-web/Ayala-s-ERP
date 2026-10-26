"""Pantalla «Ventas de hoy» (docs/index.html): está en el menú, llama al endpoint en vivo y no mete colores fijos."""
import os
import re

INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'docs', 'index.html')
SRC = open(INDEX, encoding='utf-8').read()


def test_menu_pagina_y_despacho():
    assert 'data-page="ventas-hoy"' in SRC and 'id="page-ventas-hoy"' in SRC
    assert "if(page==='ventas-hoy')ventasHoyEntrar();" in SRC and "'ventas-hoy'," in SRC.split("const PAGINAS_ESTILO_NUEVO=new Set([")[1][:40]


def test_llama_al_endpoint_en_vivo_se_refresca_solo_y_escapa_los_sku():
    assert "/rentabilidad/ventas-hoy" in SRC and "setInterval(" in SRC.split("function ventasHoyEntrar")[1][:400]
    assert "acEsc(x.sku)" in SRC and "?forzar=true" in SRC


def test_los_estilos_de_la_pantalla_usan_solo_tokens():
    css = re.findall(r"\.vh-[^{]*\{[^}]*\}", SRC)
    assert css and not any(re.search(r"#[0-9a-fA-F]{3,8}\b", c) for c in css)
