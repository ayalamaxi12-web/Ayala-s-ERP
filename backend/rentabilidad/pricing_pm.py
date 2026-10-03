"""Motor de precios, etapa 2: carga inicial de los precios de los PM desde
sus planillas y vista de todos los SKU con su margen proyectado por canal.

**Carga** (`leer_planilla_pm` + `cargar_precios_pm`): lee la planilla de un
PM ("VENTAS POR CANALES <PM>") y guarda en `pricing_sku`
SOLO lo que el PM decide (doc de diseño §4.1): precio web, forma de pago
web, % ML, condición ML, precio Frávega / OnCity. Todo lo demás (costo,
IVA, comisiones) lo pone el ERP. Las columnas se buscan por título, no por
letra: cada planilla tiene el bloque en otra posición. Relevado de las 4
planillas reales (2026-09-29):

- "WEB NUEVO" = precio web con IVA.
- Forma de pago web: "3 Cuotas" (Laura) o la primera "Forma De Pago" (el
  resto) — valores "Simple" / "3· Cuotas" / "6 Cuotas"...
- % ML: "% ML" (Laura) o "%". ML publica `ROUNDDOWN(web × %; -1) + 9`,
  mismo redondeo que `motor_precios.redondear_precio`.
- Condición ML: solo Laura la tiene (la "Forma De Pago" después de "% ML");
  el resto queda contado.
- Frávega: la primera columna "Fravega" es el precio (= precio ML salvo que
  el PM lo cambie); la otra columna "Fravega" y "On City" son casillas de
  "se publica ahí". Matías no tiene precio propio: toma el de ML.
  OnCity no tiene columna de precio en ninguna planilla: toma el de Frávega.

Fuente principal: el Sheet de cada PM en vivo por API
(`sincronizar_desde_sheets`, decisión de Maxx 2026-10-03: "no quiero cargar
las planillas a mano"). Respaldos: las filas que lee el navegador con su
propia conexión a los Sheets, y el .xlsx subido a mano.

Nada se pisa: si un SKU no cambió respecto de lo vigente no se escribe; si
cambió, fila nueva. `vigente_desde` = "Fecha de Cambio de Precio" de la
planilla si es posterior a la vigente, si no la fecha de carga.

**Vista** (`vista_pricing`): por SKU, precio y margen proyectado en Web, ML,
Frávega y OnCity con el motor, y el margen real de las ventas del ciclo
(órdenes de un solo SKU — la corrida no guarda el importe por línea).
Pendientes conocidos, marcados en `avisos` y no inventados:
- ML ≥ $33.000 sin envío: falta el costo real de envío por publicación.
- Frávega: sin peso y medidas (depósito), el fee es el promedio histórico
  del SKU en las liquidaciones y, si no tiene, el promedio general.
- OnCity: solo comisión (15% + IVA), igual que la rentabilidad real.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Callable

from sqlalchemy.orm import Session

from . import motor_precios as motor
from .models import LiquidacionFravega, PricingSku, VentaEcom

CAMPOS_PM = ("precio_web", "forma_pago_web", "pct_ml", "condicion_ml", "precio_fravega", "precio_oncity")
_INVISIBLES = re.compile(r"[\s​‌‍﻿]+")


def norm_sku(s) -> str:
    if isinstance(s, float) and s.is_integer():  # SKU numérico en Excel: 1020000172.0
        s = int(s)
    return _INVISIBLES.sub("", str(s or "")).upper()


# ── Lectura de la planilla ──

def _texto(v) -> str:
    return str(v).strip() if v is not None else ""


def _num(v) -> Decimal | None:
    """Número de una celda: número de Excel, o texto de Sheets
    ("$ 3.699,50", "108,11%"). Vacío, "-", "#N/A" → None."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float, Decimal)):
        return Decimal(str(v)).quantize(Decimal("0.000001"))
    s = _texto(v).replace("$", "").replace(" ", "")
    pct = s.endswith("%")
    s = s.rstrip("%")
    if not s or s.startswith("#") or s == "-":
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        n = Decimal(s)
    except InvalidOperation:
        return None
    return (n / 100 if pct else n).quantize(Decimal("0.000001"))


def _si(v) -> bool:
    return v is True or _texto(v).upper() in ("TRUE", "VERDADERO", "SI", "SÍ", "1")


def plan_de_forma_pago(v) -> str | None:
    """"Simple" → "1"; "3· Cuotas" / "3 Cuotas" → "3"; vacío → None."""
    s = _texto(v).lower()
    if not s:
        return None
    if s in ("simple", "contado", "1"):
        return "1"
    m = re.match(r"(\d+)", s)
    return m.group(1) if m else None


def _condicion_ml(v) -> str:
    s = _texto(v).lower()
    if "reducid" in s:
        return "reducida"
    plan = plan_de_forma_pago(s)
    return "contado" if plan in (None, "1") else plan


def _fecha(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", _texto(v))
    if not m:
        return None
    a, b, anio = int(m.group(1)), int(m.group(2)), int(m.group(3))
    dia, mes = (b, a) if b > 12 else (a, b)  # Sheet en formato de EE.UU. (m/d/aaaa)
    try:
        return date(anio, mes, dia)
    except ValueError:
        return None


@dataclass
class FilaPm:
    sku: str
    pm: str | None
    precio_web: Decimal | None
    forma_pago_web: str | None
    pct_ml: Decimal | None
    condicion_ml: str
    precio_fravega: Decimal | None
    precio_oncity: Decimal | None
    fecha_cambio: date | None


@dataclass
class LecturaPm:
    filas: list[FilaPm] = field(default_factory=list)
    duplicados: list[str] = field(default_factory=list)
    sin_precio_web: list[str] = field(default_factory=list)


class PlanillaPmInvalida(ValueError):
    pass


def precio_ml(web: Decimal | None, pct: Decimal | None) -> Decimal | None:
    """Precio ML como lo arma la planilla: ROUNDDOWN(web × %; -1) + 9."""
    if not web or not pct:
        return None
    return motor.redondear_precio(web * pct)


def _fila_de_titulos(filas: list[list]) -> int | None:
    """Fila con 'SKU' en A y 'WEB NUEVO' (Matías tiene arriba otra fila de
    títulos de grupo que también empieza con 'SKU')."""
    for i, f in enumerate(filas[:6]):
        if f and _texto(f[0]).upper() == "SKU" and any(_texto(t).lower() == "web nuevo" for t in f):
            return i
    return None


def leer_planilla_pm(filas: list[list]) -> LecturaPm:
    """Filas crudas (fila de títulos incluida) → lo que decide el PM."""
    hr = _fila_de_titulos(filas)
    if hr is None:
        raise PlanillaPmInvalida("No encuentro la fila de títulos ('SKU' en la columna A y 'WEB NUEVO') en las primeras 6 filas.")
    titulos = [_texto(t).lower() for t in filas[hr]]

    def todas(nombre: str) -> list[int]:
        return [i for i, t in enumerate(titulos) if t == nombre]

    def primera(*nombres: str, despues_de: int = -1) -> int | None:
        for n in nombres:
            for i in todas(n):
                if i > despues_de:
                    return i
        return None

    i_web = primera("web nuevo")
    i_fp_web = primera("3 cuotas", "forma de pago")
    i_pct = primera("% ml", "%")
    i_cond = primera("forma de pago", despues_de=i_pct) if i_pct is not None and "% ml" in titulos else None
    i_frav = todas("fravega")
    i_oncity = primera("on city")
    i_pm = primera("pm")
    i_fecha = primera("fecha de cambio de precio")

    def celda(fila, i):
        return fila[i] if i is not None and i < len(fila) else None

    lectura, vistos = LecturaPm(), set()
    for fila in filas[hr + 1:]:
        sku = norm_sku(celda(fila, 0))
        if not sku or sku.startswith("TESTER"):
            continue
        if sku in vistos:
            lectura.duplicados.append(sku)
            continue
        vistos.add(sku)
        web = _num(celda(fila, i_web))
        if not web or web <= 0:
            lectura.sin_precio_web.append(sku)
            web = None
        pct = _num(celda(fila, i_pct))
        pct = pct if pct and pct > 0 else None
        p_ml = precio_ml(web, pct)
        valores_frav = [celda(fila, i) for i in i_frav]
        precios = [n for n in (_num(v) for v in valores_frav) if n and n > 0]
        casilla = [v for v in valores_frav if isinstance(v, bool) or _texto(v).upper() in ("TRUE", "FALSE", "VERDADERO", "FALSO")]
        se_publica = any(_si(v) for v in casilla) if casilla else bool(precios)
        p_frav = (precios[0] if precios else p_ml) if se_publica else None
        p_oncity = (p_frav or p_ml) if _si(celda(fila, i_oncity)) else None
        lectura.filas.append(FilaPm(
            sku=sku, pm=_texto(celda(fila, i_pm)) or None, precio_web=web,
            forma_pago_web=plan_de_forma_pago(celda(fila, i_fp_web)), pct_ml=pct,
            condicion_ml=_condicion_ml(celda(fila, i_cond)), precio_fravega=p_frav, precio_oncity=p_oncity,
            fecha_cambio=_fecha(celda(fila, i_fecha)),
        ))
    return lectura


def leer_xlsx_pm(path: str) -> list[list]:
    """La pestaña del libro que tenga los títulos 'SKU' y 'WEB NUEVO'."""
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    for ws in wb.worksheets:
        filas = [list(f) for f in ws.iter_rows(values_only=True)]
        if _fila_de_titulos(filas) is not None:
            return filas
    raise PlanillaPmInvalida("Ninguna pestaña del archivo tiene las columnas 'SKU' y 'WEB NUEVO'.")


# ── Lectura en vivo de los Sheets de los PM (fuente principal) ──
#
# Los mismos Sheets que el ERP ya lee para comparar precios. Cada PM se
# configura por variable de entorno (Railway): `RENT_SHEET_PM_<PM>_ID` y,
# opcional, `RENT_SHEET_PM_<PM>_TAB` (sin pestaña se busca la que tenga
# 'SKU' + 'WEB NUEVO'). Si falta el ID se usa `RENT_SHEET_MARGEN_<PM>_ID`,
# el que ya usa la rentabilidad de Táctica. La cuenta de servicio
# (`GOOGLE_CREDENTIALS_JSON`) tiene que tener acceso de lectura al Sheet.

PMS = {"VERONICA": "Verónica", "LAURA": "Laura", "CRISTIAN": "Cristian", "MATIAS": "Matías"}


@dataclass(frozen=True)
class FuentePm:
    pm: str  # clave: VERONICA / LAURA / CRISTIAN / MATIAS
    sheet_id: str | None
    tab: str | None

    @property
    def nombre(self) -> str:
        return PMS.get(self.pm, self.pm.title())


def fuentes_pm(env: dict | None = None) -> list[FuentePm]:
    import os

    env = os.environ if env is None else env
    return [
        FuentePm(
            pm=pm,
            sheet_id=env.get(f"RENT_SHEET_PM_{pm}_ID") or env.get(f"RENT_SHEET_MARGEN_{pm}_ID") or None,
            tab=env.get(f"RENT_SHEET_PM_{pm}_TAB") or None,
        )
        for pm in PMS
    ]


def leer_sheet_pm(sheet_id: str, tab: str | None = None, cliente=None) -> list[list]:
    """Filas de la pestaña de precios del PM, con los valores SIN formato
    (números como números, casillas como TRUE/FALSE): el % ML con todos sus
    decimales, no el "108%" que se ve en pantalla."""
    from . import gsheets

    libro = (cliente or gsheets.get_client()).open_by_key(sheet_id)
    hojas = [libro.worksheet(tab)] if tab else libro.worksheets()
    for ws in hojas:
        if not tab and _fila_de_titulos(ws.get_values("A1:FZ6")) is None:
            continue
        return ws.get_values(
            value_render_option="UNFORMATTED_VALUE",  # = gspread.utils.ValueRenderOption.unformatted
            date_time_render_option="FORMATTED_STRING",
        )
    raise PlanillaPmInvalida(
        "Ninguna pestaña del Sheet tiene las columnas 'SKU' y 'WEB NUEVO'" + (f" (pestaña '{tab}')" if tab else "") + "."
    )


@dataclass
class ResultadoSyncPm:
    pm: str
    ok: bool
    detalle: str
    carga: ResultadoCargaPm | None = None


LeerSheetFn = Callable[[str, "str | None"], list[list]]


def sincronizar_desde_sheets(
    db: Session, hoy: date, fuentes: list[FuentePm] | None = None, leer: LeerSheetFn | None = None,
) -> list[ResultadoSyncPm]:
    """Lee el Sheet de cada PM y guarda solo lo que cambió (`cargar_precios_pm`).
    Un PM que falla (sin configurar, sin acceso, sin títulos) no frena a los
    demás: queda en el resultado con el motivo."""
    leer = leer or (lambda sheet_id, tab: leer_sheet_pm(sheet_id, tab))
    resultados = []
    for f in fuentes if fuentes is not None else fuentes_pm():
        if not f.sheet_id:
            resultados.append(ResultadoSyncPm(f.nombre, False, f"Sin configurar: falta RENT_SHEET_PM_{f.pm}_ID."))
            continue
        try:
            lectura = leer_planilla_pm(leer(f.sheet_id, f.tab))
        except Exception as e:  # cada PM por separado: uno caído no tapa al resto
            resultados.append(ResultadoSyncPm(f.nombre, False, f"No se pudo leer el Sheet ({type(e).__name__}: {e})."))
            continue
        carga = cargar_precios_pm(db, lectura, cargado_por=f"Sheet {f.nombre}", hoy=hoy, motivo="Sincronizado desde el Sheet del PM")
        resultados.append(ResultadoSyncPm(
            f.nombre, True, f"{carga.leidos} SKU: {carga.nuevos} nuevos, {carga.cambiados} cambiados, {carga.sin_cambios} sin cambios.",
            carga,
        ))
    return resultados


# ── Carga en pricing_sku ──

def _a_fecha(d):
    return d.date() if isinstance(d, datetime) else d


def vigentes(db: Session, fecha: date | None = None) -> dict[str, PricingSku]:
    """SKU → su fila vigente a `fecha` (default: todas las cargadas)."""
    res: dict[str, PricingSku] = {}
    for f in db.query(PricingSku).all():
        if fecha is not None and f.vigente_desde > fecha:
            continue
        k = norm_sku(f.sku)
        if k not in res or (f.vigente_desde, f.cargado_en) > (res[k].vigente_desde, res[k].cargado_en):
            res[k] = f
    return res


def _igual(a, b) -> bool:
    a, b = (None if x == "" else x for x in (a, b))
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, (Decimal, int, float)) or isinstance(b, (Decimal, int, float)):
        return Decimal(str(a)) == Decimal(str(b))
    return a == b


@dataclass
class ResultadoCargaPm:
    leidos: int = 0
    nuevos: int = 0
    cambiados: int = 0
    sin_cambios: int = 0
    duplicados: list[str] = field(default_factory=list)
    sin_precio_web: list[str] = field(default_factory=list)


def cargar_precios_pm(db: Session, lectura: LecturaPm, cargado_por: str, hoy: date, motivo: str | None = None) -> ResultadoCargaPm:
    res = ResultadoCargaPm(leidos=len(lectura.filas), duplicados=lectura.duplicados, sin_precio_web=lectura.sin_precio_web)
    actuales = vigentes(db)
    for f in lectura.filas:
        valores = {c: getattr(f, c) for c in CAMPOS_PM}
        actual = actuales.get(f.sku)
        if actual is not None and all(_igual(getattr(actual, c), v) for c, v in valores.items()):
            res.sin_cambios += 1
            continue
        if actual is None:
            desde = f.fecha_cambio or hoy
            res.nuevos += 1
        else:
            desde = f.fecha_cambio if f.fecha_cambio and f.fecha_cambio > actual.vigente_desde else hoy
            res.cambiados += 1
        db.add(PricingSku(sku=f.sku, vigente_desde=desde, cargado_por=cargado_por, motivo=motivo, **valores))
    db.flush()
    return res


# ── Vista: todos los SKU con su margen proyectado ──

@dataclass(frozen=True)
class DatosSku:
    costo_usd: Decimal | None
    iva_factor: Decimal | None
    pm: str | None
    categoria: str | None
    subcategoria: str | None


DatosFn = Callable[[str], DatosSku]

_CANAL_REAL = (("MERCADOLIBRE", "ML"), ("WOOCOMMERCE", "WEB"), ("FRAVEGA", "FRAVEGA"), ("ONCITY", "ONCITY"))


def _canal_de_venta(canal: str | None) -> str | None:
    c = (canal or "").upper().replace(" ", "")
    return next((m for prefijo, m in _CANAL_REAL if c.startswith(prefijo)), None)


def margen_real(db: Session, periodo: str | None) -> dict[tuple[str, str], dict]:
    """(SKU, canal) → margen real del período: Σ rentabilidad / Σ venta sin
    IVA de las órdenes de un solo SKU (sin kits ni carritos)."""
    if not periodo:
        return {}
    acum: dict[tuple[str, str], list] = {}
    q = db.query(VentaEcom).filter(VentaEcom.periodo == periodo, VentaEcom.excluido.is_(False))
    for v in q.all():
        skus = (v.skus_vendidos or "").strip()
        canal = _canal_de_venta(v.canal_de_venta)
        if not skus or "," in skus or canal is None or v.rentabilidad is None or not v.precio_sin_iva:
            continue
        a = acum.setdefault((norm_sku(skus), canal), [Decimal(0), Decimal(0), 0])
        a[0] += v.rentabilidad
        a[1] += v.precio_sin_iva
        a[2] += 1
    return {k: {"margen": (r / s).quantize(Decimal("0.0001")), "ordenes": n} for k, (r, s, n) in acum.items() if s}


def fee_historico_fravega(db: Session) -> dict[str, Decimal]:
    """SKU → fee logístico promedio (sin IVA) que Frávega le cobró en las
    liquidaciones cargadas. Cruza la orden de la liquidación con la venta de
    Ecom (`orden_externa`); solo órdenes de un SKU y con fee > 0 (las
    devoluciones netean a 0). Es el paso 2 del orden decidido (2026-09-29):
    sin peso/medidas, el histórico del SKU antes que el promedio."""
    skus = {
        v.orden_externa: norm_sku(v.skus_vendidos)
        for v in db.query(VentaEcom).filter(VentaEcom.orden_externa.isnot(None)).all()
        if v.skus_vendidos and "," not in v.skus_vendidos
    }
    por_orden: dict[str, Decimal] = {}
    for f in db.query(LiquidacionFravega).all():
        por_orden[f.orden] = por_orden.get(f.orden, Decimal(0)) + f.fee_logistico
    acum: dict[str, list[Decimal]] = {}
    for orden, fee in por_orden.items():
        if fee > 0 and orden in skus:
            acum.setdefault(skus[orden], []).append(fee)
    return {sku: (sum(fees) / len(fees)).quantize(_CENTAVO) for sku, fees in acum.items()}


_CENTAVO = Decimal("0.01")
_AVISO_FEE = {
    "historico": "Fee logístico: promedio histórico del SKU en las liquidaciones",
    "promedio": "Fee logístico promedio general: faltan peso y medidas, y el SKU no tiene liquidaciones",
}


def _entradas(
    p: PricingSku, datos: DatosSku, tc: Decimal, fee_hist: dict[str, Decimal] | None = None,
) -> dict[str, tuple[Decimal | None, motor.EntradaMotor | None, list[str]]]:
    costo = datos.costo_usd * tc if datos.costo_usd else None
    base = dict(costo=costo or Decimal(0), iva_factor=datos.iva_factor or Decimal("1.21"))
    p_ml = precio_ml(p.precio_web, p.pct_ml)
    avisos_ml = ["Sin envío: falta el costo real de envío de la publicación"] if p_ml and p_ml >= 33000 else []
    fee = (fee_hist or {}).get(norm_sku(p.sku))
    return {
        "WEB": (p.precio_web, motor.EntradaMotor(canal="WEB", plan=p.forma_pago_web, **base), []),
        "ML": (p_ml, motor.EntradaMotor(canal="ML", categoria=datos.categoria, plan=p.condicion_ml, **base), avisos_ml),
        "FRAVEGA": (p.precio_fravega, motor.EntradaMotor(canal="FRAVEGA", fee_logistico=fee, **base), []),
        "ONCITY": (p.precio_oncity, motor.EntradaMotor(canal="ONCITY", **base),
                   ["Sin fee logístico ni comisión financiera: OnCity no los informa (igual que la rentabilidad real)"]),
    }


def calcular_sku(
    p: PricingSku, datos: DatosSku, tc: Decimal, par: motor.ParametrosMotor, detalle: bool = False,
    fee_hist: dict[str, Decimal] | None = None,
) -> dict:
    canales = {}
    for canal, (precio, entrada, avisos) in _entradas(p, datos, tc, fee_hist).items():
        if not precio:
            continue
        fila = {"precio": precio, "margen": None, "rentabilidad": None, "avisos": list(avisos)}
        if not datos.costo_usd:
            fila["avisos"].insert(0, "Sin costo vigente en Táctica")
        elif not datos.iva_factor:
            fila["avisos"].insert(0, "Sin alícuota de IVA en Táctica")
        else:
            try:
                r = motor.precio_a_margen(precio, entrada, par)
                fila.update(margen=r.margen, rentabilidad=r.rentabilidad)
                if canal == "FRAVEGA":
                    fila["avisos"].append(_AVISO_FEE.get(r.origen_fee, ""))
                if detalle:
                    fila.update(venta_sin_iva=r.venta_sin_iva, cargos=r.cargos, plan=entrada.plan)
            except (motor.ParametroFaltante, ValueError) as e:
                fila["avisos"].insert(0, str(e))
        canales[canal] = fila
    return canales


@dataclass
class FiltrosVista:
    pm: str | None = None
    categoria: str | None = None
    canal: str | None = None
    solo_negativos: bool = False
    margen_max: Decimal | None = None  # fracción
    buscar: str | None = None
    cambiado_desde: date | None = None


def _pasa(fila: dict, f: FiltrosVista) -> bool:
    if f.pm and (fila["pm"] or "").lower() != f.pm.lower():
        return False
    if f.categoria and (fila["categoria"] or "").lower() != f.categoria.lower():
        return False
    if f.buscar and f.buscar.upper() not in fila["sku"]:
        return False
    if f.cambiado_desde and fila["vigente_desde"] < f.cambiado_desde:
        return False
    canales = [c for k, c in fila["canales"].items() if not f.canal or k == f.canal]
    if f.canal and not canales:
        return False
    margenes = [c["margen"] for c in canales if c["margen"] is not None]
    if f.solo_negativos and not any(m < 0 for m in margenes):
        return False
    if f.margen_max is not None and not any(m < f.margen_max for m in margenes):
        return False
    return True


def vista_pricing(
    db: Session, datos_fn: DatosFn, tc: Decimal, fecha: date, filtros: FiltrosVista | None = None,
    periodo_real: str | None = None,
) -> list[dict]:
    par = motor.cargar_parametros(db, fecha)
    real = margen_real(db, periodo_real)
    fee_hist = fee_historico_fravega(db)
    filtros = filtros or FiltrosVista()
    filas = []
    for sku, p in sorted(vigentes(db, fecha).items()):
        datos = datos_fn(p.sku)
        fila = {
            "sku": sku, "pm": datos.pm, "categoria": datos.categoria, "subcategoria": datos.subcategoria,
            "costo_usd": datos.costo_usd, "iva_factor": datos.iva_factor,
            "vigente_desde": _a_fecha(p.vigente_desde), "cargado_por": p.cargado_por,
            "canales": calcular_sku(p, datos, tc, par, fee_hist=fee_hist),
        }
        for canal, c in fila["canales"].items():
            r = real.get((sku, canal))
            c["real"] = r["margen"] if r else None
            c["real_ordenes"] = r["ordenes"] if r else 0
        if _pasa(fila, filtros):
            filas.append(fila)
    return filas


def historial(db: Session, sku: str) -> list[PricingSku]:
    k = norm_sku(sku)
    filas = [f for f in db.query(PricingSku).all() if norm_sku(f.sku) == k]
    return sorted(filas, key=lambda f: (f.vigente_desde, f.cargado_en), reverse=True)
