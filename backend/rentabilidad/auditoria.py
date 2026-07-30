"""Auditoría de costo — §4 RENTABILIDAD_IMPLEMENTACION.md.

Separada de los calculadores a propósito: "esta auditoría es adicional y no
interviene en el resultado" — construirla es responsabilidad de quien
orquesta el cálculo (fuera de alcance de esta etapa: no hay endpoints/
frontend todavía), no del calculador ni del validador.
"""
from datetime import UTC, datetime

from .adapters import CostoVigenteProvider
from .models import AuditoriaCosto


def construir_auditoria_costo(
    costo_provider: CostoVigenteProvider, linea_id: str, sku: str, calculo_id: str
) -> AuditoriaCosto:
    """Resuelve el costo vigente (misma cascada que usa el calculador,
    §5.6) y devuelve el registro de auditoría listo para persistir — no lo
    persiste acá, para no acoplar esta función a una sesión de DB.

    `leido_en` se fija acá, al momento real de la lectura — no se deja
    librado al default de inserción del ORM, que solo se aplicaría recién
    al hacer flush/commit (podría ser bastante más tarde que la lectura real).
    """
    costo, columna = costo_provider.obtener_con_origen(sku)
    return AuditoriaCosto(
        linea_id=linea_id,
        sku=sku,
        costo_usd_usado=costo,
        columna_origen=columna,
        calculo_id=calculo_id,
        leido_en=datetime.now(UTC),
    )
