"""Modelo de datos del motor de Rentabilidad.

Fuente normativa: RENTABILIDAD_FUNCIONAL.md §6.4 (TACTICA), §7.7 (ECOM), §5 (reglas
transversales). Diseño técnico: RENTABILIDAD_IMPLEMENTACION.md §1.

No unificar `VentaTactica` y `VentaEcom`: son dos motores estructuralmente
distintos que solo se concilian por agregación (funcional §2). Cada campo lleva
en su comentario la columna de origen (letra del libro) y su clasificación:
DATO · CALCULADO · INFORMATIVO · ROTO (§1.1 del diseño técnico) — es metadata
de esquema, no un valor que se persista por fila.

Todo importe es `Numeric`, nunca `Float` (prohibición técnica #2).
"""
import enum
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Enum, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

MONEY = Numeric(18, 6)
FACTOR = Numeric(10, 6)


def _uuid() -> str:
    return str(uuid.uuid4())


# ── Enums de control transversal (§1.2 RENTABILIDAD_IMPLEMENTACION.md) ──

class Regimen(str, enum.Enum):
    CUENTA_1 = "CUENTA_1"
    CUENTA_2 = "CUENTA_2"
    PERDIDA_DEFINITIVA = "PERDIDA_DEFINITIVA"
    EXCLUIDO = "EXCLUIDO"
    NO_DETERMINADO = "NO_DETERMINADO"  # MLA, pendiente P-01
    NO_RECONOCIDO = "NO_RECONOCIDO"


class MotivoExclusion(str, enum.Enum):
    NOTA_DEBITO = "NOTA_DEBITO"
    FIXTURE = "FIXTURE"
    ENVIO = "ENVIO"
    SKU_AUXILIAR = "SKU_AUXILIAR"
    MANUAL = "MANUAL"


# ── Tablas de hechos ──

class VentaTactica(Base):
    """Una fila = comprobante + SKU (funcional §3). Fuente: hoja Facturación
    (`Borrador Diario Tactica` / `<periodo> TACTICA`).
    """

    __tablename__ = "venta_tactica"
    # Sin UniqueConstraint(nro_factura, codigo) a propósito: el control V-16
    # (§12) trata los duplicados como INFORMATIVO — se detectan y reportan
    # (Etapa 8, validador), no se bloquean a nivel de esquema.

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    # Campos de control transversal (§1.2)
    periodo: Mapped[str] = mapped_column(String(64), index=True)
    excluido: Mapped[bool] = mapped_column(Boolean, default=False)
    motivo_exclusion: Mapped[MotivoExclusion | None] = mapped_column(Enum(MotivoExclusion), nullable=True)
    regimen: Mapped[Regimen | None] = mapped_column(Enum(Regimen), nullable=True)

    # A · Fecha · DATO
    fecha: Mapped[date] = mapped_column(Date)
    # B · Empresa · DATO
    empresa: Mapped[str] = mapped_column(String(255))
    # C · Codigo (SKU) · DATO — clave de todos los lookups
    codigo: Mapped[str] = mapped_column(String(64), index=True)
    # D · Descripción · DATO
    descripcion: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # E · Fabricante · DATO
    fabricante: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # F · Tipo de Producto · DATO
    tipo_producto: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # G · Familia · DATO
    familia: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # H · Vendedor · DATO
    vendedor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # I · Tipo de Factura · DATO — determina el régimen (§6.1)
    tipo_factura: Mapped[str] = mapped_column(String(10))
    # J · Nº Factura · DATO — PREFIJO-NUMERO, el prefijo determina pérdida definitiva
    nro_factura: Mapped[str] = mapped_column(String(32))
    # K · Precio de Compra de Lista · INFORMATIVO
    precio_compra_lista: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # L · Costo de Lista · CALCULADO — costo vigente USD, cascada §5.6
    costo_lista: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # M · Precio de Venta de Lista · INFORMATIVO
    precio_venta_lista: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # N · Cantidad · DATO — negativa en notas de crédito
    cantidad: Mapped[Decimal] = mapped_column(MONEY)
    # O · Costo Total En Dolares · CALCULADO = L * N
    costo_total_dolares: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # P · Precio de Venta · DATO — neto sin IVA, base de todo el cálculo
    precio_venta: Mapped[Decimal] = mapped_column(MONEY)
    # Q · IVA PRODUCTO · CALCULADO — factor 1,21 / 1,105 / null (§5.4)
    iva_producto: Mapped[Decimal | None] = mapped_column(FACTOR, nullable=True)
    # R · Margen · INFORMATIVO — no se usa (observación O-01)
    margen_informado: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # S · IVA · CALCULADO = (P * Q) - P
    iva: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # T · imp ch · CALCULADO = ((P + S) * 1,2%) * -1
    imp_cheque: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # U · IIBB · CALCULADO = (P * 5%) * -1
    iibb: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # V · TC · DATO — obligatorio e inmutable a nivel de línea (§5.5)
    tc: Mapped[Decimal] = mapped_column(MONEY)
    # W · Costo Total Pesos · CALCULADO = ((L * V) * N) * -1
    costo_total_pesos: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # X · Margen · INFORMATIVO — incoherente, = P - W (observación O-02)
    margen_x: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # Y · COSTO FINANCIERO 1 · CALCULADO = ((P + S) * 3%) * -1
    costo_financiero_1: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # Z · COSTO FINANCIERO 2 · CALCULADO
    costo_financiero_2: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # AA · Margen real · CALCULADO — resultado del motor
    margen_real: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # AB · Margen % · CALCULADO = AA / P
    margen_pct: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # AC · SKU MARGEN NEGATIVO · CALCULADO — bandera de gestión (§8.3)
    sku_margen_negativo: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # AD · PM · CALCULADO — lookup (§8.1)
    pm: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # AE · Canal Tactica · DATO — constante "Canal Tactica"
    canal_tactica: Mapped[str] = mapped_column(String(32), default="Canal Tactica")
    # AF · Subcategoria · CALCULADO — lookup (§8.1)
    subcategoria: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # AG · Precio de Venta IVA · CALCULADO = P + S
    precio_venta_iva: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # AH · Responsable · CALCULADO — lookup por empresa (§8.2)
    responsable: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # AI/AJ/AK · Margen L3/L4/L5 · INFORMATIVO — objetivo por SKU (§9)
    margen_l3: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    margen_l4: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    margen_l5: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)


class VentaEcom(Base):
    """Una fila = una orden (funcional §7). `Sku's Vendidos` puede traer varios
    SKU separados por coma en un mismo registro — no se normaliza/divide acá,
    se persiste tal cual llega del origen.
    """

    __tablename__ = "venta_ecom"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    # Campos de control transversal (§1.2). ECOM no tiene régimen de cuentas
    # (funcional §7.3: "no hay régimen de cuentas ni notas de crédito").
    periodo: Mapped[str] = mapped_column(String(64), index=True)
    excluido: Mapped[bool] = mapped_column(Boolean, default=False)
    motivo_exclusion: Mapped[MotivoExclusion | None] = mapped_column(Enum(MotivoExclusion), nullable=True)

    # A · Número Orden · DATO — sin `unique`: V-16 (§12) es informativo, no
    # se bloquea a nivel de esquema (mismo criterio que venta_tactica).
    numero_orden: Mapped[str] = mapped_column(String(64), index=True)
    # B · Sku's Vendidos · DATO — SKU o lista separada por coma, sin normalizar
    skus_vendidos: Mapped[str] = mapped_column(String(1000))
    # C · FechaCreaciónVenta · DATO
    fecha_creacion_venta: Mapped[date | None] = mapped_column(Date, nullable=True)
    # D · EstadoVenta · DATO — Abierta/Cerrada, no se filtra (§10)
    estado_venta: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # E · FechaPago · DATO
    fecha_pago: Mapped[date | None] = mapped_column(Date, nullable=True)
    # F · EstadoPago · DATO — Cobrado/Cobro Parcial, no se filtra (§10)
    estado_pago: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # G · Costo Sin Iva · DATO — costo vigente TOTAL de la orden, en USD
    costo_sin_iva: Mapped[Decimal] = mapped_column(MONEY)
    # H · IVA A Favor · INFORMATIVO — pendiente P-02
    iva_a_favor: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # I · Canal De Venta · DATO
    canal_de_venta: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # J · Usuario Integración · DATO
    usuario_integracion: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # K · Medio De Cobro · DATO
    medio_de_cobro: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # L · Entrega-Envío · DATO
    entrega_envio: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # M · Comisión Venta · DATO — se deduce íntegra en Z, no se recalcula
    comision_venta: Mapped[Decimal] = mapped_column(MONEY)
    # N · Comisión Cobro · DATO — siempre 0, NO participa del cálculo (§7.5)
    comision_cobro: Mapped[Decimal] = mapped_column(MONEY, default=0)
    # O · Costo Envío · DATO — se deduce íntegro en Z
    costo_envio: Mapped[Decimal] = mapped_column(MONEY, default=0)
    # P · Impuestos (retenciones) · DATO — informado, NO deducido (observación O-03)
    impuestos_informados: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # Q · Precio SIN IVA · DATO — neto de la orden, base del cálculo. No se recalcula (§7.2)
    precio_sin_iva: Mapped[Decimal] = mapped_column(MONEY)
    # R · Total Impuestos · DATO — IVA contenido, = U - Q en el origen
    total_impuestos: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # S · imp ch · CALCULADO = U * 1,2% (base bruta)
    imp_cheque: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # T · IIBB · CALCULADO = Q * 5% (base neta)
    iibb: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # U · Precio Final · DATO — bruto cobrado
    precio_final: Mapped[Decimal] = mapped_column(MONEY)
    # V · Dif IVA · INFORMATIVO = R - H
    dif_iva: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # W · Cash · INFORMATIVO — pendiente P-02
    cash: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # X · Utilidad Venta · INFORMATIVO — pendiente P-02
    utilidad_venta: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # Y · Utilidad Costo · INFORMATIVO — pendiente P-02
    utilidad_costo: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # Z · Neto · CALCULADO = Q - M - O - S - T
    neto: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # AA · Costo Total · CALCULADO = G * AM
    costo_total: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # AB · Rentabilidad · CALCULADO — resultado del motor = Z - AA
    rentabilidad: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # AC · PM · CALCULADO — lookup (§8.1)
    pm: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # AD · Subcategoria · CALCULADO
    subcategoria: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # AE · Rentabilidad USD · CALCULADO = AB / AM
    rentabilidad_usd: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # AF · Facturacion USD · CALCULADO = U / AM
    facturacion_usd: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # AG · Responsable De Ventas · DATO — vacío en el período vigente
    responsable_de_ventas: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # AH · Categoria · CALCULADO
    categoria: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # AI · Subcategoria2 · CALCULADO
    subcategoria2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # AJ · Periodo (columna propia del libro, distinta del campo de control
    # transversal `periodo` de arriba) · DATO — etiqueta manual
    periodo_excel: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # AK · Semana · DATO — etiqueta manual
    semana: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # AL · Sku Negativo · CALCULADO — bandera de gestión (§8.3)
    sku_negativo: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # AM · TC · DATO — obligatorio e inmutable a nivel de línea (§5.5)
    tc: Mapped[Decimal] = mapped_column(MONEY)
    # AN · Vinculacion · CALCULADO — lookup por Nº de orden, default "OK" (§8.4)
    vinculacion: Mapped[str] = mapped_column(String(32), default="OK")
    # AO · IVA · CALCULADO — factor 1,21/1,105/null, solo se usa en AP
    iva: Mapped[Decimal | None] = mapped_column(FACTOR, nullable=True)
    # AP · Facturacion +IVA · CALCULADO = U * AO (informativo)
    facturacion_iva: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # AQ · Stock · CALCULADO — lookup en Global
    stock: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # AR · Ventas 30 Dias · CALCULADO — lookup en Global
    ventas_30_dias: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # AS · Dias de Stock · CALCULADO — número O el texto "Sin ventas" en la misma
    # columna (§8.5); se persiste como texto para no perder ese estado dual.
    dias_de_stock: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # AT · Precio De Venta · ROTO — la hoja `Worksheet` no existe, siempre 0 (O-04)
    precio_de_venta_roto: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # AU · Rentabilidad Real · INFORMATIVO — esperada por el PM, no interviene (§9)
    rentabilidad_real: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    # AV · % Rentabilidad · CALCULADO = 1 - (AA/Z), equivalente a AB/Z
    pct_rentabilidad: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)


# ── Tablas paramétricas (§1.3) — ninguna tasa/prefijo/régimen vive en código ──

class ParametroTasa(Base):
    """Tasas de §5.3. `motor` acota a qué motor aplica cada tasa."""

    __tablename__ = "parametro_tasa"

    nombre: Mapped[str] = mapped_column(String(64), primary_key=True)
    valor: Mapped[Decimal] = mapped_column(FACTOR)
    motor: Mapped[str] = mapped_column(String(16))  # TACTICA | ECOM | AMBOS
    descripcion: Mapped[str | None] = mapped_column(String(255), nullable=True)


class PrefijoPerdidaDefinitiva(Base):
    """Prefijos de Nº de comprobante que fuerzan PÉRDIDA DEFINITIVA (§6.1),
    con prioridad absoluta sobre el tipo de comprobante.
    """

    __tablename__ = "prefijo_perdida_definitiva"

    prefijo: Mapped[str] = mapped_column(String(16), primary_key=True)


class RegimenComprobante(Base):
    """Mapeo comprobante → régimen (§6.1). Fuente única de verdad — el
    calculador NUNCA hardcodea esta tabla (prohibición técnica #1).
    """

    __tablename__ = "regimen_comprobante"

    comprobante: Mapped[str] = mapped_column(String(10), primary_key=True)
    regimen: Mapped[Regimen] = mapped_column(Enum(Regimen))
    descripcion: Mapped[str | None] = mapped_column(String(255), nullable=True)


class SkuExcluido(Base):
    """Fixture, envíos y SKU auxiliares a excluir. Vacía por defecto —
    pendiente P-05 del funcional, se completa por el operador.
    """

    __tablename__ = "sku_excluido"

    sku: Mapped[str] = mapped_column(String(64), primary_key=True)
    motivo: Mapped[MotivoExclusion] = mapped_column(Enum(MotivoExclusion))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)


class SkuAuxiliar(Base):
    """Patrones de SKU promocional (ej. `PROMOS-*`) para trazabilidad — no
    altera el cálculo (funcional §7.6).
    """

    __tablename__ = "sku_auxiliar"

    patron: Mapped[str] = mapped_column(String(64), primary_key=True)
    descripcion: Mapped[str | None] = mapped_column(String(255), nullable=True)


class AuditoriaCosto(Base):
    """§4 RENTABILIDAD_IMPLEMENTACION.md — adicional, no interviene en el
    resultado. El costo vigente NO se persiste como snapshot en la línea de
    venta a los fines del cálculo (se resuelve en el momento, §5.6): esta
    tabla es la única forma de responder "por qué cambió la rentabilidad de
    un período si no se tocó nada" cuando el costo del SKU cambió.
    """

    __tablename__ = "auditoria_costo"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    linea_id: Mapped[str] = mapped_column(String(36), index=True)
    sku: Mapped[str] = mapped_column(String(64), index=True)
    costo_usd_usado: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    columna_origen: Mapped[str | None] = mapped_column(String(4), nullable=True)  # "S" o "R" (§5.6)
    leido_en: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    calculo_id: Mapped[str] = mapped_column(String(64), index=True)
