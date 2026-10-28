"""Tests de `campanas_ml_xlsx.py`: la hoja agregada no debe alterar nada del
original. Se construye un xlsx tipo ML (hoja oculta, validación, estilos) sin
depender del archivo real; si está en el scratchpad también se prueba."""
import io
import os
import zipfile

import openpyxl
import pytest
from openpyxl.styles import PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

import campanas_ml_xlsx as c

REAL = "/tmp/claude-0/-home-user/f12170ee-4e93-5b42-a699-852f592134b3/scratchpad/ml/madre.xlsx"


def _ml_sintetico() -> bytes:
    wb = openpyxl.Workbook()
    wb.active.title = "Ayuda"
    oc = wb.create_sheet("hidden")
    oc["A1"] = "meli-campaign-id"
    oc.sheet_state = "veryHidden"
    ws = wb.create_sheet("Promociones")
    ws.append(["TITLE", "ITEM_ID", "SKU", "PROMO_NAME", "ORIGINAL_PRICE", "SELLER_AMOUNT",
               "SELLER_PERCENTAGE", "MELI_AMOUNT", "MELI_PERCENTAGE", "DISCOUNT_PERCENTAGE", "FINAL_PRICE", "ACTION"])
    for _ in range(4):
        ws.append(["texto"])
    ws.append(["Toner", "MLA1", "SKU-1", "Día", 10000.0, "500", "5", "-", "-", 5.0, 9500.0, "Aplicar propuesta"])
    ws.append(["Cart", "MLA2", None, "Día", 20000.0, 1000.0, 9.5, 100.0, 0.5, 10.0, 18000.0, "Participar"])
    ws["G6"].fill = PatternFill("solid", fgColor="FFCADDF8")
    ws["G6"].number_format = "0.00"
    ws.freeze_panes = "C6"
    dv = DataValidation(type="list", formula1='"Aplicar propuesta,No aplicar"')
    ws.add_data_validation(dv)
    dv.add("L6:L7")
    ws.row_dimensions[1].hidden = True
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def test_leer_por_nombre_y_valores():
    r = c.leer_promociones(_ml_sintetico())
    assert [f["ITEM_ID"] for f in r["filas"]] == ["MLA1", "MLA2"]
    f1, f2 = r["filas"]
    assert f1["SELLER_PERCENTAGE"] == 5.0 and f1["MELI_PERCENTAGE"] is None and f1["SELLER_AMOUNT"] == 500.0
    assert f2["MELI_PERCENTAGE"] == 0.5 and f2["SKU"] is None
    assert f1["fila"] == 6


def test_leer_falla_fuerte_si_falta_columna_o_hoja():
    wb = openpyxl.Workbook()
    wb.active.title = "Promociones"
    wb.active.append(["ITEM_ID", "TITLE"])
    b = io.BytesIO(); wb.save(b)
    with pytest.raises(c.ExcelInvalido, match="Faltan columnas"):
        c.leer_promociones(b.getvalue())
    with pytest.raises(c.ExcelInvalido, match="No existe la hoja"):
        c.leer_promociones(_ml_sintetico(), hoja="Otra")
    with pytest.raises(c.ExcelInvalido):
        c.leer_promociones(b"no es un zip")


def _agregar(xlsx):
    return c.agregar_hoja(xlsx, "ERP Análisis", ["ITEM_ID", "VALOR A COPIAR"],
                          [["MLA1", (5, "copiar")], ["MLA2", ("x & <y>", "txt")]])


def test_agregar_no_toca_nada_del_original():
    o = _ml_sintetico()
    n, info = _agregar(o)
    rep = c.verificar_integridad(o, n, info["hoja"])
    assert rep["ok"], rep
    zo, zn = zipfile.ZipFile(io.BytesIO(o)), zipfile.ZipFile(io.BytesIO(n))
    for nom in zo.namelist():
        if nom not in ("[Content_Types].xml", "xl/workbook.xml", "xl/_rels/workbook.xml.rels", "xl/styles.xml"):
            assert zo.read(nom) == zn.read(nom), nom
    wb = openpyxl.load_workbook(io.BytesIO(n))
    assert wb.sheetnames == ["Ayuda", "hidden", "Promociones", "ERP Análisis"]
    assert wb["hidden"].sheet_state == "veryHidden"
    assert wb["ERP Análisis"]["B3"].value == "x & <y>" and wb["ERP Análisis"]["B2"].value == 5
    assert wb["ERP Análisis"].freeze_panes == "A2"
    # Validación y relleno de Promociones siguen intactos.
    assert len(wb["Promociones"].data_validations.dataValidation) == 1
    assert wb["Promociones"]["G6"].fill.fgColor.rgb == "FFCADDF8"


def test_verificar_detecta_alteraciones():
    o = _ml_sintetico()
    n, info = _agregar(o)
    zin = zipfile.ZipFile(io.BytesIO(n))
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for i in zin.infolist():
            d = zin.read(i.filename)
            if i.filename.endswith("sheet3.xml"):
                d = d.replace(b"MLA1", b"MLA9")
            z.writestr(i.filename, d)
    rep = c.verificar_integridad(o, b.getvalue(), info["hoja"])
    assert not rep["ok"] and any("sheet3" in p for p in rep["problemas"])


def test_nombre_de_hoja_unico_y_31_chars():
    n, info = c.agregar_hoja(_ml_sintetico(), "Promociones", ["A"], [["x"]])
    assert info["hoja"] == "Promociones (2)"
    n, info = c.agregar_hoja(_ml_sintetico(), "x" * 50 + "[?]", ["A"], [["x"]])
    assert len(info["hoja"]) <= 31


def test_agregar_dos_veces_ids_unicos():
    o = _ml_sintetico()
    n1, i1 = _agregar(o)
    n2, i2 = c.agregar_hoja(n1, "Otra", ["A"], [["x"]])
    assert i1["ruta"] != i2["ruta"]
    assert openpyxl.load_workbook(io.BytesIO(n2)).sheetnames[-2:] == ["ERP Análisis", "Otra"]


@pytest.mark.skipif(not os.path.exists(REAL), reason="Excel real de ML no disponible")
def test_excel_real_de_ml():
    o = open(REAL, "rb").read()
    r = c.leer_promociones(o)
    assert len(r["filas"]) == 1885 and sum(f["editable"] for f in r["filas"]) == 1877
    n, info = _agregar(o)
    rep = c.verificar_integridad(o, n, info["hoja"])
    assert rep["ok"], rep
    assert zipfile.ZipFile(io.BytesIO(o)).read("xl/worksheets/sheet3.xml") == zipfile.ZipFile(io.BytesIO(n)).read("xl/worksheets/sheet3.xml")


def test_endpoints(monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.delenv("ERP_API_KEY", raising=False)
    import main
    cli = TestClient(main.app)
    f = {"archivo": ("a.xlsx", _ml_sintetico())}
    r = cli.post("/campanas-ml/leer", files=f)
    assert r.status_code == 200 and r.json()["filas"] == 2 and r.json()["con_aporte_ml"] == 1
    r = cli.post("/campanas-ml/probar-hoja", files={"archivo": ("a.xlsx", _ml_sintetico())})
    assert r.status_code == 200 and '"ok": true' in r.headers["x-integridad"]
    assert "ERP Prueba" in openpyxl.load_workbook(io.BytesIO(r.content)).sheetnames
    assert cli.post("/campanas-ml/leer", files={"archivo": ("a.xlsx", b"basura")}).status_code == 422


# ── Campañas SIMPLES (solo DISCOUNT_PERCENTAGE) y variantes de columnas ──
COMUNES = ["TITLE", "ITEM_ID", "SKU", "PROMO_NAME", "ORIGINAL_PRICE", "DISCOUNT_PERCENTAGE", "FINAL_PRICE", "NEW_RECEIVES",
           "STATUS", "ACTION", "ERRORS", "PROMO_TYPE"]


def _ml_simple(cols=None, extra=(), celeste=True, filas=None):
    """Excel de campaña simple como los de ML: fila 1 con nombres, 4 filas de ayuda, datos desde la 6."""
    cols = list(cols or COMUNES) + list(extra)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Promociones"
    ws.append(cols)
    for _ in range(4):
        ws.append(["ayuda"])
    datos = filas or [
        {"TITLE": "Silla", "ITEM_ID": "MLA10", "SKU": "SIL-1", "PROMO_NAME": "Sumate", "ORIGINAL_PRICE": 20000.0,
         "DISCOUNT_PERCENTAGE": 10.0, "FINAL_PRICE": 18000.0, "NEW_RECEIVES": "$ 12,000.50", "STATUS": "Nueva propuesta",
         "ACTION": "Aplicar propuesta", "PROMO_TYPE": "SMART_CAMPAIGN"},
        {"TITLE": "Mesa", "ITEM_ID": "MLA11", "SKU": None, "PROMO_NAME": "Sumate", "ORIGINAL_PRICE": 50000.0,
         "DISCOUNT_PERCENTAGE": 15, "FINAL_PRICE": 42500.0, "STATUS": "Participando", "ACTION": "Participar", "PROMO_TYPE": "SMART_CAMPAIGN"}]
    for d in datos:
        ws.append([d.get(c) for c in cols])
    if celeste and "DISCOUNT_PERCENTAGE" in cols:
        ws.cell(6, cols.index("DISCOUNT_PERCENTAGE") + 1).fill = PatternFill("solid", fgColor="FFCADDF8")
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def test_campana_simple_se_detecta_y_el_descuento_es_todo_del_vendedor():
    r = c.leer_promociones(_ml_simple())
    assert r["tipo"] == "simple" and r["col_editable"] == "DISCOUNT_PERCENTAGE" and r["avisos"] == []
    f1, f2 = r["filas"]
    assert (f1["SELLER_PERCENTAGE"], f1["SELLER_AMOUNT"], f1["MELI_PERCENTAGE"], f1["MELI_AMOUNT"]) == (10.0, 2000.0, None, None)
    assert f1["editable"] is True and f2["editable"] is False and f2["SELLER_PERCENTAGE"] == 15.0
    assert r["campana"] == "Sumate"


def test_reparto_sigue_siendo_reparto():
    r = c.leer_promociones(_ml_sintetico())
    assert r["tipo"] == "reparto" and r["col_editable"] == "SELLER_PERCENTAGE"


def test_sin_celdas_celestes_asume_editable_lo_que_no_participa_y_avisa():
    r = c.leer_promociones(_ml_simple(celeste=False))
    assert [f["editable"] for f in r["filas"]] == [True, False]
    assert any("celestes" in a for a in r["avisos"])


def test_columnas_opcionales_faltantes_son_aviso_no_error():
    cols = ["ITEM_ID", "ORIGINAL_PRICE", "DISCOUNT_PERCENTAGE"]  # sin TITLE, SKU, FINAL_PRICE, ERRORS, ...
    datos = [{"ITEM_ID": "MLA10", "ORIGINAL_PRICE": 100.0, "DISCOUNT_PERCENTAGE": 8.0}]
    r = c.leer_promociones(_ml_simple(cols=cols, filas=datos))
    assert len(r["filas"]) == 1 and r["filas"][0]["SELLER_AMOUNT"] is None
    assert any("Faltan columnas que traen todas las campañas" in a and "SKU" in a for a in r["avisos"])


@pytest.mark.parametrize("extra", [(), tuple(f"EXTRA_{i}" for i in range(8))])
def test_28_a_36_columnas_con_columnas_desconocidas(extra):
    r = c.leer_promociones(_ml_simple(cols=COMUNES + [f"RELLENO_{i}" for i in range(16)], extra=extra))
    assert len(r["filas"]) == 2 and r["tipo"] == "simple"


def test_sin_lo_indispensable_si_falla_con_mensaje_claro():
    with pytest.raises(c.ExcelInvalido, match="ORIGINAL_PRICE"):
        c.leer_promociones(_ml_simple(cols=["ITEM_ID", "DISCOUNT_PERCENTAGE"], filas=[{"ITEM_ID": "MLA1", "DISCOUNT_PERCENTAGE": 5}]))
    with pytest.raises(c.ExcelInvalido, match="DISCOUNT_PERCENTAGE"):
        c.leer_promociones(_ml_simple(cols=["ITEM_ID", "ORIGINAL_PRICE"], filas=[{"ITEM_ID": "MLA1", "ORIGINAL_PRICE": 5}]))


def test_filas_cortas_no_rompen_la_lectura():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Promociones"
    ws.append(COMUNES)
    ws.append(["x"]); ws.append(["x"]); ws.append(["x"]); ws.append(["x"])
    ws.append(["Silla", "MLA10"])  # fila truncada: faltan todas las demás celdas
    ws.append(["Mesa", "MLA11", "S", "P", 100.0, 5.0])
    b = io.BytesIO(); wb.save(b)
    r = c.leer_promociones(b.getvalue())
    assert [f["ITEM_ID"] for f in r["filas"]] == ["MLA10", "MLA11"] and r["filas"][0]["ORIGINAL_PRICE"] is None


def test_la_hoja_nueva_es_la_misma_venga_el_tipo_que_venga():
    for xl in (_ml_simple(), _ml_sintetico()):
        r = c.leer_promociones(xl)
        filas = [[f["ITEM_ID"], f.get("SKU"), f["ORIGINAL_PRICE"], f["SELLER_PERCENTAGE"]] for f in r["filas"]]
        n, info = c.agregar_hoja(xl, "ERP Análisis", ["ITEM_ID", "SKU", "LISTA", "% ACTUAL"], filas)
        assert c.verificar_integridad(xl, n, info["hoja"])["ok"]
        ws = openpyxl.load_workbook(io.BytesIO(n))["ERP Análisis"]
        assert [x.value for x in ws[1]] == ["ITEM_ID", "SKU", "LISTA", "% ACTUAL"]


# Excels reales de 6 campañas de ML (si están en el scratchpad de la sesión; se saltea si no).
_CAMP = "/tmp/claude-0/-home-user/f12170ee-4e93-5b42-a699-852f592134b3/scratchpad/camp/"
_ESPERADO = {"1_Dia_de_la_Madre": ("reparto", 1885), "1_Con_aporte_de_Mercado_Libre": ("reparto", 191),
             "1_Sumate_al_Dia_de_la_Madre": ("simple", 4), "1_SEMANA_DEL_MUEBLE": ("simple", 2),
             "1_Acelera_tus_ventas_de_stock_Full": ("simple", 3), "1_Lo_mejor_de_todos_los_dias": ("simple", 79)}


@pytest.mark.parametrize("nombre", sorted(_ESPERADO))
def test_campanas_reales_de_ml(nombre):
    path = _CAMP + nombre + ".xlsx"
    if not os.path.exists(path):
        pytest.skip("Excel real no disponible")
    o = open(path, "rb").read()
    r = c.leer_promociones(o)
    tipo, n = _ESPERADO[nombre]
    assert r["tipo"] == tipo and len(r["filas"]) == n
    assert r["col_editable"] == ("SELLER_PERCENTAGE" if tipo == "reparto" else "DISCOUNT_PERCENTAGE")
    assert all(f["ORIGINAL_PRICE"] and f["SELLER_PERCENTAGE"] is not None for f in r["filas"]) and any(f["editable"] for f in r["filas"])
    nuevo, info = c.agregar_hoja(o, "ERP Análisis", ["ITEM_ID"], [[f["ITEM_ID"]] for f in r["filas"]])
    assert c.verificar_integridad(o, nuevo, info["hoja"])["ok"]


# ── Decisiones sobre propuestas de ML (FINAL_PRICE + ACTION) ──

def test_aplicar_decisiones_cambia_solo_precio_y_accion_de_las_filas_que_cambian():
    b = _ml_sintetico()
    nuevo, inf = c.aplicar_decisiones(b, [{"fila": 6, "aplicar": False, "final_price": 9000.5}, {"fila": 7, "aplicar": True, "final_price": 18000}])
    assert inf["precios_cambiados"] == 1 and inf["no_aplicar"] == 1 and inf["resto_del_archivo_igual"] is True and inf["rechazadas"] == []
    f = {x["fila"]: x for x in c.leer_promociones(nuevo)["filas"]}
    assert f[6]["FINAL_PRICE"] == 9000.5 and f[6]["ACTION"] == "No aplicar"
    assert f[7]["FINAL_PRICE"] == 18000.0 and f[7]["ACTION"] == "Aplicar propuesta"     # la 7 ya estaba igual en precio; ACTION "Participar" pasa a la opción de ML
    ws = openpyxl.load_workbook(io.BytesIO(nuevo))["Promociones"]
    assert ws.data_validations.dataValidation and ws["G6"].fill.fgColor.rgb == "FFCADDF8"   # validación y formato intactos


def test_aplicar_decisiones_rechaza_precios_invalidos_y_filas_inexistentes_sin_tocar_nada():
    b = _ml_sintetico()
    nuevo, inf = c.aplicar_decisiones(b, [{"fila": 6, "aplicar": True, "final_price": 99999}, {"fila": 6, "aplicar": True, "final_price": 0}, {"fila": 99, "aplicar": True}])
    assert len(inf["rechazadas"]) == 3 and inf["precios_cambiados"] == 0
    assert {x["fila"]: x["FINAL_PRICE"] for x in c.leer_promociones(nuevo)["filas"]}[6] == 9500.0


def test_aplicar_decisiones_sin_cambios_deja_el_archivo_igual():
    b = _ml_sintetico()
    nuevo, inf = c.aplicar_decisiones(b, [{"fila": 6, "aplicar": True, "final_price": 9500}])
    assert inf["sin_cambio"] == 1 and inf["precios_cambiados"] == 0 and inf["resto_del_archivo_igual"] is True


def test_aplicar_decisiones_exige_columnas_de_propuestas():
    wb = openpyxl.Workbook()
    wb.active.title = "Promociones"
    wb.active.append(["ITEM_ID", "ORIGINAL_PRICE", "SELLER_PERCENTAGE"])
    wb.active.append(["MLA1", 100.0, 5])
    bio = io.BytesIO(); wb.save(bio)
    with pytest.raises(c.ExcelInvalido, match="FINAL_PRICE"):
        c.aplicar_decisiones(bio.getvalue(), [{"fila": 2, "aplicar": False}])
