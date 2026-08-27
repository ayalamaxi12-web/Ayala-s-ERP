"""Etapa 2 — prueba la lógica de cascada de cada adaptador con datos de
fixture inyectados (`fetch_fn`), sin red. La conexión real a Sheets
(`gsheets.get_client`) no se testea acá: no hay credenciales/hojas reales
en este entorno."""
from decimal import Decimal

import pytest

from rentabilidad.adapters import (
    ClasificacionProvider,
    CostoVigenteProvider,
    IvaProvider,
    MargenObjetivoProvider,
    ResponsableProvider,
    StockProvider,
    VinculacionProvider,
)
from rentabilidad.config import ConfiguracionFaltante

# ── CostoVigenteProvider (§5.6) — SQL directo de Táctica, no Sheets ──
# (cambio de fuente confirmado por Maxx 2026-08-14: `productosprecios.Costo`
# es un único valor por producto, ya no hay cascada de dos columnas S/R).

def _fila_catalogo(sku: str, costo=None, iva_descripcion=None):
    return {"sku": sku, "costo": costo, "iva_descripcion": iva_descripcion}


def test_costo_vigente_lee_de_la_consulta_inyectada():
    catalogo = [_fila_catalogo("SKU1", costo="2.65")]
    prov = CostoVigenteProvider(consultar=lambda: catalogo)
    assert prov.obtener("SKU1") == Decimal("2.65")


def test_costo_vigente_cero_se_trata_como_sin_costo():
    catalogo = [_fila_catalogo("SKU1", costo="0")]
    prov = CostoVigenteProvider(consultar=lambda: catalogo)
    assert prov.obtener("SKU1") is None  # "0 es sin costo", no costo cero


def test_costo_vigente_sku_no_encontrado_devuelve_none():
    catalogo = [_fila_catalogo("OTRO", costo="2.65")]
    prov = CostoVigenteProvider(consultar=lambda: catalogo)
    assert prov.obtener("SKU1") is None


def test_costo_vigente_sin_costo_configurado_devuelve_none():
    catalogo = [_fila_catalogo("SKU1", costo=None)]
    prov = CostoVigenteProvider(consultar=lambda: catalogo)
    assert prov.obtener("SKU1") is None


def test_costo_vigente_origen_es_sql():
    catalogo = [_fila_catalogo("SKU1", costo="2.65")]
    prov = CostoVigenteProvider(consultar=lambda: catalogo)
    assert prov.obtener_con_origen("SKU1") == (Decimal("2.65"), "SQL")


def test_costo_vigente_sku_con_padding_en_catalogo_resuelve_igual():
    # Bug real corregido 2026-08-18: `productos.Codigo` es una columna de
    # ancho fijo en Táctica y llega con espacios finales de padding
    # (confirmado con TN1060COMP: 'TN1060COMP      ', 16 bytes) -- el
    # `codigo` de cada línea ya llega recortado (`ingesta_tactica.
    # _fila_desde_row`), así que el catálogo tiene que recortar su propia
    # clave o el `.get()` nunca matchea.
    catalogo = [_fila_catalogo("SKU1      ", costo="1.24")]
    prov = CostoVigenteProvider(consultar=lambda: catalogo)
    assert prov.obtener("SKU1") == Decimal("1.24")


def test_costo_vigente_sin_configurar_levanta_error_claro():
    # Sin RENT_TACTICA_SQL_* configuradas (limpiadas por el fixture autouse
    # de conftest.py), la consulta real levanta ConfiguracionFaltante recién
    # al usarse -- no al construirse (mismo principio que el resto de los
    # adaptadores).
    prov = CostoVigenteProvider()
    with pytest.raises(ConfiguracionFaltante):
        prov.obtener("SKU1")


# ── `_consultar_catalogo_tactica_real` — reintento ante corte de conexión.
# Bug real 2026-08-27: el link a Táctica cortó a mitad de consulta durante
# una corrida real de Ofertas ML ("DB-Lib error 20017: Unexpected EOF from
# the server") y mató el job entero -- no había reintento. ──

def test_consultar_catalogo_tactica_reintenta_ante_corte_de_conexion(monkeypatch):
    import pymssql

    from rentabilidad.adapters import _consultar_catalogo_tactica_real

    monkeypatch.setenv("RENT_TACTICA_SQL_SERVER", "x")
    monkeypatch.setenv("RENT_TACTICA_SQL_USER", "x")
    monkeypatch.setenv("RENT_TACTICA_SQL_PASSWORD", "x")
    monkeypatch.setenv("RENT_TACTICA_SQL_DATABASE", "x")
    monkeypatch.setattr("time.sleep", lambda s: None)

    class _FakeCursor:
        def execute(self, query):
            pass
        def __iter__(self):
            return iter([{"sku": "SKU1", "costo": "1.5", "iva_descripcion": "IVA Debito 21%"}])

    class _FakeConn:
        def cursor(self):
            return _FakeCursor()
        def close(self):
            pass

    intentos = {"n": 0}
    def fake_connect(**kwargs):
        intentos["n"] += 1
        if intentos["n"] < 3:
            raise pymssql.OperationalError((20017, b"DB-Lib error message 20017, severity 9:\nUnexpected EOF from the server\n"))
        return _FakeConn()

    monkeypatch.setattr(pymssql, "connect", fake_connect)

    filas = _consultar_catalogo_tactica_real()

    assert intentos["n"] == 3
    assert filas == [{"sku": "SKU1", "costo": "1.5", "iva_descripcion": "IVA Debito 21%"}]


def test_consultar_catalogo_tactica_agota_reintentos_y_relanza(monkeypatch):
    import pymssql

    from rentabilidad.adapters import _consultar_catalogo_tactica_real

    monkeypatch.setenv("RENT_TACTICA_SQL_SERVER", "x")
    monkeypatch.setenv("RENT_TACTICA_SQL_USER", "x")
    monkeypatch.setenv("RENT_TACTICA_SQL_PASSWORD", "x")
    monkeypatch.setenv("RENT_TACTICA_SQL_DATABASE", "x")
    monkeypatch.setattr("time.sleep", lambda s: None)

    def fake_connect(**kwargs):
        raise pymssql.OperationalError((20017, b"Unexpected EOF from the server"))

    monkeypatch.setattr(pymssql, "connect", fake_connect)

    with pytest.raises(pymssql.OperationalError):
        _consultar_catalogo_tactica_real()


# ── IvaProvider (§5.4) — comparación exacta, sensible a mayúsculas ──

def test_iva_factor_21_por_ciento():
    catalogo = [_fila_catalogo("SKU1", iva_descripcion="IVA Debito 21%")]
    prov = IvaProvider(consultar=lambda: catalogo)
    assert prov.factor("SKU1") == Decimal("1.21")


def test_iva_factor_10_5_por_ciento():
    catalogo = [_fila_catalogo("SKU1", iva_descripcion="IVA Debito 10.5%")]
    prov = IvaProvider(consultar=lambda: catalogo)
    assert prov.factor("SKU1") == Decimal("1.105")


def test_iva_valor_no_reconocido_devuelve_none():
    catalogo = [_fila_catalogo("SKU1", iva_descripcion="iva debito 21%")]  # minúsculas: no matchea
    prov = IvaProvider(consultar=lambda: catalogo)
    assert prov.factor("SKU1") is None


def test_iva_sku_con_padding_en_catalogo_resuelve_igual():
    # Mismo bug/fix que CostoVigenteProvider (misma fuente SQL) — ver su test.
    catalogo = [_fila_catalogo("SKU1      ", iva_descripcion="IVA Debito 21%")]
    prov = IvaProvider(consultar=lambda: catalogo)
    assert prov.factor("SKU1") == Decimal("1.21")


def test_iva_sku_no_encontrado():
    catalogo = [_fila_catalogo("OTRO", iva_descripcion="IVA Debito 21%")]
    prov = IvaProvider(consultar=lambda: catalogo)
    assert prov.factor("SKU1") is None


# ── ClasificacionProvider (§8.1) ──

def test_clasificacion_sku_vacio_da_sin_pm():
    prov = ClasificacionProvider(sheet_id="x", fetch_fn=lambda sid, tab: [])
    assert prov.pm_y_subcategoria("") == ("SIN PM", None)


def test_clasificacion_match_directo_columna_a():
    fila = [""] * 10
    fila[0], fila[3], fila[4] = "SKU1", "Matias", "Notebooks"
    prov = ClasificacionProvider(sheet_id="x", fetch_fn=lambda sid, tab: [fila])
    assert prov.pm_y_subcategoria("SKU1") == ("Matias", "Notebooks")


def test_clasificacion_fallback_primer_sku_de_lista():
    fila = [""] * 10
    fila[0], fila[3], fila[4] = "SKU1", "Matias", "Notebooks"
    prov = ClasificacionProvider(sheet_id="x", fetch_fn=lambda sid, tab: [fila])
    assert prov.pm_y_subcategoria("SKU1, SKU2") == ("Matias", "Notebooks")


def test_clasificacion_fallback_rango_alternativo_u():
    fila = [""] * 30
    idx_u = ord("U") - ord("A")
    fila[idx_u], fila[idx_u + 3], fila[idx_u + 4] = "SKU1", "Cristian", "Perifericos"
    prov = ClasificacionProvider(sheet_id="x", fetch_fn=lambda sid, tab: [fila])
    assert prov.pm_y_subcategoria("SKU1") == ("Cristian", "Perifericos")


def test_clasificacion_no_encuentra_nada():
    prov = ClasificacionProvider(sheet_id="x", fetch_fn=lambda sid, tab: [[""] * 30])
    assert prov.pm_y_subcategoria("SKU1") == (None, None)


# ── ResponsableProvider (§8.2) ──

def test_responsable_match():
    filas = [["Empresa", "Responsable"], ["Cliente A", "Juan"]]
    prov = ResponsableProvider(sheet_id="x", fetch_fn=lambda sid, tab: filas)
    assert prov.obtener("Cliente A") == "Juan"


def test_responsable_sin_match_devuelve_none():
    filas = [["Empresa", "Responsable"], ["Cliente A", "Juan"]]
    prov = ResponsableProvider(sheet_id="x", fetch_fn=lambda sid, tab: filas)
    assert prov.obtener("Cliente B") is None


# ── MargenObjetivoProvider (§9, §8.6) ──

def test_margen_objetivo_cascada_veronica_matias_cristian():
    hdr = ["SKU", "L3 usd SIN IVA", "L4 usd SIN IVA", "L5 usd SIN IVA"]
    filas_matias = [hdr, ["SKU1", "10", "12", "15"]]

    def fetch(sheet_id, tab):
        return filas_matias if sheet_id == "matias-id" else []

    prov = MargenObjetivoProvider(
        sheet_ids={"veronica": "veronica-id", "matias": "matias-id", "cristian": None},
        fetch_fn=fetch,
    )
    assert prov.l3_l4_l5("SKU1") == (Decimal("10"), Decimal("12"), Decimal("15"))


def test_rentabilidad_real_default_no_encuentro_sku():
    prov = MargenObjetivoProvider(sheet_master_id="master-id", fetch_fn=lambda sid, tab: [["SKU"], ["OTRO"]])
    assert prov.rentabilidad_real("SKU1") == "NO ENCUENTRO SKU"


def test_rentabilidad_real_encontrada():
    hdr = ["SKU", "Margen / Ganancia actual"]
    filas = [hdr, ["SKU1", "25"]]
    prov = MargenObjetivoProvider(sheet_master_id="master-id", fetch_fn=lambda sid, tab: filas)
    assert prov.rentabilidad_real("SKU1") == Decimal("25")


# ── VinculacionProvider (§8.4) — default "OK", nunca se invierte ──

def test_vinculacion_default_ok_sin_match():
    filas = [["Orden", "Vinculacion"], ["999", "PROBLEMA"]]
    prov = VinculacionProvider(sheet_id="x", fetch_fn=lambda sid, tab: filas)
    assert prov.estado("1405031") == "OK"


def test_vinculacion_devuelve_estado_informado():
    filas = [["Orden", "Vinculacion"], ["1405031", "REVISAR"]]
    prov = VinculacionProvider(sheet_id="x", fetch_fn=lambda sid, tab: filas)
    assert prov.estado("1405031") == "REVISAR"


# ── StockProvider (§8.5) ──

def test_stock_y_ventas_30_dias():
    hdr = ["SKU", "Stock", "Ventas 30 Dias"]
    filas = [hdr, ["SKU1", "45", "30"]]
    prov = StockProvider(sheet_id="x", fetch_fn=lambda sid, tab: filas)
    assert prov.stock("SKU1") == Decimal("45")
    assert prov.ventas_30d("SKU1") == Decimal("30")


def test_dias_de_stock_calculado():
    hdr = ["SKU", "Stock", "Ventas 30 Dias"]
    filas = [hdr, ["SKU1", "45", "30"]]
    prov = StockProvider(sheet_id="x", fetch_fn=lambda sid, tab: filas)
    assert prov.dias_de_stock("SKU1") == str(Decimal("45") / (Decimal("30") / Decimal(30)))


def test_dias_de_stock_sin_ventas_da_texto_literal():
    hdr = ["SKU", "Stock", "Ventas 30 Dias"]
    filas = [hdr, ["SKU1", "45", "0"]]
    prov = StockProvider(sheet_id="x", fetch_fn=lambda sid, tab: filas)
    assert prov.dias_de_stock("SKU1") == "Sin ventas"
