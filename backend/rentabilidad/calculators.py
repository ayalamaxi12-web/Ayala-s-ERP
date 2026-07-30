"""Calculadores del motor de Rentabilidad — RENTABILIDAD_FUNCIONAL.md §6 (TACTICA)
y §7 (ECOM). Dos clases independientes, sin base compartida ni fórmulas en
común (prohibición técnica #7): TACTICA y ECOM solo se concilian por
agregación (funcional §2), nunca por esquema o código compartido.

Ninguna tasa vive hardcodeada acá — todas salen de `parametro_tasa`
(prohibición técnica #1). Todo en `Decimal` (prohibición #2).
"""
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from .adapters import CostoVigenteProvider, IvaProvider
from .models import ParametroTasa, Regimen
from .regimen import resolver_regimen


def _tasa(db: Session, nombre: str) -> Decimal:
    fila = db.get(ParametroTasa, nombre)
    if fila is None:
        raise ValueError(f"Falta sembrar el parámetro de tasa '{nombre}' (ver seed.py).")
    return fila.valor

LINEAS_SIN_CALCULO = (Regimen.EXCLUIDO, Regimen.NO_DETERMINADO, Regimen.NO_RECONOCIDO)


# ── TACTICA (§6) ──

@dataclass
class LineaTacticaInput:
    codigo: str  # C
    tipo_factura: str  # I
    nro_factura: str  # J
    cantidad: Decimal  # N
    precio_venta: Decimal  # P
    tc: Decimal  # V


@dataclass
class ResultadoTactica:
    regimen: Regimen
    costo_lista: Decimal | None = None  # L
    costo_total_dolares: Decimal | None = None  # O
    iva_producto: Decimal | None = None  # Q
    iva: Decimal | None = None  # S
    imp_cheque: Decimal | None = None  # T
    iibb: Decimal | None = None  # U
    costo_total_pesos: Decimal | None = None  # W
    costo_financiero_1: Decimal | None = None  # Y
    costo_financiero_2: Decimal | None = None  # Z
    margen_real: Decimal | None = None  # AA — resultado del motor
    margen_pct: Decimal | None = None  # AB
    precio_venta_iva: Decimal | None = None  # AG
    incidencia: str | None = None


class RentabilidadTacticaCalculator:
    def __init__(self, db: Session, costo_provider: CostoVigenteProvider, iva_provider: IvaProvider):
        self.db = db
        self.costo_provider = costo_provider
        self.iva_provider = iva_provider

    def calcular(self, linea: LineaTacticaInput) -> ResultadoTactica:
        # Paso 1 (§6.2): régimen se resuelve primero, antes de cualquier cálculo.
        regimen = resolver_regimen(self.db, linea.tipo_factura, linea.nro_factura)

        if regimen in LINEAS_SIN_CALCULO:
            return ResultadoTactica(regimen=regimen, incidencia="LINEA_NO_CALCULADA")

        P, N, V = linea.precio_venta, linea.cantidad, linea.tc

        # Paso 2: pérdida definitiva — todo anulado, AA = P, fin del cálculo.
        # No se resuelve L: "W anulado aunque O tenga valor" (funcional §6.3, caso T-8).
        if regimen == Regimen.PERDIDA_DEFINITIVA:
            return ResultadoTactica(regimen=regimen, margen_real=P)

        # Paso 3-4: costo vigente (§5.6) — "no asumir costo 0"
        L = self.costo_provider.obtener(linea.codigo)
        if L is None:
            return ResultadoTactica(regimen=regimen, incidencia="COSTO_NO_RESUELTO")  # V-5, bloqueante
        O = L * N

        # Paso 5: factor de IVA del SKU (§5.4)
        Q = self.iva_provider.factor(linea.codigo)

        imp_cheque_tasa = _tasa(self.db, "imp_cheque")
        iibb_tasa = _tasa(self.db, "iibb")
        cf1_tasa = _tasa(self.db, "cf1")
        cf2_tasa = _tasa(self.db, "cf2")

        # Paso 6, precedencias obligatorias: S antes de T y de Y · Y antes de Z
        if regimen == Regimen.CUENTA_1:
            if Q is None:
                # §5.4: factor vacío en TACTICA propaga error a S/T/Y/AG/AA —
                # "no asumir 21%, no asumir 0". Incidencia bloqueante (V-3).
                return ResultadoTactica(
                    regimen=regimen, costo_lista=L, costo_total_dolares=O,
                    costo_total_pesos=-((L * V) * N), incidencia="IVA_NO_RESUELTO",
                )
            S = (P * Q) - P
            AG = P + S
            T = -((P + S) * imp_cheque_tasa)
            U = -(P * iibb_tasa)
            Y = -((P + S) * cf1_tasa)
            Z = Decimal(0)
        else:  # CUENTA_2 — S, T, U vacíos; Y = 0 literal (§5.8)
            S = T = U = None
            AG = None
            Y = Decimal(0)
            Z = -(P * cf2_tasa)

        # Paso 7
        W = -((L * V) * N)
        # Paso 8 — vacíos cuentan como 0 en la suma (§5.8)
        AA = P + (T or Decimal(0)) + (U or Decimal(0)) + W + (Y or Decimal(0)) + Z
        # Paso 9
        AB = (AA / P) if P else None

        return ResultadoTactica(
            regimen=regimen, costo_lista=L, costo_total_dolares=O, iva_producto=Q,
            iva=S, imp_cheque=T, iibb=U, costo_total_pesos=W,
            costo_financiero_1=Y, costo_financiero_2=Z,
            margen_real=AA, margen_pct=AB, precio_venta_iva=AG,
        )


# ── ECOM (§7) ──
#
# Nota sobre §7.6 (Promociones): ese apartado describe el SKU `PROMOS-*` cayendo
# bajo "régimen de pérdida definitiva" con terminología de TACTICA (comprobante
# CVA, prefijo 00007) dentro de la sección del motor ECOM — pero §7.3 es
# explícito en que ECOM "no tiene régimen de cuentas ni comprobantes". Es una
# inconsistencia del relevamiento entre secciones, no una regla a replicar acá:
# el propio §7.6 concluye "Ninguna regla especial de promociones. Se replica
# exactamente el circuito actual" — por eso este calculador NO tiene ninguna
# rama especial para PROMOS-*, aplica la fórmula general a toda orden por
# igual. Señalado para confirmar con Maxx, no bloquea (adjustment #5).
#
# Casos especiales del canal (§7.4, Posventa/Canal vacío) tampoco tienen rama
# propia: son descripciones de lo que la fórmula general produce con esos
# datos (Posventa: M=O=0 en el origen), no reglas adicionales — igual que el
# reverso de notas de crédito en TACTICA (§6.3: "no existe ni debe existir
# lógica especial").
#
# Comisión de Cobro (N, §7.5): se ignora siempre en la fórmula, tenga o no
# valor. Detectar y reportar N≠0 como incidencia informativa es del validador
# (Etapa 8, control V-11), no de este calculador.

@dataclass
class LineaEcomInput:
    numero_orden: str  # A
    costo_sin_iva: Decimal  # G — costo vigente total de la orden, USD
    comision_venta: Decimal  # M
    costo_envio: Decimal  # O
    precio_sin_iva: Decimal  # Q — neto, dato del origen, nunca se recalcula (§7.2)
    precio_final: Decimal  # U — bruto, dato del origen
    tc: Decimal  # AM


@dataclass
class ResultadoEcom:
    imp_cheque: Decimal  # S = U * 1,2%
    iibb: Decimal  # T = Q * 5%
    neto: Decimal  # Z = Q - M - O - S - T
    costo_total: Decimal  # AA = G * AM
    rentabilidad: Decimal  # AB = Z - AA — resultado del motor
    rentabilidad_usd: Decimal  # AE = AB / AM
    facturacion_usd: Decimal  # AF = U / AM
    pct_rentabilidad: Decimal  # AV = 1 - (AA/Z), 0 ante error (§7.1 paso 7, literal)


class RentabilidadEcomCalculator:
    def __init__(self, db: Session):
        self.db = db

    def calcular(self, linea: LineaEcomInput) -> ResultadoEcom:
        imp_cheque_tasa = _tasa(self.db, "imp_cheque")
        iibb_tasa = _tasa(self.db, "iibb")

        Q, U, G = linea.precio_sin_iva, linea.precio_final, linea.costo_sin_iva
        M, O, AM = linea.comision_venta, linea.costo_envio, linea.tc

        # Paso 2-3
        S = U * imp_cheque_tasa
        T = Q * iibb_tasa
        # Paso 4
        Z = Q - M - O - S - T
        # Paso 5
        AA = G * AM
        # Paso 6 — resultado del motor
        AB = Z - AA
        # Paso 7
        AE = AB / AM
        AF = U / AM
        AV = (Decimal(1) - (AA / Z)) if Z else Decimal(0)  # "con 0 ante error", literal

        return ResultadoEcom(
            imp_cheque=S, iibb=T, neto=Z, costo_total=AA, rentabilidad=AB,
            rentabilidad_usd=AE, facturacion_usd=AF, pct_rentabilidad=AV,
        )


def resolver_ao_orden(iva_provider: IvaProvider, skus_vendidos: str) -> Decimal | None:
    """AO (§7.7) se resuelve por SKU igual que en TACTICA (§5.4). Una orden
    ECOM puede traer varios SKU separados por coma — se usa el primero, mismo
    criterio documentado para clasificación multi-SKU (§8.1 paso 3), no una
    regla nueva inventada para este caso."""
    primer_sku = skus_vendidos.split(",")[0].strip()
    return iva_provider.factor(primer_sku)


def calcular_facturacion_iva(precio_final: Decimal, ao: Decimal | None) -> Decimal | None:
    """AP = U * AO (§7.1 no la incluye entre los pasos del motor; es
    informativa, §7.7). Separada del resultado del motor porque no participa
    de Z/AA/AB — se calcula aparte para no ensuciar `ResultadoEcom`."""
    if ao is None:
        return None
    return precio_final * ao
