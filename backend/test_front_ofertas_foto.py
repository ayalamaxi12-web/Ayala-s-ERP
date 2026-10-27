"""Pantalla «Precios y ofertas ML»: muestra la foto guardada con fecha y hora, se engancha a una lectura en curso y «Actualizar ahora» incluye los descuentos propios."""
import os

SRC = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'docs', 'index.html'), encoding='utf-8').read()


def test_al_abrir_se_lee_la_foto_del_servidor_antes_que_la_del_navegador():
    fn = SRC.split("async function ofmReconectarJobActivo")[1][:900]
    assert fn.index("await ofmFotoCargar()") < fn.index("localStorage.getItem(OFM_RESULT_KEY)")


def test_la_foto_se_pide_barata_primero_y_muestra_fecha_hora_y_aviso_de_falla():
    f = SRC.split("async function ofmFotoCargar")[1].split("\n}\n")[0]
    assert "/ml-ofertas/foto?meta=true" in f and "m.obtenido_en!==OFM_FOTO_TS" in f and "m.job_id" in f
    i = SRC.split("function ofmFotoInfo")[1].split("\n}\n")[0]
    assert "Última actualización" in i and "America/Argentina/Buenos_Aires" in i and "falló la última actualización" in i and "se actualiza sola todos los días" in i


def test_actualizar_ahora_arranca_tildado_con_los_descuentos_propios():
    assert 'id="ofm-incluir-propias" checked' in SRC and "Actualizar ahora</button>" in SRC and 'id="ofm-foto-info"' in SRC


def test_la_pagina_tiene_cabecera_limpia_cuenta_segmentada_y_secciones_plegadas():
    pag = SRC[SRC.index('id="page-ofertas-margen"'):SRC.index('<!-- Motor de precios, etapa 2')]
    assert '<h2 class="ofm-tit">Precios y ofertas ML</h2>' in pag and "📊" not in pag and "📦" not in pag and "🔎" not in pag and "🔔" not in pag and "💸" not in pag
    assert pag.count('<details class="ofm-sec">') == 3                                       # buscar, candidatos y costos de envío: plegados por defecto
    assert 'id="ofm-tab-IT" aria-pressed="true"' in pag and "setAttribute('aria-pressed'" in SRC.split("function ofmTab(cuenta)")[1][:300]
    for i in ("ofm-buscar-mla", "ofm-alertas-tbody", "btn-ofm-costos-envio", "ofm-operador", "ofm-incluir-propias", "btn-ofm-run"):
        assert f'id="{i}"' in pag, i                                                         # mismos ids: nada se rompe
