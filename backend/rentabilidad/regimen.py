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
import re
from datetime import date

from sqlalchemy.orm import Session

from .models import PrefijoPerdidaDefinitiva, Regimen, RegimenComprobante

# §6.1 del funcional: la tabla que empareja la descripción textual del
# comprobante (lo que trae la columna "Tipo de Factura" del export de
# Táctica) con el código corto que espera `resolver_regimen` — ambos nombran
# la misma columna I, el código ya viene embebido como palabra suelta dentro
# del texto descriptivo. No es una regla nueva, es la tabla §6.1 usada para
# traducir formato, igual que `_tipo_factura()` en ingesta_tactica.py hace
# desde CAE en vez de desde texto. Vive acá (no en api.py) para que
# `importar_historico.py` pueda usarla sin import circular con la API.
_CODIGOS_COMPROBANTE = ("FEA", "FEB", "FEE", "FAE", "CEA", "CEB", "CEE", "CVE", "CVA", "CVB", "MLA")
_RE_COMPROBANTE = re.compile(r"\b(" + "|".join(_CODIGOS_COMPROBANTE) + r")\b")


def extraer_comprobante(texto_tipo_factura: str) -> str:
    m = _RE_COMPROBANTE.search((texto_tipo_factura or "").upper())
    return m.group(1) if m else (texto_tipo_factura or "").strip()


def periodo_de_rango(desde: date, hasta: date) -> str:
    """Etiqueta de período para un rango de fechas — reemplaza el nombre de
    hoja mensual ("Junio-Julio") por algo derivable y sin ambigüedad. Es
    metadata de partición, no una regla de negocio (§1.2 IMPLEMENTACION)."""
    return f"{desde.isoformat()}_{hasta.isoformat()}"


def resolver_regimen(db: Session, comprobante: str, nro_comprobante: str) -> Regimen:
    prefijo = (nro_comprobante or "").split("-")[0]
    if prefijo and db.get(PrefijoPerdidaDefinitiva, prefijo) is not None:
        return Regimen.PERDIDA_DEFINITIVA

    fila = db.get(RegimenComprobante, comprobante)
    if fila is None:
        return Regimen.NO_RECONOCIDO
    return fila.regimen
