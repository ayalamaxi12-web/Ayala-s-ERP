"""«Ventas de hoy» (en vivo, solo lectura): mismo criterio que el reporte diario, por canal."""
from datetime import date, datetime, timezone
from decimal import Decimal

from rentabilidad import ventas_hoy as vh
from rentabilidad.models import VentaEcom

HOY = date(2026, 10, 26)


def _v(orden, pf, rent, sku="SKU-A", canal="Mercadolibre Carrito", dia=HOY, **kw):
    base = dict(periodo="p", numero_orden=orden, skus_vendidos=sku, fecha_creacion_venta=dia, costo_sin_iva=Decimal(1), comision_venta=Decimal(0), costo_envio=Decimal(0),
                precio_final=Decimal(pf), precio_sin_iva=Decimal(pf) / Decimal("1.21"), rentabilidad=None if rent is None else Decimal(rent), tc=Decimal(1500), canal_de_venta=canal,
                es_full=False, origen_comision="API", excluido=False)
    base.update(kw)
    return VentaEcom(**base)


def test_la_fecha_es_la_argentina_y_no_la_utc():
    # 01:00 UTC del 27 son las 22:00 del 26 en Argentina
    assert vh.hoy_en_argentina(datetime(2026, 10, 27, 1, 0, tzinfo=timezone.utc)) == date(2026, 10, 26)
    assert vh.hoy_en_argentina(datetime(2026, 10, 27, 3, 0, tzinfo=timezone.utc)) == date(2026, 10, 27)


def test_canales():
    assert [vh.canal_de(c) for c in ("Mercadolibre Carrito", "Mercadolibre", "Woocommerce", "Fravega", "OnCity", "Megatone", "Posventa", "", None)] == \
        ["ml", "ml", "web", "fravega", "oncity", "megatone", "otros", "otros", "otros"]


def test_total_y_canales_con_y_sin_iva_renta_y_top_5():
    ventas = [_v("1", "12100", "1000", "TONER-1"), _v("2", "24200", "-500", "PLANCHA-1"), _v("3", "13310", "800", "TONER-1"),
              _v("4", "60500", "9000", "NOTE-1", canal="Fravega"), _v("5", "1210", "100", "WEB-1", canal="Woocommerce"),
              _v("6", "999", "9", excluido=True), _v("7", "999", "9", dia=date(2026, 10, 25))]   # excluida y de ayer: no cuentan
    r = vh.armar_ventas_hoy(ventas, HOY)
    tar = {t["clave"]: t for t in r["tarjetas"]}
    assert list(tar) == ["total", "ml", "web", "fravega"]
    t = tar["total"]
    assert t["facturacion"] == 111320.0 and t["ordenes"] == 5
    assert t["facturacion_sin_iva"] == 92000.0 and t["rentabilidad"] == 10400.0
    assert t["rentabilidad_pct"] == round(10400 / 92000 * 100, 2)
    ml = tar["ml"]
    assert ml["facturacion"] == 49610.0 and ml["ordenes"] == 3
    assert [x["sku"] for x in ml["top_skus"]] == ["TONER-1", "PLANCHA-1"]          # por monto cobrado
    toner = ml["top_skus"][0]
    assert toner["facturacion"] == 25410.0 and toner["facturacion_sin_iva"] == 21000.0 and toner["rentabilidad"] == 1800.0 and toner["ordenes"] == 2
    assert tar["fravega"]["top_skus"][0]["sku"] == "NOTE-1"


def test_top_5_y_tarjetas_fijas_aunque_no_haya_ventas():
    ventas = [_v(str(i), 1000 * (i + 1), "1", f"S{i}") for i in range(8)]
    r = vh.armar_ventas_hoy(ventas, HOY)
    assert [x["sku"] for x in r["tarjetas"][1]["top_skus"]] == ["S7", "S6", "S5", "S4", "S3"]
    vacio = {t["clave"]: t for t in vh.armar_ventas_hoy([], HOY)["tarjetas"]}
    assert set(vacio) == {"total", "ml", "web", "fravega"} and vacio["web"]["facturacion"] == 0 and vacio["web"]["top_skus"] == [] and vacio["web"]["rentabilidad_pct"] is None


def test_un_canal_desconocido_va_a_otros_y_las_ordenes_sin_costo_se_cuentan():
    r = vh.armar_ventas_hoy([_v("1", "1210", None, canal="Posventa", costo_sin_iva=Decimal(0))], HOY)
    otros = [t for t in r["tarjetas"] if t["clave"] == "otros"][0]
    assert otros["sin_costo"] == 1 and otros["facturacion"] == 1210.0


def test_endpoint_usa_el_cache_de_60_segundos_y_no_toca_ecom_dos_veces(monkeypatch):
    from rentabilidad import api
    llamadas = []

    class FakeAdapter:
        def periodo(self, desde, hasta, tc):
            llamadas.append((desde, hasta))
            from types import SimpleNamespace
            return SimpleNamespace(excluidas_por_estado_pago=[], incidencias_costo=[])

    monkeypatch.setattr(api, "EcomApiAdapter", FakeAdapter)
    monkeypatch.setattr(api, "_resolver_tc", lambda tc: Decimal(1500))
    monkeypatch.setattr(api, "_fetch_fn_con_cache", lambda *a, **k: None)
    monkeypatch.setattr(api, "_consultar_catalogo_tactica_con_cache", lambda *a, **k: None)
    monkeypatch.setattr(api, "IvaProvider", lambda **k: None)
    monkeypatch.setattr(api, "_providers_ecom", lambda f: {})
    from types import SimpleNamespace
    monkeypatch.setattr(api, "construir_filas_ecom", lambda db, ing, iva, **k: SimpleNamespace(filas=[_v("1", "12100", "1000", dia=api._ventas_hoy.hoy_en_argentina())]))
    api._ventas_hoy_cache.update(ts=0.0, dia=None, payload=None)
    a = api.ventas_hoy()
    b = api.ventas_hoy()
    c = api.ventas_hoy(forzar=True)           # dentro de los 15 s mínimos: tampoco vuelve a Ecom
    assert len(llamadas) == 1 and a["cache_seg"] == 0 and b["cache_seg"] <= 1 and c["cache_seg"] <= 1
    assert a["tarjetas"][0]["facturacion"] == 12100.0
    assert a["tarjetas"][0]["rentabilidad_pct"] is not None
