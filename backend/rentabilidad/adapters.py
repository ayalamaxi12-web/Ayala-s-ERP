"""Adaptadores de solo lectura (§2 RENTABILIDAD_IMPLEMENTACION.md).

Cada proveedor separa la lectura de red (gspread, vía `sheet_id` + `fetch_fn`)
de la lógica de cascada documentada, que es lo que se testea sin red: los
tests inyectan `fetch_fn` con filas de fixture. Si `sheet_id` no está
configurado, el proveedor igual existe (adjustment #7) y solo falla —
`ConfiguracionFaltante`, con mensaje claro— cuando efectivamente se lo usa.

GAPS DOCUMENTALES (implementados con el mejor criterio disponible, marcados
para confirmar contra la hoja real — no son reglas inventadas, son
supuestos de "qué columna/hoja exacta" que el relevamiento no precisó):

- `CostoVigenteProvider` asume que el SKU vive en la columna A de `Global`
  (el funcional da las columnas S/R por letra pero no dice dónde está la
  clave de búsqueda).
- `IvaProvider` busca por título de columna ('sku'/'codigo' y 'iva') en
  `Importacion Tactica`, ya que el funcional no da los títulos exactos.
- `StockProvider` busca por título ('stock', 'ventas 30 dias') en `Global`
  por el mismo motivo.
- `ResponsableProvider` implementa un lookup directo por empresa; las
  "búsquedas anidadas de respaldo" que menciona el funcional (§8.2) no están
  especificadas con el detalle suficiente para replicarlas — queda como
  comportamiento pendiente de confirmar, no inventado.
"""
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


class CostoVigenteProvider(_AdaptadorBase):
    """Cascada exacta de RENTABILIDAD_FUNCIONAL.md §5.6."""

    def __init__(self, sheet_id: str | None = None, fetch_fn: FetchFn | None = None):
        super().__init__(sheet_id or config.SHEET_GLOBAL_ID, fetch_fn, "RENT_SHEET_GLOBAL_ID")

    def obtener(self, sku: str) -> Decimal | None:
        return self.obtener_con_origen(sku)[0]

    def obtener_con_origen(self, sku: str) -> tuple[Decimal | None, str | None]:
        """Igual que `obtener`, pero además indica qué columna del libro
        ("S" o "R") aportó el valor — insumo de la auditoría de costo
        (Etapa 10, §4 RENTABILIDAD_IMPLEMENTACION.md)."""
        filas = self._filas(config.TAB_GLOBAL)
        idx_s, idx_r = _letra_a_indice("S"), _letra_a_indice("R")
        fila = next((f for f in filas if gsheets.valor(f, 0) == sku), None)
        if fila is None:
            # "si la búsqueda falla... usar Global columna R" — pero sin fila
            # no hay valor de R para ese SKU: no hay nada que devolver.
            return None, None
        valor_s = gsheets.valor(fila, idx_s)
        if valor_s and Decimal(valor_s.replace(",", ".")) != 0:
            return Decimal(valor_s.replace(",", ".")), "S"
        # valor_s vacío o 0 ("0 se trata como sin costo") → columna R
        valor_r = gsheets.valor(fila, idx_r)
        if valor_r:
            try:
                return Decimal(valor_r.replace(",", ".")), "R"
            except Exception:
                return None, None
        return None, None


class IvaProvider(_AdaptadorBase):
    """§5.4 — comparación exacta de cadena, sensible a mayúsculas, sin normalizar."""

    FACTORES = {"IVA Debito 21%": Decimal("1.21"), "IVA Debito 10.5%": Decimal("1.105")}

    def __init__(self, sheet_id: str | None = None, fetch_fn: FetchFn | None = None):
        super().__init__(sheet_id or config.SHEET_GLOBAL_ID, fetch_fn, "RENT_SHEET_GLOBAL_ID")

    def factor(self, sku: str) -> Decimal | None:
        filas = self._filas(config.TAB_IMPORTACION_TACTICA)
        if not filas:
            return None
        hdr_idx = gsheets.encontrar_fila_headers(filas, ["sku", "codigo", "iva"])
        mapa = gsheets.mapa_columnas(filas[hdr_idx])
        idx_sku = gsheets.indice_columna(mapa, ["sku", "codigo"])
        idx_iva = gsheets.indice_columna(mapa, ["iva"])
        for fila in filas[hdr_idx + 1:]:
            if gsheets.valor(fila, idx_sku) == sku:
                texto = gsheets.valor(fila, idx_iva)
                return self.FACTORES.get(texto)  # comparación exacta — sin .get con default normalizado
        return None


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
