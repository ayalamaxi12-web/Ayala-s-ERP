"""Migración histórica (Sheet -> venta_tactica/venta_ecom, sin motor) --
fixtures basadas en headers reales confirmados en vivo contra el Sheet de
Ventas & Rentabilidad (2026-08-18), no inventados."""
from datetime import date
from decimal import Decimal

from rentabilidad.importar_historico import (
    ORIGEN_IMPORTADO,
    _fecha,
    _num,
    guardar_historico,
    importar,
    parsear_ecom,
    parsear_tactica,
    periodo_23_a_22,
    tabs_historicas,
)
from rentabilidad.models import CierreRentabilidad, Regimen, VentaTactica


# ── tabs_historicas — matchea por sufijo, no por prefijo "Base " ──

def test_tabs_historicas_matchea_con_y_sin_prefijo_base():
    pestanas = [
        "Base Abril - Mayo ECOM", "Base Abril - Mayo TACTICA",
        "Julio - Agosto ECOM", "Julio - Agosto TACTICA",  # sin "Base " -- caso real
        "Base Brasil", "Cobranza", "Tabla Ventas Julio", "Explicacion",
    ]
    ecom, tactica = tabs_historicas(pestanas)
    assert ecom == ["Base Abril - Mayo ECOM", "Julio - Agosto ECOM"]
    assert tactica == ["Base Abril - Mayo TACTICA", "Julio - Agosto TACTICA"]


def test_tabs_historicas_excluye_brasil():
    ecom, tactica = tabs_historicas(["Base Brasil ECOM", "Base Brasil TACTICA"])
    assert ecom == []
    assert tactica == []


def test_tabs_historicas_excluye_borradores():
    # Hallazgo real del dry-run 2026-08-18: "Borrador Diario Tactica"/
    # "Borrador MP TACTICA/ECOM" matchean el sufijo pero son planillas de
    # trabajo, no períodos cerrados.
    ecom, tactica = tabs_historicas(["Borrador Diario Tactica", "Borrador MP TACTICA", "Borrador MP ECOM"])
    assert ecom == []
    assert tactica == []


# ── periodo_23_a_22 ──

def test_periodo_dia_23_arranca_periodo_del_mismo_mes():
    assert periodo_23_a_22(date(2026, 7, 23)) == (date(2026, 7, 23), date(2026, 8, 22))


def test_periodo_dia_22_cierra_periodo_del_mes_anterior():
    assert periodo_23_a_22(date(2026, 8, 22)) == (date(2026, 7, 23), date(2026, 8, 22))


def test_periodo_dia_1_pertenece_al_periodo_que_arranco_el_23_anterior():
    assert periodo_23_a_22(date(2026, 8, 1)) == (date(2026, 7, 23), date(2026, 8, 22))


def test_periodo_cruza_fin_de_anio():
    assert periodo_23_a_22(date(2026, 12, 23)) == (date(2026, 12, 23), date(2027, 1, 22))
    assert periodo_23_a_22(date(2027, 1, 5)) == (date(2026, 12, 23), date(2027, 1, 22))


# ── _num / _fecha ──

def test_num_parsea_formato_real_del_sheet():
    assert _num("$1,269.00") == Decimal("1269.00")
    assert _num(" $1,269.00") == Decimal("1269.00")
    assert _num("220.238") == Decimal("220.238")
    assert _num("83%") == Decimal("83")
    assert _num("#N/A") is None
    assert _num("-") is None
    assert _num("") is None
    assert _num(None) is None


def test_fecha_formato_d_m_aaaa():
    assert _fecha("13/5/2026") == date(2026, 5, 13)
    assert _fecha("") is None
    assert _fecha(None) is None


def test_fecha_cae_a_m_d_cuando_d_m_es_invalido():
    # Hallazgo real del dry-run 2026-08-18: el mes más nuevo de cada
    # pestaña "X - Y TACTICA" viene en m/d, ej. "6/22/2026" = 22 de junio
    # (día=6/mes=22 es imposible, 22 no es un mes real).
    assert _fecha("6/22/2026") == date(2026, 6, 22)
    assert _fecha("7/21/2026") == date(2026, 7, 21)


def test_fecha_ambigua_prefiere_d_m():
    # "5/6/2026" es válido en ambos órdenes -- gana d/m (no se pisa una
    # lectura ya válida con el fallback).
    assert _fecha("5/6/2026") == date(2026, 6, 5)


# ── parsear_tactica — headers reales de "Base Abril - Mayo TACTICA" ──

_HEADERS_TACTICA_ABRIL_MAYO = [
    "Fecha", "Empresa", "Codigo", "Descripción", "Fabricante", "Tipo de Producto",
    "Familia", "Vendedor", "Tipo de Factura", "Nº Factura", "Precio de Compra de Lista",
    "Costo de Lista", "Precio de Venta de Lista", "Cantidad", "Costo Total En Dolares",
    "Precio de Venta", "Precio de Venta IVA", "Margen", "IVA", "imp ch", "IIBB", "TC",
    "Costo Total Pesos", "Margen", "COSTO FINANCIERO  1", "COSTO FINANCIERO 2",
    "Margen real", "Margen %", "SKU MARGEN NEGATIVO", "PM", "Canal Tactica",
    "DEVUELVE GUITA", "Responasables", "Subcategoria",  # typo real confirmado en vivo
]


def test_parsear_tactica_fila_real_abril_mayo(db_session):
    fila = [
        "15/5/2026", "Zona de Oportunidades SRL", "106R02773COMP", "Cartucho Toner",
        "SkyFord", "Productos para la venta", "CARTUCHOS", "Estefania Zeballos",
        "CEA - Nota de Crédito A En Ventas - Electrónica", "00003-00009517",
        "0.00", "2.64", "-8,187.00", "-10.00", "-26.40", "-79,370.00", "1.21",
        "-41,354.00", "-16,667.70", "952.44", "3,968.50", "1,425.00", "37,620.00",
        "-116,990.00", "$2,881.13", "", "-33,947.93", "42.77%", "MARGEN POSITIVO",
        "Veronica", "Canal Tactica", "NO DEVUELVE GUITA", "Estefania Zeballos", "Cartucho De Toner",
    ]
    [venta] = parsear_tactica(db_session, [_HEADERS_TACTICA_ABRIL_MAYO, fila], "Base Abril - Mayo TACTICA")

    assert venta.origen == ORIGEN_IMPORTADO
    assert venta.fecha == date(2026, 5, 15)
    assert venta.codigo == "106R02773COMP"
    assert venta.cantidad == Decimal("-10.00")
    assert venta.tc == Decimal("1425.00")
    assert venta.costo_total_pesos == Decimal("37620.00")
    assert venta.margen_real == Decimal("-33947.93")
    assert venta.pm == "Veronica"
    # typo "Responasables" -- no se pierde el dato
    assert venta.responsable == "Estefania Zeballos"
    # 15/5 -> período 23/04 al 22/05
    assert venta.periodo == "2026-04-23_2026-05-22"
    # régimen resuelto igual que el motor en vivo (CEA -> Cuenta 1)
    assert venta.regimen == Regimen.CUENTA_1


def test_parsear_tactica_ignora_fila_sin_codigo(db_session):
    fila_vacia = [""] * len(_HEADERS_TACTICA_ABRIL_MAYO)
    resultado = parsear_tactica(db_session, [_HEADERS_TACTICA_ABRIL_MAYO, fila_vacia], "x")
    assert resultado == []


# ── parsear_ecom — headers reales de "Base Abril - Mayo ECOM" ──

_HEADERS_ECOM = [
    "Número Orden", "Sku's Vendidos", "FechaCreaciónVenta", "EstadoVenta", "FechaPago",
    "EstadoPago", "Costo Sin Iva (total de productos)", "IVA A Favor", "Canal De Venta",
    "Usuario Integración", "Medio De Cobro", "Entrega / Envio", "Comisión Venta",
    "Comisión Cobro", "Costo Envío", "Impuestos (retenciones)", "Precio SIN IVA",
    "Total Impuestos", "imp ch", "IIBB", "Precio Final", "Dif IVA", "Cash",
    "Utilidad Venta", "Utilidad Costo", "Neto", "Costo Total", "Rentabilidad", "PM",
    "Subcategoria", "Rentabilidad USD", "Facturacion USD", "Responsable De Ventas",
    "Categoria", "Subcategoria2", "Periodo", "Semana", "Sku Negativo", "TC",
]


def test_parsear_ecom_fila_real_abril_mayo():
    fila = [
        "1378417", "HEATTAPE-6MM", "13/5/2026", "Cerrada", "13/5/2026", "Cobrado",
        "0.01", "$0.00", "Mercadolibre Carrito", "GLOBALELECTRONICSARG", "Mercado Pago",
        "Prioritario a domicilio - Envío gratis", "0", "0", "0", "11.48", "1048.76",
        "220.24", "15.23", "52.44", "$1,269.00", "220.238", "1048.752", "83%", "476%",
        "$981.09", "$14.15", "$966.94", "Matias", "Sublimación", "$0.68", "$0.90",
        "NOESTA", "Gráfica y Estampado", "Consumibles para Sublimación", "Mayo", "3",
        "MARGEN NEGATIVO", "1415",
    ]
    [venta] = parsear_ecom([_HEADERS_ECOM, fila], "Base Abril - Mayo ECOM")

    assert venta.origen == ORIGEN_IMPORTADO
    assert venta.numero_orden == "1378417"
    assert venta.skus_vendidos == "HEATTAPE-6MM"
    assert venta.fecha_creacion_venta == date(2026, 5, 13)
    assert venta.canal_de_venta == "Mercadolibre Carrito"
    assert venta.costo_sin_iva == Decimal("0.01")
    assert venta.precio_final == Decimal("1269.00")
    assert venta.rentabilidad == Decimal("966.94")
    assert venta.pm == "Matias"
    assert venta.tc == Decimal("1415")
    assert venta.periodo == "2026-04-23_2026-05-22"


def test_parsear_ecom_header_numero_orden_en_blanco_cae_a_columna_a():
    # Hallazgo real del dry-run 2026-08-18: "Base Mayo - Junio ECOM" tiene el
    # header de la columna A vacío ("  ") -- sin el fallback posicional, las
    # 11.430 filas de ese período se perdían enteras (numero_orden vacío).
    headers_sin_header_a = ["  "] + _HEADERS_ECOM[1:]
    fila = [
        "1384326", "INKCARTHP664XLCV2", "25/5/2026", "Abierta", "25/5/2026", "Cobrado",
    ] + [""] * (len(_HEADERS_ECOM) - 6)
    [venta] = parsear_ecom([headers_sin_header_a, fila], "Base Mayo - Junio ECOM")
    assert venta.numero_orden == "1384326"


def test_parsear_ecom_ignora_fila_sin_orden_o_sku():
    fila_sin_sku = ["1", ""] + [""] * (len(_HEADERS_ECOM) - 2)
    resultado = parsear_ecom([_HEADERS_ECOM, fila_sin_sku], "x")
    assert resultado == []


# ── importar() — corta en la fecha de corte, no pisa el período actual ──

def test_importar_excluye_filas_del_periodo_actual(db_session):
    fila_vieja = [
        "15/5/2026", "Empresa", "SKU1", "Desc", "Fab", "Tipo", "Fam", "Vend",
        "FEA", "00003-00000001", "0", "1", "0", "1", "-1", "1000", "1210",
        "", "210", "0", "0", "1500", "1000", "", "0", "0", "1000", "82.6%",
        "", "PM1", "Canal Tactica", "", "Resp1", "Sub1",
    ]
    fila_actual = [
        "1/8/2026", "Empresa", "SKU1", "Desc", "Fab", "Tipo", "Fam", "Vend",
        "FEA", "00003-00000002", "0", "1", "0", "1", "-1", "1000", "1210",
        "", "210", "0", "0", "1500", "1000", "", "0", "0", "1000", "82.6%",
        "", "PM1", "Canal Tactica", "", "Resp1", "Sub1",
    ]

    def fetch_fn(sheet_id, tab):
        return [_HEADERS_TACTICA_ABRIL_MAYO, fila_vieja, fila_actual]

    resultado = importar(
        db_session, "sheet-x", ["Base Mayo - Junio TACTICA"], fetch_fn,
        hasta_fecha_exclusive=date(2026, 7, 23),
    )
    assert len(resultado.tactica) == 1
    assert resultado.tactica[0].fecha == date(2026, 5, 15)
    assert resultado.filas_ignoradas.get("Base Mayo - Junio TACTICA") == 1


# ── guardar_historico — borra e inserta por período, registra el cierre ──

def test_guardar_historico_persiste_y_registra_cierre(db_session):
    fila_vieja = [
        "15/5/2026", "Empresa", "SKU1", "Desc", "Fab", "Tipo", "Fam", "Vend",
        "FEA", "00003-00000001", "0", "1", "0", "1", "-1", "1000", "1210",
        "", "210", "0", "0", "1500", "1000", "", "0", "0", "1000", "82.6%",
        "", "PM1", "Canal Tactica", "", "Resp1", "Sub1",
    ]

    def fetch_fn(sheet_id, tab):
        return [_HEADERS_TACTICA_ABRIL_MAYO, fila_vieja]

    resultado = importar(
        db_session, "sheet-x", ["Base Abril - Mayo TACTICA"], fetch_fn,
        hasta_fecha_exclusive=date(2026, 7, 23),
    )
    guardar_historico(db_session, resultado)
    db_session.commit()

    filas = db_session.query(VentaTactica).all()
    assert len(filas) == 1
    assert filas[0].origen == ORIGEN_IMPORTADO
    assert filas[0].periodo == "2026-04-23_2026-05-22"

    cierre = db_session.get(CierreRentabilidad, "2026-04-23_2026-05-22")
    assert cierre is not None
    assert cierre.tactica_guardado is True
    assert cierre.desde == date(2026, 4, 23)
    assert cierre.hasta == date(2026, 5, 22)


def test_guardar_historico_reemplaza_periodo_no_hace_upsert(db_session):
    fila = [
        "15/5/2026", "Empresa", "SKU1", "Desc", "Fab", "Tipo", "Fam", "Vend",
        "FEA", "00003-00000001", "0", "1", "0", "1", "-1", "1000", "1210",
        "", "210", "0", "0", "1500", "1000", "", "0", "0", "1000", "82.6%",
        "", "PM1", "Canal Tactica", "", "Resp1", "Sub1",
    ]

    def fetch_fn(sheet_id, tab):
        return [_HEADERS_TACTICA_ABRIL_MAYO, fila]

    # Dos corridas independientes (cada `importar()` arma objetos nuevos,
    # como pasaría en la vida real al ejecutar la migración de nuevo) --
    # `guardar_historico` debe reemplazar el período, no duplicar filas.
    resultado1 = importar(db_session, "sheet-x", ["Base Abril - Mayo TACTICA"], fetch_fn, date(2026, 7, 23))
    guardar_historico(db_session, resultado1)
    db_session.commit()

    resultado2 = importar(db_session, "sheet-x", ["Base Abril - Mayo TACTICA"], fetch_fn, date(2026, 7, 23))
    guardar_historico(db_session, resultado2)
    db_session.commit()

    filas = db_session.query(VentaTactica).all()
    assert len(filas) == 1  # no duplica
