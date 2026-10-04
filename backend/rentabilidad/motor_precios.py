"""Motor de precios unificado — un solo motor, en los dos sentidos.

Diseño: doc "Motor de Pricing Ayala — Diseño detallado" (aprobado por Maxx,
2026-09-29). Para cada SKU y canal arma UNA cuenta por unidad, en pesos:

    rentabilidad = venta sin IVA − cargos del canal − IIBB − imp. cheque − costo
    margen       = rentabilidad / venta sin IVA

— la misma definición que la rentabilidad real del ERP (rentabilidad /
facturación sin IVA), para que proyectado y real se comparen sin conversión.

- `precio_a_margen`: el PM carga un precio → cada cargo y el margen que queda.
- `margen_a_precio`: el PM pide un margen → el precio que lo cumple (misma
  cuenta despejada; es el modo del motor Ayala de Matías).

Reglas (decisiones de Maxx, 2026-09-29):
- Comisiones y cargos del canal son un % sobre el precio CON IVA (lo que
  paga el cliente) y se descuentan completos: el IVA que el canal factura
  aparte (MP, Frávega) se suma (`iva_cargos`). Solo la venta se lleva a sin
  IVA. IIBB va sobre la venta sin IVA, como en las planillas.
- ML: comisión 15,5% única (la de categoría queda sin usar), costo fijo por publicación (de la API; la
  tabla de tramos es el respaldo), cargo por cuotas, envío real del ítem
  desde el umbral de envío gratis.
- Web (Mercado Pago): comisión por medio de pago + cuotas que absorbe el
  vendedor. Tabla propia, nunca la de ML.
- Frávega / Megatone / OnCity: comisión base + financiera por plan + fee
  logístico. Fee: el que pase quien llama (histórico del SKU) → por kilo
  aforado con la tabla → promedio `fee_logistico_default` (8.500).

Solo cálculo: no lee Sheets, ni ML, ni costos — todo entra por
`EntradaMotor` y `ParametrosMotor` (`cargar_parametros` los arma de la base
para una fecha). No reemplaza a `ayala_core.py` (piloto que escribe precios
en ML), que sigue igual hasta migrarlo a este motor.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from .models import PricingComisionCategoria, PricingCuotas, PricingParametro, PricingTramo

CANALES = ("ML", "WEB", "FRAVEGA", "MEGATONE", "ONCITY")
MARKETPLACES = ("FRAVEGA", "MEGATONE", "ONCITY")
_PLANES_SIN_COSTO = ("", "contado", "simple", "1")
_CENTAVO = Decimal("0.01")


class ParametroFaltante(ValueError):
    pass


# ── Parámetros ──

@dataclass(frozen=True)
class Tramo:
    desde: Decimal
    hasta: Decimal | None
    valor: Decimal
    unidad: str  # "precio" → [desde, hasta) · "kg" → (desde, hasta]

    def contiene(self, x: Decimal) -> bool:
        if self.unidad == "kg":
            return x > self.desde and (self.hasta is None or x <= self.hasta)
        return x >= self.desde and (self.hasta is None or x < self.hasta)


@dataclass(frozen=True)
class ParametrosMotor:
    valores: dict[tuple[str, str], Decimal]  # (canal | "*", clave) → valor
    comision_categoria: dict[tuple[str, str], Decimal] = field(default_factory=dict)  # (canal, categoría)
    cuotas: dict[tuple[str, str], Decimal] = field(default_factory=dict)  # (canal, plan)
    tramos: dict[str, list[Tramo]] = field(default_factory=dict)

    def valor(self, canal: str, clave: str) -> Decimal:
        for k in ((canal, clave), ("*", clave)):
            if k in self.valores:
                return self.valores[k]
        raise ParametroFaltante(f"Falta el parámetro '{clave}' para {canal} (pricing_parametro).")

    def cuota(self, canal: str, plan: str | None) -> Decimal:
        plan = (plan or "").strip().lower()
        if plan in _PLANES_SIN_COSTO:
            return Decimal(0)
        if (canal, plan) not in self.cuotas:
            raise ParametroFaltante(f"Falta el costo del plan '{plan}' para {canal} (pricing_cuotas).")
        return self.cuotas[(canal, plan)]

    def tramo(self, tabla: str, x: Decimal) -> Decimal | None:
        """Valor del tramo que contiene `x`; None si ninguno (ej. costo fijo
        ML desde $33.000)."""
        if tabla not in self.tramos:
            raise ParametroFaltante(f"Falta la tabla '{tabla}' (pricing_tramo).")
        return next((t.valor for t in self.tramos[tabla] if t.contiene(x)), None)


def _vigentes(filas, clave, fecha: date):
    """Por cada clave, la fila con la `vigente_desde` más reciente <= fecha."""
    elegidas = {}
    for f in filas:
        if f.vigente_desde > fecha:
            continue
        k = clave(f)
        if k not in elegidas or (f.vigente_desde, f.cargado_en) > (elegidas[k].vigente_desde, elegidas[k].cargado_en):
            elegidas[k] = f
    return elegidas


def cargar_parametros(db: Session, fecha: date) -> ParametrosMotor:
    """Los parámetros vigentes a `fecha`. Una tabla de tramos vale entera: se
    toma el conjunto de filas con la `vigente_desde` más reciente <= fecha."""
    valores = {k: f.valor for k, f in _vigentes(db.query(PricingParametro).all(), lambda f: (f.canal, f.clave), fecha).items()}
    comision = {k: f.pct for k, f in _vigentes(
        db.query(PricingComisionCategoria).all(), lambda f: (f.canal, f.categoria.strip().lower()), fecha).items()}
    cuotas = {k: f.pct for k, f in _vigentes(
        db.query(PricingCuotas).all(), lambda f: (f.canal, f.plan.strip().lower()), fecha).items()}
    tramos: dict[str, list[Tramo]] = {}
    filas = [f for f in db.query(PricingTramo).all() if f.vigente_desde <= fecha]
    for tabla in {f.tabla for f in filas}:
        de_tabla = [f for f in filas if f.tabla == tabla]
        ultima = max(f.vigente_desde for f in de_tabla)
        tramos[tabla] = sorted(
            (Tramo(f.desde, f.hasta, f.valor, f.unidad) for f in de_tabla if f.vigente_desde == ultima),
            key=lambda t: t.desde,
        )
    return ParametrosMotor(valores=valores, comision_categoria=comision, cuotas=cuotas, tramos=tramos)


# ── Entrada y resultado ──

@dataclass(frozen=True)
class EntradaMotor:
    canal: str  # ML | WEB | FRAVEGA | MEGATONE | ONCITY
    costo: Decimal  # costo del producto en pesos, sin IVA (costo USD vigente × TC BNA)
    iva_factor: Decimal  # 1 + alícuota del SKU (1,21 / 1,105)
    categoria: str | None = None  # GRAL CATEGORIAS — comisión ML
    plan: str | None = None  # ML: contado/reducida/3..12 · WEB/marketplaces: cuotas sin interés
    medio_pago: str = "credito"  # WEB: credito | otros
    envio: Decimal = Decimal(0)  # ML: envío real del ítem (aplica desde el umbral) · WEB: lo que pagamos
    costo_fijo_ml: Decimal | None = None  # el de la publicación (API de ML); None → tabla de tramos
    kg_aforado: Decimal | None = None  # max(peso real, volumétrico cm³/4000)
    fee_logistico: Decimal | None = None  # histórico del SKU; tiene prioridad sobre el kilo aforado
    colecta: bool = False  # Frávega: Global vende sin colecta
    # Costo de cuotas YA con IVA, como fracción del precio (ej. el cargo real
    # que cobró ML en una venta / su precio). Si viene, reemplaza al del plan.
    cuotas_pct_final: Decimal | None = None


@dataclass(frozen=True)
class Desglose:
    canal: str
    precio: Decimal
    venta_sin_iva: Decimal
    cargos: dict[str, Decimal]  # nombre → monto en pesos (positivo = se descuenta)
    rentabilidad: Decimal
    margen: Decimal  # fracción: 0.301 = 30,1%
    origen_fee: str | None = None  # marketplaces: "historico" | "kg_aforado" | "promedio"


def _q(x: Decimal) -> Decimal:
    return x.quantize(_CENTAVO, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class _Estructura:
    """Cargos de un canal a un precio dado: los % sobre P (ya con el IVA de
    cargos) y los montos fijos. Separados para poder despejar P."""
    pct: dict[str, Decimal]
    fijos: dict[str, Decimal]
    origen_fee: str | None = None


def _cuotas(e: EntradaMotor, par: ParametrosMotor, mas_iva: Decimal) -> Decimal:
    if e.cuotas_pct_final is not None:
        return e.cuotas_pct_final
    return par.cuota(e.canal, e.plan) * mas_iva


def _estructura(p: Decimal, e: EntradaMotor, par: ParametrosMotor) -> _Estructura:
    canal = e.canal
    if canal not in CANALES:
        raise ValueError(f"Canal desconocido: {canal!r}")
    mas_iva = 1 + par.valor(canal, "iva_cargos")
    if canal == "ML":
        # Criterio de margen §2: comisión ML 15,5% ÚNICO por ahora. La tabla
        # por categoría (`par.comision_categoria`, pricing_comision_categoria)
        # queda cargada y sin usar: es el futuro (comisión real por categoría).
        comision = par.valor(canal, "comision_general")
        fijo = e.costo_fijo_ml if e.costo_fijo_ml is not None else (par.tramo("ml_costo_fijo", p) or Decimal(0))
        envio = e.envio if p >= par.valor(canal, "umbral_envio_gratis") else Decimal(0)
        return _Estructura(
            pct={"comision": comision * mas_iva, "cuotas": _cuotas(e, par, mas_iva)},
            fijos={"costo_fijo": fijo * mas_iva, "envio": envio},
        )
    if canal == "WEB":
        medio = "comision_mp_credito" if e.medio_pago == "credito" else "comision_mp_otros"
        return _Estructura(
            pct={"comision": par.valor(canal, medio) * mas_iva, "cuotas": _cuotas(e, par, mas_iva)},
            fijos={"envio": e.envio},
        )
    # Marketplaces
    if e.fee_logistico is not None:
        fee, origen = e.fee_logistico, "historico"
    elif e.kg_aforado is not None and e.kg_aforado > 0:
        escala = "alto" if p >= par.valor(canal, "umbral_escala_fee") else "bajo"
        tabla = f"{canal.lower()}_fee_{'con' if e.colecta else 'sin'}_colecta_{escala}"
        fee, origen = par.tramo(tabla, e.kg_aforado), "kg_aforado"
        if fee is None:
            raise ParametroFaltante(f"{e.kg_aforado} kg fuera de la tabla '{tabla}'.")
    else:
        fee, origen = par.valor(canal, "fee_logistico_default"), "promedio"
    return _Estructura(
        pct={"comision": par.valor(canal, "comision_base") * mas_iva,
             "financiera": par.cuota(canal, e.plan) * mas_iva},
        fijos={"fee_logistico": fee * mas_iva},
        origen_fee=origen,
    )


def precio_a_margen(precio: Decimal, e: EntradaMotor, par: ParametrosMotor) -> Desglose:
    """Modo precio → margen: cada descuento por separado y el margen que queda."""
    p = Decimal(precio)
    if p <= 0:
        raise ValueError("El precio tiene que ser mayor a 0.")
    n = p / e.iva_factor
    est = _estructura(p, e, par)
    cargos = {k: p * v for k, v in est.pct.items()}
    cargos.update(est.fijos)
    cargos["imp_cheque"] = p * par.valor(e.canal, "imp_cheque")
    cargos["iibb"] = n * par.valor(e.canal, "iibb")
    cargos["costo"] = e.costo
    rent = n - sum(cargos.values(), Decimal(0))
    return Desglose(
        canal=e.canal, precio=p, venta_sin_iva=_q(n), cargos={k: _q(v) for k, v in cargos.items()},
        rentabilidad=_q(rent), margen=(rent / n).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
        origen_fee=est.origen_fee,
    )


def redondear_precio(p: Decimal) -> Decimal:
    """Como las planillas: hacia abajo a la decena y terminado en 9."""
    return (p / 10).to_integral_value(rounding=ROUND_FLOOR) * 10 + 9


def margen_a_precio(margen: Decimal, e: EntradaMotor, par: ParametrosMotor, redondear: bool = True) -> Desglose:
    """Modo margen → precio. Todos los cargos son % de P o montos fijos:

        P = (costo + fijos) / ((1 − margen) / IVA − Σ% − cheque − IIBB / IVA)

    Los fijos dependen del tramo de P (costo fijo ML, envío gratis, escala
    del fee): se calcula, se mira en qué tramo cayó y se recalcula hasta que
    no cambie."""
    m = Decimal(margen)
    cheque, iibb = par.valor(e.canal, "imp_cheque"), par.valor(e.canal, "iibb")
    p = Decimal("1e12")  # arranca como precio alto (sin costo fijo ML, con envío)
    vistos = set()
    for _ in range(10):
        est = _estructura(p, e, par)
        denominador = (1 - m) / e.iva_factor - sum(est.pct.values(), Decimal(0)) - cheque - iibb / e.iva_factor
        if denominador <= 0:
            raise ValueError(f"Margen {m} inalcanzable en {e.canal}: los cargos se comen toda la venta.")
        nuevo = (e.costo + sum(est.fijos.values(), Decimal(0))) / denominador
        clave = tuple(sorted(est.fijos.items())) + tuple(sorted(est.pct.items()))
        if clave in vistos:
            p = max(p, nuevo)  # oscila entre dos tramos: el más alto cumple el margen
            break
        vistos.add(clave)
        p = nuevo
    return precio_a_margen(redondear_precio(p) if redondear else p, e, par)
