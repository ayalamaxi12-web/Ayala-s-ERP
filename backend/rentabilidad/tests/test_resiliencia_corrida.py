"""Bug real (corridas del 02 y 03/10/2026): una orden con `skus_vendidos`
de más de 1000 caracteres hizo fallar el INSERT y la corrida no guardó
nada (reporte diario en $0). La columna pasa a Text y la corrida saltea y
lista las órdenes que no puede procesar en vez de caerse entera."""
import os
import tempfile
from datetime import date
from decimal import Decimal

from alembic import command
from alembic.config import Config
from sqlalchemy import Text, create_engine, inspect

from rentabilidad import ingesta_ecom_api
from rentabilidad.adapters import IvaProvider
from rentabilidad.cierre_ecom_diario import correr, formatear
from rentabilidad.ingesta_ecom import ResultadoIngestaEcom
from rentabilidad.models import VentaEcom
from rentabilidad.persistencia import _recortar_largos
from rentabilidad.tests.test_cierre_ecom_diario import _AdaptadorFake, _fila, _providers
from rentabilidad.tests.test_migrations import RENTABILIDAD_DIR

SKUS_LARGOS = ", ".join(f"SKU-MUY-LARGO-{i:04d}" for i in range(80))  # ~1.600 caracteres


def test_skus_vendidos_largo_se_guarda_completo(db_session):
    assert len(SKUS_LARGOS) > 1000
    ingesta = ResultadoIngestaEcom(lineas=[_fila("1", skus_vendidos=SKUS_LARGOS)], excluidas_por_estado_pago=[], incidencias_costo=[])
    correr(db_session, _AdaptadorFake(ingesta), Decimal("1540"), IvaProvider(), _providers(), hasta=date(2026, 10, 2))
    db_session.flush()
    assert db_session.query(VentaEcom).one().skus_vendidos == SKUS_LARGOS


def test_columna_es_text_en_el_modelo_y_en_la_migracion():
    assert isinstance(VentaEcom.__table__.c.skus_vendidos.type, Text)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        url = f"sqlite:///{os.path.join(tmp, 'm.sqlite3')}"
        cfg = Config(str(RENTABILIDAD_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(RENTABILIDAD_DIR / "migrations"))
        cfg.set_main_option("sqlalchemy.url", url)
        command.upgrade(cfg, "head")
        engine = create_engine(url)
        try:
            col = next(c for c in inspect(engine).get_columns("venta_ecom") if c["name"] == "skus_vendidos")
        finally:
            engine.dispose()
    assert isinstance(col["type"], Text)


def test_una_orden_que_rompe_se_saltea_y_el_resto_se_guarda(db_session, monkeypatch):
    from rentabilidad import persistencia

    original = persistencia.construir_venta_ecom

    def construir(fila, *a, **k):
        if fila.numero_orden == "2":
            raise ValueError("dato inesperado")
        return original(fila, *a, **k)

    monkeypatch.setattr(persistencia, "construir_venta_ecom", construir)
    ingesta = ResultadoIngestaEcom(lineas=[_fila("1"), _fila("2"), _fila("3")], excluidas_por_estado_pago=[], incidencias_costo=[])
    resumen = correr(db_session, _AdaptadorFake(ingesta), Decimal("1540"), IvaProvider(), _providers(), hasta=date(2026, 10, 2))
    db_session.flush()
    assert sorted(v.numero_orden for v in db_session.query(VentaEcom).all()) == ["1", "3"]
    assert resumen.con_error == [("2", "ValueError: dato inesperado")]
    assert "ÓRDENES CON ERROR" in formatear(resumen)


def test_texto_mas_largo_que_su_columna_se_recorta_en_vez_de_romper():
    venta = VentaEcom(numero_orden="1", observacion="x" * 400, canal_de_venta="c" * 10)
    assert _recortar_largos(venta) == ["observacion"]
    assert len(venta.observacion) == 255 and venta.observacion.endswith("…")


def test_orden_ilegible_de_la_api_se_saltea(monkeypatch):
    ordenes = [{"id": "1", "customOrderId": "100"}, {"id": "2", "customOrderId": "200"}]

    def fila(orden, *a, **k):
        if orden["id"] == "2":
            raise TypeError("campo raro")
        return _fila(orden["customOrderId"])

    monkeypatch.setattr(ingesta_ecom_api, "_tabla_de_filtro", lambda c, f: {})
    monkeypatch.setattr(ingesta_ecom_api, "buscar_ordenes", lambda *a, **k: ordenes)
    monkeypatch.setattr(ingesta_ecom_api, "_limite_dias_de_rango", lambda c: 31)
    monkeypatch.setattr(ingesta_ecom_api, "ids_fulfillment", lambda *a: set())
    monkeypatch.setattr(ingesta_ecom_api, "_fila_desde_orden", fila)
    r = ingesta_ecom_api.EcomApiAdapter(cliente=object()).periodo(date(2026, 10, 2), date(2026, 10, 2), Decimal(1))
    assert [f.numero_orden for f in r.lineas] == ["100"]
    assert r.ilegibles == [("200", "TypeError: campo raro")]
