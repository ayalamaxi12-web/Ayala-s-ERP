from types import SimpleNamespace

import ml_ofertas as mo


def test_costo_de_un_envio_ya_hecho_se_pide_a_ml_una_sola_vez(monkeypatch):
    mo._costo_por_envio.clear()
    llamadas = []

    class _ML:
        def _token(self, cuenta): return "t"

        def _get(self, url, params, headers):
            llamadas.append(url)
            return {"lead_time": {"cost_type": "free", "list_cost": 8890}}
    a = mo.costo_envio_real(_ML(), "IT", 111, mo._costo_por_envio)
    b = mo.costo_envio_real(_ML(), "IT", 111, mo._costo_por_envio)
    assert a == b == {"cost_type": "free", "costo_envio_real": 8890.0} and len(llamadas) == 1


def test_lote_de_envios_de_referencia(monkeypatch):
    import main
    mo._ultima_venta_cache.clear()
    mo._ultima_venta_cache["MLA1"] = {"cuenta": "IT", "shipping_id": 1, "orden_id": 9, "fecha": "2026-11-10"}
    monkeypatch.setattr(mo, "costo_envio_real_item", lambda ml, item, cuenta, memo=None: {"cost_type": "free", "costo_envio_real": 8500.0, "orden_id": 9, "fecha_venta": "2026-11-10"})
    r = main._costos_envio_lote_sync([{"item_id": "MLA1", "cuenta": "IT"}, {"item_id": "MLA2", "cuenta": "IT"}])
    assert r["costos"] == {"MLA1": {"cost_type": "free", "costo_envio_real": 8500.0, "fecha_venta": "2026-11-10"}}
    assert r["estado"] == {"requeridos": 2, "resueltos": 1, "sin_venta": 1, "barrido_hecho": True}
    mo._ultima_venta_cache.clear()
    assert main._costos_envio_lote_sync([{"item_id": "MLA1"}])["estado"]["barrido_hecho"] is False      # sin barrido no hay referencia


def test_front_pm_esperado_suma_el_envio_solo_desde_el_umbral_y_con_el_real_si_lo_hay():
    import json
    import os
    import subprocess
    from scripts.paridad_margenes import extraer_funcion
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'docs', 'index.html'), encoding='utf-8').read()
    js = ("const normSku=s=>String(s).toLowerCase();const S={pmData:{a:{ml:231499},b:{ml:20000}},shippingThreshold:33000,shippingCost:8500};const CUOTAS_PCT_ML={3:8.5};const OFM_ENVIO_REF={MLA1:{cost_type:'free',costo_envio_real:7000}};"
          + ''.join(extraer_funcion(src, n) + '\n' for n in ('ofmEnvioParaEsperado', 'ofmPrecioEsperadoPM')) + """
const f=(id,sku,po,extra)=>({item_id:id,sku,precio_oferta:po,precio_normal:po,...extra});
console.log(JSON.stringify([
 ofmPrecioEsperadoPM(f('MLA1','a',239999)),                                            // referencia real de la última venta: 231.499 + 7.000
 ofmPrecioEsperadoPM(f('MLA2','a',239999)),                                            // sin referencia: estimado 8.500 → 239.999 (la diferencia da 0)
 ofmPrecioEsperadoPM(f('MLA3','b',20000)),                                             // bajo el umbral: sin envío
 ofmPrecioEsperadoPM(f('MLA4','a',239999,{costo_envio_real:{cost_type:'free',costo_envio_real:6000}})),   // el de Gestionar manda
 ofmPrecioEsperadoPM(f('MLA5','a',239999,{costo_envio_real:{cost_type:'charged',costo_envio_real:0}}))]));""")
    r = json.loads(subprocess.run(['node', '-e', js], capture_output=True, text=True, check=True).stdout)
    assert r == [238499, 239999, 20000, 237499, 231499]
