"""Resolución de régimen — RENTABILIDAD_FUNCIONAL.md §6.1.

Se resuelve antes de cualquier cálculo (§6.2 paso 1). El prefijo del Nº de
comprobante tiene PRIORIDAD ABSOLUTA sobre el tipo de comprobante — se
chequea primero, siempre.

Ningún prefijo ni comprobante se hardcodea acá (prohibición técnica #1): todo
sale de `prefijo_perdida_definitiva` y `regimen_comprobante` (ver seed.py).

GAP CONOCIDO (heredado de seed.py — no inventado): "nota de débito → EXCLUIDO"
(§6.1) no tiene código de comprobante documentado, por lo que ningún
comprobante real de nota de débito está seedeado con régimen EXCLUIDO. Hoy
cualquier código no seedeado cae en NO_RECONOCIDO, que tiene el mismo efecto
práctico ("la línea no se calcula"), pero el control V-2 del validador
(§12, Etapa 8) que debe reportar específicamente "nota de débito presente"
no podrá distinguir ese caso hasta tener el código real.
"""
from sqlalchemy.orm import Session

from .models import PrefijoPerdidaDefinitiva, Regimen, RegimenComprobante


def resolver_regimen(db: Session, comprobante: str, nro_comprobante: str) -> Regimen:
    prefijo = (nro_comprobante or "").split("-")[0]
    if prefijo and db.get(PrefijoPerdidaDefinitiva, prefijo) is not None:
        return Regimen.PERDIDA_DEFINITIVA

    fila = db.get(RegimenComprobante, comprobante)
    if fila is None:
        return Regimen.NO_RECONOCIDO
    return fila.regimen
