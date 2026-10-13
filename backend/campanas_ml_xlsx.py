"""Excel de campañas de MercadoLibre (Central de Promociones): lectura y
agregado de UNA hoja nueva sin alterar nada de lo que ya trae el archivo.

ML valida el formato exacto al subirlo, así que NO se reescribe el libro con
openpyxl (perdería estilos, validaciones, hojas ocultas). Se trabaja a nivel ZIP:
todas las entradas existentes se copian byte a byte y solo se editan, por
inserción de texto, `[Content_Types].xml`, `xl/workbook.xml`,
`xl/_rels/workbook.xml.rels` y `xl/styles.xml` (se agregan fuentes/rellenos/
estilos al final, sin renumerar los existentes). La hoja nueva usa strings
inline, así que `sharedStrings.xml` queda intacto.
"""
import io
import re
import zipfile
from xml.sax.saxutils import escape

HOJA_PROMOCIONES = "Promociones"
# Nombres de columna de ML (fila oculta con los nombres técnicos). Se buscan por nombre, nunca por posición.
# Hay dos tipos de campaña: "reparto" (SELLER_* + MELI_*; se edita SELLER_PERCENTAGE) y "simple"
# (solo DISCOUNT_PERCENTAGE, que se edita; sin aporte de ML separado).
COLUMNAS_LECTURA = (
    "TITLE", "ITEM_ID", "SKU", "PROMO_NAME", "DATE", "ORIGINAL_PRICE", "SELLER_AMOUNT",
    "SELLER_PERCENTAGE", "MELI_AMOUNT", "MELI_PERCENTAGE", "DISCOUNT_PERCENTAGE",
    "FINAL_PRICE", "NEW_RECEIVES", "STATUS", "ACTION", "TARGET_TYPE", "PROMO_ID", "PROMO_TYPE", "ERRORS",
)
# Las que traen TODAS las campañas (las que se conocen; si falta alguna es un aviso, no un corte).
COMUNES = ("TITLE", "ITEM_ID", "SKU", "ORIGINAL_PRICE", "DISCOUNT_PERCENTAGE", "FINAL_PRICE", "NEW_RECEIVES",
           "STATUS", "ACTION", "ERRORS", "PROMO_TYPE")
# Sin estas tres no se puede calcular nada: único caso en que se corta.
INDISPENSABLES = ("ITEM_ID", "ORIGINAL_PRICE")
_CELESTE = "FFCADDF8"

_NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_TIPO_HOJA = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
_CT_HOJA = "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"


class ExcelInvalido(ValueError):
    pass


# ── lectura ─────────────────────────────────────────────────────────────────
def _num(v):
    """Número de una celda de ML: puede venir float, texto '5', '524.95' o '-'."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("\xa0", "").replace("$", "")
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _celda(fila, i):
    return fila[i] if i is not None and i < len(fila) else None


def _es_celeste(c) -> bool:
    return bool(c is not None and c.fill and c.fill.fill_type and (c.fill.fgColor.rgb or "").upper() == _CELESTE)


def leer_promociones(xlsx: bytes, hoja: str = HOJA_PROMOCIONES) -> dict:
    """Lee la hoja de ML de cualquier tipo de campaña. Devuelve
    {'filas', 'columnas', 'campana', 'hojas', 'tipo', 'col_editable', 'avisos'}.

    - tipo = "reparto" si hay SELLER_PERCENTAGE, si no "simple".
    - col_editable = SELLER_PERCENTAGE (reparto) o DISCOUNT_PERCENTAGE (simple).
    - Cada fila sale con el mismo formato: en las simples SELLER_PERCENTAGE = DISCOUNT_PERCENTAGE, SELLER_AMOUNT =
      lista − precio final y MELI_* vacío (el descuento es todo del vendedor).
    - Solo se corta si no es un xlsx, falta la hoja, la fila de nombres o ITEM_ID / ORIGINAL_PRICE / el % de
      descuento. Cualquier otra columna que falte es un aviso."""
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(xlsx), read_only=False, data_only=False)
    except Exception as e:  # zip roto, no es xlsx
        raise ExcelInvalido(f"No se pudo abrir el Excel: {e}")
    if hoja not in wb.sheetnames:
        raise ExcelInvalido(f"No existe la hoja '{hoja}'. Hojas: {wb.sheetnames}")
    ws = wb[hoja]
    cab = None
    for r in range(1, 11):
        vals = [c.value for c in ws[r]]
        if "ITEM_ID" in [str(v).strip() for v in vals if v]:
            cab, fila_cab = {str(v).strip(): i for i, v in enumerate(vals) if v}, r
            break
    if cab is None:
        raise ExcelInvalido("No encontré la fila con los nombres de columna (ITEM_ID).")
    tipo = "reparto" if "SELLER_PERCENTAGE" in cab else "simple"
    col_editable = "SELLER_PERCENTAGE" if tipo == "reparto" else "DISCOUNT_PERCENTAGE"
    faltan = [c for c in (*INDISPENSABLES, col_editable) if c not in cab]
    if faltan:
        raise ExcelInvalido(f"Faltan columnas sin las que no se puede calcular ({tipo}): {faltan}")
    avisos = []
    sin = [c for c in COMUNES if c not in cab]
    if sin:
        avisos.append(f"Faltan columnas que traen todas las campañas (se sigue sin ellas): {', '.join(sin)}")
    if tipo == "reparto":
        sin = [c for c in ("SELLER_AMOUNT", "MELI_PERCENTAGE", "MELI_AMOUNT") if c not in cab]
        if sin:
            avisos.append(f"Campaña con reparto sin las columnas {', '.join(sin)}: se calcula con lo que haya")
    filas = []
    for r in range(fila_cab + 1, ws.max_row + 1):
        fila = [c for c in ws[r]]
        item = (_celda(fila, cab["ITEM_ID"]).value if _celda(fila, cab["ITEM_ID"]) is not None else None)
        if not (isinstance(item, str) and re.match(r"^ML[A-Z]\d+$", item.strip())):
            continue
        d = {"fila": r}
        for n in COLUMNAS_LECTURA:
            if n in cab:
                c = _celda(fila, cab[n])
                d[n] = c.value if c is not None else None
        d["ITEM_ID"] = d["ITEM_ID"].strip()
        d["_celeste"] = _es_celeste(_celda(fila, cab[col_editable]))
        for n in ("ORIGINAL_PRICE", "SELLER_AMOUNT", "SELLER_PERCENTAGE", "MELI_AMOUNT",
                  "MELI_PERCENTAGE", "DISCOUNT_PERCENTAGE", "FINAL_PRICE"):
            if n in d:
                d[n] = _num(d[n])
        if tipo == "simple":
            d["SELLER_PERCENTAGE"] = d.get("DISCOUNT_PERCENTAGE")
            fp, op = d.get("FINAL_PRICE"), d.get("ORIGINAL_PRICE")
            d["SELLER_AMOUNT"] = round(op - fp, 2) if fp is not None and op is not None else None
            d["MELI_PERCENTAGE"] = d["MELI_AMOUNT"] = None
        filas.append(d)
    # Editable = celda celeste. Si ninguna fila la trae (otro formato de campaña), se asume editable todo lo que
    # no esté ya participando, y se avisa.
    if any(f["_celeste"] for f in filas):
        for f in filas:
            f["editable"] = f["_celeste"]
    else:
        if filas:
            avisos.append("No encontré celdas celestes (editables) en la columna del descuento: se asumen editables las filas que no están participando.")
        for f in filas:
            part = str(f.get("STATUS") or "").lower().startswith("particip") or str(f.get("ACTION") or "").lower() == "participar"
            f["editable"] = not part
    for f in filas:
        del f["_celeste"]
    campana = next((f.get("PROMO_NAME") for f in filas if f.get("PROMO_NAME")), None)
    return {"filas": filas, "columnas": cab, "campana": campana, "hojas": wb.sheetnames,
            "tipo": tipo, "col_editable": col_editable, "avisos": avisos}


# ── agregado de hoja a nivel ZIP ────────────────────────────────────────────
def _col(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _nombre_valido(nombre: str, existentes) -> str:
    n = re.sub(r"[\[\]\*\?/\\:]", "-", nombre).strip()[:31] or "ERP"
    base, k = n, 2
    low = {e.lower() for e in existentes}
    while n.lower() in low:
        suf = f" ({k})"
        n, k = base[: 31 - len(suf)] + suf, k + 1
    return n


def _agregar_estilos(styles: str):
    """Agrega 2 fuentes, 3 rellenos y 6 estilos de celda AL FINAL. Devuelve
    (styles_nuevo, {nombre: índice cellXfs}). Los índices existentes no cambian."""
    def cuenta(tag):
        m = re.search(r"<%s count=\"(\d+)\"" % tag, styles)
        if not m:
            raise ExcelInvalido(f"styles.xml sin <{tag}>")
        return int(m.group(1))

    nf, nfill, nxf = cuenta("fonts"), cuenta("fills"), cuenta("cellXfs")
    fuentes = '<font><b/><sz val="10"/><color rgb="FFFFFFFF"/><name val="Arial"/></font><font><b/><sz val="10"/><name val="Arial"/></font><font><sz val="10"/><name val="Arial"/></font>'
    rellenos = ('<fill><patternFill patternType="solid"><fgColor rgb="FF1F3A5F"/><bgColor indexed="64"/></patternFill></fill>'
                '<fill><patternFill patternType="solid"><fgColor rgb="FFFFF2CC"/><bgColor indexed="64"/></patternFill></fill>'
                '<fill><patternFill patternType="solid"><fgColor rgb="FFD9EAD3"/><bgColor indexed="64"/></patternFill></fill>')
    F_H, F_B, F_N = nf, nf + 1, nf + 2
    R_H, R_Y, R_G = nfill, nfill + 1, nfill + 2
    def xf(font, fill, fmt):
        return (f'<xf numFmtId="{fmt}" fontId="{font}" fillId="{fill}" borderId="0" xfId="0" '
                f'applyNumberFormat="1" applyFont="1" applyFill="{1 if fill else 0}"/>')
    xfs = [
        ("cab", xf(F_H, R_H, 0)), ("txt", xf(F_N, 0, 0)), ("num", xf(F_N, 0, 4)),
        ("pct", xf(F_N, 0, 2)), ("copiar", xf(F_B, R_Y, 2)), ("ok", xf(F_B, R_G, 0)),
    ]
    mapa = {n: nxf + i for i, (n, _) in enumerate(xfs)}
    nuevo = styles
    nuevo = re.sub(r'<fonts count="\d+"', f'<fonts count="{nf + 3}"', nuevo, 1)
    nuevo = nuevo.replace("</fonts>", fuentes + "</fonts>", 1)
    nuevo = re.sub(r'<fills count="\d+"', f'<fills count="{nfill + 3}"', nuevo, 1)
    nuevo = nuevo.replace("</fills>", rellenos + "</fills>", 1)
    nuevo = re.sub(r'<cellXfs count="\d+"', f'<cellXfs count="{nxf + len(xfs)}"', nuevo, 1)
    nuevo = nuevo.replace("</cellXfs>", "".join(x for _, x in xfs) + "</cellXfs>", 1)
    return nuevo, mapa


def _xml_hoja(encabezados, filas, estilos) -> str:
    """Hoja con strings inline, fila de encabezado congelada. `filas` es lista de
    listas; cada celda es valor o (valor, 'estilo')."""
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
           f'<dimension ref="A1:{_col(max(len(encabezados), 1) - 1)}{len(filas) + 1}"/>',
           '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
           '<selection pane="bottomLeft"/></sheetView></sheetViews>',
           '<sheetFormatPr defaultRowHeight="15"/>',
           '<cols>' + "".join(f'<col min="{i + 1}" max="{i + 1}" width="{16 if i else 28}" customWidth="1"/>'
                              for i in range(len(encabezados))) + '</cols>',
           '<sheetData>']

    def celda(r, c, v, est):
        ref = f"{_col(c)}{r}"
        s = estilos[est]
        if v is None or v == "":
            return f'<c r="{ref}" s="{s}"/>'
        if isinstance(v, bool):
            v = "SI" if v else "NO"
        if isinstance(v, (int, float)):
            return f'<c r="{ref}" s="{s}"><v>{repr(float(v)) if isinstance(v, float) else v}</v></c>'
        return f'<c r="{ref}" s="{s}" t="inlineStr"><is><t xml:space="preserve">{escape(str(v))}</t></is></c>'

    out.append('<row r="1">' + "".join(celda(1, i, h, "cab") for i, h in enumerate(encabezados)) + '</row>')
    for n, fila in enumerate(filas, start=2):
        cs = []
        for i, v in enumerate(fila):
            est = "txt"
            if isinstance(v, tuple):
                v, est = v
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                est = "num"
            cs.append(celda(n, i, v, est))
        out.append(f'<row r="{n}">' + "".join(cs) + '</row>')
    out.append('</sheetData><pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/></worksheet>')
    return "".join(out)


def agregar_hoja(xlsx: bytes, nombre: str, encabezados, filas) -> tuple[bytes, dict]:
    """Devuelve (xlsx_nuevo, info). Copia byte a byte todas las entradas y agrega
    una hoja al final. No toca `Promociones` ni sharedStrings ni hojas ocultas."""
    try:
        zin = zipfile.ZipFile(io.BytesIO(xlsx))
    except zipfile.BadZipFile as e:
        raise ExcelInvalido(f"No es un xlsx válido: {e}")
    nombres = zin.namelist()
    for req in ("[Content_Types].xml", "xl/workbook.xml", "xl/_rels/workbook.xml.rels", "xl/styles.xml"):
        if req not in nombres:
            raise ExcelInvalido(f"Falta {req} en el xlsx")
    wb = zin.read("xl/workbook.xml").decode("utf-8")
    rels = zin.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    ct = zin.read("[Content_Types].xml").decode("utf-8")
    styles = zin.read("xl/styles.xml").decode("utf-8")
    avisos = []
    if "<workbookProtection" in wb:
        avisos.append("El libro tiene la estructura protegida: agregar hojas puede ser rechazado.")
    existentes = re.findall(r'<sheet [^>]*?name="([^"]*)"', wb)
    nombre = _nombre_valido(nombre, existentes)

    n = 1
    while f"xl/worksheets/sheet{n}.xml" in nombres:
        n += 1
    ruta = f"xl/worksheets/sheet{n}.xml"
    rid = 1 + max([int(x) for x in re.findall(r'Id="rId(\d+)"', rels)] or [0])
    sid = 1 + max([int(x) for x in re.findall(r'sheetId="(\d+)"', wb)] or [0])
    if "</sheets>" not in wb or "</Relationships>" not in rels or "</Types>" not in ct:
        raise ExcelInvalido("Estructura XML inesperada en el xlsx")

    styles_n, estilos = _agregar_estilos(styles)
    hoja_xml = _xml_hoja(encabezados, filas, estilos)
    wb_n = wb.replace("</sheets>", f'<sheet name="{escape(nombre, {chr(34): "&quot;"})}" sheetId="{sid}" r:id="rId{rid}"/></sheets>', 1)
    if 'xmlns:r="' not in wb_n.split(">", 2)[1] and "xmlns:r=" not in wb_n[:wb_n.find("<sheets")]:
        wb_n = wb_n.replace("<workbook ", f'<workbook xmlns:r="{_NS_REL}" ', 1)
    rels_n = rels.replace("</Relationships>", f'<Relationship Id="rId{rid}" Type="{_TIPO_HOJA}" Target="worksheets/sheet{n}.xml"/></Relationships>', 1)
    ct_n = ct.replace("</Types>", f'<Override PartName="/{ruta}" ContentType="{_CT_HOJA}"/></Types>', 1)

    reemplazos = {
        "[Content_Types].xml": ct_n.encode("utf-8"),
        "xl/workbook.xml": wb_n.encode("utf-8"),
        "xl/_rels/workbook.xml.rels": rels_n.encode("utf-8"),
        "xl/styles.xml": styles_n.encode("utf-8"),
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = reemplazos.get(info.filename, zin.read(info.filename))
            zi = zipfile.ZipInfo(info.filename, info.date_time)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = info.external_attr
            zout.writestr(zi, data)
        zi = zipfile.ZipInfo(ruta, (2026, 1, 1, 0, 0, 0))
        zi.compress_type = zipfile.ZIP_DEFLATED
        zout.writestr(zi, hoja_xml.encode("utf-8"))
    return buf.getvalue(), {"hoja": nombre, "ruta": ruta, "avisos": avisos}


def verificar_integridad(original: bytes, nuevo: bytes, hoja_nueva: str) -> dict:
    """Compara original vs nuevo: toda entrada original debe ser idéntica salvo las
    4 editadas a propósito, y esas deben diferir SOLO por lo agregado."""
    zo, zn = zipfile.ZipFile(io.BytesIO(original)), zipfile.ZipFile(io.BytesIO(nuevo))
    editadas = {"[Content_Types].xml", "xl/workbook.xml", "xl/_rels/workbook.xml.rels", "xl/styles.xml"}
    problemas, identicas = [], 0
    for nom in zo.namelist():
        if nom not in zn.namelist():
            problemas.append(f"falta {nom}")
            continue
        a, b = zo.read(nom), zn.read(nom)
        if nom in editadas:
            continue
        if a == b:
            identicas += 1
        else:
            problemas.append(f"cambió {nom}")
    # Las editadas: quitando lo insertado debe volver al original.
    wb_o, wb_n = zo.read("xl/workbook.xml").decode(), zn.read("xl/workbook.xml").decode()
    quitado = re.sub(r'<sheet name="%s"[^>]*/>' % re.escape(escape(hoja_nueva)), "", wb_n, 1)
    if quitado.replace('xmlns:r="%s" ' % _NS_REL, "") != wb_o.replace('xmlns:r="%s" ' % _NS_REL, ""):
        problemas.append("workbook.xml difiere en más que la hoja nueva")
    extra = [n for n in zn.namelist() if n not in zo.namelist()]
    if len(extra) != 1 or not extra[0].startswith("xl/worksheets/sheet"):
        problemas.append(f"entradas nuevas inesperadas: {extra}")
    if zn.testzip() is not None:
        problemas.append("zip dañado")
    # Estilos: los índices originales no cambian (lo nuevo solo se agrega al final).
    so, sn = zo.read("xl/styles.xml").decode(), zn.read("xl/styles.xml").decode()
    for tag in ("fonts", "fills", "borders", "cellXfs", "dxfs"):
        mo = re.search(r"<%s [^>]*>(.*?)</%s>" % (tag, tag), so, re.S)
        mn = re.search(r"<%s [^>]*>(.*?)</%s>" % (tag, tag), sn, re.S)
        if mo and not (mn and mn.group(1).startswith(mo.group(1))):
            problemas.append(f"styles.xml: se alteró el prefijo de <{tag}>")
    return {"ok": not problemas, "entradas_identicas": identicas, "problemas": problemas, "entradas_nuevas": extra}
