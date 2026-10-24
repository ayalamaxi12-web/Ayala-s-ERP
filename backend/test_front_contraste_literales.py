"""Contraste: el amarillo viejo #ffd166 solo puede aparecer como definición de la variable --yellow; en las plantillas se usa var(--yellow) (que en las pantallas con estilo nuevo pasa a --atencion, 5:1)."""
import re

from test_front_analisis import INDEX


def test_no_quedan_amarillos_fijos_en_las_plantillas():
    s = open(INDEX, encoding='utf-8').read()
    sueltos = [m.group(0) for m in re.finditer(r'.{25}#ffd166', s) if '--yellow:' not in m.group(0)]
    assert sueltos == []
