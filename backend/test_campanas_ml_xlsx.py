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
