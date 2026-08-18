"""Migración histórica: pestañas viejas del Sheet de Ventas & Rentabilidad
(`docs/index.html`, `DASH_SHEET_ID`) -> `venta_tactica`/`venta_ecom`, **sin
correr el motor**.

Pedido de Maxx (2026-08-18): los períodos ya cerrados en el Sheet se
persisten tal cual ya están calculados (Ecom re-derivado hoy vía API tiene
costo *vigente*, no histórico — ver docstring de `ingesta_ecom_api.py`, así
que recalcular períodos viejos daría números distintos a los que realmente
se usaron en su momento). Solo el período actual (desde que existe acceso
directo SQL/API) se recalcula con el motor nuevo — eso lo hace
`/cierres/tactica` y `/cierres/ecom` de siempre, no este módulo.

Cada pestaña ya está separada por sistema — "<algo> ECOM" y "<algo>
TACTICA" (a veces con prefijo "Base ", a veces sin él: se matchea por
sufijo, no por prefijo, porque "Junio - Julio TACTICA" y "Julio - Agosto
ECOM/TACTICA" no tienen "Base " y por eso hoy el dashboard en vivo ni
siquiera las carga — hallazgo aparte, no bug de este módulo). Las pestañas
"Tabla Ventas <mes>"/"Nueva Tabla Ventas <mes>" son tablas dinámicas
armadas a mano a partir de estas dos — no son fuente, se ignoran solas al
no matchear el sufijo.

Período: no se usan los nombres de pestaña como período (`_periodo_de_rango`
ya es la convención del resto de `rentabilidad/` — ver api.py). Cada fila se
re-etiqueta por su propia fecha con la regla real del negocio (23 de un mes
a 22 del siguiente, confirmada por Maxx), no por en qué pestaña vivía.

Columnas ambiguas/no usadas en ningún cálculo (`Margen` informativo,
`Margen` incoherente en TACTICA; `Utilidad Venta`/`Utilidad Costo` en % en
ECOM) se guardan con el mejor esfuerzo de parseo tal cual vienen, sin
inventar una convención distinta a la que ya tenían en el Sheet -- son
INFORMATIVO/ROTO, ningún cálculo depende de ellas.
"""
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from . import gsheets
from .api import _periodo_de_rango, extraer_comprobante
from .models import VentaEcom, VentaTactica
from .persistencia import registrar_cierre
from .regimen import resolver_regimen

ORIGEN_IMPORTADO = "importado_sheet"

_RE_TAB_ECOM = re.compile(r"ecom\s*$", re.IGNORECASE)
_RE_TAB_TACTICA = re.compile(r"tactica\s*$", re.IGNORECASE)


def tabs_historicas(todas_las_pestanas: list[str]) -> tuple[list[str], list[str]]:
    """Separa las pestañas fuente (ECOM/TACTICA) de todo lo demás del libro
    (Cobranza, Explicacion, tablas dinámicas, reportes por PM, etc.) -- por
    sufijo, no por prefijo "Base " (ver docstring del módulo). Excluye
    "Brasil" (página aparte) y "Borrador" (hallazgo del dry-run 2026-08-18:
    "Borrador Diario Tactica"/"Borrador MP TACTICA/ECOM" matchean el sufijo
    pero son planillas de trabajo, no períodos cerrados)."""
    def _valida(t: str) -> bool:
        tl = t.lower()
        return "brasil" not in tl and "borrador" not in tl

    ecom = [t for t in todas_las_pestanas if _valida(t) and _RE_TAB_ECOM.search(t)]
    tactica = [t for t in todas_las_pestanas if _valida(t) and _RE_TAB_TACTICA.search(t)]
    return ecom, tactica


def _num(valor: str | None) -> Decimal | None:
    """Parsea un número tal como lo escribe el Excel: `$1,269.00`, `220.238`,
    `83%`, `#N/A`, `-`, vacío. `#N/A`/`-`/vacío -> None. `%` se guarda como
    el número tal cual (ej. "83%" -> 83), no se convierte a fracción -- ver
    docstring del módulo."""
    if valor is None:
        return None
    s = str(valor).strip()
    if s in ("", "-", "#N/A", "#¡DIV/0!", "#DIV/0!"):
        return None
    s = s.replace("$", "").replace("%", "").replace(",", "").strip()
    if s in ("", "-"):
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


_RE_FECHA = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


def _fecha(valor: str | None) -> date | None:
    """Formato real del Sheet: `d/m/aaaa` (ej. `13/5/2026`) -- con un
    fallback real, no inventado: hallazgo del dry-run 2026-08-18, en las
    pestañas de dos meses ("Mayo - Junio", "Junio - Julio", "Julio -
    Agosto") el mes MÁS NUEVO del período viene cargado en `m/d/aaaa` (ej.
    `6/22/2026` = 22 de junio) mientras el resto de la pestaña está en
    `d/m/aaaa` -- confirmado sin excepciones: las ~819/124/145 fechas que
    `d/m` no puede interpretar (día > 12 imposible como mes) SIEMPRE caen,
    bajo `m/d`, exactamente en el mes más nuevo nombrado por la pestaña, sin
    dispersarse a meses random. Por eso el fallback solo se activa cuando
    `d/m` da una fecha imposible -- nunca pisa una lectura `d/m` ya válida,
    aunque sea ambigua."""
    if not valor:
        return None
    m = _RE_FECHA.match(str(valor).strip())
    if not m:
        return None
    a, b, anio = (int(g) for g in m.groups())
    try:
        return date(anio, b, a)  # d/m
    except ValueError:
        pass
    try:
        return date(anio, a, b)  # fallback m/d
    except ValueError:
        return None


def periodo_23_a_22(fecha: date) -> tuple[date, date]:
    """Período real del negocio (confirmado por Maxx, 2026-08-18): del 23 de
    un mes al 22 del siguiente. Una fecha del 1 al 22 pertenece al período
    que empezó el 23 del mes anterior; del 23 al fin de mes, al que arranca
    ese mismo 23."""
    if fecha.day >= 23:
        desde = date(fecha.year, fecha.month, 23)
        mes_siguiente = fecha.month + 1
        anio_hasta = fecha.year + (1 if mes_siguiente > 12 else 0)
        mes_siguiente = mes_siguiente if mes_siguiente <= 12 else 1
    else:
        mes_anterior = fecha.month - 1
        anio_desde = fecha.year - (1 if mes_anterior < 1 else 0)
        mes_anterior = mes_anterior if mes_anterior >= 1 else 12
        desde = date(anio_desde, mes_anterior, 23)
        anio_hasta = fecha.year
        mes_siguiente = fecha.month
    hasta = date(anio_hasta, mes_siguiente, 22)
    return desde, hasta


def _idx(mapa: dict[str, int], *candidatos: str) -> int | None:
    return gsheets.indice_columna(mapa, candidatos)


@dataclass
class ResultadoImportacion:
    tactica: list[VentaTactica] = field(default_factory=list)
    ecom: list[VentaEcom] = field(default_factory=list)
    filas_ignoradas: dict[str, int] = field(default_factory=dict)  # pestaña -> cantidad


def parsear_tactica(db: Session, filas: list[list[str]], pestana: str) -> list[VentaTactica]:
    if len(filas) < 2:
        return []
    mapa = gsheets.mapa_columnas(filas[0])
    c = {
        "fecha": _idx(mapa, "fecha"),
        "empresa": _idx(mapa, "empresa"),
        "codigo": _idx(mapa, "codigo"),
        "descripcion": _idx(mapa, "descripción", "descripcion"),
        "fabricante": _idx(mapa, "fabricante"),
        "tipo_producto": _idx(mapa, "tipo de producto"),
        "familia": _idx(mapa, "familia"),
        # "Responasables" es un typo real en "Base Abril - Mayo TACTICA" —
        # candidato extra para no perder el dato en ese período puntual.
        "vendedor": _idx(mapa, "vendedor"),
        "responsable": _idx(mapa, "responsable", "responasables"),
        "tipo_factura": _idx(mapa, "tipo de factura"),
        "nro_factura": _idx(mapa, "nº factura", "n° factura", "numero factura"),
        "precio_compra_lista": _idx(mapa, "precio de compra de lista"),
        "costo_lista": _idx(mapa, "costo de lista"),
        "precio_venta_lista": _idx(mapa, "precio de venta de lista"),
        "cantidad": _idx(mapa, "cantidad"),
        "costo_total_dolares": _idx(mapa, "costo total en dolares", "costo total en dólares"),
        "precio_venta": _idx(mapa, "precio de venta"),
        "precio_venta_iva": _idx(mapa, "precio de venta iva"),
        "iva_producto": _idx(mapa, "iva producto"),
        "iva": _idx(mapa, "iva"),
        "imp_cheque": _idx(mapa, "imp ch"),
        "iibb": _idx(mapa, "iibb"),
        "tc": _idx(mapa, "tc"),
        "costo_total_pesos": _idx(mapa, "costo total pesos"),
        "costo_financiero_1": _idx(mapa, "costo financiero  1", "costo financiero 1"),
        "costo_financiero_2": _idx(mapa, "costo financiero 2"),
        "margen_real": _idx(mapa, "margen real"),
        "margen_pct": _idx(mapa, "margen %"),
        "sku_margen_negativo": _idx(mapa, "sku margen negativo"),
        "pm": _idx(mapa, "pm"),
        "subcategoria": _idx(mapa, "subcategoria", "subcategoría"),
        "margen_l3": _idx(mapa, "margen l3"),
        "margen_l4": _idx(mapa, "margen l4"),
        "margen_l5": _idx(mapa, "margen l5"),
    }

    resultado = []
    for fila in filas[1:]:
        def g(clave):
            return gsheets.valor(fila, c[clave])

        codigo = g("codigo")
        fecha_venta = _fecha(g("fecha"))
        if not codigo or fecha_venta is None:
            continue

        tipo_factura_txt = g("tipo_factura")
        nro_factura = g("nro_factura")
        comprobante = extraer_comprobante(tipo_factura_txt)
        regimen = resolver_regimen(db, comprobante, nro_factura)

        desde, hasta = periodo_23_a_22(fecha_venta)
        responsable = g("responsable") or g("vendedor") or None

        resultado.append(VentaTactica(
            periodo=_periodo_de_rango(desde, hasta),
            origen=ORIGEN_IMPORTADO,
            excluido=False,
            motivo_exclusion=None,
            regimen=regimen,
            fecha=fecha_venta,
            empresa=g("empresa"),
            codigo=codigo,
            descripcion=g("descripcion") or None,
            fabricante=g("fabricante") or None,
            tipo_producto=g("tipo_producto") or None,
            familia=g("familia") or None,
            vendedor=g("vendedor") or None,
            tipo_factura=tipo_factura_txt,
            nro_factura=nro_factura,
            precio_compra_lista=_num(g("precio_compra_lista")),
            costo_lista=_num(g("costo_lista")),
            precio_venta_lista=_num(g("precio_venta_lista")),
            cantidad=_num(g("cantidad")) or Decimal(0),
            costo_total_dolares=_num(g("costo_total_dolares")),
            precio_venta=_num(g("precio_venta")) or Decimal(0),
            iva_producto=_num(g("iva_producto")),
            margen_informado=None,
            iva=_num(g("iva")),
            imp_cheque=_num(g("imp_cheque")),
            iibb=_num(g("iibb")),
            tc=_num(g("tc")) or Decimal(0),
            costo_total_pesos=_num(g("costo_total_pesos")),
            margen_x=None,
            costo_financiero_1=_num(g("costo_financiero_1")),
            costo_financiero_2=_num(g("costo_financiero_2")),
            margen_real=_num(g("margen_real")),
            margen_pct=_num(g("margen_pct")),
            sku_margen_negativo=g("sku_margen_negativo") or None,
            pm=g("pm") or None,
            canal_tactica="Canal Tactica",
            subcategoria=g("subcategoria") or None,
            precio_venta_iva=_num(g("precio_venta_iva")),
            responsable=responsable,
            margen_l3=_num(g("margen_l3")),
            margen_l4=_num(g("margen_l4")),
            margen_l5=_num(g("margen_l5")),
        ))
    return resultado


def parsear_ecom(filas: list[list[str]], pestana: str) -> list[VentaEcom]:
    if len(filas) < 2:
        return []
    mapa = gsheets.mapa_columnas(filas[0])
    idx_numero_orden = _idx(mapa, "número orden", "numero orden")
    if idx_numero_orden is None:
        # Hallazgo real del dry-run 2026-08-18: en "Base Mayo - Junio ECOM"
        # el header de la columna A está en blanco (celda vacía) -- el dato
        # sigue estando ahí, así que se cae a la posición fija (columna A,
        # siempre "Número Orden" en toda pestaña ECOM real vista hasta hoy).
        idx_numero_orden = 0
    c = {
        "numero_orden": idx_numero_orden,
        "skus_vendidos": _idx(mapa, "sku's vendidos", "skus vendidos"),
        "fecha_creacion": _idx(mapa, "fechacreaciónventa", "fecha creación venta", "fecha creacion venta"),
        "estado_venta": _idx(mapa, "estadoventa", "estado venta"),
        "fecha_pago": _idx(mapa, "fechapago", "fecha pago"),
        "estado_pago": _idx(mapa, "estadopago", "estado pago"),
        "costo_sin_iva": _idx(mapa, "costo sin iva"),
        "iva_a_favor": _idx(mapa, "iva a favor"),
        "canal": _idx(mapa, "canal de venta"),
        "usuario_integracion": _idx(mapa, "usuario integración", "usuario integracion"),
        "medio_de_cobro": _idx(mapa, "medio de cobro"),
        "entrega_envio": _idx(mapa, "entrega"),
        "comision_venta": _idx(mapa, "comisión venta", "comision venta"),
        "comision_cobro": _idx(mapa, "comisión cobro", "comision cobro"),
        "costo_envio": _idx(mapa, "costo env"),
        "impuestos_informados": _idx(mapa, "impuestos (retenciones)", "impuestos"),
        "precio_sin_iva": _idx(mapa, "precio sin iva"),
        "total_impuestos": _idx(mapa, "total impuestos"),
        "imp_cheque": _idx(mapa, "imp ch"),
        "iibb": _idx(mapa, "iibb"),
        "precio_final": _idx(mapa, "precio final"),
        "dif_iva": _idx(mapa, "dif iva"),
        "cash": _idx(mapa, "cash"),
        "utilidad_venta": _idx(mapa, "utilidad venta"),
        "utilidad_costo": _idx(mapa, "utilidad costo"),
        "neto": _idx(mapa, "neto"),
        "costo_total": _idx(mapa, "costo total"),
        "rentabilidad": _idx(mapa, "rentabilidad"),
        "pm": _idx(mapa, "pm"),
        "subcategoria": _idx(mapa, "subcategoria", "subcategoría"),
        "rentabilidad_usd": _idx(mapa, "rentabilidad usd"),
        "facturacion_usd": _idx(mapa, "facturacion usd", "facturación usd"),
        "responsable_de_ventas": _idx(mapa, "responsable de ventas"),
        "categoria": _idx(mapa, "categoria", "categoría"),
        "subcategoria2": _idx(mapa, "subcategoria2"),
        "periodo_excel": _idx(mapa, "periodo"),
        "semana": _idx(mapa, "semana"),
        "sku_negativo": _idx(mapa, "sku negativo"),
        "tc": _idx(mapa, "tc"),
    }

    resultado = []
    for fila in filas[1:]:
        def g(clave):
            return gsheets.valor(fila, c[clave])

        numero_orden = g("numero_orden")
        skus = g("skus_vendidos")
        if not numero_orden or not skus:
            continue
        fecha_ref = _fecha(g("fecha_creacion")) or _fecha(g("fecha_pago"))
        if fecha_ref is None:
            continue
        desde, hasta = periodo_23_a_22(fecha_ref)

        resultado.append(VentaEcom(
            periodo=_periodo_de_rango(desde, hasta),
            origen=ORIGEN_IMPORTADO,
            excluido=False,
            motivo_exclusion=None,
            numero_orden=numero_orden,
            skus_vendidos=skus,
            fecha_creacion_venta=_fecha(g("fecha_creacion")),
            estado_venta=g("estado_venta") or None,
            fecha_pago=_fecha(g("fecha_pago")),
            estado_pago=g("estado_pago") or None,
            costo_sin_iva=_num(g("costo_sin_iva")) or Decimal(0),
            iva_a_favor=_num(g("iva_a_favor")),
            canal_de_venta=g("canal") or None,
            usuario_integracion=g("usuario_integracion") or None,
            medio_de_cobro=g("medio_de_cobro") or None,
            entrega_envio=g("entrega_envio") or None,
            comision_venta=_num(g("comision_venta")) or Decimal(0),
            comision_cobro=_num(g("comision_cobro")) or Decimal(0),
            costo_envio=_num(g("costo_envio")) or Decimal(0),
            impuestos_informados=_num(g("impuestos_informados")),
            precio_sin_iva=_num(g("precio_sin_iva")) or Decimal(0),
            total_impuestos=_num(g("total_impuestos")),
            imp_cheque=_num(g("imp_cheque")),
            iibb=_num(g("iibb")),
            precio_final=_num(g("precio_final")) or Decimal(0),
            dif_iva=_num(g("dif_iva")),
            cash=_num(g("cash")),
            utilidad_venta=_num(g("utilidad_venta")),
            utilidad_costo=_num(g("utilidad_costo")),
            neto=_num(g("neto")),
            costo_total=_num(g("costo_total")),
            rentabilidad=_num(g("rentabilidad")),
            pm=g("pm") or None,
            subcategoria=g("subcategoria") or None,
            rentabilidad_usd=_num(g("rentabilidad_usd")),
            facturacion_usd=_num(g("facturacion_usd")),
            responsable_de_ventas=g("responsable_de_ventas") or None,
            categoria=g("categoria") or None,
            subcategoria2=g("subcategoria2") or None,
            periodo_excel=g("periodo_excel") or None,
            semana=g("semana") or None,
            sku_negativo=g("sku_negativo") or None,
            tc=_num(g("tc")) or Decimal(0),
            vinculacion="OK",
            iva=None,
            facturacion_iva=None,
            stock=None,
            ventas_30_dias=None,
            dias_de_stock=None,
            precio_de_venta_roto=None,
            rentabilidad_real=None,
            pct_rentabilidad=None,
        ))
    return resultado


def importar(
    db: Session,
    sheet_id: str,
    todas_las_pestanas: list[str],
    fetch_fn,
    hasta_fecha_exclusive: date,
) -> ResultadoImportacion:
    """Importa todas las pestañas ECOM/TACTICA con datos hasta
    `hasta_fecha_exclusive` (sin incluir) -- así el período actual (que se
    guarda vía el motor nuevo, no acá) no se pisa con datos del Sheet.
    No escribe en la sesión: eso lo decide el caller (mismo patrón que
    `construir_filas_*` en persistencia.py)."""
    tabs_ecom, tabs_tactica = tabs_historicas(todas_las_pestanas)
    resultado = ResultadoImportacion()

    for tab in tabs_tactica:
        filas = fetch_fn(sheet_id, tab)
        parseadas = parsear_tactica(db, filas, tab)
        antes = len(parseadas)
        parseadas = [v for v in parseadas if v.fecha < hasta_fecha_exclusive]
        if antes != len(parseadas):
            resultado.filas_ignoradas[tab] = antes - len(parseadas)
        resultado.tactica.extend(parseadas)

    for tab in tabs_ecom:
        filas = fetch_fn(sheet_id, tab)
        parseadas = parsear_ecom(filas, tab)
        antes = len(parseadas)
        parseadas = [v for v in parseadas if (v.fecha_creacion_venta or date.min) < hasta_fecha_exclusive]
        if antes != len(parseadas):
            resultado.filas_ignoradas[tab] = antes - len(parseadas)
        resultado.ecom.extend(parseadas)

    return resultado


def _rango_de_periodo(periodo: str) -> tuple[date, date]:
    desde_str, hasta_str = periodo.split("_")
    return date.fromisoformat(desde_str), date.fromisoformat(hasta_str)


def guardar_historico(db: Session, resultado: ResultadoImportacion) -> None:
    """Persiste el resultado de `importar()` -- reemplaza el período
    completo por cada `periodo` distinto encontrado (mismo criterio que
    `guardar_cierre_tactica`/`guardar_cierre_ecom`: sin upsert, borra e
    inserta de nuevo). No hace commit -- eso lo decide quien tiene la
    sesión, igual que el resto de `persistencia.py`."""
    periodos_tactica: dict[str, list[VentaTactica]] = {}
    for venta in resultado.tactica:
        periodos_tactica.setdefault(venta.periodo, []).append(venta)

    periodos_ecom: dict[str, list[VentaEcom]] = {}
    for venta in resultado.ecom:
        periodos_ecom.setdefault(venta.periodo, []).append(venta)

    for periodo, ventas in periodos_tactica.items():
        db.query(VentaTactica).filter(VentaTactica.periodo == periodo).delete(synchronize_session=False)
        for venta in ventas:
            db.add(venta)
        desde, hasta = _rango_de_periodo(periodo)
        registrar_cierre(db, periodo, desde, hasta, tactica_guardado=True)

    for periodo, ventas in periodos_ecom.items():
        db.query(VentaEcom).filter(VentaEcom.periodo == periodo).delete(synchronize_session=False)
        for venta in ventas:
            db.add(venta)
        desde, hasta = _rango_de_periodo(periodo)
        registrar_cierre(db, periodo, desde, hasta, ecom_guardado=True, ecom_origen="sheet")
