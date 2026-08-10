"""Orquestación fuente -> motor -> base única (`persistencia.py`). No
prueba el cálculo en sí (ya cubierto por test_calculators_*.py /
test_ecom_regresion.py / test_tactica_regresion.py) — prueba que la fila
correcta termine en `venta_tactica`/`venta_ecom`, que un período se pueda
recargar sin duplicar, que un lookup informativo sin configurar no tumbe la
fila, y que `sku_excluido` (vacía por defecto) sí excluya cuando tiene datos."""
from datetime import date
from decimal import Decimal

from rentabilidad.adapters import (
    ClasificacionProvider,
    CostoVigenteProvider,
    IvaProvider,
    MargenObjetivoProvider,
    ResponsableProvider,
    StockProvider,
    VinculacionProvider,
)
from rentabilidad.ingesta_ecom import FilaEcom, ResultadoIngestaEcom
from rentabilidad.ingesta_tactica import FilaTactica
from rentabilidad.models import MotivoExclusion, SkuExcluido, VentaEcom, VentaTactica
from rentabilidad.persistencia import (
    construir_filas_ecom,
    construir_filas_tactica,
    guardar_cierre_ecom,
    guardar_cierre_tactica,
    registrar_cierre,
)

TOLERANCIA = Decimal("0.01")


def _cerca(a, b):
    return abs(Decimal(a) - Decimal(b)) <= TOLERANCIA


# ── providers sin configurar (default para no arrastrar red en cada test) ──

def _sin_clasificar():
    return dict(
        clasificacion_provider=ClasificacionProvider(sheet_id=None),
        responsable_provider=ResponsableProvider(sheet_id=None),
        margen_provider=MargenObjetivoProvider(sheet_ids={}, sheet_master_id=None),
    )


def _costo_iva(costo_s="2.65", iva_texto="IVA Debito 21%", sku="CF217ACOMP"):
    fila_global = [""] * 30
    fila_global[0] = sku
    fila_global[18] = costo_s
    filas_iva = [["SKU", "IVA"], [sku, iva_texto]]
    costo = CostoVigenteProvider(sheet_id="x", fetch_fn=lambda sid, tab: [fila_global])
    iva = IvaProvider(sheet_id="x", fetch_fn=lambda sid, tab: filas_iva)
    return costo, iva


def _fila_tactica(**overrides) -> FilaTactica:
    base = dict(
        fecha=date(2026, 7, 31), empresa="Sign Solutions SA", codigo="CF217ACOMP",
        descripcion="Producto", fabricante="Fab X", tipo_producto="Productos para la venta",
        vendedor="Brian Avila", nro_factura="00003-00127071", tipo_factura="FEA",
        cantidad=Decimal("6"), precio_venta=Decimal("31153.50"), tc=Decimal("1500"),
    )
    base.update(overrides)
    return FilaTactica(**base)


# ── TACTICA ──

def test_persistir_periodo_tactica_inserta_una_fila_calculada(db_session):
    costo, iva = _costo_iva()
    resultado = guardar_cierre_tactica(
        db_session, "2026-07", [_fila_tactica()], costo, iva, **_sin_clasificar(),
    )
    db_session.commit()
    assert resultado.config_faltante == []
    [fila] = db_session.query(VentaTactica).all()
    assert fila.periodo == "2026-07"
    assert fila.codigo == "CF217ACOMP"
    assert _cerca(fila.margen_real, "4162.60")
    assert fila.excluido is False
    assert fila.pm is None  # clasificación sin configurar -> degrada a None, no rompe la fila


def test_persistir_periodo_tactica_recarga_sin_duplicar(db_session):
    costo, iva = _costo_iva()
    guardar_cierre_tactica(db_session, "2026-07", [_fila_tactica(nro_factura="A")], costo, iva, **_sin_clasificar())
    db_session.commit()
    guardar_cierre_tactica(db_session, "2026-07", [_fila_tactica(nro_factura="B")], costo, iva, **_sin_clasificar())
    db_session.commit()
    filas = db_session.query(VentaTactica).filter_by(periodo="2026-07").all()
    assert [f.nro_factura for f in filas] == ["B"]  # la de "A" se borró al recargar el período


def test_persistir_periodo_tactica_no_toca_otros_periodos(db_session):
    costo, iva = _costo_iva()
    guardar_cierre_tactica(db_session, "2026-06", [_fila_tactica(nro_factura="JUNIO")], costo, iva, **_sin_clasificar())
    db_session.commit()
    guardar_cierre_tactica(db_session, "2026-07", [_fila_tactica(nro_factura="JULIO")], costo, iva, **_sin_clasificar())
    db_session.commit()
    assert db_session.query(VentaTactica).filter_by(periodo="2026-06").count() == 1
    assert db_session.query(VentaTactica).filter_by(periodo="2026-07").count() == 1


def test_persistir_periodo_tactica_sin_costo_configurado_salta_la_fila_no_rompe(db_session):
    costo_sin_config = CostoVigenteProvider(sheet_id=None)
    _, iva = _costo_iva()
    resultado = guardar_cierre_tactica(
        db_session, "2026-07", [_fila_tactica()], costo_sin_config, iva, **_sin_clasificar(),
    )
    db_session.commit()
    assert resultado.filas == []
    assert resultado.config_faltante == ["00003-00127071"]
    assert db_session.query(VentaTactica).count() == 0


def test_persistir_periodo_tactica_excluye_por_sku_excluido(db_session):
    db_session.add(SkuExcluido(sku="CF217ACOMP", motivo=MotivoExclusion.FIXTURE, activo=True))
    db_session.commit()
    costo, iva = _costo_iva()
    guardar_cierre_tactica(db_session, "2026-07", [_fila_tactica()], costo, iva, **_sin_clasificar())
    db_session.commit()
    [fila] = db_session.query(VentaTactica).all()
    assert fila.excluido is True
    assert fila.motivo_exclusion == MotivoExclusion.FIXTURE
    # exclusión lógica, no borrado: el margen sigue calculado y visible
    assert _cerca(fila.margen_real, "4162.60")


def test_persistir_periodo_tactica_resuelve_clasificacion_cuando_esta_configurada(db_session):
    fila_cat = [""] * 5
    fila_cat[0] = "CF217ACOMP"
    fila_cat[3] = "Matias"
    fila_cat[4] = "Impresoras"
    clasificacion = ClasificacionProvider(sheet_id="x", fetch_fn=lambda sid, tab: [fila_cat])
    costo, iva = _costo_iva()
    resultado = guardar_cierre_tactica(
        db_session, "2026-07", [_fila_tactica()], costo, iva,
        clasificacion_provider=clasificacion,
        responsable_provider=ResponsableProvider(sheet_id=None),
        margen_provider=MargenObjetivoProvider(sheet_ids={}, sheet_master_id=None),
    )
    db_session.commit()
    [fila] = resultado.filas
    assert fila.pm == "Matias"
    assert fila.subcategoria == "Impresoras"


# ── ECOM ──

def _fila_ecom(**overrides) -> FilaEcom:
    base = dict(
        numero_orden="1406205", skus_vendidos="SKU-1", canal_de_venta="Mercadolibre Carrito",
        estado_pago="Cobrado", costo_sin_iva=Decimal("13.25"), comision_venta=Decimal("20828.7"),
        costo_envio=Decimal("7821.0"), precio_sin_iva=Decimal("70653.636"), precio_final=Decimal("77719.0"),
        tc=Decimal("1500"), incidencia=None,
    )
    base.update(overrides)
    return FilaEcom(**base)


def _sin_clasificar_ecom():
    return dict(
        clasificacion_provider=ClasificacionProvider(sheet_id=None),
        vinculacion_provider=VinculacionProvider(sheet_id=None),
        stock_provider=StockProvider(sheet_id=None),
        margen_provider=MargenObjetivoProvider(sheet_ids={}, sheet_master_id=None),
    )


def test_persistir_ecom_persiste_las_tres_categorias_del_adaptador(db_session):
    normal = _fila_ecom(numero_orden="1")
    excluida = _fila_ecom(numero_orden="2", estado_pago="Reembolsado")
    incidencia = _fila_ecom(numero_orden="3", costo_sin_iva=Decimal(0), incidencia="COSTO_NO_RESUELTO")
    resultado_ingesta = ResultadoIngestaEcom(
        lineas=[normal], excluidas_por_estado_pago=[excluida], incidencias_costo=[incidencia],
    )
    iva = IvaProvider(sheet_id=None)
    resultado = guardar_cierre_ecom(db_session, "2026-07", resultado_ingesta, iva, **_sin_clasificar_ecom())
    db_session.commit()

    por_orden = {f.numero_orden: f for f in db_session.query(VentaEcom).all()}
    assert set(por_orden) == {"1", "2", "3"}

    assert por_orden["1"].excluido is False
    assert por_orden["1"].rentabilidad is not None

    assert por_orden["2"].excluido is True
    assert por_orden["2"].motivo_exclusion == MotivoExclusion.MANUAL  # placeholder, ver GAP en persistencia.py

    assert por_orden["3"].excluido is False  # incidencia de costo != exclusión por regla
    assert por_orden["3"].rentabilidad is None  # el motor nunca corrió sobre esta fila
    assert por_orden["3"].costo_sin_iva == Decimal(0)  # el dato crudo se conserva para revisión


def test_persistir_ecom_recarga_sin_duplicar(db_session):
    iva = IvaProvider(sheet_id=None)
    r1 = ResultadoIngestaEcom(lineas=[_fila_ecom(numero_orden="A")], excluidas_por_estado_pago=[], incidencias_costo=[])
    guardar_cierre_ecom(db_session, "2026-07", r1, iva, **_sin_clasificar_ecom())
    db_session.commit()
    r2 = ResultadoIngestaEcom(lineas=[_fila_ecom(numero_orden="B")], excluidas_por_estado_pago=[], incidencias_costo=[])
    guardar_cierre_ecom(db_session, "2026-07", r2, iva, **_sin_clasificar_ecom())
    db_session.commit()
    filas = db_session.query(VentaEcom).filter_by(periodo="2026-07").all()
    assert [f.numero_orden for f in filas] == ["B"]


def test_persistir_ecom_excluye_por_sku_excluido(db_session):
    db_session.add(SkuExcluido(sku="SKU-1", motivo=MotivoExclusion.SKU_AUXILIAR, activo=True))
    db_session.commit()
    iva = IvaProvider(sheet_id=None)
    resultado_ingesta = ResultadoIngestaEcom(lineas=[_fila_ecom()], excluidas_por_estado_pago=[], incidencias_costo=[])
    guardar_cierre_ecom(db_session, "2026-07", resultado_ingesta, iva, **_sin_clasificar_ecom())
    db_session.commit()
    [fila] = db_session.query(VentaEcom).all()
    assert fila.excluido is True
    assert fila.motivo_exclusion == MotivoExclusion.SKU_AUXILIAR


# ── Consulta en vivo (construir_filas_*) — el punto central del ajuste de
# arquitectura del 2026-08-10: calcula igual, pero NUNCA debe tocar la base. ──

def test_construir_filas_tactica_no_agrega_nada_a_la_sesion(db_session):
    costo, iva = _costo_iva()
    resultado = construir_filas_tactica(db_session, [_fila_tactica()], costo, iva, **_sin_clasificar())
    assert len(resultado.filas) == 1
    assert _cerca(resultado.filas[0].margen_real, "4162.60")
    assert db_session.query(VentaTactica).count() == 0  # nada persistido
    db_session.commit()
    assert db_session.query(VentaTactica).count() == 0  # ni siquiera tras commit


def test_construir_filas_ecom_no_agrega_nada_a_la_sesion(db_session):
    iva = IvaProvider(sheet_id=None)
    resultado_ingesta = ResultadoIngestaEcom(lineas=[_fila_ecom()], excluidas_por_estado_pago=[], incidencias_costo=[])
    resultado = construir_filas_ecom(db_session, resultado_ingesta, iva, **_sin_clasificar_ecom())
    assert len(resultado.filas) == 1
    assert resultado.filas[0].rentabilidad is not None
    db_session.commit()
    assert db_session.query(VentaEcom).count() == 0


def test_repetir_una_consulta_no_acumula_filas(db_session):
    """70 consultas del mismo día no deben dejar 70 copias — no dejan
    ninguna, porque `construir_filas_tactica` nunca escribe."""
    costo, iva = _costo_iva()
    for _ in range(5):
        construir_filas_tactica(db_session, [_fila_tactica()], costo, iva, **_sin_clasificar())
        db_session.commit()
    assert db_session.query(VentaTactica).count() == 0


# ── registrar_cierre — metadata del cierre guardado ──

def test_registrar_cierre_crea_la_fila_con_los_flags_pedidos(db_session):
    cierre = registrar_cierre(
        db_session, "2026-07-23_2026-08-22", date(2026, 7, 23), date(2026, 8, 22),
        tactica_guardado=True,
    )
    db_session.commit()
    assert cierre.tactica_guardado is True
    assert cierre.ecom_guardado is False  # default, todavía no se guardó esa pata


def test_registrar_cierre_no_pisa_flags_no_mencionados(db_session):
    registrar_cierre(db_session, "P1", date(2026, 7, 23), date(2026, 8, 22), tactica_guardado=True)
    db_session.commit()
    cierre = registrar_cierre(db_session, "P1", date(2026, 7, 23), date(2026, 8, 22), ecom_guardado=True, ecom_origen="excel")
    db_session.commit()
    assert cierre.tactica_guardado is True  # sigue en True, esta llamada no lo tocó
    assert cierre.ecom_guardado is True
    assert cierre.ecom_origen == "excel"
