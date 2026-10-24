"""Precios & Márgenes: el aviso de IVA de respaldo va en texto y la caja de SKU no corta el código."""
from test_front_analisis import INDEX


def test_la_caja_de_busqueda_de_sku_entra_un_codigo_de_24_caracteres():
    s = open(INDEX, encoding='utf-8').read()
    assert 'id="pr-buscar" class="fi" placeholder="Buscar SKU..." style="width:30ch;max-width:100%"' in s


def test_la_celda_dice_en_texto_de_donde_salio_el_iva():
    s = open(INDEX, encoding='utf-8').read()
    f = s[s.index('function prCelda'):s.index('async function pricingLoad')]
    assert "startsWith('IVA tomado de Ecom')" in f
