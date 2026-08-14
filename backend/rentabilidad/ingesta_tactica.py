"""Adaptador de solo lectura sobre el SQL Server de Táctica — reemplaza la
exportación manual de Excel de "Facturación → Análisis de productos", hoy
la fuente de `venta_tactica`. Relevamiento completo de tablas/joins/regla de
régimen en `TACTICA_SQL_RELEVAMIENTO.md` (raíz del repo).

Igual que los adaptadores de `adapters.py` sobre Sheets: solo lectura, nunca
escribe en Táctica, y separa la lectura de red (`ejecutar_query`, inyectable
en tests) de la lógica de traducción a `LineaTacticaInput`, que es lo que se
testea sin red.

No decide exclusión de SKU (`SkuExcluido`) ni asigna `periodo`/persiste nada:
esa es responsabilidad de la etapa de ingesta/persistencia, no de este
adaptador — mismo alcance que los providers de `adapters.py`, que tampoco
persisten.

Regla de régimen (§5 de TACTICA_SQL_RELEVAMIENTO.md, oficial — Maxx,
2026-07-31, reemplaza cualquier inferencia estadística sobre
`talonarios.Tipo`): el régimen depende únicamente de si el comprobante es
electrónico o no — verificado con `facturas.CAE` (`0` = no autorizado por
AFIP = Cuenta 2; no-cero = Cuenta 1) — nunca de la letra fiscal A/B/E, que
Maxx confirma indistinguible en el cálculo. El prefijo de talonario
(pérdida definitiva, `00007`/`05007`) tiene prioridad absoluta y ya lo
resuelve `resolver_regimen` a partir de `nro_factura`, sin cambios acá.

**Bug real corregido 2026-08-14, encontrado al validar contra Táctica real
(no de una fixture — Maxx vio el margen absurdo en una orden puntual y lo
señaló):** `facturasitems.ImportePrecioVenta1` es un precio **unitario**,
no el total de la línea — confirmado sin excepciones sobre 20 líneas
reales del 2026-08-12 con cantidad>1: coincide exacto con
`ImporteUnitario1` en 19 de 20 (la única distinta tenía un descuento de
vendedor aplicado — Maxx: "los vendedores tienen que jugar con los
números", el precio final de venta puede diferir del de lista, pero sigue
siendo unitario). Verificado además contra la factura real
`00003-00127258` (SKU `HP664XLKCOMP-PRM`, cantidad 12): Táctica muestra
$223.804,80 como importe de esa línea, que es exactamente
`ImportePrecioVenta1 (18.650,40) × Cantidad (12)` — no el valor crudo sin
multiplicar. `_fila_desde_row` multiplica por `cantidad` antes de armar
`FilaTactica.precio_venta`, igual criterio que ya usa el costo (`O = L *
N`, L unitario en USD, N=cantidad) — y de paso resuelve el signo en notas
de crédito de la misma forma: `ImportePrecioVenta1` es una magnitud
positiva, `cantidad` (negativa en NC) es quien determina el signo del
total, sin necesidad de un caso especial.
"""
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Callable

from . import config
from .calculators import LineaTacticaInput

# Une factura + talonario (prefijo de Nº Factura y régimen) + línea + cliente
# + vendedor + cotización de la línea (TC inmutable, tomado al momento de la
# carga — §5.5 del funcional). Ver TACTICA_SQL_RELEVAMIENTO.md §2 y §3 para
# la validación de cada join contra datos reales.
_QUERY = """
    SELECT
        f.FechaEmision, fis.RazonSocial AS Empresa,
        fi.Codigo, fi.Descripcion, fi.Fabricante, fi.TipoProducto,
        u.Usuario AS Vendedor,
        t.NroSucursal, f.Numero, f.CAE,
        fi.Cantidad, fi.ImportePrecioVenta1 AS PrecioVenta,
        mc.CotMoneda2 AS TC
    FROM facturas f
    JOIN talonarios t              ON t.RecID = f.IDTalonario
    JOIN facturasitems fi          ON fi.IDFactura = f.RecID
    LEFT JOIN fiscal fis           ON fis.RecID = f.IDFiscal
    LEFT JOIN usuarios u           ON u.RecID = fi.IDUsuarioVendedor
    LEFT JOIN monedacotizaciones mc ON mc.RecID = fi.IDCotizacionMoneda
    WHERE f.FechaEmision BETWEEN %(desde)s AND %(hasta)s
    ORDER BY f.FechaEmision, f.Numero
"""


@dataclass
class FilaTactica:
    """Una línea de `facturasitems` ya traducida — columnas DATO de
    `VentaTactica` (§1.1 RENTABILIDAD_IMPLEMENTACION.md) más lo necesario
    para alimentar el calculador."""

    fecha: date
    empresa: str | None
    codigo: str
    descripcion: str | None
    fabricante: str | None
    tipo_producto: str | None
    vendedor: str | None
    nro_factura: str
    tipo_factura: str
    cantidad: Decimal
    precio_venta: Decimal
    tc: Decimal

    def a_linea_input(self) -> LineaTacticaInput:
        return LineaTacticaInput(
            codigo=self.codigo,
            tipo_factura=self.tipo_factura,
            nro_factura=self.nro_factura,
            cantidad=self.cantidad,
            precio_venta=self.precio_venta,
            tc=self.tc,
        )


def _nro_factura(nro_sucursal: int, numero: int) -> str:
    """Prefijo-número, ej. `00003-00127071` — validado contra los prefijos
    de pérdida definitiva ya sembrados (`00007`/`05007`), TACTICA_SQL_RELEVAMIENTO.md §4."""
    return f"{int(nro_sucursal):05d}-{int(numero):08d}"


def _tipo_factura(cae, cantidad: Decimal) -> str:
    """Cuenta 1 vs Cuenta 2 por `CAE` (ver docstring del módulo). El signo de
    `Cantidad` distingue Factura (>=0) de Nota de Crédito (<0) únicamente
    para el string de la columna I (paridad visual con el Excel) — no
    cambia el régimen, idéntico dentro de cada cuenta. Los 4 strings usados
    ya están sembrados en `regimen_comprobante` (seed.py): no hace falta
    agregar filas nuevas."""
    electronica = bool(cae)
    if cantidad >= 0:
        return "FEA" if electronica else "FAE"
    return "CEA" if electronica else "CVE"


def _fila_desde_row(row: dict) -> FilaTactica:
    cantidad = Decimal(str(row["Cantidad"]))
    tc = row["TC"]
    if tc is None:
        # §5.5 del funcional: TC obligatorio e inmutable. Sin cotización
        # vinculada a la línea no hay valor que inventar (prohibición #3,
        # extendida por analogía: no asumir un TC por defecto).
        raise ValueError(
            f"Línea sin cotización de moneda (IDCotizacionMoneda) — "
            f"factura {_nro_factura(row['NroSucursal'], row['Numero'])}, SKU {row['Codigo']!r}."
        )
    fecha = row["FechaEmision"]
    return FilaTactica(
        fecha=fecha.date() if isinstance(fecha, datetime) else fecha,
        empresa=row["Empresa"],
        codigo=(row["Codigo"] or "").strip(),
        descripcion=row["Descripcion"],
        fabricante=row["Fabricante"],
        tipo_producto=row["TipoProducto"],
        vendedor=row["Vendedor"],
        nro_factura=_nro_factura(row["NroSucursal"], row["Numero"]),
        tipo_factura=_tipo_factura(row["CAE"], cantidad),
        cantidad=cantidad,
        # ImportePrecioVenta1 es un precio unitario -- el total real de la
        # línea (lo que Táctica muestra facturado) es unitario × cantidad,
        # igual criterio que el costo (ver docstring del módulo).
        precio_venta=Decimal(str(row["PrecioVenta"])) * cantidad,
        tc=Decimal(str(tc)),
    )


EjecutarQuery = Callable[[date, date], list[dict]]


def _ejecutar_query_real(desde: date, hasta: date) -> list[dict]:
    """Import perezoso de pymssql — igual que `gsheets.get_client()` con
    gspread, para que el resto de `rentabilidad/` no dependa de este driver
    ni de conectividad real para correr sus tests."""
    import pymssql

    conn = pymssql.connect(
        server=config.requerido("RENT_TACTICA_SQL_SERVER"),
        user=config.requerido("RENT_TACTICA_SQL_USER"),
        password=config.requerido("RENT_TACTICA_SQL_PASSWORD"),
        database=config.requerido("RENT_TACTICA_SQL_DATABASE"),
        login_timeout=20,
        as_dict=True,
    )
    try:
        cur = conn.cursor()
        # `hasta` incluye el día completo — el reporte de Táctica es
        # inclusivo en ambas puntas del rango de fechas elegido.
        cur.execute(_QUERY, {"desde": desde, "hasta": datetime.combine(hasta, time.max)})
        return list(cur)
    finally:
        conn.close()


class TacticaSqlAdapter:
    """Solo lectura. Dado un rango de fechas (el mismo que hoy se elige en
    "Facturación → Análisis de productos"), devuelve una `FilaTactica` por
    línea de comprobante."""

    def __init__(self, ejecutar_query: EjecutarQuery | None = None):
        self._ejecutar_query = ejecutar_query or _ejecutar_query_real

    def lineas(self, desde: date, hasta: date) -> list[FilaTactica]:
        return [_fila_desde_row(row) for row in self._ejecutar_query(desde, hasta)]
