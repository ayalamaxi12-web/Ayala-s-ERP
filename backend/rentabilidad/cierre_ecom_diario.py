"""Corrida diaria de Rentabilidad ECOM desde la API de Ecom.

Cada día recalcula el **ciclo mensual en curso** (23 → 22, el mismo corte de
los cierres ya guardados: `2026-08-23_2026-09-22`, etc.) desde el día 23
hasta AYER, y lo guarda bajo la etiqueta del ciclo completo. Así:

- el ciclo tiene una sola etiqueta de período todo el mes (el informe y las
  agregaciones por período siguen funcionando igual, sin órdenes duplicadas
  entre un "cierre diario" y el mensual);
- cada corrida vuelve a aplicar el costo vigente a todo el ciclo (regla de
  Maxx, 2026-09-27: "siempre tomamos el dato actual del costo");
- las órdenes de Frávega toman la liquidación real si ya se cargó (queda en
  `liquidacion_fravega`) o la comisión base estimada si no.

El día 23 se cierra el ciclo anterior: AYER es 22, último día de ese ciclo.

Reglas de cálculo: las del adaptador (`ingesta_ecom_api`) y del motor
(`calculators`), aprobadas por Maxx el 2026-09-27 — acá solo se orquesta.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from .adapters import IvaProvider
from .ingesta_ecom import ORIGEN_COMISION_ESTIMADO_FRAVEGA, ResultadoIngestaEcom
from .persistencia import (
    OBSERVACION_CANCELADA_EN_FRAVEGA,
    ResultadoPersistenciaEcom,
    construir_filas_ecom,
    guardar_cierre_ecom,
    registrar_cierre,
)
from .regimen import periodo_de_rango

DIA_CORTE = 23
_ZONA_HORARIA_ARGENTINA = timezone(timedelta(hours=-3))


def ayer_en_argentina(ahora: datetime | None = None) -> date:
    ahora = ahora or datetime.now(timezone.utc)
    return ahora.astimezone(_ZONA_HORARIA_ARGENTINA).date() - timedelta(days=1)


def ciclo_de(dia: date, dia_corte: int = DIA_CORTE) -> tuple[date, date]:
    """(primer día, último día) del ciclo 23 → 22 que contiene `dia`."""
    if dia.day >= dia_corte:
        inicio = dia.replace(day=dia_corte)
    else:
        mes_anterior = dia.replace(day=1) - timedelta(days=1)
        inicio = mes_anterior.replace(day=dia_corte)
    siguiente = (inicio.replace(day=1) + timedelta(days=32)).replace(day=1)
    return inicio, siguiente.replace(day=dia_corte) - timedelta(days=1)


@dataclass
class ResumenCorrida:
    periodo: str
    desde: date
    hasta: date
    tc: Decimal
    guardado: bool
    tc_origen: str = ""
    ordenes: int = 0
    excluidas_por_estado_pago: int = 0
    # Costo 0 = casi siempre SKU madre en vez de variante (Maxx, 2026-09-27):
    # no se calculan ni se inventa el costo, se listan para corregir a mano.
    costo_cero: list[tuple[str, str]] = field(default_factory=list)  # (orden, skus)
    fravega_estimadas: int = 0
    observaciones: list[tuple[str, str]] = field(default_factory=list)  # (orden, observación)
    sin_pm: list[str] = field(default_factory=list)
    config_faltante: list[str] = field(default_factory=list)
    con_error: list[tuple[str, str]] = field(default_factory=list)  # (orden, error) — no se guardaron
    recortadas: list[tuple[str, str]] = field(default_factory=list)  # (orden, campo)
    facturacion: Decimal = Decimal(0)
    rentabilidad: Decimal = Decimal(0)


def _resumir(
    periodo: str, desde: date, hasta: date, tc: Decimal, guardado: bool,
    ingesta: ResultadoIngestaEcom, resultado: ResultadoPersistenciaEcom,
) -> ResumenCorrida:
    resumen = ResumenCorrida(periodo=periodo, desde=desde, hasta=hasta, tc=tc, guardado=guardado)
    resumen.excluidas_por_estado_pago = len(ingesta.excluidas_por_estado_pago)
    resumen.costo_cero = [(f.numero_orden, f.skus_vendidos) for f in ingesta.incidencias_costo]
    resumen.config_faltante = resultado.config_faltante
    resumen.con_error = list(ingesta.ilegibles) + resultado.con_error
    resumen.recortadas = resultado.recortadas
    for venta in resultado.filas:
        if venta.excluido:
            continue
        resumen.ordenes += 1
        resumen.facturacion += venta.precio_final or 0
        resumen.rentabilidad += venta.rentabilidad or 0
        if venta.origen_comision == ORIGEN_COMISION_ESTIMADO_FRAVEGA and venta.observacion != OBSERVACION_CANCELADA_EN_FRAVEGA:
            resumen.fravega_estimadas += 1
        if venta.observacion:
            resumen.observaciones.append((venta.numero_orden, venta.observacion))
        if venta.pm in (None, "", "#N/A"):
            resumen.sin_pm.append(venta.numero_orden)
    return resumen


def correr(
    db: Session,
    adaptador,
    tc: Decimal,
    iva_provider: IvaProvider,
    providers: dict,
    hasta: date,
    desde: date | None = None,
    guardar: bool = True,
    dia_corte: int = DIA_CORTE,
    tc_origen: str = "",
    log=None,
) -> ResumenCorrida:
    """Trae de la API las órdenes `[desde, hasta]` (por defecto, del inicio
    del ciclo de `hasta` hasta `hasta`) y, si `guardar`, reemplaza el
    período del ciclo en `venta_ecom`. Con `guardar=False` solo calcula
    (modo consulta, para validar sin escribir)."""
    inicio_ciclo, fin_ciclo = ciclo_de(hasta, dia_corte)
    desde = desde or inicio_ciclo
    if desde > hasta:
        raise ValueError(f"'desde' ({desde}) es posterior a 'hasta' ({hasta}).")
    if guardar and desde != inicio_ciclo:
        # Guardar un rango parcial crearía un período solapado con el del
        # ciclo y las mismas órdenes quedarían dos veces en `venta_ecom`.
        raise ValueError(
            f"Para guardar, el rango tiene que arrancar el día {dia_corte} ({inicio_ciclo}); "
            "un rango parcial solo se puede correr como consulta."
        )
    periodo = periodo_de_rango(inicio_ciclo, fin_ciclo) if desde == inicio_ciclo else periodo_de_rango(desde, hasta)

    log = log or (lambda _msg: None)
    log(f"Período {periodo}: datos {desde} → {hasta}, TC {tc}")
    ingesta = adaptador.periodo(desde, hasta, tc)
    total = len(ingesta.lineas) + len(ingesta.excluidas_por_estado_pago) + len(ingesta.incidencias_costo)
    log(f"Calculando {total} órdenes ({len(ingesta.incidencias_costo)} con costo 0, "
        f"{len(ingesta.excluidas_por_estado_pago)} excluidas por estado de pago)")
    if guardar:
        resultado = guardar_cierre_ecom(db, periodo, ingesta, iva_provider, **providers, log=log)
        registrar_cierre(db, periodo, desde, hasta, ecom_guardado=True, ecom_origen="api",
                         tc_ecom=tc, tc_ecom_origen=tc_origen or None)
    else:
        resultado = construir_filas_ecom(db, ingesta, iva_provider, **providers, log=log)
    log("Cálculo terminado" + (" — falta el commit a la base" if guardar else " (solo consulta, no se guarda)"))
    resumen = _resumir(periodo, desde, hasta, tc, guardar, ingesta, resultado)
    resumen.tc_origen = tc_origen
    return resumen


def formatear(resumen: ResumenCorrida) -> str:
    def m(v: Decimal) -> str:
        return f"{'-' if v < 0 else ''}$ {abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    lineas = [
        f"Rentabilidad ECOM — período {resumen.periodo} (datos {resumen.desde} → {resumen.hasta}, TC {resumen.tc})",
        "GUARDADO en venta_ecom" if resumen.guardado else "SOLO CONSULTA — no se guardó nada",
        f"Órdenes: {resumen.ordenes} (incluye {len(resumen.costo_cero)} con costo 0, sin calcular)  ·  "
        f"excluidas por estado de pago: {resumen.excluidas_por_estado_pago}",
        f"Facturación: {m(resumen.facturacion)}  ·  Rentabilidad: {m(resumen.rentabilidad)}",
        f"Frávega con comisión estimada (esperan liquidación): {resumen.fravega_estimadas}",
    ]
    if resumen.costo_cero:
        lineas.append(f"COSTO 0 — probable SKU madre, revisar a mano ({len(resumen.costo_cero)}):")
        lineas += [f"  {orden}  {skus or '(sin SKU: la línea no tiene variante cargada)'}" for orden, skus in resumen.costo_cero]
    if resumen.observaciones:
        lineas.append(f"OBSERVACIONES ({len(resumen.observaciones)}):")
        lineas += [f"  {orden}  {obs}" for orden, obs in resumen.observaciones]
    if resumen.sin_pm:
        muestra = ", ".join(resumen.sin_pm[:20]) + (" ..." if len(resumen.sin_pm) > 20 else "")
        lineas.append(f"Sin PM ({len(resumen.sin_pm)}): {muestra}")
    if resumen.con_error:
        lineas.append(f"ÓRDENES CON ERROR — no se guardaron, revisar ({len(resumen.con_error)}):")
        lineas += [f"  {orden}  {error}" for orden, error in resumen.con_error]
    if resumen.recortadas:
        lineas.append(f"Textos recortados por largo ({len(resumen.recortadas)}): "
                      + ", ".join(f"{o} ({c})" for o, c in resumen.recortadas[:20]))
    if resumen.config_faltante:
        lineas.append(f"Sin calcular por configuración faltante ({len(resumen.config_faltante)}): {', '.join(resumen.config_faltante)}")
    # Al pie, a propósito (pedido de Maxx, 2026-09-28): para verificar que el
    # TC con que se calculó todo el ciclo fue el correcto.
    lineas.append(f"TC usado: {m(resumen.tc)}" + (f" — {resumen.tc_origen}" if resumen.tc_origen else ""))
    return "\n".join(lineas)
