"""C3: hoja "ERP Análisis" y columna VALOR A COPIAR (misma estructura para los dos tipos de campaña)."""
import pytest

import campanas_ml_export as ex


def test_valor_a_copiar_simple_es_el_descuento_total():
    assert ex.valor_a_copiar("simple", 12, 20000, None) == (12.0, None, None)
    assert ex.valor_a_copiar("simple", 5, 20000, 0)[0] == 5.0 and ex.valor_a_copiar("simple", 80, 20000, 0)[0] == 80.0


def test_valor_a_copiar_reparto_es_el_total_menos_el_aporte_de_ml():
    # lista 41.699, ML pone $202,35 (0,4853%): total 12% → vendedor 11,515% = $4.801,53
    pct, monto, motivo = ex.valor_a_copiar("reparto", 12, 41699.0, 202.35)
    assert motivo is None and pct == 11.515 and monto == 4801.53
    assert ex.valor_a_copiar("reparto", 10, 10000, 50) == (9.5, 950.0, None)        # el ejemplo: 10% total, ML 0,5%
    assert ex.valor_a_copiar("reparto", 10, 10000, 0) == (10.0, 1000.0, None)


@pytest.mark.parametrize("tipo,total,meli", [("simple", 4, 0), ("simple", 81, 0), ("simple", 7.5, 0), ("reparto", 5, 1500), ("simple", None, 0)])
def test_sin_valor_a_copiar_cuando_ml_no_lo_aceptaria(tipo, total, meli):
    pct, monto, motivo = ex.valor_a_copiar(tipo, total, 20000, meli)
    assert pct is None and monto is None and motivo


def _analisis(filas):
    return {"filas": filas}


def _fila(fila, total=10, editable=True, tipo_orig=10.0, **k):
    base = {"fila": fila, "item_id": f"MLA{fila}", "sku": "S", "titulo": "T", "editable": editable, "precio_original": 20000.0,
            "descuento_total_pct": total, "meli_monto": 0, "margenes": {"contado": {"margen": 30.0}, "3": {"margen": 20.0}}, "avisos": []}
    return dict(base, **k), {"DISCOUNT_PERCENTAGE": tipo_orig}


def test_la_hoja_tiene_las_mismas_columnas_para_los_dos_tipos():
    a, oa = _fila(6)
    for tipo in ("reparto", "simple"):
        enc, filas = ex.construir(_analisis([a]), tipo, {6: oa})
        assert enc == ex.ENCABEZADOS and len(filas[0]) == len(enc)
    enc, f = ex.construir(_analisis([a]), "reparto", {6: oa})
    h = {n: v for n, v in zip(enc, f[0])}
    assert h["COLUMNA DE ML"] == "SELLER_PERCENTAGE" and h["VALOR A COPIAR"] == (10.0, "copiar") and h["CAMBIÓ vs EXCEL"] == "NO"
    enc, f = ex.construir(_analisis([a]), "simple", {6: oa})
    assert {n: v for n, v in zip(enc, f[0])}["COLUMNA DE ML"] == "DISCOUNT_PERCENTAGE"


def test_cambio_no_editable_y_sin_valor():
    cambiada, oc = _fila(6, total=15)
    fija, of = _fila(7, editable=False)
    mala, om = _fila(8, total=4)
    enc, filas = ex.construir(_analisis([cambiada, fija, mala]), "simple", {6: oc, 7: of, 8: om})
    h = [{n: v for n, v in zip(enc, f)} for f in filas]
    assert h[0]["CAMBIÓ vs EXCEL"] == "SI" and h[0]["VALOR A COPIAR"] == (15.0, "copiar")
    assert h[1]["EDITABLE EN ML"] == "NO" and h[1]["VALOR A COPIAR"] == ("—", "txt") and h[1]["CAMBIÓ vs EXCEL"] == "—"
    assert h[2]["VALOR A COPIAR"] == ("—", "txt") and h[2]["AVISOS"].startswith("SIN VALOR A COPIAR")


def test_una_fila_sin_cambios_lleva_exactamente_el_valor_que_trae_ml():
    # total 5% con ML aportando $202,35 de $41.699: la resta da 4,515 pero ML trae 4,5 (redondeado): se copia lo de ML
    f = {"fila": 6, "item_id": "MLA1", "editable": True, "precio_original": 41699.0, "descuento_total_pct": 5.0, "meli_monto": 202.35,
         "margenes": {}, "avisos": []}
    orig = {"DISCOUNT_PERCENTAGE": 5.0, "SELLER_PERCENTAGE": 4.5, "SELLER_AMOUNT": 1882.6}
    enc, filas = ex.construir({"filas": [f]}, "reparto", {6: orig})
    h = {n: v for n, v in zip(enc, filas[0])}
    assert h["CAMBIÓ vs EXCEL"] == "NO" and h["VALOR A COPIAR"] == (4.5, "copiar") and h["MONTO ALTERNATIVO $ (SELLER_AMOUNT)"] == 1882.6
    enc, filas = ex.construir({"filas": [dict(f, descuento_total_pct=12.0)]}, "reparto", {6: orig})     # con cambio: se recalcula
    assert {n: v for n, v in zip(enc, filas[0])}["VALOR A COPIAR"] == (11.515, "copiar")
