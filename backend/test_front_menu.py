"""Menú lateral (28/10): módulos sacados por decisión de Maxx; sus links viejos abren el que los reemplaza."""
import os
import re

SRC = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'docs', 'index.html'), encoding='utf-8').read()
MENU = SRC[SRC.index('<nav'):SRC.index('</nav>')]


def test_el_menu_ya_no_tiene_los_modulos_retirados():
    for pg in ('pricing', 'verificar-ml', 'intel-entidades', 'intel-referencias', 'intel-mix', 'mltools', 'competidores'):
        assert f'data-page="{pg}"' not in MENU, pg
    assert 'Inteligencia Comercial' not in MENU


def test_el_menu_conserva_los_que_quedan():
    quedan = re.findall(r'data-page="([a-z0-9-]+)"', MENU)
    for pg in ('dashboard', 'ventas-hoy', 'ayala-core', 'verificar-ecom', 'verificar-tactica', 'full-ml', 'ofertas-margen', 'campanas-ml', 'analisis-competencia', 'proyeccion', 'distribucion', 'config', 'reglas'):
        assert pg in quedan, pg


def test_los_links_viejos_redirigen():
    bloque = SRC.split("const MENU_RETIRADOS={")[1].split("}")[0]
    for viejo in ('pricing', 'verificar-ml', 'intel-entidades', 'intel-referencias', 'intel-mix', 'mltools'):
        assert f"'{viejo}':" in bloque, viejo


def test_la_pagina_de_criterios_esta_en_el_menu_y_sin_colores_fijos():
    assert 'data-page="reglas"' in MENU and "Criterios de precio</a>" in MENU
    assert "if(page==='reglas')criteriosCargar();" in SRC
    css = " ".join(c for c in SRC.split("\n") if c.startswith((".cr-", ".cr-fila")))
    assert css and not re.search(r"#[0-9a-fA-F]{3,8}\b", css)
    for fn in ("criteriosGuardar", "criteriosVolver"):
        cuerpo = SRC.split(f"async function {fn}")[1].split("\n}\n")[0]
        assert "cr-operador" in cuerpo and "confirm(" in cuerpo          # operador obligatorio y confirmación
