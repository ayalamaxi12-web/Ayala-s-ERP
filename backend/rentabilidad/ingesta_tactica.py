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

**Bug real corregido 2026-08-14 (primer intento, INCOMPLETO — ver
corrección siguiente):** se creyó que `facturasitems.ImportePrecioVenta1`
era el precio unitario correcto y que multiplicarlo por `cantidad` daba el
total de línea, validado contra la factura `00003-00127258` (SKU
`HP664XLKCOMP-PRM`, cantidad 12, $223.804,80). Ese caso coincidía por
casualidad: ahí `ImportePrecioVenta1 == ImporteUnitario1`.

**Corrección 2026-08-14 (segunda vuelta, la vigente):** Maxx detectó otra
factura real, `00003-00127272` (cliente Polgraf SH, SKU
`WFSLV-15%-152X30`, cantidad 8), donde el importe correcto confirmado es
$1.336.800,00 — y ahí `ImportePrecioVenta1 (177.156,0) × cantidad` da
$1.417.248, **mal**. Consultando la factura completa:
`ImporteUnitario1=167.100,0`, `ImportePrecio1=1.336.800,0` — coincide con
`ImporteUnitario1 × cantidad`, no con `ImportePrecioVenta1`. Se verificó
además sobre una muestra de 100 líneas reales con
`ImportePrecioVenta1 <> ImporteUnitario1`: en el 100% de los casos
`ImportePrecio1 == ImporteUnitario1 × Cantidad`, nunca coincide con
`ImportePrecioVenta1 × Cantidad`. `ImportePrecioVenta1` es otro campo
(parece un precio de referencia/sugerido — no el efectivamente facturado)
y no se usa acá. `_fila_desde_row` ahora toma `ImportePrecio1`
directamente (ya viene totalizado por línea desde Táctica, no hace falta
recalcularlo multiplicando).

**Corrección 2026-08-14 (tercera vuelta, Nota de Crédito/Débito —
confirmada por Maxx contra 5 facturas reales de distintos períodos/letras/
sucursales: CVE 05001-19036035, CEA 00003-00009815, CEB 00003-00001128,
CEE 00004-00000069, CVA 00007-00000001):** `Cantidad`/`ImportePrecio1`
vienen SIEMPRE en positivo en `facturasitems` — Táctica no usa el signo
para marcar Nota de Crédito. Lo marca `facturas.Tipo`, el mismo campo que
alimenta el filtro "Tipo de Factura" del buscador de Táctica (desplegable
con 3 opciones en este orden: Factura, Nota de Crédito, Nota de Débito —
confirmado por Maxx mirando la pantalla real): `Tipo=0` Factura, `Tipo=1`
Nota de Crédito, `Tipo=2` Nota de Débito. Las 5 facturas reales que Maxx
confirmó como Nota de Crédito tienen `Tipo=1` sin excepción. Regla de
negocio de Maxx: **Nota de Débito se excluye por completo, no entra en el
cálculo** — filtrada en el propio `WHERE` de `_QUERY`. **Nota de Crédito sí
participa**, pero como revierte una venta, `_fila_desde_row` le invierte el
signo a `cantidad` (y por lo tanto a `precio_venta`, que ya viene positivo
desde `ImportePrecio1`) — mismo criterio que ya asumían `_tipo_factura`/los
tests desde el principio (cantidad negativa = NC), solo que ahora el signo
sale de `facturas.Tipo`, no de una columna que nunca es negativa. El costo
también queda invertido río abajo, porque el calculador multiplica el
costo unitario por `cantidad` (ya negativa).
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
_TIPO_FACTURA = 0
_TIPO_NOTA_CREDITO = 1
_TIPO_NOTA_DEBITO = 2

_QUERY = """
    SELECT
        f.FechaEmision, fis.RazonSocial AS Empresa,
        fi.Codigo, fi.Descripcion, fi.Fabricante, fi.TipoProducto,
        u.Usuario AS Vendedor,
        t.NroSucursal, f.Numero, f.CAE, f.Tipo AS TipoComprobante,
        fi.Cantidad, fi.ImportePrecio1 AS PrecioVenta,
        mc.CotMoneda2 AS TC
    FROM facturas f
    JOIN talonarios t              ON t.RecID = f.IDTalonario
    JOIN facturasitems fi          ON fi.IDFactura = f.RecID
    LEFT JOIN fiscal fis           ON fis.RecID = f.IDFiscal
    LEFT JOIN usuarios u           ON u.RecID = fi.IDUsuarioVendedor
    LEFT JOIN monedacotizaciones mc ON mc.RecID = fi.IDCotizacionMoneda
    WHERE f.FechaEmision BETWEEN %(desde)s AND %(hasta)s
      AND f.Tipo <> {nota_debito}
    ORDER BY f.FechaEmision, f.Numero
""".format(nota_debito=_TIPO_NOTA_DEBITO)


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
    # Cantidad/PrecioVenta vienen siempre en positivo desde Táctica -- la
    # Nota de Crédito (facturas.Tipo=1, ver docstring del módulo) revierte
    # la venta, así que se le invierte el signo acá, antes de armar la fila.
    es_nota_de_credito = row["TipoComprobante"] == _TIPO_NOTA_CREDITO
    signo = -1 if es_nota_de_credito else 1
    cantidad = Decimal(str(row["Cantidad"])) * signo
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
        # `fis.RazonSocial` viene con padding de la misma forma que
        # `productos.Codigo` (ver `CostoVigenteProvider`, corregido
        # 2026-08-18) -- sin recortar, rompe el match contra
        # `ResponsableProvider` (comparación exacta contra la hoja "BASE
        # GENERAL", que sí llega recortada vía `gsheets.valor`).
        empresa=(row["Empresa"] or "").strip(),
        codigo=(row["Codigo"] or "").strip(),
        descripcion=row["Descripcion"],
        fabricante=row["Fabricante"],
        tipo_producto=row["TipoProducto"],
        vendedor=row["Vendedor"],
        nro_factura=_nro_factura(row["NroSucursal"], row["Numero"]),
        tipo_factura=_tipo_factura(row["CAE"], cantidad),
        cantidad=cantidad,
        # ImportePrecio1 ya es el total facturado de la línea (Táctica lo
        # calcula como ImporteUnitario1 × Cantidad) -- no ImportePrecioVenta1,
        # que es otro campo y no coincide con lo facturado (ver docstring).
        precio_venta=Decimal(str(row["PrecioVenta"])) * signo,
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
