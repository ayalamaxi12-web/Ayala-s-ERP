#!/usr/bin/env python3
"""Muestrea el color dominante de un logo y verifica el contraste del texto sobre ese color (WCAG, mínimo 4,5:1).

Uso:  python muestrear_color.py logo.png [otro.png ...]     (necesita Pillow)

Reglas (docs/ESTETICA_ERP_GLOBAL.md §2): el color de un marketplace sale del logo oficial, nunca se inventa. Se ignoran los píxeles transparentes
y los casi blancos / casi grises (fondos y sombras); el dominante es el color más frecuente entre el resto, agrupado en cubos de 16 niveles por canal y
promediado dentro del cubo ganador. Después se prueba qué texto (blanco, la tinta del ERP #0B2733 o la versión oscurecida del propio color) da >= 4,5:1.
Imprime la fila lista para pegar en la tabla de temas. Si ningún texto llega a 4,5:1 sobre el color, lo avisa: ese color solo puede ir en la banda y el logo."""
import sys
from collections import Counter

from PIL import Image

TINTA = (0x0B, 0x27, 0x33)
BLANCO = (255, 255, 255)


def luminancia(rgb):
    def c(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (c(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(a, b):
    la, lb = sorted((luminancia(a), luminancia(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def hexa(rgb):
    return '#%02X%02X%02X' % tuple(rgb)


def dominante(ruta):
    im = Image.open(ruta).convert('RGBA')
    im.thumbnail((200, 200))
    cubos = Counter()
    suma = {}
    for r, g, b, a in (im.get_flattened_data() if hasattr(im, "get_flattened_data") else im.getdata()):
        if a < 200 or (min(r, g, b) > 235) or (max(r, g, b) - min(r, g, b) < 24 and max(r, g, b) > 60):
            continue          # transparente, casi blanco o gris: no es el color de marca
        k = (r >> 4, g >> 4, b >> 4)
        cubos[k] += 1
        s = suma.setdefault(k, [0, 0, 0])
        s[0] += r; s[1] += g; s[2] += b
    if not cubos:
        return None
    k, n = cubos.most_common(1)[0]
    return tuple(round(v / n) for v in suma[k]), n / sum(cubos.values())


def oscurecer(rgb, f):
    return tuple(round(v * f) for v in rgb)


def texto_sobre(rgb):
    """-> (nombre, hex, ratio) del primer texto que llega a 4,5:1: blanco, tinta o el propio color oscurecido; None si ninguno."""
    candidatos = [('blanco', BLANCO), ('tinta', TINTA)] + [(f'color oscurecido {int(f * 100)} %', oscurecer(rgb, f)) for f in (0.6, 0.45, 0.3)]
    for nombre, c in candidatos:
        if contraste(rgb, c) >= 4.5:
            return nombre, hexa(c), contraste(rgb, c)
    return None


if __name__ == '__main__':
    for ruta in sys.argv[1:]:
        r = dominante(ruta)
        if not r:
            print(f'{ruta}: sin color dominante (¿todo blanco o transparente?)')
            continue
        rgb, parte = r
        t = texto_sobre(rgb)
        print(f'{ruta}: dominante {hexa(rgb)} ({parte:.0%} de los píxeles con color) · contraste con blanco {contraste(rgb, BLANCO):.2f}:1, con tinta {contraste(rgb, TINTA):.2f}:1')
        print('   texto sobre el acento:', f'{t[0]} {t[1]} ({t[2]:.2f}:1)' if t else 'NINGUNO llega a 4,5:1: solo banda y logo')
