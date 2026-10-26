"""Full ML, simulador: «Por qué», columnas nuevas, selección y exportación (funciones JS extraídas de docs/index.html y corridas con node)."""
import json
import subprocess

from test_front_analisis import INDEX, _fn

SRC = open(INDEX, encoding="utf-8").read()


def _porque(fila, pend=0):
    js = "let fullRepoEnviosPend={};" + _fn(SRC, "fullFechaCorta") + _fn(SRC, "fullRepoPorQue") + f"\nconst f={json.dumps(fila)};fullRepoEnviosPend[f.item_id]={pend};console.log(fullRepoPorQue(f));"
    return subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout.strip()


BASE = {"item_id": "M1", "flags": [], "ventas_diarias": 2, "_objetivo": 42, "_aLlegada": 0, "_necesarioReal": 42, "_sugerido": 42, "_cantidadEnviar": 42, "_disp": 100}


def test_motivos_de_quiebre_y_de_deposito_parcial():
    q = _porque({**BASE, "censurado": True, "ventas_full": 50, "primera_venta": "2026-10-01", "ultima_venta": "2026-10-11", "ventas_diarias": 5, "dias_periodo": 30})
    assert "quebró stock en Full: 50 ventas entre 01/10/2026 y 11/10/2026" in q and "5/día (no 1.7)" in q
    d = _porque({**BASE, "deposito_usado": 27, "ventas_deposito": 90})
    assert "30 % de lo que vende desde mi depósito (90 u.)" in d


def test_motivos_en_texto():
    assert _porque(BASE) == ""
    assert _porque({**BASE, "ventas_diarias": 0, "_necesarioReal": 0, "_sugerido": 0, "_cantidadEnviar": 0}) == "sin ventas en el período"
    assert _porque({**BASE, "_necesarioReal": 0, "_sugerido": 0, "_cantidadEnviar": 0, "_aLlegada": 50}) == "Full ya cubre el objetivo"
    assert _porque({**BASE, "_necesarioReal": 0, "_sugerido": 0, "_cantidadEnviar": 0}, pend=50) == "el envío pendiente cubre"
    assert _porque({**BASE, "_sugerido": 0, "_disp": 0}) == "sin disponible en Pitec ni Táctica"
    assert _porque({**BASE, "_sugerido": 0}) == "el disponible se asignó a otra publicación del mismo SKU"
    assert _porque({**BASE, "_sugerido": 10}) == "el disponible alcanza solo en parte"
    assert _porque({**BASE, "flags": ["no_full", "sin_vincular"]}) == "sin vincular en Ecom (factor 1 asumido) · hay que habilitarla en Mercado Libre"
    assert _porque({**BASE, "flags": ["sin_sku"], "_sugerido": 0, "_disp": 0}).startswith("sin SKU")
    assert "sin match en Ecom" in _porque({**BASE, "flags": ["sin_ecom"], "_sugerido": 0, "_disp": 0})


def test_pantalla_columnas_interruptor_y_exportacion():
    for t in ("Ventas Full 30d", "Ventas mi depósito 30d", "Demanda usada", "<th>En Full</th>", "<th>Por qué</th>", 'id="full-repo-deposito" checked', "Usar ventas de mi depósito como referencia", "full-repo-frac"):
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


def test_periodo_visible_y_ver_detalle():
    for t in ("Período leído de Mercado Libre: del", "fullRepoDetalle(this,", "/ml-full/foto/detalle/", "no disponible"):
        assert t in SRC, t


def test_layout_kpi_titulo_con_logo_actualizar_arriba_y_scroll_en_caja():
    assert "kpi-card::after{content:'';grid-row:1/span 3;grid-column:1;justify-self:center;align-self:center" in SRC      # el glifo ya no depende del alto de toda la tarjeta
    assert ".section-hdr:has(>img,>svg,>[data-ico]){display:flex;align-items:center;gap:14px" in SRC
    assert SRC.index('id="full-reposicion-pie"') < SRC.index('id="full-reposicion-tbody"') and SRC.index('id="full-conciliar-pie"') < SRC.index('id="full-conciliar-tbody"')
    assert "#full-reposicion-wrap)>.table-wrap{max-height:calc(100vh - 9rem);overflow:auto}" in SRC


def _objetivo(fila, sem, fecha, params, hoy="2026-10-26"):
    js = ("const _q={'full-repo-semanas':{value:'%s'},'full-repo-fecha-llegada':{value:'%s'}};const qs=i=>_q[i];" % (sem, fecha)
          + "const fullRepoResult={params:%s};" % json.dumps(params)
          + "const _D=Date;Date=class extends _D{constructor(...a){a.length?super(...a):super('%sT00:00:00')}};" % hoy
          + _fn(SRC, "fullRepoObjetivo") + f"\nconst f={json.dumps(fila)};fullRepoObjetivo(f);console.log(JSON.stringify([f._objetivo,f._aLlegada]));")
    return json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)


def test_semanas_y_fecha_recalculan_sin_actualizar():
    fila = {"ventas_diarias_exacta": 0.5, "ventas_diarias": 0.5, "stock_full": 20, "stock_objetivo": 7.0, "stock_a_llegada": 14.0}
    params = {"semanas_objetivo": 2, "fecha_llegada": "2026-11-03"}
    assert _objetivo(fila, "2", "2026-11-03", params) == [7.0, 14.0]          # mismos valores que la lectura: números del servidor
    assert _objetivo(fila, "3", "2026-11-03", params) == [10.5, 16.0]         # 0,5/día × 3 semanas × 7; en Full 20 − 0,5 × 8 días = 16
    assert _objetivo({**fila, "ventas_diarias_exacta": None}, "3", "2026-11-03", params) == [7.0, 14.0]     # lectura vieja sin dato exacto: no se inventa nada

def test_filtros_para_revisar_y_seleccion_para_enviar_son_cosas_distintas():
    for t in ('id="full-repo-filtros"', "Para revisar (solo cambia lo que ves)", "Para enviar (marca filas)", "fullRepoSeleccionar('visibles-sugerido')", "Nuevos: sin historial en Full"):
        assert t in SRC, t
    # el filtro no toca la selección: solo las acciones de «Para enviar» y el casillero de la cabecera cambian fullRepoSeleccion
    assert "fullRepoSeleccion" not in _fn(SRC, "fullRepoSetFiltro") and "fullRepoVisibles()" in _fn(SRC, "fullRepoSeleccionar") and "fullRepoVisibles()" in _fn(SRC, "fullRepoToggleAll")

def test_pdf_de_envio_pendiente_acepta_varios_y_los_suma():
    assert 'id="full-repo-pdf-input" accept="application/pdf" multiple' in SRC
    f = _fn(SRC, "fullRepoSubirPDF")
    assert "suma[inv]=(suma[inv]||0)+u" in f and "for(const file of files)" in f
