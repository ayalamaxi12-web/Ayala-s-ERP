"""Adaptadores de solo lectura (§2 RENTABILIDAD_IMPLEMENTACION.md).

Cada proveedor Sheets-based separa la lectura de red (gspread, vía
`sheet_id` + `fetch_fn`) de la lógica de cascada documentada, que es lo que
se testea sin red: los tests inyectan `fetch_fn` con filas de fixture. Si
`sheet_id` no está configurado, el proveedor igual existe (adjustment #7) y
solo falla — `ConfiguracionFaltante`, con mensaje claro— cuando efectivamente
se lo usa.

`CostoVigenteProvider`/`IvaProvider` son la excepción: leen SQL directo de
Táctica, no Sheets (ver docstring de cada clase — cambio de fuente
confirmado por Maxx 2026-08-14).

GAPS DOCUMENTALES (implementados con el mejor criterio disponible, marcados
para confirmar contra la hoja real — no son reglas inventadas, son
supuestos de "qué columna/hoja exacta" que el relevamiento no precisó):

- `StockProvider` busca por título ('stock', 'ventas 30 dias') en `Global`
  por el mismo motivo.
- `ResponsableProvider` implementa un lookup directo por empresa; las
  "búsquedas anidadas de respaldo" que menciona el funcional (§8.2) no están
  especificadas con el detalle suficiente para replicarlas — queda como
  comportamiento pendiente de confirmar, no inventado.
"""
import time
from decimal import Decimal
from typing import Callable, Sequence

from . import config, gsheets
from .config import ConfiguracionFaltante, requerido

FetchFn = Callable[[str, str], list[list[str]]]


def _letra_a_indice(letra: str) -> int:
    """'A' -> 0, 'S' -> 18, 'R' -> 17, etc. (columnas de una sola letra,
    suficiente para las referencias literales del funcional)."""
    return ord(letra.upper()) - ord("A")


class _AdaptadorBase:
    """Resuelve el sheet_id de forma perezosa: no falla al construirse, solo
    al leer (adjustment #7)."""

    def __init__(self, sheet_id: str | None, fetch_fn: FetchFn | None = None, env_var: str = ""):
        self._sheet_id = sheet_id
        self._fetch_fn = fetch_fn or gsheets.leer_valores
        self._env_var = env_var

    def _filas(self, tab: str) -> list[list[str]]:
        if not self._sheet_id:
            raise ConfiguracionFaltante(
                f"Falta configurar '{self._env_var}' para leer la pestaña '{tab}'."
            )
        return self._fetch_fn(self._sheet_id, tab)


ConsultarCatalogoTactica = Callable[[], list[dict]]

# Costo vigente + IVA por SKU, directo de la base de Táctica — reemplaza a
# `Global`/`Importacion Tactica` (Sheets). Cambio de fuente confirmado por
# Maxx (2026-08-14): esas hojas eran una bajada manual del propio sistema,
# usada solo mientras no había acceso directo a la base; con acceso SQL ya
# confirmado (2026-08-14, servidor 10.10.10.99/FG), se lee del sistema, no
# de su copia. Ver docstrings de `CostoVigenteProvider`/`IvaProvider`.
#
# - IVA: `productos.IDTasaIVAVentas` -> `tasasiva.RecID` da `Descripcion`
#   ("IVA Debito 21%"/"10.5%"/...) -- confirmado contra productos reales,
#   coincide exacto con los valores que ya esperaba `IvaProvider.FACTORES`.
# - Costo: `productosprecios.Costo` por `IDProducto` -- confirmado con un
#   producto real que el valor es IDÉNTICO en las 6 listas de precio
#   (NroLista 1-6), así que no importa cuál se traiga; se toma la de menor
#   NroLista vía `OUTER APPLY ... ORDER BY NroLista` para no depender de
#   que exista una lista en particular.
_QUERY_CATALOGO_COSTO_IVA = """
SELECT
    p.Codigo AS sku,
    costo_lista.Costo AS costo,
    ti.Descripcion AS iva_descripcion
FROM productos p
OUTER APPLY (
    SELECT TOP 1 pp.Costo
    FROM productosprecios pp
    WHERE pp.IDProducto = p.RecID
    ORDER BY pp.NroLista
) costo_lista
LEFT JOIN tasasiva ti ON ti.RecID = p.IDTasaIVAVentas
WHERE p.Codigo IS NOT NULL AND p.Codigo <> ''
"""


def _consultar_catalogo_tactica_real() -> list[dict]:
    """Import perezoso de pymssql — mismo principio que
    `ingesta_tactica._ejecutar_query_real()`: el resto del módulo no
    depende de este driver ni de conectividad real para correr sus tests.

    Reintenta ante errores de conexión transitorios -- confirmado en
    producción (2026-08-27) que el link a Táctica corta a veces a mitad de
    consulta (`DB-Lib error 20017: Unexpected EOF from the server`, sin
    reintento antes, mataba el job de Ofertas ML entero por un corte de
    red). 3 intentos con backoff corto (2s/4s); solo cubre errores de
    `pymssql` (conexión/protocolo) -- no reinterpreta ni oculta un error
    real de la query."""
    import pymssql

    ultimo_error: Exception | None = None
    for intento in range(3):
        try:
            conn = pymssql.connect(
                server=requerido("RENT_TACTICA_SQL_SERVER"),
                user=requerido("RENT_TACTICA_SQL_USER"),
                password=requerido("RENT_TACTICA_SQL_PASSWORD"),
                database=requerido("RENT_TACTICA_SQL_DATABASE"),
                login_timeout=20,
                as_dict=True,
            )
            try:
                cur = conn.cursor()
                cur.execute(_QUERY_CATALOGO_COSTO_IVA)
                return list(cur)
            finally:
                conn.close()
        except pymssql.Error as e:
            ultimo_error = e
            if intento < 2:
                time.sleep(2 ** (intento + 1))
                continue
    raise ultimo_error


class CostoVigenteProvider:
    """Costo vigente USD por SKU — RENTABILIDAD_FUNCIONAL.md §5.6, corregido
    2026-08-14. La cascada original (columna S de `Global`, con fallback a
    columna R si S es 0) ya no aplica: `productosprecios.Costo` es un único
    valor por producto en la base de Táctica, confirmado idéntico entre
    listas de precio — no hay dos fuentes entre las que elegir. El
    documento funcional se actualizó para reflejar esto (decisión de Maxx,
    2026-08-14).

    "El 0 se trata como sin costo, no como costo cero" (§5.6) se conserva
    tal cual: sigue siendo funcionalmente relevante, solo cambió de dónde
    sale el valor.

    Bug real corregido 2026-08-18: `productos.Codigo` es una columna de
    ancho fijo en la base de Táctica y viene con espacios finales de
    padding (confirmado con `TN1060COMP` — el valor real es
    `'TN1060COMP      '`, 16 bytes). El catálogo se armaba con esa clave
    sin limpiar, mientras que el `codigo` de cada línea (`ingesta_tactica.
    _fila_desde_row`) ya llega recortado — la comparación de diccionario
    nunca podía coincidir para ningún SKU con padding real, no de forma
    intermitente: se verificó contra 5 facturas reales de `TN1060COMP`
    (2026-07-31 a 2026-08-14), las 5 con `costo_lista=None`. Maxx notó el
    mismo patrón de espacios finales al bajar el Excel de Táctica a mano
    (SKU y empresa/responsable) y lo confirmó como la misma causa."""

    def __init__(self, consultar: ConsultarCatalogoTactica | None = None):
        self._consultar = consultar or _consultar_catalogo_tactica_real
        self._catalogo: dict[str, dict] | None = None

    def _obtener_catalogo(self) -> dict[str, dict]:
        if self._catalogo is None:
            self._catalogo = {fila["sku"].strip(): fila for fila in self._consultar()}
        return self._catalogo

    def obtener(self, sku: str) -> Decimal | None:
        return self.obtener_con_origen(sku)[0]

    def obtener_con_origen(self, sku: str) -> tuple[Decimal | None, str | None]:
        """Igual que `obtener`, pero además indica el origen — insumo de la
        auditoría de costo (Etapa 10, §4 RENTABILIDAD_IMPLEMENTACION.md).
        Antes distinguía columna "S"/"R" de Sheets; con una única fuente
        SQL, el origen es siempre "SQL" cuando hay valor."""
        fila = self._obtener_catalogo().get(sku)
        if fila is None or fila.get("costo") is None:
            return None, None
        costo = Decimal(str(fila["costo"]))
        if costo == 0:
            # "el 0 se trata como sin costo" (§5.6) — se mantiene igual
            return None, None
        return costo, "SQL"


class IvaProvider:
    """§5.4 — comparación exacta de cadena, sensible a mayúsculas, sin
    normalizar. Corregido 2026-08-14: lee `tasasiva.Descripcion` (vía
    `productos.IDTasaIVAVentas`) directo de la base de Táctica, no de la
    hoja `Importacion Tactica` — mismo cambio de fuente que
    `CostoVigenteProvider`, misma tabla de origen (`_QUERY_CATALOGO_COSTO_IVA`,
    ambos proveedores comparten forma de consulta aunque cada instancia
    cachea la suya)."""

    FACTORES = {"IVA Debito 21%": Decimal("1.21"), "IVA Debito 10.5%": Decimal("1.105")}

    def __init__(self, consultar: ConsultarCatalogoTactica | None = None):
        self._consultar = consultar or _consultar_catalogo_tactica_real
        self._catalogo: dict[str, dict] | None = None

    def _obtener_catalogo(self) -> dict[str, dict]:
        if self._catalogo is None:
            # Mismo bug de padding que `CostoVigenteProvider` (ver su
            # docstring, corregido 2026-08-18) — misma fuente, mismo fix.
            self._catalogo = {fila["sku"].strip(): fila for fila in self._consultar()}
        return self._catalogo

    def factor(self, sku: str) -> Decimal | None:
        fila = self._obtener_catalogo().get(sku)
        if fila is None:
            return None
        return self.FACTORES.get(fila.get("iva_descripcion"))  # comparación exacta — sin default normalizado


class ClasificacionProvider(_AdaptadorBase):
    """Cascada de 3 intentos, §8.1."""

    def __init__(self, sheet_id: str | None = None, fetch_fn: FetchFn | None = None):
        super().__init__(sheet_id or config.SHEET_CATEGORIAS_ID, fetch_fn, "RENT_SHEET_CATEGORIAS_ID")

    def _buscar(self, filas: list[list[str]], sku: str, col_inicio: int) -> tuple[str | None, str | None]:
        for fila in filas:
            if gsheets.valor(fila, col_inicio) == sku:
                pm = gsheets.valor(fila, col_inicio + 3) or None  # "col. 4" relativa
                subcat = gsheets.valor(fila, col_inicio + 4) or None  # "col. 5" relativa
                return pm, subcat
        return None, None

    def pm_y_subcategoria(self, sku: str) -> tuple[str | None, str | None]:
        if not sku:
            return "SIN PM", None

        filas = self._filas(config.TAB_CATEGORIAS)
        col_a = _letra_a_indice("A")
        pm, subcat = self._buscar(filas, sku, col_a)
        if pm is not None:
            return pm, subcat

        primer_sku = sku.split(",")[0].strip()
        pm, subcat = self._buscar(filas, primer_sku, col_a)
        if pm is not None:
            return pm, subcat

        col_u = _letra_a_indice("U")
        pm, subcat = self._buscar(filas, primer_sku, col_u)
        if pm is not None:
            return pm, subcat

        return None, None  # "todo falla → error / vacío" (§8.1, sin default textual documentado acá)


class ResponsableProvider(_AdaptadorBase):
    """Lookup directo por empresa. Las "búsquedas anidadas de respaldo" de
    §8.2 no están documentadas con precisión suficiente para replicarse —
    ver nota de módulo. Sin default: la ausencia es significativa (afecta AGIN)."""

    def __init__(self, sheet_id: str | None = None, fetch_fn: FetchFn | None = None):
        super().__init__(sheet_id or config.SHEET_BASE_GENERAL_ID, fetch_fn, "RENT_SHEET_BASE_GENERAL_ID")

    def obtener(self, empresa: str) -> str | None:
        filas = self._filas("BASE GENERAL")
        if not filas:
            return None
        hdr_idx = gsheets.encontrar_fila_headers(filas, ["empresa", "cliente", "responsable"])
        mapa = gsheets.mapa_columnas(filas[hdr_idx])
        idx_empresa = gsheets.indice_columna(mapa, ["empresa", "cliente"])
        idx_resp = gsheets.indice_columna(mapa, ["responsable"])
        for fila in filas[hdr_idx + 1:]:
            if gsheets.valor(fila, idx_empresa) == empresa:
                return gsheets.valor(fila, idx_resp) or None
        return None


class MargenObjetivoProvider:
    """§9 (L3/L4/L5) y §9/§8.6 (Rentabilidad Real). No hereda de
    `_AdaptadorBase`: combina varias hojas independientes."""

    _PMS_EN_ORDEN = ("veronica", "matias", "cristian")

    def __init__(
        self,
        sheet_ids: dict[str, str | None] | None = None,
        sheet_master_id: str | None = None,
        fetch_fn: FetchFn | None = None,
    ):
        self._sheet_ids = sheet_ids or {
            "veronica": config.SHEET_MARGEN_VERONICA_ID,
            "matias": config.SHEET_MARGEN_MATIAS_ID,
            "cristian": config.SHEET_MARGEN_CRISTIAN_ID,
        }
        self._sheet_master_id = sheet_master_id or config.SHEET_MASTER_COMPRAS_ML_ID
        self._fetch_fn = fetch_fn or gsheets.leer_valores

    def l3_l4_l5(self, sku: str) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
        for pm in self._PMS_EN_ORDEN:
            sheet_id = self._sheet_ids.get(pm)
            if not sheet_id:
                continue
            filas = self._fetch_fn(sheet_id, "Sheet1")
            if not filas:
                continue
            hdr_idx = gsheets.encontrar_fila_headers(
                filas, ["sku", "l3 usd sin iva", "l4 usd sin iva", "l5 usd sin iva"]
            )
            mapa = gsheets.mapa_columnas(filas[hdr_idx])
            idx_sku = gsheets.indice_columna(mapa, ["sku", "codigo"])
            idx_l3 = gsheets.indice_columna(mapa, ["l3 usd sin iva"])
            idx_l4 = gsheets.indice_columna(mapa, ["l4 usd sin iva"])
            idx_l5 = gsheets.indice_columna(mapa, ["l5 usd sin iva"])
            for fila in filas[hdr_idx + 1:]:
                if gsheets.valor(fila, idx_sku) == sku:
                    def _num(idx):
                        v = gsheets.valor(fila, idx)
                        return Decimal(v.replace(",", ".")) if v else None
                    return _num(idx_l3), _num(idx_l4), _num(idx_l5)
        return None, None, None

    def rentabilidad_real(self, sku: str) -> Decimal | str:
        if not self._sheet_master_id:
            raise ConfiguracionFaltante("Falta configurar 'RENT_SHEET_MASTER_COMPRAS_ML_ID'.")
        filas = self._fetch_fn(self._sheet_master_id, "Sheet1")
        if not filas:
            return "NO ENCUENTRO SKU"
        hdr_idx = gsheets.encontrar_fila_headers(filas, ["sku", "margen / ganancia actual"])
        mapa = gsheets.mapa_columnas(filas[hdr_idx])
        idx_sku = gsheets.indice_columna(mapa, ["sku", "codigo"])
        idx_margen = gsheets.indice_columna(mapa, ["margen / ganancia actual"])
        for fila in filas[hdr_idx + 1:]:
            if gsheets.valor(fila, idx_sku) == sku:
                v = gsheets.valor(fila, idx_margen)
                if not v:
                    return "NO ENCUENTRO SKU"
                try:
                    return Decimal(v.replace(",", ".").replace("%", ""))
                except Exception:
                    return v
        return "NO ENCUENTRO SKU"  # default textual (§8.6) — no invertir, no reemplazar por 0


class VinculacionProvider(_AdaptadorBase):
    """§8.4 — default `"OK"`. No invertir: la ausencia de match es el estado bueno."""

    def __init__(self, sheet_id: str | None = None, fetch_fn: FetchFn | None = None):
        super().__init__(sheet_id or config.SHEET_VINCULACION_ID, fetch_fn, "RENT_SHEET_VINCULACION_ID")

    def estado(self, nro_orden: str) -> str:
        filas = self._filas(config.TAB_VINCULACION)
        if not filas:
            return "OK"
        hdr_idx = gsheets.encontrar_fila_headers(filas, ["orden", "vinculacion", "estado"])
        mapa = gsheets.mapa_columnas(filas[hdr_idx])
        idx_orden = gsheets.indice_columna(mapa, ["orden", "numero orden", "número orden"])
        idx_estado = gsheets.indice_columna(mapa, ["vinculacion", "vinculación", "estado"])
        for fila in filas[hdr_idx + 1:]:
            if gsheets.valor(fila, idx_orden) == nro_orden:
                return gsheets.valor(fila, idx_estado) or "OK"
        return "OK"


class StockProvider(_AdaptadorBase):
    """§8.5 — lookups en `Global`. Nombres de columna asumidos, ver nota de módulo."""

    def __init__(self, sheet_id: str | None = None, fetch_fn: FetchFn | None = None):
        super().__init__(sheet_id or config.SHEET_GLOBAL_ID, fetch_fn, "RENT_SHEET_GLOBAL_ID")

    def _lookup(self, sku: str, titulos: Sequence[str]) -> Decimal | None:
        filas = self._filas(config.TAB_GLOBAL)
        if not filas:
            return None
        hdr_idx = gsheets.encontrar_fila_headers(filas, ["sku", *titulos])
        mapa = gsheets.mapa_columnas(filas[hdr_idx])
        idx_sku = gsheets.indice_columna(mapa, ["sku", "codigo"])
        idx_val = gsheets.indice_columna(mapa, titulos)
        for fila in filas[hdr_idx + 1:]:
            if gsheets.valor(fila, idx_sku) == sku:
                v = gsheets.valor(fila, idx_val)
                return Decimal(v.replace(",", ".")) if v else None
        return None

    def stock(self, sku: str) -> Decimal | None:
        return self._lookup(sku, ["stock"])

    def ventas_30d(self, sku: str) -> Decimal | None:
        return self._lookup(sku, ["ventas 30 dias", "ventas 30 días"])

    def dias_de_stock(self, sku: str) -> str:
        """§8.5 — AS = SI.ERROR(AQ / (AR/30); "Sin ventas"). Puede devolver un
        número (como texto) o el texto "Sin ventas" — nunca 0."""
        stock = self.stock(sku)
        ventas_30d = self.ventas_30d(sku)
        if stock is None or not ventas_30d:
            return "Sin ventas"
        try:
            return str(stock / (ventas_30d / Decimal(30)))
        except Exception:
            return "Sin ventas"
