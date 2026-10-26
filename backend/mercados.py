"""Mercados del Motor de Precios (Bloque 2, PR 4): Mercado Libre, Frávega, OnCity, Megatone y la Web (Mercado Pago).

Las TARIFAS viven en la pestaña «Mercados» del Sheet del ERP (columnas: mercado, concepto, cuotas, porcentaje, incluye IVA, vigencia desde, vigencia hasta,
fuente, nota), no en el código: este módulo las lee, las valida (falta una fila, vigencia vencida, «a confirmar») y arma los parámetros de cada mercado.
`FILAS_INICIALES` es solo la carga inicial de la pestaña (`POST /mercados/init`) y el respaldo cuando la pestaña todavía no existe (se avisa).

La CUENTA de precios es la de siempre (`ayala_core.calcular_precio_condicion`, reverse-markup): para cada mercado cambian los números (comisión base, costo
financiero de cada cuota), nunca la forma. Mercado Libre sigue con los parámetros que ya tenía el Motor (`ayala_core` / `ml_ofertas`): sus filas en la pestaña
son de referencia y no se leen. Nada de acá escribe en Mercado Libre ni en el Sheet del PM.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal

import ayala_core
import ml_foto
from ml_ofertas import CUOTAS_PCT_DEFAULT, IIBB_PCT_DEFAULT, IMP_CHEQUE_PCT_DEFAULT

MERCADOS: dict[str, dict] = {
    "ml": {"nombre": "Mercado Libre", "condiciones": ["contado", "reducida", "3", "6", "9", "12"], "etiqueta_contado": "Contado"},
    "fravega": {"nombre": "Frávega", "condiciones": ["contado", "3", "6", "9", "12"], "etiqueta_contado": "Simple"},
    "oncity": {"nombre": "OnCity", "condiciones": ["contado", "3", "6", "9", "12"], "etiqueta_contado": "Simple"},
    "megatone": {"nombre": "Megatone", "condiciones": ["contado", "3", "6", "9", "12"], "etiqueta_contado": "Simple"},
    "web": {"nombre": "Web (Mercado Pago)", "condiciones": ["contado", "3", "6", "9", "12", "18", "24"], "etiqueta_contado": "Simple"},
}
HEADERS = ["mercado", "concepto", "cuotas", "porcentaje", "incluye IVA", "vigencia desde", "vigencia hasta", "fuente", "nota"]
HEADERS_ENVIOS = ["mercado", "peso desde", "peso hasta", "largo", "ancho", "alto", "costo", "vigencia"]
MODULO_FOTO, CUENTA_FOTO = "mercados_tarifas", "todas"
A_CONFIRMAR = "a confirmar"
# Lo que Maxx ya decidió (2026-10-25): no se marca «a confirmar» aunque la columna «incluye IVA» de la pestaña esté vacía. Siguen a confirmar solo las cuotas de la Web.
DECIDIDOS = {("todos", "costo_orden"), ("web", "comision_base"), ("web", "recargo_cuotas"),
             *{(m, c) for m in ("fravega", "oncity", "megatone") for c in ("comision_base", "cuotas")}}

# Por defecto, ¿qué descuentos comunes aplica cada mercado? Mercado Libre NO lleva el costo por orden hasta que se decida: sumarlo cambiaría sus precios de hoy.
ACTIVOS_POR_DEFECTO = {
    "ml": {"orden": False, "cheque": True, "iibb": True},
    "fravega": {"orden": True, "cheque": True, "iibb": True}, "oncity": {"orden": True, "cheque": True, "iibb": True},
    "megatone": {"orden": True, "cheque": True, "iibb": True}, "web": {"orden": True, "cheque": True, "iibb": True},
}


def _f(mercado, concepto, cuotas="", pct="", iva="", desde="", hasta="", fuente="", nota=""):
    return [mercado, concepto, cuotas, str(pct), iva, desde, hasta, fuente, nota]


def _cuotas_ml():
    return [_f("ml", "cuotas", str(n), str(p), "SI", fuente="panel de parámetros de ML (referencia, no se lee)") for n, p in CUOTAS_PCT_DEFAULT.items()]


def _bloque_fravega(mercado: str, copiado: bool) -> list[list[str]]:
    nota = "copiado de Frávega" if copiado else "comisión base más cuotas (decidido por Maxi)"
    f = "copiado de Frávega" if copiado else "Maxi 2026-10-24"
    cuotas = [("3", "6.8", "21/10/2024", "ID 1034 v6"), ("6", "10.6", "21/02/2024", "ID 1033 v6"), ("9", "13.7", "21/10/2024", "ID 1032 v5"), ("12", "16.6", "21/10/2024", "ID 1031 v5")]
    out = [_f(mercado, "comision_base", "", "15.5", "", fuente=f, nota=nota)]
    for n, p, desde, idv in cuotas:
        out.append(_f(mercado, "cuotas", n, p, "", desde, "31/05/2027", idv if not copiado else f"copiado de Frávega ({idv})",
                      "cuotas sin interés, origen Todos, banco emisor vacío" + ("; copiado de Frávega" if copiado else "")))
    return out


FILAS_INICIALES: list[list[str]] = [
    _f("todos", "costo_orden", "", "149.12", "", fuente="Maxi 2026-10-24", nota="MONTO EN PESOS por orden de Ecom (no es un %). Vale para todos los mercados; activable por mercado."),
    _f("todos", "impuesto_cheque", "", str(IMP_CHEQUE_PCT_DEFAULT), "", fuente="CRITERIOS_MARGEN §2", nota="sobre el precio con IVA"),
    _f("todos", "iibb", "", str(IIBB_PCT_DEFAULT), "", fuente="CRITERIOS_MARGEN §2", nota="sobre el precio sin IVA"),
    _f("ml", "comision_base", "", str(ayala_core.COMISION_ML_DEFAULT), "SI", fuente="panel de parámetros de ML (referencia, no se lee)",
       nota="Decidido por Maxi (25/10): en el Motor la comisión de ML queda en 15,32 %."),
    _f("ml", "reducida", "", str(ayala_core.REDUCIDA_PCT_DEFAULT), "SI", fuente="panel de parámetros de ML (referencia, no se lee)", nota="solo existe en Mercado Libre"),
    *_cuotas_ml(),
    _f("web", "comision_base", "", "6", "", fuente="Mercado Pago (Maxi 2026-10-24)", nota="6 % por cobro, cualquier medio de pago"),
    _f("web", "cuotas", "simple", "0.00", A_CONFIRMAR, fuente="Mercado Pago"),
    *[_f("web", "cuotas", n, p, A_CONFIRMAR, fuente="Mercado Pago") for n, p in (("3", "3.40"), ("6", "7.90"), ("9", "12.60"), ("12", "15.20"), ("18", "22.10"), ("24", "27.60"))],
    _f("web", "recargo_cuotas", "", "20", "", fuente="regla de Maxi", nota="Recargo de 20 % sobre la comisión de cuotas (4,08; 9,48; 15,12; 18,24; 26,52; 33,12 = cuota × 1,20). Editable."),
    *_bloque_fravega("fravega", False), *_bloque_fravega("oncity", True), *_bloque_fravega("megatone", True),
]


# ── lectura / validación ──

def _num(v) -> Decimal | None:
    t = str(v if v is not None else "").strip().replace("$", "").replace("%", "").replace(" ", "")
    if not t:
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return Decimal(t)
    except Exception:
        return None


def _fecha(v) -> date | None:
    t = str(v or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            pass
    return None


def parsear_filas(valores: list[list[str]]) -> list[dict]:
    """Filas crudas de la pestaña (con encabezado) → lista de dicts con claves normalizadas. Ignora filas vacías."""
    if not valores:
        return []
    cab = [re.sub(r"\s+", " ", str(c).strip().lower()) for c in valores[0]]
    idx = {h: cab.index(h) for h in HEADERS if h in cab}
    out = []
    for fila in valores[1:]:
        if not any(str(c).strip() for c in fila):
            continue
        g = lambda h: (fila[idx[h]].strip() if h in idx and idx[h] < len(fila) else "")
        out.append({"mercado": g("mercado").lower(), "concepto": g("concepto").lower(), "cuotas": g("cuotas").lower(), "porcentaje": g("porcentaje"),
                    "incluye_iva": g("incluye iva").lower() or "", "desde": g("vigencia desde"), "hasta": g("vigencia hasta"), "fuente": g("fuente"), "nota": g("nota")})
    return out


def filas_iniciales_parseadas() -> list[dict]:
    return parsear_filas([HEADERS] + FILAS_INICIALES)


def _buscar(filas, mercado, concepto, cuotas=None):
    for f in filas:
        if f["mercado"] == mercado and f["concepto"] == concepto and (cuotas is None or f["cuotas"] == cuotas):
            return f
    return None


def comunes(filas: list[dict]) -> dict:
    """Valores del panel compartido (costo por orden, cheque, IIBB). Si falta una fila de la pestaña se usa el valor de siempre y se avisa."""
    out, avisos = {}, []
    for clave, concepto, defecto in (("costo_orden", "costo_orden", Decimal("149.12")), ("cheque_pct", "impuesto_cheque", IMP_CHEQUE_PCT_DEFAULT), ("iibb_pct", "iibb", IIBB_PCT_DEFAULT)):
        f = _buscar(filas, "todos", concepto)
        v = _num(f["porcentaje"]) if f else None
        if v is None:
            avisos.append({"tipo": "falta", "texto": f"falta dato: «{concepto}» en la pestaña Mercados (se usa {defecto})"})
            v = defecto
        out[clave] = v
    return {"valores": out, "avisos": avisos}


def parametros_mercado(mercado: str, filas: list[dict], hoy: date | None = None, recargo_cuotas: Decimal | None = None) -> dict:
    """Parámetros de un mercado listos para calcular + avisos de configuración (falta una fila, vigencia vencida/futura, «a confirmar», dato copiado)."""
    if mercado not in MERCADOS:
        raise KeyError(mercado)
    hoy = hoy or date.today()
    meta = MERCADOS[mercado]
    nombre = meta["nombre"]
    avisos: list[dict] = []
    notas: list[dict] = []     # información, no cuenta como aviso (p. ej. «copiado de Frávega»)
    if mercado == "ml":
        fin = {"contado": Decimal("0"), "reducida": ayala_core.REDUCIDA_PCT_DEFAULT, **{str(k): v for k, v in CUOTAS_PCT_DEFAULT.items()}}
        return {"mercado": mercado, "nombre": nombre, "condiciones": list(meta["condiciones"]), "etiqueta_contado": meta["etiqueta_contado"],
                "comision_pct": ayala_core.COMISION_ML_DEFAULT, "financiero": fin, "recargo_cuotas": None, "faltantes": {}, "avisos": avisos, "notas": notas,
                "desglose": {c: {"base": ayala_core.COMISION_ML_DEFAULT, "cuotas": fin[c], "recargo": Decimal("0"), "total": ayala_core.COMISION_ML_DEFAULT + fin[c]} for c in fin}}
    def revisar(f, que):
        if not f:
            return
        if f["incluye_iva"] in ("", A_CONFIRMAR) and (f["mercado"], f["concepto"]) not in DECIDIDOS:
            if (A_CONFIRMAR, que) not in {(a["tipo"], a["que"]) for a in avisos}:
                avisos.append({"tipo": A_CONFIRMAR, "que": que, "texto": f"{que}: a confirmar"})
        if "copiado" in (f["nota"] + f["fuente"]).lower() and not any(n["que"] == "copiado" for n in notas):
            notas.append({"que": "copiado", "texto": f"Las cifras de {nombre} están copiadas de Frávega."})
        h, d = _fecha(f["hasta"]), _fecha(f["desde"])
        if h and h < hoy:
            avisos.append({"tipo": "vencida", "que": que, "texto": f"{que}: vigencia vencida el {h.strftime('%d/%m/%Y')}"})
        if d and d > hoy:
            avisos.append({"tipo": "no_vigente", "que": que, "texto": f"{que}: vigente desde el {d.strftime('%d/%m/%Y')} (todavía no rige)"})
    base_f = _buscar(filas, mercado, "comision_base")
    base = _num(base_f["porcentaje"]) if base_f else None
    faltantes: dict[str, str] = {}
    if base is None:
        avisos.append({"tipo": "falta", "que": "comisión base", "texto": f"falta dato: comisión base de {nombre}"})
        for c in meta["condiciones"]:
            faltantes[c] = f"falta dato: comisión base de {nombre}"
    revisar(base_f, f"Comisión base de {nombre}")
    recargo = Decimal("0")
    if mercado == "web":
        rf = _buscar(filas, "web", "recargo_cuotas")
        recargo = recargo_cuotas if recargo_cuotas is not None else (_num(rf["porcentaje"]) if rf and _num(rf["porcentaje"]) is not None else Decimal("0"))
        if rf:
            revisar(rf, "Recargo sobre comisión de cuotas")
        else:
            avisos.append({"tipo": "falta", "que": "recargo", "texto": "falta dato: recargo sobre la comisión de cuotas de la Web (se usa 0)"})
    fin, desglose = {}, {}
    for c in meta["condiciones"]:
        if c == "contado":
            f = _buscar(filas, mercado, "cuotas", "simple")
            p = _num(f["porcentaje"]) if f else Decimal("0")        # Simple: solo la base (la Web trae su propia fila con 0,00)
            if f:
                revisar(f, f"Cuotas de {nombre}")
        else:
            f = _buscar(filas, mercado, "cuotas", c)
            p = _num(f["porcentaje"]) if f else None
            if p is None:
                faltantes.setdefault(c, f"falta dato: tarifa de {c} cuotas de {nombre}")
                avisos.append({"tipo": "falta", "que": f"{c} cuotas", "texto": f"falta dato: tarifa de {c} cuotas de {nombre}"})
                continue
            revisar(f, f"Cuotas de {nombre}")
        r = (p * recargo / 100) if c != "contado" else Decimal("0")
        fin[c] = p + r
        desglose[c] = {"base": base, "cuotas": p, "recargo": r, "total": (base + p + r) if base is not None else None}
    return {"mercado": mercado, "nombre": nombre, "condiciones": list(meta["condiciones"]), "etiqueta_contado": meta["etiqueta_contado"], "comision_pct": base,
            "financiero": fin, "recargo_cuotas": recargo if mercado == "web" else None, "faltantes": faltantes, "avisos": avisos, "notas": notas, "desglose": desglose}


def calcular_mercado(par: dict, *, costo_sin_iva: Decimal, iva_factor: Decimal, envio_real: Decimal, renta_por_condicion: dict[str, Decimal],
                     envio_full: bool = False, costo_orden: Decimal = Decimal("0"), cheque_pct: Decimal = IMP_CHEQUE_PCT_DEFAULT,
                     iibb_pct: Decimal = IIBB_PCT_DEFAULT) -> tuple[dict[str, Decimal], dict[str, str]]:
    """Precio de cada condición de pago del mercado con la fórmula de siempre. Devuelve (precios, errores): una condición con un dato que falta no se
    calcula y queda en `errores` como «falta dato: …» (nunca se inventa una tarifa)."""
    precios, errores = {}, {}
    for c in par["condiciones"]:
        if c in par["faltantes"] or c not in par["financiero"]:
            errores[c] = par["faltantes"].get(c, "falta dato")
            continue
        renta = renta_por_condicion.get(c)
        if renta is None:
            errores[c] = f"falta dato: renta objetivo de {c}"
            continue
        precios[c] = ayala_core.calcular_precio_condicion(
            costo_sin_iva=costo_sin_iva, iva_factor=iva_factor, envio_real=envio_real, financiero_pct=par["financiero"][c], renta_pct=renta,
            comision_pct=par["comision_pct"], iibb_pct=iibb_pct, imp_cheque_pct=cheque_pct, envio_full=envio_full, costo_orden=costo_orden)
    return precios, errores


def desglose(precio: Decimal, *, costo_sin_iva: Decimal, iva_factor: Decimal, envio_real: Decimal, comision_pct: Decimal, financiero_pct: Decimal,
             iibb_pct: Decimal, cheque_pct: Decimal, costo_orden: Decimal = Decimal("0"), envio_full: bool = False) -> dict[str, Decimal]:
    """De qué se compone el precio (los mismos conceptos y signos que el desglose de Mercado Libre de la pantalla, `ayalaCoreDesgloseDesdeP`): lo que se
    descuenta de la venta y lo que queda de renta en pesos. Solo para mostrar; el precio sale de `ayala_core.calcular_precio_condicion`."""
    iva_serv = Decimal("1.21")
    comision = -(comision_pct / 100) * precio
    financiero = -(financiero_pct / 100) * precio
    envio = -envio_real
    iibb = -(iibb_pct / 100) * (precio / iva_factor)
    cheque = -(cheque_pct / 100) * precio
    full = -(ayala_core.ENVIO_FULL_PCT_DEFAULT / 100) * precio if envio_full else Decimal("0")
    iva_comision = comision / iva_serv - comision
    iva_envio = envio / iva_serv - envio
    renta = precio / iva_factor + (-costo_sin_iva + comision + financiero + envio + iibb + cheque + full + iva_comision + iva_envio - costo_orden)
    return {"comision": -comision, "financiero": -financiero, "envio": -envio, "iibb": -iibb, "imp_cheque": -cheque, "envio_full": -full, "costo_orden": costo_orden, "renta": renta}


# ── foto guardada de las tarifas («Tarifas: hace X · Actualizar») ──

def leer_hoja(gs, spreadsheet_id: str, pestana: str = "Mercados") -> list[list[str]]:
    return gs.open_by_key(spreadsheet_id).worksheet(pestana).get_all_values()


def armar_payload(filas: list[dict], origen: str) -> dict:
    return {"filas": filas, "origen": origen}


def actualizar_foto(sesion_fn, lector, ahora=None) -> dict:
    """Lee la pestaña «Mercados» (con `lector()`), la guarda como foto y devuelve el payload. Si falla conserva la foto anterior y anota el error (sin URL)."""
    try:
        filas = parsear_filas(lector())
        if not filas:
            raise ValueError("la pestaña «Mercados» está vacía")
    except Exception as e:  # noqa: BLE001
        with sesion_fn() as db:
            ml_foto.guardar_fallo(db, MODULO_FOTO, CUENTA_FOTO, "", ml_foto.mensaje_para_usuario(e))
        raise
    p = armar_payload(filas, "hoja")
    with sesion_fn() as db:
        ml_foto.guardar_exito(db, MODULO_FOTO, CUENTA_FOTO, "", p, "completa", 0, 0, [])
    return p


def foto_o_iniciales(sesion_fn) -> tuple[dict, dict]:
    """(payload, info). Sin foto guardada se usan las filas iniciales del código y `info.origen == 'codigo'` (la pantalla lo avisa)."""
    try:
        with sesion_fn() as db:
            f = ml_foto.leer(db, MODULO_FOTO, CUENTA_FOTO, "")
            v = ml_foto.vista_foto(f)
    except Exception:  # noqa: BLE001 -- base caída: igual se puede calcular con los valores iniciales
        v = {"existe": False}
    if v.get("existe"):
        return v["payload"], {"origen": "hoja", "obtenido_en": v["obtenido_en"], "error_msg": v.get("error_msg"), "error_en": v.get("error_en")}
    return armar_payload(filas_iniciales_parseadas(), "codigo"), {"origen": "codigo", "obtenido_en": None, "error_msg": v.get("error_msg"), "error_en": v.get("error_en")}


def crear_pestanas(gs, spreadsheet_id: str) -> dict:
    """Crea «Mercados» (con los valores iniciales) y «Envios» (solo encabezados, para cargarla después) si todavía no existen. No pisa nada existente."""
    ss = gs.open_by_key(spreadsheet_id)
    existentes = {w.title for w in ss.worksheets()}
    hecho = {}
    if "Mercados" not in existentes:
        ws = ss.add_worksheet(title="Mercados", rows=max(100, len(FILAS_INICIALES) + 20), cols=len(HEADERS))
        ws.update(values=[HEADERS] + FILAS_INICIALES, range_name="A1")
        hecho["Mercados"] = f"creada con {len(FILAS_INICIALES)} filas"
    else:
        hecho["Mercados"] = "ya existía: no se tocó"
    if "Envios" not in existentes:
        ws = ss.add_worksheet(title="Envios", rows=200, cols=len(HEADERS_ENVIOS))
        ws.update(values=[HEADERS_ENVIOS], range_name="A1")
        hecho["Envios"] = "creada vacía, con encabezados"
    else:
        hecho["Envios"] = "ya existía: no se tocó"
    return hecho
