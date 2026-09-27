"""Corrida diaria ECOM: ciclo 23 → 22 hasta ayer, guardado bajo la etiqueta
del ciclo completo."""
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from rentabilidad.adapters import (
    ClasificacionProvider,
    IvaProvider,
    MargenObjetivoProvider,
    StockProvider,
    VinculacionProvider,
)
from rentabilidad.cierre_ecom_diario import ayer_en_argentina, ciclo_de, correr, formatear
from rentabilidad.ingesta_ecom import FilaEcom, ResultadoIngestaEcom
from rentabilidad.models import CierreRentabilidad, VentaEcom


def test_ciclo_de_un_dia_desde_el_23():
    assert ciclo_de(date(2026, 9, 26)) == (date(2026, 9, 23), date(2026, 10, 22))


def test_ciclo_de_un_dia_antes_del_23_es_el_del_mes_anterior():
    assert ciclo_de(date(2026, 10, 22)) == (date(2026, 9, 23), date(2026, 10, 22))
    assert ciclo_de(date(2026, 6, 1)) == (date(2026, 5, 23), date(2026, 6, 22))


def test_ciclo_de_cruza_el_anio():
    assert ciclo_de(date(2026, 12, 30)) == (date(2026, 12, 23), date(2027, 1, 22))
    assert ciclo_de(date(2027, 1, 5)) == (date(2026, 12, 23), date(2027, 1, 22))


def test_ayer_se_calcula_en_hora_argentina():
    # 02:00 UTC del 28/09 = 23:00 ART del 27/09 → ayer es el 26/09
    assert ayer_en_argentina(datetime(2026, 9, 28, 2, 0, tzinfo=timezone.utc)) == date(2026, 9, 26)


def _fila(numero_orden, **overrides):
    base = dict(
        numero_orden=numero_orden, skus_vendidos="SKU-1", canal_de_venta="Mercadolibre Carrito",
        estado_pago="Cobrado", costo_sin_iva=Decimal("10"), comision_venta=Decimal("1000"),
        costo_envio=Decimal("0"), precio_sin_iva=Decimal("50000"), precio_final=Decimal("60500"),
        tc=Decimal("1540"), origen_comision="API",
    )
    base.update(overrides)
    return FilaEcom(**base)


class _AdaptadorFake:
    def __init__(self, ingesta):
        self.ingesta, self.pedidos = ingesta, []

    def periodo(self, desde, hasta, tc):
        self.pedidos.append((desde, hasta, tc))
        return self.ingesta


def _providers():
    return dict(
        clasificacion_provider=ClasificacionProvider(sheet_id=None),
        vinculacion_provider=VinculacionProvider(sheet_id=None),
        stock_provider=StockProvider(sheet_id=None),
        margen_provider=MargenObjetivoProvider(sheet_ids={}, sheet_master_id=None),
    )


def _ingesta():
    return ResultadoIngestaEcom(
        lineas=[_fila("1"), _fila("2", canal_de_venta="Fravega", origen_comision="ESTIMADO_FRAVEGA",
                                 orden_externa="v1frvg-01", comision_venta=Decimal(0))],
        excluidas_por_estado_pago=[_fila("3", estado_pago="Reembolsado")],
        incidencias_costo=[_fila("4", skus_vendidos="MADRE-SKU", costo_sin_iva=Decimal(0), incidencia="COSTO_NO_RESUELTO")],
    )


def test_correr_trae_del_inicio_del_ciclo_hasta_ayer_y_guarda_con_la_etiqueta_del_ciclo(db_session):
    adaptador = _AdaptadorFake(_ingesta())
    resumen = correr(db_session, adaptador, Decimal("1540"), IvaProvider(), _providers(), hasta=date(2026, 9, 26))
    db_session.flush()

    assert adaptador.pedidos == [(date(2026, 9, 23), date(2026, 9, 26), Decimal("1540"))]
    assert resumen.periodo == "2026-09-23_2026-10-22"
    assert {v.periodo for v in db_session.query(VentaEcom).all()} == {"2026-09-23_2026-10-22"}
    cierre = db_session.get(CierreRentabilidad, "2026-09-23_2026-10-22")
    assert cierre.ecom_guardado and cierre.ecom_origen == "api" and cierre.hasta == date(2026, 9, 26)

    assert resumen.ordenes == 3  # 1, 2 y la incidencia 4 (no excluida, sin rentabilidad)
    assert resumen.excluidas_por_estado_pago == 1
    assert resumen.costo_cero == [("4", "MADRE-SKU")]
    assert resumen.fravega_estimadas == 1
    assert resumen.facturacion == Decimal("60500") * 3


def test_correr_al_dia_siguiente_reemplaza_el_ciclo_sin_duplicar(db_session):
    for hasta in (date(2026, 9, 26), date(2026, 9, 27)):
        correr(db_session, _AdaptadorFake(_ingesta()), Decimal("1540"), IvaProvider(), _providers(), hasta=hasta)
        db_session.flush()
    assert db_session.query(VentaEcom).count() == 4


def test_solo_consulta_no_escribe_nada(db_session):
    resumen = correr(db_session, _AdaptadorFake(_ingesta()), Decimal("1540"), IvaProvider(), _providers(),
                     hasta=date(2026, 6, 1), desde=date(2026, 6, 1), guardar=False)
    assert resumen.periodo == "2026-06-01_2026-06-01"
    assert db_session.query(VentaEcom).count() == 0
    assert "SOLO CONSULTA" in formatear(resumen)
    assert "COSTO 0" in formatear(resumen)


def test_guardar_un_rango_parcial_se_rechaza_para_no_duplicar(db_session):
    with pytest.raises(ValueError, match="rango parcial"):
        correr(db_session, _AdaptadorFake(_ingesta()), Decimal("1540"), IvaProvider(), _providers(),
               hasta=date(2026, 9, 26), desde=date(2026, 9, 25))
