"""Tablas de costos de ML editables desde el backend (fuente ÚNICA para el motor, Competidores, Ofertas ML y Análisis de Competencia).

Cuotas de ML: costo de financiación como % del precio de venta (el vendedor lo absorbe). Valores oficiales de ML confirmados por Maxx
(2026-10): 3 cuotas 8,9 % · 6 cuotas 13,4 % · 9 cuotas 17,8 % · 12 cuotas 21,6 % (más "reducida" 5 %). Viven en `pricing_cuotas`; cambiarlos
= agregar filas con una `vigente_desde` más nueva (el motor toma la más reciente <= la fecha), así queda el historial de cada cambio."""
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from .models import PricingCuotas
from .motor_precios import ParametrosMotor

PLANES_ML = ("reducida", "3", "6", "9", "12")
CANAL = "ML"
MAX_PCT = Decimal("50")


class CuotasInvalidas(ValueError):
    pass


def cuotas_ml(par: ParametrosMotor) -> list[dict]:
    """Planes de ML vigentes: [{plan, pct (fracción, 0.089), pct_texto (8.9)}], reducida primero y después por número de cuotas."""
    filas = [(plan, pct) for (canal, plan), pct in par.cuotas.items() if canal == CANAL]
    filas.sort(key=lambda x: (0, 0) if x[0] == "reducida" else (1, int(x[0]) if x[0].isdigit() else 999))
    return [{"plan": plan, "pct": pct, "pct_texto": (pct * 100).normalize()} for plan, pct in filas]


def validar_planes(planes_pct: dict) -> dict[str, Decimal]:
    """{"3": 8.9, ...} en % -> {"3": Decimal("0.089")}. Solo planes conocidos, 0 <= % <= 50; falla con un mensaje que dice qué está mal."""
    if not planes_pct:
        raise CuotasInvalidas("No viene ningún plan.")
    out = {}
    for plan, v in planes_pct.items():
        p = str(plan).strip().lower()
        if p not in PLANES_ML:
            raise CuotasInvalidas(f"Plan desconocido {plan!r}: los planes de ML son {', '.join(PLANES_ML)}.")
        try:
            pct = Decimal(str(v).replace(",", "."))
        except InvalidOperation:
            raise CuotasInvalidas(f"El porcentaje del plan {p} no es un número: {v!r}.")
        if pct < 0 or pct > MAX_PCT:
            raise CuotasInvalidas(f"El porcentaje del plan {p} ({pct} %) está fuera de 0–{MAX_PCT} %.")
        out[p] = pct / 100
    return out


def previsualizar(par: ParametrosMotor, planes_pct: dict) -> list[dict]:
    """Qué cambiaría: [{plan, actual_pct, nuevo_pct, cambia}] (en %), sin escribir nada."""
    nuevos = validar_planes(planes_pct)
    actuales = {x["plan"]: x["pct"] for x in cuotas_ml(par)}
    return [{"plan": p, "actual_pct": (actuales[p] * 100).normalize() if p in actuales else None, "nuevo_pct": (n * 100).normalize(),
             "cambia": actuales.get(p) != n} for p, n in nuevos.items()]


def guardar(db: Session, planes_pct: dict, vigente_desde: date, cargado_por: str) -> int:
    """Agrega una fila por plan que CAMBIA (los iguales no se tocan). -> cantidad de filas escritas."""
    par_actual = None
    from .motor_precios import cargar_parametros
    par_actual = cargar_parametros(db, vigente_desde, criterios=False)
    actuales = {x["plan"]: x["pct"] for x in cuotas_ml(par_actual)}
    n = 0
    for plan, pct in validar_planes(planes_pct).items():
        if actuales.get(plan) == pct:
            continue
        db.add(PricingCuotas(canal=CANAL, plan=plan, pct=pct, vigente_desde=vigente_desde, cargado_por=cargado_por[:128]))
        n += 1
    db.flush()
    return n
