"""Full ML, simulador: «Por qué», columnas nuevas, selección y exportación (funciones JS extraídas de docs/index.html y corridas con node)."""
import json
import subprocess

from test_front_analisis import INDEX, _fn

SRC = open(INDEX, encoding="utf-8").read()


def _porque(fila, pend=0):
    js = "let fullRepoEnviosPend={};" + _fn(SRC, "fullRepoPorQue") + f"\nconst f={json.dumps(fila)};fullRepoEnviosPend[f.item_id]={pend};console.log(fullRepoPorQue(f));"
    return subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout.strip()


BASE = {"item_id": "M1", "flags": [], "ventas_diarias": 2, "stock_objetivo": 42, "stock_a_llegada": 0, "_necesarioReal": 42, "_sugerido": 42, "_cantidadEnviar": 42, "_disp": 100}


def test_motivos_en_texto():
    assert _porque(BASE) == ""
    assert _porque({**BASE, "ventas_diarias": 0, "_necesarioReal": 0, "_sugerido": 0, "_cantidadEnviar": 0}) == "sin ventas en el período"
    assert _porque({**BASE, "_necesarioReal": 0, "_sugerido": 0, "_cantidadEnviar": 0, "stock_a_llegada": 50}) == "Full ya cubre el objetivo"
    assert _porque({**BASE, "_necesarioReal": 0, "_sugerido": 0, "_cantidadEnviar": 0}, pend=50) == "el envío pendiente cubre"
    assert _porque({**BASE, "_sugerido": 0, "_disp": 0}) == "sin disponible en Pitec ni Táctica"
    assert _porque({**BASE, "_sugerido": 0}) == "el disponible se asignó a otra publicación del mismo SKU"
    assert _porque({**BASE, "_sugerido": 10}) == "el disponible alcanza solo en parte"
    assert _porque({**BASE, "flags": ["no_full", "sin_vincular"]}) == "sin vincular en Ecom (factor 1 asumido) · hay que habilitarla en Mercado Libre"
    assert _porque({**BASE, "flags": ["sin_sku"], "_sugerido": 0, "_disp": 0}).startswith("sin SKU")
    assert "sin match en Ecom" in _porque({**BASE, "flags": ["sin_ecom"], "_sugerido": 0, "_disp": 0})


def test_pantalla_columnas_interruptor_y_exportacion():
    for t in ("Ventas Full 30d", "Ventas mi depósito 30d", "Demanda usada", "<th>En Full</th>", "<th>Por qué</th>", 'id="full-repo-deposito" checked', "Contar ventas de mi depósito"):
        assert t in SRC, t
    assert "contar_deposito=${qs('full-repo-deposito')" in SRC
    assert "Ventas Full 30d,Ventas mi deposito 30d,Demanda usada" in SRC and ",Por que'" in SRC
    exp = _fn(SRC, "exportFullReposicionParaML")
    assert "f.inventory_id && f._sugerido>0" in exp                       # nunca líneas con cantidad 0
    assert "Math.max(0,grupo[0].stock_ecom||0)" in SRC                     # Ecom negativo = 0
    assert "sin dato de Táctica" in SRC


def test_el_script_principal_no_tiene_errores_de_sintaxis():
    """Un error de sintaxis deja la página muerta (nada de goPage): los tests de funciones sueltas no lo ven."""
    import re
    import tempfile
    big = max(re.findall(r"<script>(.*?)</script>", SRC, re.S), key=len)
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(big)
    r = subprocess.run(["node", "--check", f.name], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[:400]


def test_presentacion_celular_botones_tarjetas_y_sin_emojis():
    for t in ("--r-recuadro);white-space:normal", "@media (max-width:768px)", ".fr-fila{display:grid", 'class="fr-chip"', "Ver más", 'class="full-logo"', 'data-ico="zap"'):
        assert t in SRC, t
    a = SRC.index('id="page-full-ml"')
    bloque = SRC[a:SRC.index('id="page-', a + 20)]
    assert not re.search(r"[\U0001F300-\U0001FAFF⬆⬇]", bloque)      # sin emojis en el módulo


import re  # noqa: E402


def test_minimizar_buscar_y_trazabilidad():
    for t in ('id="full-min-conc"', 'id="full-min-repo"', 'aria-controls="full-cuerpo-repo"', 'id="full-repo-busq"', 'id="full-conc-busq"', "SALE_CONFIRMATION", "not_available_quantity"):
        assert t in SRC, t
    js = _fn(SRC, "fullCoincide")
    prueba = "const acNormTxt=t=>String(t||'').split('').map(c=>c.normalize('NFD').charAt(0).toLowerCase()).join('');" + js + \
        "console.log(JSON.stringify([fullCoincide('w1105 acomp',['MLA1','W1105ACOMP']),fullCoincide('abcb',['ABCB37443']),fullCoincide('zzz',['ABC']),fullCoincide('',['x'])]));"
    assert json.loads(subprocess.run(["node", "-e", prueba], capture_output=True, text=True, check=True).stdout) == [True, True, False, True]
