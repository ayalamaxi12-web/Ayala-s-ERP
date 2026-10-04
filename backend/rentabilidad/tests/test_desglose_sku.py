"""Desglose por SKU de combos/kits/carritos: cada SKU recibe solo su parte y
la suma de los SKU cierra con el total de la orden."""
from datetime import date
from decimal import Decimal

from rentabilidad import agregaciones, desglose_sku as ds
from rentabilidad.adapters import IvaProvider
from rentabilidad.ingesta_ecom import ResultadoIngestaEcom
from rentabilidad.ingesta_ecom_api import _fila_desde_orden
from rentabilidad.models import PricingSku, VentaEcom, VentaEcomLinea
from rentabilidad.persistencia import guardar_cierre_ecom
from rentabilidad.reporte_diario import reporte_diario

from .conftest import d
from .test_ingesta_ecom_api import _CANALES, _ESTADOS_PAGO, _orden
from .test_persistencia import _sin_clasificar_ecom

P = "2026-09-23_2026-10-22"
DIA = date(2026, 10, 1)
TC = d("1500")


class _Clasificacion:
    """PM por SKU, como GRAL CATEGORIAS: la clasificación de la orden sale del primer SKU."""
    PM = {"TINTA": ("Veronica", "Tintas", "Insumos"), "PLANCHA": ("Matias", "Planchas", "Sublimacion")}

    def clasificacion_ecom(self, skus):
        pm, sub, cat = self.PM[skus.split(",")[0].strip()]
        return {"pm": pm, "subcategoria": sub, "categoria": cat, "subcategoria2": sub}


def _combo():
    """Combo botella de tinta + plancha: $500.000 con IVA la orden, comisión ML $50.000."""
    return _orden(
        id="9", customOrderId="COMBO-1", shipping={"listCost": 0, "cost": 0}, payments=[{"totalFeeAmount": 50000}],
        created="2026-10-01T12:00:00Z",
        orderLists=[
            {"quantity": 1, "subtotal": 100000, "subtotalSinImpuestos": 82644.63, "taxTag": "21",
             "variant": {"sku": "TINTA", "cost": 20, "product": {"sku": None}}},
            {"quantity": 1, "subtotal": 400000, "subtotalSinImpuestos": 330578.51, "taxTag": "21",
             "variant": {"sku": "PLANCHA", "cost": 80, "product": {"sku": None}}},
        ],
    )


def _guardar_combo(db):
    fila = _fila_desde_orden(_combo(), TC, _CANALES, _ESTADOS_PAGO)
    providers = _sin_clasificar_ecom()
    providers["clasificacion_provider"] = _Clasificacion()
    guardar_cierre_ecom(db, P, ResultadoIngestaEcom(lineas=[fila], excluidas_por_estado_pago=[], incidencias_costo=[]),
                        IvaProvider(), **providers)
    db.flush()
    return db.query(VentaEcom).one()


def test_la_api_trae_el_importe_de_cada_linea():
    fila = _fila_desde_orden(_combo(), TC, _CANALES, _ESTADOS_PAGO)
    assert [(l.sku, l.precio_final, l.costo_sin_iva) for l in fila.lineas] == [
        ("TINTA", d("100000"), d("20")), ("PLANCHA", d("400000"), d("80"))]
    assert sum(l.precio_final for l in fila.lineas) == fila.precio_final == d("500000")


def test_se_guardan_las_lineas_y_el_total_de_la_orden_no_cambia(db_session):
    v = _guardar_combo(db_session)
    assert v.precio_final == d("500000") and v.skus_vendidos == "TINTA, PLANCHA"
    assert [(l.sku, l.pm, l.periodo) for l in v.lineas] == [("TINTA", "Veronica", P), ("PLANCHA", "Matias", P)]
    assert v.pm == "Veronica"  # la orden conserva la clasificación del primer SKU


def test_cada_sku_recibe_su_parte_y_la_suma_cierra_con_la_orden(db_session):
    v = _guardar_combo(db_session)
    tinta, plancha = ds.desglosar(db_session, [v])
    assert (tinta.sku, tinta.precio_final, plancha.precio_final) == ("TINTA", d("100000"), d("400000"))
    assert not tinta.prorrateado and not plancha.prorrateado
    # cargos de la orden en proporción al precio sin IVA (1/5 y 4/5), costo propio de cada SKU
    assert tinta.comision_venta == v.comision_venta * tinta.precio_sin_iva / v.precio_sin_iva
    assert tinta.costo_total == d("20") * TC and plancha.costo_total == d("80") * TC
    for campo in ("precio_final", "precio_sin_iva", "costo_total", "rentabilidad", "comision_venta"):
        assert abs(sum(getattr(l, campo) for l in (tinta, plancha)) - getattr(v, campo)) < d("0.0001"), campo
    # el margen de cada SKU es el suyo (cada uno con su costo), no el de la orden
    cargos = v.precio_sin_iva - v.neto
    assert tinta.rentabilidad == tinta.precio_sin_iva - cargos * tinta.precio_sin_iva / v.precio_sin_iva - d("20") * TC
    assert tinta.rentabilidad / tinta.precio_sin_iva != plancha.rentabilidad / plancha.precio_sin_iva


def test_orden_recalculada_las_lineas_siguen_cerrando(db_session):
    """La liquidación de Frávega cambia comisión y rentabilidad de la orden: como el
    reparto se calcula al leer, las líneas siguen sumando el total."""
    v = _guardar_combo(db_session)
    v.comision_venta, v.neto, v.rentabilidad = d("1000"), v.neto + d("49000"), v.rentabilidad + d("49000")
    assert abs(sum(l.rentabilidad for l in ds.desglosar(db_session, [v])) - v.rentabilidad) < d("0.0001")


def test_cada_sku_va_a_su_pm_en_las_agregaciones(db_session):
    _guardar_combo(db_session)
    por_pm = {f.dimension_valor: f for f in agregaciones.agregar_ecom(db_session, P, "pm")}
    assert por_pm["Veronica"].suma_precio_final == d("100000") and por_pm["Matias"].suma_precio_final == d("400000")
    assert por_pm["Veronica"].cantidad_lineas == por_pm["Matias"].cantidad_lineas == 1
    assert sum(f.suma_precio_final for f in por_pm.values()) == d("500000")
    por_cat = {f.dimension_valor: f.suma_precio_final for f in agregaciones.agregar_ecom(db_session, P, "categoria")}
    assert por_cat == {"Insumos": d("100000"), "Sublimacion": d("400000")}
    assert agregaciones.agregar_ecom(db_session, P, "canal")[0].suma_precio_final == d("500000")


def test_reporte_diario_desglosa_el_combo_por_sku_y_por_pm(db_session):
    _guardar_combo(db_session)
    r = reporte_diario(db_session, DIA)["general"]
    assert r["ayer"]["facturacion"] == 500000.0 and r["ayer"]["ordenes"] == 1  # la orden no cambia
    assert {x["sku"]: x["facturacion"] for x in r["ayer_mas_facturaron"]} == {"PLANCHA": 400000.0, "TINTA": 100000.0}
    pms = {p["pm"]: p for p in r["por_pm"]["ayer"]}
    assert pms["Matias"]["facturacion"] == 400000.0 and pms["Veronica"]["facturacion"] == 100000.0
    assert sum(p["facturacion"] for p in r["por_pm"]["ayer"]) == r["ayer"]["facturacion"]


# ── órdenes viejas, sin líneas ──

def _venta_vieja(skus, **kw):
    base = dict(
        periodo=P, numero_orden="OLD-1", skus_vendidos=skus, fecha_creacion_venta=DIA, canal_de_venta="Mercadolibre",
        costo_sin_iva=d("100"), comision_venta=d("50000"), costo_envio=d(0), precio_final=d("500000"),
        precio_sin_iva=d("413223.14"), neto=d("300000"), costo_total=d("150000"), rentabilidad=d("150000"),
        tc=TC, pm="Veronica", origen="importado_sheet",
    )
    base.update(kw)
    return VentaEcom(**base)


def test_orden_vieja_de_un_solo_sku_es_exacta(db_session):
    v = _venta_vieja("TINTA", unidades=3)
    db_session.add(v)
    db_session.flush()
    (l,) = ds.desglosar(db_session, [v])
    assert l.precio_final == d("500000") and l.rentabilidad == d("150000") and l.cantidad == 3 and not l.prorrateado


def test_orden_vieja_de_combo_se_prorratea_por_precio_de_lista_y_se_marca(db_session):
    db_session.add_all([
        PricingSku(sku="TINTA", precio_web=d("20000"), vigente_desde=date(2026, 9, 1), cargado_por="Sheet Verónica"),
        PricingSku(sku="PLANCHA", precio_web=d("80000"), vigente_desde=date(2026, 9, 1), cargado_por="Sheet Verónica"),
    ])
    v = _venta_vieja("TINTA, PLANCHA")
    db_session.add(v)
    db_session.flush()
    tinta, plancha = ds.desglosar(db_session, [v])
    assert tinta.prorrateado and plancha.prorrateado and tinta.metodo_prorrateo == ds.METODO_PRECIO_LISTA
    assert (tinta.precio_final, plancha.precio_final) == (d("100000"), d("400000"))
    assert tinta.rentabilidad + plancha.rentabilidad == v.rentabilidad
    assert reporte_diario(db_session, DIA)["general"]["alertas"]["combos_prorrateados"]["ordenes"] == 1
    assert all(x["prorrateado"] for x in reporte_diario(db_session, DIA)["general"]["ayer_mas_facturaron"])


def test_orden_vieja_de_combo_sin_precios_de_lista_va_en_partes_iguales(db_session):
    v = _venta_vieja("TINTA, PLANCHA")
    db_session.add(v)
    db_session.flush()
    a, b = ds.desglosar(db_session, [v])
    assert a.metodo_prorrateo == ds.METODO_PARTES_IGUALES and a.precio_final == b.precio_final == d("250000")


def test_borrar_el_periodo_borra_tambien_las_lineas(db_session):
    _guardar_combo(db_session)
    assert db_session.query(VentaEcomLinea).count() == 2
    _guardar_combo(db_session)  # re-corrida del ciclo: reemplaza, no duplica
    assert db_session.query(VentaEcomLinea).count() == 2 and db_session.query(VentaEcom).count() == 1
