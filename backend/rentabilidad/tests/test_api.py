"""Wiring HTTP hacia el ERP (`api.py`) — traducción CSV -> motor, sin tocar
el cálculo en sí (ya cubierto por test_tactica_regresion.py). Mismo patrón
que el resto de `rentabilidad/`: proveedores con `fetch_fn` de fixture, sin
red ni credenciales reales."""
from datetime import date
from decimal import Decimal

from rentabilidad.adapters import (
    ClasificacionProvider,
    CostoVigenteProvider,
    IvaProvider,
    MargenObjetivoProvider,
    ResponsableProvider,
)
import pytest
from fastapi import HTTPException

from rentabilidad import api
from rentabilidad.api import (
    CalcularTacticaPeriodoIn,
    LineaTacticaIn,
    _periodo_de_rango,
    _resolver_tc,
    _venta_tactica_a_out,
    calcular_lineas,
    calcular_tactica_periodo,
    extraer_comprobante,
    incidencias_de_periodo,
    incidencias_en_memoria_tactica,
)
from rentabilidad.tc_bna import TcBnaError
from rentabilidad.config import ConfiguracionFaltante
from rentabilidad.ingesta_tactica import FilaTactica
from rentabilidad.models import MotivoExclusion, Regimen, VentaTactica
from rentabilidad.persistencia import construir_filas_tactica

TOLERANCIA = Decimal("0.01")


def _cerca(actual, esperado):
    if esperado is None or actual is None:
        return actual == esperado
    return abs(Decimal(actual) - Decimal(esperado)) <= TOLERANCIA


# ── extraer_comprobante — traducción de formato §6.1, no una regla nueva ──

def test_extrae_codigo_embebido_en_texto_descriptivo():
    assert extraer_comprobante("Factura A - FEA") == "FEA"
    assert extraer_comprobante("factura e electronica fee") == "FEE"
    assert extraer_comprobante("Nota de Credito CEA") == "CEA"


def test_extrae_mla_de_multiproposito():
    assert extraer_comprobante("Multipropósito Factura MLA") == "MLA"


def test_sin_codigo_reconocido_devuelve_texto_tal_cual():
    # Cae a NO_RECONOCIDO en resolver_regimen — mismo efecto que "no se
    # calcula" que ya tenía la nota de débito en el JS viejo.
    assert extraer_comprobante("Nota de Débito") == "Nota de Débito"


def test_extraccion_no_confunde_fea_con_fae():
    assert extraer_comprobante("Factura E no electronica FAE") == "FAE"
    assert extraer_comprobante("Factura Venta A Electronica FEA") == "FEA"


# ── calcular_lineas — traducción de tipos + orquestación, motor ya probado ──

def _fila_global(sku: str, costo_s: str):
    fila = [""] * 30
    fila[0] = sku
    fila[18] = costo_s
    return fila


def _providers(costo_s: str, iva_texto: str | None, sku="CF217ACOMP"):
    filas_costo = [_fila_global(sku, costo_s)]
    filas_iva = [["SKU", "IVA"], [sku, iva_texto]] if iva_texto else []
    costo = CostoVigenteProvider(sheet_id="x", fetch_fn=lambda sid, tab: filas_costo)
    iva = IvaProvider(sheet_id="x", fetch_fn=lambda sid, tab: filas_iva)
    return costo, iva


def test_t1_via_endpoint_reproduce_el_caso_de_aceptacion(db_session):
    # T-1 de RENTABILIDAD_FUNCIONAL.md §13.1, pero entrando por el mismo
    # camino que usará el frontend: texto crudo de "Tipo de Factura", no el
    # código corto ya resuelto.
    costo, iva = _providers("2.65", "IVA Debito 21%")
    linea = LineaTacticaIn(
        codigo="CF217ACOMP", tipo_factura="Factura de Venta A - FEA",
        nro_factura="00003-00127071", cantidad="6", precio_venta="31153.50", tc="1500",
    )
    [r] = calcular_lineas([linea], db_session, costo, iva)
    assert r.regimen == Regimen.CUENTA_1.value
    assert _cerca(r.iva, "6542.235")
    assert _cerca(r.imp_cheque, "-452.35")
    assert _cerca(r.iibb, "-1557.675")
    assert _cerca(r.costo_total_pesos, "-23850.00")
    assert _cerca(r.costo_financiero_1, "-1130.87")
    assert _cerca(r.margen_real, "4162.60")


def test_mla_no_calculado_pendiente_p01(db_session):
    costo, iva = _providers("2.65", "IVA Debito 21%")
    linea = LineaTacticaIn(
        codigo="CF217ACOMP", tipo_factura="Multipropósito Factura MLA",
        nro_factura="00003-00000001", cantidad="1", precio_venta="1000", tc="1500",
    )
    [r] = calcular_lineas([linea], db_session, costo, iva)
    assert r.regimen == Regimen.NO_DETERMINADO.value
    assert r.margen_real is None


def test_costo_no_resuelto_es_incidencia_no_numero(db_session):
    costo, iva = _providers("2.65", "IVA Debito 21%", sku="OTRO-SKU")
    linea = LineaTacticaIn(
        codigo="CF217ACOMP", tipo_factura="FEA",
        nro_factura="00003-00000001", cantidad="1", precio_venta="1000", tc="1500",
    )
    [r] = calcular_lineas([linea], db_session, costo, iva)
    assert r.incidencia == "COSTO_NO_RESUELTO"
    assert r.margen_real is None


def test_sheet_id_faltante_no_rompe_el_lote_completo(db_session):
    # Sin sheet_id configurado, el proveedor levanta ConfiguracionFaltante —
    # el endpoint lo captura como incidencia en vez de tirar abajo el request.
    costo = CostoVigenteProvider(sheet_id=None)
    iva = IvaProvider(sheet_id=None)
    linea = LineaTacticaIn(
        codigo="CF217ACOMP", tipo_factura="FEA",
        nro_factura="00003-00000001", cantidad="1", precio_venta="1000", tc="1500",
    )
    [r] = calcular_lineas([linea], db_session, costo, iva)
    assert r.incidencia.startswith("CONFIG_FALTANTE")
    assert r.margen_real is None


# ── /tactica/periodo — construir_filas_tactica (con clasificación) ya está
# probado en test_persistencia.py; acá solo se prueba el wiring propio de
# este endpoint: la traducción a VentaTacticaOut y el validador en memoria.
# `FilaTactica.tipo_factura` ya viene resuelto (a diferencia de
# `LineaTacticaIn.tipo_factura`, que es texto crudo) — no hay
# `extraer_comprobante` de por medio en este camino.

def _fila_tactica(**overrides) -> FilaTactica:
    base = dict(
        fecha=date(2026, 7, 31), empresa="Sign Solutions SA", codigo="CF217ACOMP",
        descripcion=None, fabricante=None, tipo_producto=None, vendedor=None,
        nro_factura="00003-00127071", tipo_factura="FEA",
        cantidad=Decimal("6"), precio_venta=Decimal("31153.50"), tc=Decimal("1500"),
    )
    base.update(overrides)
    return FilaTactica(**base)


def _sin_clasificar_tactica():
    return dict(
        clasificacion_provider=ClasificacionProvider(sheet_id=None),
        responsable_provider=ResponsableProvider(sheet_id=None),
        margen_provider=MargenObjetivoProvider(sheet_ids={}, sheet_master_id=None),
    )


def test_periodo_venta_tactica_a_out_expone_los_campos_que_necesita_el_frontend(db_session):
    # PM/subcategoría no vienen de un CSV en este camino — se resuelven con
    # el mismo provider que usa /cierres/tactica (a diferencia de
    # calcular_lineas, que hoy toma el PM directo de la columna del archivo).
    costo, iva = _providers("2.65", "IVA Debito 21%")
    resultado = construir_filas_tactica(db_session, [_fila_tactica()], costo, iva, **_sin_clasificar_tactica())
    [out] = [_venta_tactica_a_out(f) for f in resultado.filas]
    assert out.codigo == "CF217ACOMP"
    assert out.empresa == "Sign Solutions SA"
    assert out.regimen == Regimen.CUENTA_1.value
    assert _cerca(out.margen_real, "4162.60")
    assert out.pm is None  # sin clasificación configurada, degrada a None (no rompe)


def test_periodo_incidencias_en_memoria_detecta_sin_pm(db_session):
    costo, iva = _providers("2.65", "IVA Debito 21%")
    resultado = construir_filas_tactica(db_session, [_fila_tactica()], costo, iva, **_sin_clasificar_tactica())
    incidencias = incidencias_en_memoria_tactica(resultado.filas)
    assert any(i.codigo == "V-13" for i in incidencias)


def test_periodo_incidencias_en_memoria_detecta_duplicados_sin_persistir(db_session):
    costo, iva = _providers("2.65", "IVA Debito 21%")
    filas = [_fila_tactica(), _fila_tactica()]  # mismo nro_factura + codigo
    resultado = construir_filas_tactica(db_session, filas, costo, iva, **_sin_clasificar_tactica())
    incidencias = incidencias_en_memoria_tactica(resultado.filas)
    assert any(i.codigo == "V-16" for i in incidencias)


def test_periodo_excluido_por_sku_excluido_se_ve_en_venta_tactica_a_out(db_session):
    from rentabilidad.models import SkuExcluido
    db_session.add(SkuExcluido(sku="CF217ACOMP", motivo=MotivoExclusion.FIXTURE, activo=True))
    db_session.commit()
    costo, iva = _providers("2.65", "IVA Debito 21%")
    resultado = construir_filas_tactica(db_session, [_fila_tactica()], costo, iva, **_sin_clasificar_tactica())
    [out] = [_venta_tactica_a_out(f) for f in resultado.filas]
    assert out.excluido is True
    assert out.motivo_exclusion == MotivoExclusion.FIXTURE.value


def test_periodo_rechaza_hasta_anterior_a_desde_sin_tocar_sql():
    # La validación de rango corre antes de instanciar TacticaSqlAdapter —
    # por eso este test no necesita red ni RENT_TACTICA_SQL_* configurado.
    payload = CalcularTacticaPeriodoIn(desde=date(2026, 8, 10), hasta=date(2026, 8, 1))
    with pytest.raises(HTTPException):
        calcular_tactica_periodo(payload)


# ── _periodo_de_rango — etiqueta del cierre, sin ambigüedad de nombre de hoja ──

def test_periodo_de_rango_es_estable_y_ordenable():
    assert _periodo_de_rango(date(2026, 7, 23), date(2026, 8, 22)) == "2026-07-23_2026-08-22"


# ── incidencias_de_periodo — wiring del validador ya probado, no reglas nuevas ──

def test_incidencias_de_periodo_tactica_detecta_sin_pm(db_session):
    db_session.add(VentaTactica(
        periodo="2026-07", fecha=date(2026, 7, 31), empresa="Cliente Demo",
        codigo="SKU1", tipo_factura="FEA", nro_factura="00003-00000001",
        cantidad=Decimal(1), precio_venta=Decimal(1000), tc=Decimal(1500),
        regimen=Regimen.CUENTA_1, pm=None,
    ))
    db_session.commit()
    incidencias = incidencias_de_periodo(db_session, "2026-07", "tactica")
    assert any(i.codigo == "V-13" for i in incidencias)


def test_incidencias_de_periodo_solo_mira_el_periodo_pedido(db_session):
    db_session.add(VentaTactica(
        periodo="OTRO-PERIODO", fecha=date(2026, 6, 1), empresa="X", codigo="SKU1",
        tipo_factura="FEA", nro_factura="1", cantidad=Decimal(1),
        precio_venta=Decimal(1000), tc=Decimal(1500), regimen=Regimen.CUENTA_1,
    ))
    db_session.commit()
    assert incidencias_de_periodo(db_session, "2026-07", "tactica") == []


def test_incidencias_de_periodo_detecta_duplicados_v16(db_session):
    for i in range(2):
        db_session.add(VentaTactica(
            periodo="2026-07", fecha=date(2026, 7, 31), empresa="Cliente Demo",
            codigo="SKU1", tipo_factura="FEA", nro_factura="00003-00000001",
            cantidad=Decimal(1), precio_venta=Decimal(1000), tc=Decimal(1500),
            regimen=Regimen.CUENTA_1, pm="Matias",
        ))
    db_session.commit()
    incidencias = incidencias_de_periodo(db_session, "2026-07", "tactica")
    assert any(i.codigo == "V-16" for i in incidencias)


# ── _resolver_tc — pedido de Maxx (2026-08-10): sin TC manual, se toma el
# del BNA al momento de ejecutar; sigue habiendo override manual. ──

def test_resolver_tc_usa_el_valor_manual_si_se_paso(monkeypatch):
    monkeypatch.setattr(api, "obtener_tc_bna", lambda: (_ for _ in ()).throw(AssertionError("no debería llamar al BNA")))
    assert _resolver_tc("1500") == Decimal("1500")


def test_resolver_tc_va_al_bna_si_no_se_paso_ninguno(monkeypatch):
    monkeypatch.setattr(api, "obtener_tc_bna", lambda: Decimal("1460.5"))
    assert _resolver_tc(None) == Decimal("1460.5")


def test_resolver_tc_rechaza_texto_no_numerico():
    with pytest.raises(HTTPException):
        _resolver_tc("no-es-un-numero")


def test_resolver_tc_da_un_error_claro_si_el_bna_falla_y_no_hay_manual(monkeypatch):
    monkeypatch.setattr(api, "obtener_tc_bna", lambda: (_ for _ in ()).throw(TcBnaError("BNA caído")))
    with pytest.raises(HTTPException):
        _resolver_tc(None)
