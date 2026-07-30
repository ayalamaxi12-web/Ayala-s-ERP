"""Validador — RENTABILIDAD_FUNCIONAL.md §12 (16 controles) +
RENTABILIDAD_IMPLEMENTACION.md §5.

Ningún control corrige un dato de forma silenciosa (prohibición técnica #13)
— solo detecta y reporta. Opera sobre filas ya calculadas (regimen y
columnas del motor ya resueltos): "antes/después del cálculo" (§5 del diseño
técnico) es una distinción conceptual de EN QUÉ MOMENTO del pipeline se
invoca, no dos implementaciones distintas — los mismos controles sirven para
ambos, según qué campos de la fila ya estén poblados quien lo invoque.

GAP heredado de seed.py/regimen.py: V-2 ("nota de débito presente") no puede
distinguirse hoy de un comprobante genuinamente NO_RECONOCIDO porque el
funcional nunca dio el código real de nota de débito — este control queda
implementado pero inerte hasta tener ese dato (no inventado).

Comprobantes de nota de crédito para V-10: se infieren de los ÚNICOS códigos
que el funcional documenta como notas de crédito (§6.1: CEA, CEB, CEE, CVE,
CVA, CVB) — no es una regla nueva, es la lista ya dada, usada para detectar
signo invertido.
"""
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from .models import MotivoExclusion, Regimen, VentaEcom, VentaTactica

BLOQUEANTE = "BLOQUEANTE"
INFORMATIVO = "INFORMATIVO"

COMPROBANTES_NOTA_CREDITO = {"CEA", "CEB", "CEE", "CVE", "CVA", "CVB"}

# Regímenes que ya implican "línea no calculada" o "no aplica el motor
# completo" — varios controles no tienen sentido sobre estas filas.
_SIN_MOTOR_COMPLETO = (Regimen.EXCLUIDO, Regimen.NO_DETERMINADO, Regimen.NO_RECONOCIDO, Regimen.PERDIDA_DEFINITIVA)


@dataclass
class Incidencia:
    codigo: str  # "V-1".."V-16"
    severidad: str  # BLOQUEANTE | INFORMATIVO
    entidad: str  # "TACTICA" | "ECOM"
    referencia: str  # id de la línea/orden, para trazabilidad
    detalle: str


def excluir_linea(linea: VentaTactica | VentaEcom, motivo: MotivoExclusion) -> None:
    """Exclusión lógica (§10): nunca borrado físico. La fila se conserva,
    se muestra y no suma en los totales de agregación (Etapa 9)."""
    linea.excluido = True
    linea.motivo_exclusion = motivo


class ValidadorRentabilidad:
    def __init__(self, db: Session):
        self.db = db

    # ── TACTICA ──

    def validar_linea_tactica(self, linea: VentaTactica) -> list[Incidencia]:
        incidencias: list[Incidencia] = []
        ref = linea.id

        # V-1 — comprobante no reconocido / no determinado (MLA, P-01)
        if linea.regimen in (Regimen.NO_DETERMINADO, Regimen.NO_RECONOCIDO):
            incidencias.append(Incidencia("V-1", BLOQUEANTE, "TACTICA", ref,
                f"Comprobante '{linea.tipo_factura}' con régimen {linea.regimen}: la línea no se calcula."))

        # V-2 — nota de débito (ver gap de módulo)
        if linea.motivo_exclusion == MotivoExclusion.NOTA_DEBITO or linea.regimen == Regimen.EXCLUIDO:
            incidencias.append(Incidencia("V-2", INFORMATIVO, "TACTICA", ref,
                "Nota de débito detectada: excluida automáticamente."))

        if linea.regimen not in _SIN_MOTOR_COMPLETO:
            # V-3 — IVA no resuelto, solo relevante en Cuenta 1 (irrelevante en Cuenta 2, §6.2/T-4)
            if linea.regimen == Regimen.CUENTA_1 and linea.iva_producto is None:
                incidencias.append(Incidencia("V-3", BLOQUEANTE, "TACTICA", ref,
                    "Factor de IVA no resuelto en Cuenta 1 — no asumir 21% ni 0."))

            # V-5 — costo vigente no resuelto
            if linea.costo_lista is None:
                incidencias.append(Incidencia("V-5", BLOQUEANTE, "TACTICA", ref,
                    "Costo vigente inexistente o 0 en ambas columnas (S y R de Global)."))

            # V-8 — régimen mal aplicado
            if linea.regimen == Regimen.CUENTA_1 and linea.costo_financiero_2 not in (None, Decimal(0)):
                incidencias.append(Incidencia("V-8", BLOQUEANTE, "TACTICA", ref,
                    "Cuenta 1 con Z (costo financiero 2) distinto de 0."))
            if linea.regimen == Regimen.CUENTA_2 and any(
                v not in (None, Decimal(0)) for v in (linea.iva, linea.imp_cheque, linea.iibb, linea.costo_financiero_1)
            ):
                incidencias.append(Incidencia("V-8", BLOQUEANTE, "TACTICA", ref,
                    "Cuenta 2 con S/T/U/Y distintos de vacío/0."))

        # V-6 — TC ausente o <= 0
        if linea.tc is None or linea.tc <= 0:
            incidencias.append(Incidencia("V-6", BLOQUEANTE, "TACTICA", ref, "TC ausente o <= 0."))

        # V-7 — Precio de Venta vacío en línea no anulada
        if linea.regimen not in (Regimen.PERDIDA_DEFINITIVA, Regimen.EXCLUIDO, Regimen.NO_DETERMINADO, Regimen.NO_RECONOCIDO):
            if not linea.precio_venta:
                incidencias.append(Incidencia("V-7", INFORMATIVO, "TACTICA", ref,
                    "Precio de Venta vacío en línea no anulada — revisar (¿Posventa legítima?)."))

        # V-9 — pérdida definitiva sin aplicar
        if linea.regimen == Regimen.PERDIDA_DEFINITIVA and linea.margen_real != linea.precio_venta:
            incidencias.append(Incidencia("V-9", BLOQUEANTE, "TACTICA", ref,
                "Comprobante de pérdida definitiva con AA distinto de P."))

        # V-10 — nota de crédito con signo no invertido
        if linea.tipo_factura in COMPROBANTES_NOTA_CREDITO:
            if (linea.cantidad and linea.cantidad > 0) or (linea.precio_venta and linea.precio_venta > 0):
                incidencias.append(Incidencia("V-10", BLOQUEANTE, "TACTICA", ref,
                    "Nota de crédito con cantidad o precio positivo — signo invertido."))

        # V-13 — clasificación sin PM
        if not linea.pm or linea.pm == "SIN PM":
            incidencias.append(Incidencia("V-13", INFORMATIVO, "TACTICA", ref, "Línea sin PM resuelto."))

        return incidencias

    def detectar_duplicados_tactica(self, periodo: str) -> list[Incidencia]:
        """V-16 — comprobante + SKU repetido dentro del período."""
        filas = (
            self.db.query(VentaTactica.nro_factura, VentaTactica.codigo, func.count().label("n"))
            .filter(VentaTactica.periodo == periodo)
            .group_by(VentaTactica.nro_factura, VentaTactica.codigo)
            .having(func.count() > 1)
            .all()
        )
        return [
            Incidencia("V-16", INFORMATIVO, "TACTICA", f"{nro}/{codigo}", f"Duplicado: {n} filas.")
            for nro, codigo, n in filas
        ]

    # ── ECOM ──

    def validar_linea_ecom(self, linea: VentaEcom) -> list[Incidencia]:
        incidencias: list[Incidencia] = []
        ref = linea.numero_orden

        # V-4 — IVA no resuelto en ECOM: solo invalida AP, informativo
        if linea.iva is None:
            incidencias.append(Incidencia("V-4", INFORMATIVO, "ECOM", ref,
                "Factor de IVA no resuelto: AP inválido, Z/AA/AB se calculan igual."))

        # V-6 — TC ausente o <= 0
        if linea.tc is None or linea.tc <= 0:
            incidencias.append(Incidencia("V-6", BLOQUEANTE, "ECOM", ref, "TC ausente o <= 0."))

        # V-7 — Precio (Q) vacío
        if not linea.precio_sin_iva:
            incidencias.append(Incidencia("V-7", INFORMATIVO, "ECOM", ref,
                "Precio SIN IVA vacío — revisar (¿Posventa legítima?)."))

        # V-11 — Comisión Cobro con valor (nunca debe deducirse, §7.5)
        if linea.comision_cobro:
            incidencias.append(Incidencia("V-11", INFORMATIVO, "ECOM", ref,
                "Comisión Cobro <> 0: se ignora en el cálculo, se informa."))

        # V-12 — Retenciones informadas (no se deducen, observación O-03)
        if linea.impuestos_informados:
            incidencias.append(Incidencia("V-12", INFORMATIVO, "ECOM", ref,
                "Retenciones informadas por el origen — confirmar que no se deducen (O-03)."))

        # V-13 — clasificación sin PM
        if not linea.pm or linea.pm == "SIN PM":
            incidencias.append(Incidencia("V-13", INFORMATIVO, "ECOM", ref, "Orden sin PM resuelto."))

        # V-14 — vinculación distinta de OK
        if linea.vinculacion != "OK":
            incidencias.append(Incidencia("V-14", INFORMATIVO, "ECOM", ref,
                f"Vinculación '{linea.vinculacion}' distinta de OK."))

        return incidencias

    def detectar_duplicados_ecom(self, periodo: str) -> list[Incidencia]:
        """V-16 — número de orden repetido dentro del período."""
        filas = (
            self.db.query(VentaEcom.numero_orden, func.count().label("n"))
            .filter(VentaEcom.periodo == periodo)
            .group_by(VentaEcom.numero_orden)
            .having(func.count() > 1)
            .all()
        )
        return [Incidencia("V-16", INFORMATIVO, "ECOM", orden, f"Duplicado: {n} filas.") for orden, n in filas]

    # ── Cuadre de período ──

    def validar_cuadre_periodo(
        self, periodo: str, suma_aa_tactica_esperada: Decimal, suma_ab_ecom_esperada: Decimal
    ) -> list[Incidencia]:
        """V-15 — bloqueante. Toma los totales esperados como parámetro: hoy
        no existen (§13.3 del funcional está pendiente de la verificación
        V-02, §16) — no se inventan, se validan en cuanto Maxx los provea."""
        incidencias = []
        suma_aa = self.db.query(func.sum(VentaTactica.margen_real)).filter(
            VentaTactica.periodo == periodo, VentaTactica.excluido.is_(False)
        ).scalar() or Decimal(0)
        suma_ab = self.db.query(func.sum(VentaEcom.rentabilidad)).filter(
            VentaEcom.periodo == periodo, VentaEcom.excluido.is_(False)
        ).scalar() or Decimal(0)

        if abs(Decimal(suma_aa) - suma_aa_tactica_esperada) > Decimal("0.01"):
            incidencias.append(Incidencia("V-15", BLOQUEANTE, "TACTICA", periodo,
                f"SUM(AA) calculado {suma_aa} no coincide con el esperado {suma_aa_tactica_esperada}."))
        if abs(Decimal(suma_ab) - suma_ab_ecom_esperada) > Decimal("0.01"):
            incidencias.append(Incidencia("V-15", BLOQUEANTE, "ECOM", periodo,
                f"SUM(AB) calculado {suma_ab} no coincide con el esperado {suma_ab_ecom_esperada}."))
        return incidencias
