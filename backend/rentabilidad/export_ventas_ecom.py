"""Exportación de las ventas Ecom guardadas, orden por orden, con las
columnas del reporte de facturación (planilla ECOM, A → AV) — para volcarlas
a un Google Sheet de historial vía n8n (pedido de Maxx, 2026-10-03).

**Solo lectura**: lee lo que la corrida diaria ya guardó en `venta_ecom`; no
recalcula ni consulta nada externo. Cada fila es un objeto cuyas claves son
EXACTAMENTE los títulos de columna del reporte, en el mismo orden, para que
n8n los mapee directo a las columnas del Sheet.

Columnas que la corrida no guarda (la API de Ecom no las trae o son
etiquetas manuales de la planilla) salen vacías — ver `COLUMNAS_SIN_DATO`.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from .models import ParametroTasa, VentaEcom

# (título de la columna en el reporte, campo de venta_ecom | función)
_TOTAL_IMPUESTOS = "__total_impuestos"
_COSTO_OPERACION = "__costo_operacion"
COLUMNAS: list[tuple[str, str]] = [
    ("Numero Orden", "numero_orden"),
    ("Sku's Vendidos", "skus_vendidos"),
    ("FechaCreacionVenta", "fecha_creacion_venta"),
    ("EstadoVenta", "estado_venta"),
    ("FechaPago", "fecha_pago"),
    ("EstadoPago", "estado_pago"),
    ("Costo Sin Iva", "costo_sin_iva"),
    ("IVA A Favor", "iva_a_favor"),
    ("Canal De Venta", "canal_de_venta"),
    ("Usuario Integracion", "usuario_integracion"),
    ("Medio De Cobro", "medio_de_cobro"),
    ("Entrega/Envio", "entrega_envio"),
    ("Comision Venta", "comision_venta"),
    ("Comision Cobro", "comision_cobro"),
    ("Costo Envio", "costo_envio"),
    ("Impuestos (retenciones)", "impuestos_informados"),
    ("Precio SIN IVA", "precio_sin_iva"),
    ("Total Impuestos", _TOTAL_IMPUESTOS),
    ("Costo por Operacion Ecom", _COSTO_OPERACION),
    ("imp ch", "imp_cheque"),
    ("IIBB", "iibb"),
    ("Precio Final", "precio_final"),
    ("Dif IVA", "dif_iva"),
    ("Cash", "cash"),
    ("Utilidad Venta", "utilidad_venta"),
    ("Utilidad Costo", "utilidad_costo"),
    ("Neto", "neto"),
    ("Costo Total", "costo_total"),
    ("Rentabilidad", "rentabilidad"),
    ("PM", "pm"),
    ("Subcategoria", "subcategoria"),
    ("Rentabilidad USD", "rentabilidad_usd"),
    ("Facturacion USD", "facturacion_usd"),
    ("Responsable De Ventas", "responsable_de_ventas"),
    ("Categoria", "categoria"),
    ("Subcategoria2", "subcategoria2"),
    ("Periodo", "periodo_excel"),
    ("Semana", "semana"),
    ("Sku Negativo", "sku_negativo"),
    ("TC", "tc"),
    ("Vinculacion", "vinculacion"),
    ("IVA", "iva"),
    ("Facturacion +IVA", "facturacion_iva"),
    ("Stock", "stock"),
    ("Ventas 30 Dias", "ventas_30_dias"),
    ("Dias de Stock", "dias_de_stock"),
    ("Precio De Venta", "precio_de_venta_roto"),
    ("Rentabilidad Real", "rentabilidad_real"),
    ("% Rentabilidad", "pct_rentabilidad"),
]

# Columnas que la corrida no completa (salen vacías) y por qué.
COLUMNAS_SIN_DATO = {
    "IVA A Favor": "informativo, pendiente de definición (P-02)",
    "Dif IVA": "depende de IVA A Favor (P-02)",
    "Cash": "informativo, pendiente de definición (P-02)",
    "Utilidad Venta": "informativo, pendiente de definición (P-02)",
    "Utilidad Costo": "informativo, pendiente de definición (P-02)",
    "Responsable De Ventas": "vacío también en la planilla",
    "Periodo": "etiqueta manual de la planilla",
    "Semana": "etiqueta manual de la planilla",
    "Sku Negativo": "lista curada a mano en la planilla (hoja SKU Margen Negativo)",
    "Precio De Venta": "columna rota en la planilla (siempre 0, O-04)",
}


def _valor(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, date):
        return v.isoformat()
    return v


def _fila(v: VentaEcom, costo_operacion: Decimal | None) -> dict:
    fila = {}
    for titulo, campo in COLUMNAS:
        if campo == _TOTAL_IMPUESTOS:
            # R = U − Q en el origen (IVA contenido en el precio)
            valor = (v.precio_final - v.precio_sin_iva) if v.total_impuestos is None and v.precio_final is not None \
                and v.precio_sin_iva is not None else v.total_impuestos
        elif campo == _COSTO_OPERACION:
            # Monto fijo por orden (`costo_operacion_ecom`) que ya está
            # descontado en el Neto (Z); vacío si la orden no se calculó.
            valor = costo_operacion if v.neto is not None else None
        else:
            valor = getattr(v, campo)
        fila[titulo] = _valor(valor)
    return fila


def exportar_ventas(
    db: Session, periodo: str, dia: date | None = None, incluir_excluidas: bool = False,
) -> dict:
    """Órdenes del período (o solo las CREADAS el `dia`), en el orden en que
    se crearon. Por defecto solo las que participan de la rentabilidad
    (Cobrado / Cobro Parcial), como el reporte de facturación."""
    q = db.query(VentaEcom).filter(VentaEcom.periodo == periodo)
    if dia is not None:
        q = q.filter(VentaEcom.fecha_creacion_venta == dia)
    if not incluir_excluidas:
        q = q.filter(VentaEcom.excluido.is_(False))
    ventas = sorted(q.all(), key=lambda v: (v.fecha_creacion_venta or date.min, v.numero_orden))
    tasa = db.get(ParametroTasa, "costo_operacion_ecom")
    costo_operacion = tasa.valor if tasa else None
    return {
        "periodo": periodo,
        "dia": dia.isoformat() if dia else None,
        "alcance": f"órdenes creadas el {dia.isoformat()}" if dia else "todo el período",
        "total": len(ventas),
        "columnas": [t for t, _ in COLUMNAS],
        "columnas_sin_dato": COLUMNAS_SIN_DATO,
        "filas": [_fila(v, costo_operacion) for v in ventas],
    }
