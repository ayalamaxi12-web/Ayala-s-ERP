"""Agregaciones — RENTABILIDAD_FUNCIONAL.md §11, RENTABILIDAD_IMPLEMENTACION.md §6.

Son consultas de rollup puras: no aplican reglas de negocio adicionales, no
recalculan ni corrigen nada (§11, "los reportes son agregaciones puras").
El % se calcula siempre sobre los totales agregados, nunca como promedio de
porcentajes de línea (§11, prohibición técnica implícita).

Cada fila resultado incluye `cantidad_lineas` para que el total sea
trazable a las líneas que lo componen (§6 técnico), y el desglose
incluido/excluido se controla con `incluir_excluidos` (§10: nunca se
excluye por borrado físico, se filtra en la consulta).

Bloque TACTICA (§11.2) y bloque ECOM (§11.1) son funciones separadas por el
mismo motivo que los calculadores no se unifican: no comparten fórmula ni
columnas (funcional §2). El bloque AGIN (§11.3) es un tercer bloque, propio
de reportes, no del motor.
"""
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from .models import ParametroTasa, VentaEcom, VentaTactica

TACTICA_DIMENSIONES = {
    "canal": VentaTactica.canal_tactica,
    "pm": VentaTactica.pm,
    "subcategoria": VentaTactica.subcategoria,
    "responsable": VentaTactica.responsable,
    "periodo": VentaTactica.periodo,
}

# ECOM también admite "semana" (AK) — Tactica no tiene esa columna en el
# diccionario de datos (§6.4), no se inventa una.
ECOM_DIMENSIONES = {
    "canal": VentaEcom.canal_de_venta,
    "pm": VentaEcom.pm,
    "subcategoria": VentaEcom.subcategoria,
    "responsable": VentaEcom.responsable_de_ventas,
    "periodo": VentaEcom.periodo,
    "semana": VentaEcom.semana,
}


@dataclass
class FilaAgregadaTactica:
    dimension_valor: str | None
    suma_precio_venta_iva: Decimal  # SUM(AG)
    suma_precio_venta: Decimal  # SUM(P)
    suma_costo_total_pesos: Decimal  # SUM(W) — negativo por convención (§5.1)
    suma_margen_real: Decimal  # SUM(AA)
    pct: Decimal | None  # SUM(AA) / SUM(P)
    cantidad_lineas: int


@dataclass
class FilaAgregadaEcom:
    dimension_valor: str | None
    suma_precio_final: Decimal  # SUM(U)
    suma_precio_sin_iva: Decimal  # SUM(Q)
    suma_costo_total: Decimal  # SUM(AA)
    suma_rentabilidad: Decimal  # SUM(AB)
    pct: Decimal | None  # SUM(AB) / SUM(Q)
    cantidad_lineas: int


def agregar_tactica(db: Session, periodo: str, dimension: str, incluir_excluidos: bool = False) -> list[FilaAgregadaTactica]:
    """§11.2 — bloque TACTICA, por la dimensión pedida."""
    col = TACTICA_DIMENSIONES[dimension]
    q = db.query(
        col,
        func.sum(VentaTactica.precio_venta_iva),
        func.sum(VentaTactica.precio_venta),
        func.sum(VentaTactica.costo_total_pesos),
        func.sum(VentaTactica.margen_real),
        func.count(),
    ).filter(VentaTactica.periodo == periodo)
    if not incluir_excluidos:
        q = q.filter(VentaTactica.excluido.is_(False))
    q = q.group_by(col)

    filas = []
    for valor, s_ag, s_p, s_w, s_aa, n in q.all():
        s_p = s_p or Decimal(0)
        pct = (s_aa / s_p) if s_aa is not None and s_p else None
        filas.append(FilaAgregadaTactica(valor, s_ag or Decimal(0), s_p, s_w or Decimal(0), s_aa or Decimal(0), pct, n))
    return filas


def agregar_ecom(db: Session, periodo: str, dimension: str, incluir_excluidos: bool = False) -> list[FilaAgregadaEcom]:
    """§11.1 — bloque ECOM, por la dimensión pedida."""
    col = ECOM_DIMENSIONES[dimension]
    q = db.query(
        col,
        func.sum(VentaEcom.precio_final),
        func.sum(VentaEcom.precio_sin_iva),
        func.sum(VentaEcom.costo_total),
        func.sum(VentaEcom.rentabilidad),
        func.count(),
    ).filter(VentaEcom.periodo == periodo)
    if not incluir_excluidos:
        q = q.filter(VentaEcom.excluido.is_(False))
    q = q.group_by(col)

    filas = []
    for valor, s_u, s_q, s_aa, s_ab, n in q.all():
        s_q = s_q or Decimal(0)
        pct = (s_ab / s_q) if s_ab is not None and s_q else None
        filas.append(FilaAgregadaEcom(valor, s_u or Decimal(0), s_q, s_aa or Decimal(0), s_ab or Decimal(0), pct, n))
    return filas


@dataclass
class FilaAgin:
    responsable: str
    suma_precio_venta: Decimal  # SUM(P) por responsable
    agin_1: Decimal
    agin_2: Decimal


def agregar_tactica_con_agin_por_responsable(db: Session, periodo: str) -> list[FilaAgin]:
    """§11.3 — bloque CON AGIN, por Responsable. Excluye a propósito las
    líneas sin responsable resuelto (misma exclusión que produce el
    descuadre documentado en O-06: NO se corrige, se reproduce)."""
    tasa_1 = db.get(ParametroTasa, "agin_1").valor
    tasa_2 = db.get(ParametroTasa, "agin_2").valor

    q = (
        db.query(VentaTactica.responsable, func.sum(VentaTactica.precio_venta))
        .filter(VentaTactica.periodo == periodo, VentaTactica.excluido.is_(False))
        .filter(VentaTactica.responsable.isnot(None))
        .group_by(VentaTactica.responsable)
    )
    return [
        FilaAgin(responsable, suma_p, suma_p * tasa_1, suma_p * tasa_2)
        for responsable, suma_p in q.all()
    ]
