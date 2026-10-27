"""«Poner precio» en Precios y ofertas ML (docs/index.html): apagado por defecto, bloqueado con promoción en curso, operador y confirmación, y el nombre nuevo del módulo."""
import os

INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'docs', 'index.html')
SRC = open(INDEX, encoding='utf-8').read()


def test_el_modulo_se_llama_precios_y_ofertas_ml():
    assert 'data-page="ofertas-margen"' in SRC and 'Precios y ofertas ML</a>' in SRC


def test_la_escritura_arranca_apagada_y_exige_operador_y_confirmacion():
    assert "localStorage.getItem('ofm_poner_precio')==='1'" in SRC
    fn = SRC.split("async function ofmConfirmarPoner")[1].split("\n}\n")[0]
    assert "ofmRequireOperador()" in fn and "!ofmPonerHabilitado()" in fn and "confirm(msg)" in fn
    assert "origen:'Precios y ofertas ML'" in fn and "bajo_umbral" in fn and "margen_pct" in fn
    assert "No se reintenta solo" in fn          # nunca reintenta solo
    assert "precio_tachado" not in fn            # solo precio de lista


def test_con_promocion_en_curso_el_boton_queda_desactivado():
    assert "promociones.some(p=>p.status==='started')" in SRC and "data-pp-bloqueo" in SRC
    assert "btn.disabled=!c.precio||bloqueada||!ofmPonerHabilitado()" in SRC


def test_el_aviso_bajo_umbral_no_depende_solo_del_color():
    fn = SRC.split("function ofgMargenHtml")[1].split("\n}\n")[0]
    assert "Bajo el umbral" in fn and "ofg-mg-bajo" in fn
    assert any("border:2px solid var(--error)" in c for c in SRC.split("\n") if c.startswith(".ofg-mg-bajo"))
    assert "Confirmar igual (bajo umbral)" in SRC.split("function ofmSimularPoner")[1].split("\n}\n")[0]


def test_el_panel_gestionar_tiene_pestanas_accesibles_y_la_cuenta_plegada():
    assert 'role="tablist"' in SRC and 'role="tab"' in SRC and 'role="tabpanel"' in SRC and "function ofgTabKey" in SRC
    assert "<details class=\"ofg-det\"><summary>Ver la cuenta</summary>" in SRC
    css = " ".join(c for c in SRC.split("\n") if c.startswith(".ofg"))
    import re
    assert css and not re.search(r"#[0-9a-fA-F]{3,8}\b", css)         # solo tokens
