"""Motor de Precios, rendimiento: el cálculo por lote usa fotos en memoria (sin leer Táctica, Ecom ni el BNA en vivo) y da EXACTAMENTE los mismos precios que antes."""
import time
from decimal import Decimal as D
from itertools import product

import pytest
from fastapi.testclient import TestClient

import ayala_core
import main
from rentabilidad import costos_ecom, tc_bna

COSTOS = {sku: D(str(round(9 + i * 3.37, 2))) for i, sku in enumerate(ayala_core.SKUS_PILOTO)}
IVA = {sku: (D("1.105") if i % 3 == 0 else D("1.21")) for i, sku in enumerate(ayala_core.SKUS_PILOTO)}
TC = D("1450.5")


class _Costo:
    def precargar(self): pass
    def obtener(self, sku): return COSTOS.get(sku)


class _Iva:
    tactica_caida = False
    def precargar(self): pass
    def factor(self, sku): return IVA.get(sku)


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setattr(main.costos_ecom, "proveedores_de_costo_e_iva", lambda: (_Costo(), _Iva()))
    monkeypatch.setattr(main, "tc_info_rapido", lambda: {"tc": TC, "source": "cache", "fecha": None})
    return TestClient(main.app)


def _qs(renta, envio, full):
    p = {f"renta_{k}": v for k, v in renta.items()}
    if envio is not None:
        p["envio_real"] = envio
    p["envio_full"] = str(full).lower()
    return p


RENTAS = [
    {"contado": 32, "reducida": 32, 3: 30, 6: 28, 9: 26, 12: 24},
    {"contado": 18.5, "reducida": 17, 3: 15.25, 6: 14, 9: 12.5, 12: 10},
    {"contado": 40, "reducida": 38, 3: 36, 6: 34, 9: 32, 12: 30},
]


@pytest.mark.parametrize("renta,envio,full", list(product(RENTAS, [None, 0, 8500, 12345.67], [False, True])))
def test_el_lote_da_el_mismo_precio_al_peso_que_el_calculo_de_siempre_para_cada_sku_y_condicion(cliente, renta, envio, full):
    r = cliente.get("/ayala-core/motor-lote", params=_qs(renta, envio, full))
    assert r.status_code == 200, r.text
    res = {x["sku"]: x for x in r.json()["resultados"]}
    assert list(res) == ayala_core.SKUS_PILOTO
    renta_dec = {("contado" if k == "contado" else "reducida" if k == "reducida" else int(k)): D(str(v)) for k, v in renta.items()}
    for sku in ayala_core.SKUS_PILOTO:
        esperado = ayala_core.calcular_precios_todas_condiciones(
            costo_sin_iva=COSTOS[sku] * TC, iva_factor=IVA[sku], envio_real=D(str(envio)) if envio is not None else D(0), renta_por_condicion=renta_dec, envio_full=full)
        assert res[sku]["precios"] == {k: float(v) for k, v in esperado.items()}, sku
        # y es idéntico al endpoint por SKU que ya existía
        uno = cliente.get(f"/ayala-core/sku/{sku}/motor", params=_qs(renta, envio, full)).json()
        assert uno["precios"] == res[sku]["precios"] and uno["costo_sin_iva_ars"] == res[sku]["costo_sin_iva_ars"]


def test_un_sku_sin_costo_no_tumba_a_los_demas(cliente, monkeypatch):
    monkeypatch.setitem(COSTOS, ayala_core.SKUS_PILOTO[0], None)
    r = cliente.get("/ayala-core/motor-lote").json()["resultados"]
    assert "SIN_COSTO" in r[0]["error"] and all("precios" in x for x in r[1:])


def test_el_lote_no_lee_nada_en_vivo_y_responde_en_menos_de_un_segundo(monkeypatch):
    """Con las fotos cargadas, un cálculo no toca Táctica (SQL), ni Ecom, ni el BNA."""
    def _prohibido(*a, **k): raise AssertionError("lectura en vivo dentro de un cálculo")
    import rentabilidad.adapters as ad
    monkeypatch.setattr(ad, "_consultar_catalogo_tactica_real", _prohibido)
    monkeypatch.setattr(costos_ecom, "descargar_catalogo", _prohibido)
    monkeypatch.setattr(tc_bna._cliente_default, "_fetch_html", _prohibido)
    cat = costos_ecom.CatalogoCostos(costos=dict(COSTOS), iva={k: v for k, v in IVA.items()}, obtenido_en=time.time())
    monkeypatch.setattr(costos_ecom, "obtener_catalogo", lambda *a, **k: cat)
    costos_ecom.limpiar_iva_tactica()
    assert costos_ecom.refrescar_iva_tactica(consultar=lambda: [{"sku": f"{k} ", "iva_descripcion": "IVA Debito 10.5%" if v == D("1.105") else "IVA Debito 21%"} for k, v in IVA.items()])
    monkeypatch.setattr(tc_bna._cliente_default, "_valor", TC); monkeypatch.setattr(tc_bna._cliente_default, "_vence", time.time() + 3600)
    t0 = time.perf_counter()
    r = TestClient(main.app).get("/ayala-core/motor-lote")
    assert r.status_code == 200, r.text
    assert time.perf_counter() - t0 < 1.5 and r.json()["tiempos_ms"]["total"] < 1000
    cc = r.json()["calculado_con"]
    assert cc["iva"] == "TACTICA" and cc["tc"] == float(TC) and cc["iva_tactica_antiguedad_seg"] is not None
    costos_ecom.limpiar_iva_tactica()


def test_sin_foto_de_tactica_el_iva_sale_de_ecom_y_se_avisa_sin_esperar(monkeypatch):
    costos_ecom.limpiar_iva_tactica()
    cat = costos_ecom.CatalogoCostos(costos=dict(COSTOS), iva=dict(IVA), obtenido_en=time.time())
    monkeypatch.setattr(costos_ecom, "obtener_catalogo", lambda *a, **k: cat)
    monkeypatch.setattr(main, "tc_info_rapido", lambda: {"tc": TC, "source": "cache", "fecha": None})
    t0 = time.perf_counter()
    r = TestClient(main.app).get("/ayala-core/motor-lote").json()
    assert time.perf_counter() - t0 < 1.5
    assert r["calculado_con"]["iva"] == "ECOM" and all("precios" in x for x in r["resultados"])


def test_refrescar_iva_tactica_guarda_la_foto_y_un_error_conserva_la_anterior_con_causa_clara():
    costos_ecom.limpiar_iva_tactica()
    assert costos_ecom.refrescar_iva_tactica(consultar=lambda: [{"sku": "A  ", "iva_descripcion": "IVA Debito 21%"}])
    assert costos_ecom.IvaTacticaFoto().factor("A") == D("1.21") and costos_ecom.estado_iva_tactica()["cantidad"] == 1
    def cae(): raise RuntimeError("DB-Lib error 20009: Unable to connect: Adaptive Server is unavailable (10.10.10.99)")
    costos_ecom.refrescar_iva_tactica(consultar=cae)
    e = costos_ecom.estado_iva_tactica()
    assert e["hay_foto"] and e["ultimo_error"] == "no se pudo conectar (¿VPN apagada o túnel caído?)" and "10.10" not in e["ultimo_error"]
    assert costos_ecom.IvaTacticaFoto().factor("A") == D("1.21")
    costos_ecom.limpiar_iva_tactica()


def test_el_tc_vencido_no_espera_a_la_red():
    llamadas = []
    reloj = {"t": 1000.0}
    c = tc_bna.TcBnaClient(fetch_html=lambda: llamadas.append(1) or "Dolar U.S.A</td><td>1.400,00</td><td>1.450,00</td>", ahora=lambda: reloj["t"],
                           leer_ultimo=lambda: None)
    assert c.obtener_info_rapido()["tc"] == D("1450.00") and len(llamadas) == 1       # primera vez de la historia: sí lee
    reloj["t"] += 7200                                                                   # venció
    info = c.obtener_info_rapido()
    assert info["tc"] == D("1450.00") and info["source"] == "cache"                      # responde con el valor viejo, sin esperar
    for _ in range(50):
        if len(llamadas) >= 2: break
        time.sleep(0.02)
    assert len(llamadas) == 2                                                            # y se refrescó aparte


def test_el_tc_guardado_responde_sin_leer_el_bna():
    from datetime import datetime, timezone
    llamadas = []
    c = tc_bna.TcBnaClient(fetch_html=lambda: llamadas.append(1) or "x", leer_ultimo=lambda: (D("1400"), datetime.now(timezone.utc)))
    info = c.obtener_info_rapido()
    assert info["tc"] == D("1400") and info["source"] == "ultimo_guardado"


def test_la_pantalla_pide_un_lote_y_recalcula_sola_sin_pisar_el_ver_cargado():
    s = open(main.__file__.replace('backend/main.py', 'docs/index.html'), encoding='utf-8').read()
    f = s[s.index('async function ayalaCoreCalcular'):s.index('// Pedido de Maxx 2026-09-21: túnel Táctica caído')]
    assert '/ayala-core/motor-lote?' in f and 'for(const s of AC_SKUS)' not in f and 'AC_CALC_SEQ' in f and 'ayalaCoreCalculadoConHtml' in f
    assert 'AC_AUTO_OK=false' in s[s.index('function ayalaCoreVerCargado'):][:120]
    assert "ayalaCoreAutoRecalcularMontar" in s and "setTimeout(()=>ayalaCoreCalcular(),300)" in s
    assert 'IVA tomado de Ecom: Táctica no respondió' in s and 'IVA Táctica: hace' in s.replace("IVA Táctica: ${costosEdadTxt", "IVA Táctica: hace")
