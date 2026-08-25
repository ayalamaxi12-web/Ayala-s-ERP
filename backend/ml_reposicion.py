"""Simulador de reposición Full — cuánto conviene enviar, por PUBLICACIÓN
(MLA), no por SKU.

Rediseñado 2026-08-25 a pedido de Maxx: la reposición real de Full se arma
publicación por publicación, no por SKU agregado -- "el stock se reparte de
acuerdo a cuánto vendió ese MLA, no ese SKU". Cada fila de este módulo es
una publicación (una cuenta, un `item_id`), con su propia venta, su propio
stock y su propio objetivo. La conciliación SKU-agregada de `ml_full.py`
(`conciliar()`) sigue existiendo tal cual -- este módulo la REUSA (mismos
datos de stock/factor de pack ya resueltos, sin pegarle de nuevo a ML) pero
ya no colapsa el resultado a un total por SKU antes de mostrarlo.

Sigue siendo de **solo lectura y de simulación**: calcula y muestra cuánto
convendría enviar a Full, pero no crea el envío real en Mercado Libre.
Confirmado con Maxx (2026-08-20): "eso lo llevamos al ERP después de
verificar que el cálculo da bien" -- la creación real del envío queda para
después, y de cualquier forma sigue detrás de la puerta de escritura de
`docs/business/COMERCIAL/00_LEEME.md` §5.

**Fuente de ventas: solo las que salieron de Full, no cualquier venta
pagada de la publicación.** Corregido 2026-08-25 -- la versión anterior
usaba `/orders/search?order.status=paid`, que cuenta CUALQUIER venta
pagada del ítem sin mirar de qué depósito salió. Una publicación
`fulfillment` puede tener coexistencia Full/Flex y despachar algunas
ventas desde el depósito propio del vendedor (self-service), no desde
Full -- confirmado con un caso real en producción (Maxx lo detectó
comparando contra el consolidado real de una publicación): 6 unidades
pagadas el mismo día contaban como venta de Full, pero el envío de esa
orden específica tenía `logistic_type=self_service`. Ahora se usa
`MLFullClient.ventas_full_por_inventory` (`stock/fulfillment/operations/
search`, `type=SALE_CONFIRMATION`, por `inventory_id`) -- scopeado al
depósito Full por diseño, no puede traer una venta self-service aunque
quisiera. Ver el docstring de ese método para el detalle del contrato
confirmado contra la cuenta real (formato de fecha, tope de 60 días,
paginación por `scroll`).

Fuente de "disponible para enviar" (Ecom): el depósito **Pitec**
(`EcomFullAdapter.stock_disponible_por_sku`, confirmado con Maxx
2026-08-20) -- no la suma de todos los depósitos que no son Full.

Fuente de "disponible para enviar" (Táctica): confirmado con Maxx
(2026-08-25) -- hoy NO hay SQL ni API de stock de Táctica (se revisó
`rentabilidad/ingesta_tactica.py`, solo trae ventas). Se lee del Sheet
"Stock e Importaciones" vía `ml_full.TacticaStockSheetAdapter` -- ver ese
docstring para el detalle de por qué es una fuente transitoria.

**La fecha de llegada del envío importa, no solo "hoy".** Confirmado con
Maxx (2026-08-25) con un ejemplo real: un envío creado el 22/08 para llegar
el 03/09 sigue vendiendo durante esos 12 días de tránsito -- si al momento
de llegar el envío el MLA ya tocó cero, había que haberle mandado las 3
semanas objetivo completas A PARTIR de la llegada, no de hoy. Por eso
`calcular_reposicion_mla` pide `fecha_llegada` (nunca asume "una semana" ni
ningún número fijo) y calcula:

    días_hasta_llegada  = fecha_llegada − hoy (nunca negativo, se clampea a 0)
    stock_a_llegada     = stock_full_hoy − ventas_diaria_mla × días_hasta_llegada
    stock_objetivo      = ventas_diaria_mla × semanas_objetivo × 7
    cantidad_enviar     = máx(0, stock_objetivo − stock_a_llegada)   [unidades reales, sin convertir todavía]

**`cantidad_enviar`/`sugerido` se muestran en PAQUETES, no en unidades
reales del SKU.** Corregido 2026-08-26 -- Maxx encontró que para una
publicación pack ("X2 EMERLIGHT-30LED", factor 2) el sistema sugería
enviar la cantidad en unidades reales del SKU (ej. 205), pero lo que la
persona prepara y carga es en paquetes, y Full cuenta el inventario de
esa publicación también en paquetes -- si mandaba 205 PAQUETES, mandaba
el doble de lo necesario (410 unidades reales). Todo el cálculo de
arriba (`stock_objetivo`, `stock_a_llegada`, `cantidad_enviar`, y el
reparto de `sugerido` contra Ecom+Táctica) se sigue haciendo en unidades
reales -- tiene que ser así para comparar bien contra Ecom/Táctica (que
llevan el stock real) y para repartir bien entre publicaciones que
pueden tener factores distintos del mismo SKU. La conversión a paquetes
(`_convertir_a_paquetes`, `cantidad_enviar ÷ factor`, redondeado para
arriba) pasa recién al final, después del reparto -- ver su docstring.

**El reparto cuando el disponible combinado (Ecom+Táctica) no alcanza para
todas las publicaciones de un mismo SKU** -- confirmado con Maxx
(2026-08-25), nunca proporcional: la publicación que más vende (mayor
`ventas_diarias`, ya corregida por censura) se abastece POR COMPLETO
primero; lo que sobra va a la siguiente en orden descendente, hasta agotar
el disponible. Eso da el campo `sugerido`, que solo difiere de
`cantidad_enviar` cuando hay escasez real a nivel SKU -- si alcanza para
todas, son el mismo número. El reparto se calcula sobre el TOTAL del SKU
cruzando las dos cuentas (el depósito es uno solo, compartido) aunque la
pantalla lo muestre en pestañas separadas por cuenta.

**"Envíos pendientes" sigue siendo un campo manual, cargado por la persona
en el ERP** (confirmado con Maxx 2026-08-25) -- este módulo no lo calcula
ni lo resta, queda en manos del frontend, que sí lo resta de
`cantidad_enviar`/`sugerido` al recalcular localmente cuando la persona lo
carga. El mismo endpoint que ahora resuelve las ventas
(`stock/fulfillment/operations/search`) también sirve para esto con
`type=INBOUND_RECEPTION` -- contrato ya confirmado contra la cuenta real
(mismo formato de fecha/paginación), pero conectarlo es trabajo aparte, no
pedido todavía.

GAPS documentados, no resueltos todavía (no son reglas inventadas, son
huecos reales sin dato para llenarlos):
- La "ventana con stock" (para detectar venta censurada) se estima por
  primera/última venta del período, igual que ya hace la planilla
  (`03_MODULO_FULL.md` §5) -- el log de movimientos exacto (§4.1) sigue sin
  confirmar si existe por API.
- La segunda condición de censura del doc ("rotación ≥ 3 y unidades ≥ 10")
  **no está implementada**: necesita stock PROMEDIO del período, que
  requiere fotos diarias de stock (§4.2) que todavía no existen. Solo se
  implementa la primera condición (stock actual en 0 + ventas ≥ 5 + días
  sin vender ≥ 3), igual que antes de este rediseño.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

from ml_auth import SELLERS
from ml_full import EcomFullAdapter, MLFullClient, TacticaStockSheetAdapter, conciliar


@dataclass
class FilaReposicionMLA:
    item_id: str
    inventory_id: str | None
    cuenta: str
    sku: str
    sku_ml: str | None
    titulo: str
    stock_full: int
    ventas_periodo: int
    dias_periodo: int
    primera_venta: str | None
    ultima_venta: str | None
    censurado: bool
    ventas_diarias: float
    stock_objetivo: float
    stock_a_llegada: float
    factor: int
    cantidad_enviar: int  # en PAQUETES (la unidad que vende esta publicación), no en unidades reales del SKU
    sugerido: int          # ídem, en paquetes
    stock_ecom: int | None
    stock_tactica: int | None


@dataclass
class ResultadoReposicionMLA:
    filas: list[FilaReposicionMLA]  # las dos cuentas juntas -- el llamador agrupa por `cuenta` al mostrar
    incidencias_sku: list[dict]
    incidencias_sin_vincular: list[dict]
    skus_no_en_ecom: list[str]


def _repartir_sugerido(filas: list[FilaReposicionMLA]) -> None:
    """Muta `sugerido` en cada fila -- en UNIDADES REALES todavía (la
    conversión a paquetes pasa después, ver `_convertir_a_paquetes`). Tiene
    que ser en unidades reales acá: el pool de Ecom+Táctica es físico y
    compartido entre publicaciones que pueden tener factores de pack
    distintos para el mismo SKU (una publicación simple y una "X2" del
    mismo producto) -- repartir en paquetes mezclaría unidades de medida
    distintas entre publicaciones.

    Agrupa por SKU cruzando las dos cuentas (el depósito de Ecom/Táctica es
    uno solo por SKU) y reparte el disponible combinado en orden de venta
    descendente -- "todo a la que más vende antes que a la siguiente",
    nunca proporcional (confirmado con Maxx, ver docstring del módulo)."""
    por_sku: dict[str, list[FilaReposicionMLA]] = {}
    for f in filas:
        por_sku.setdefault(f.sku, []).append(f)
    for grupo in por_sku.values():
        disponible = (grupo[0].stock_ecom or 0) + (grupo[0].stock_tactica or 0)
        for f in sorted(grupo, key=lambda x: x.ventas_diarias, reverse=True):
            asignado = max(0, min(f.cantidad_enviar, disponible))
            f.sugerido = asignado
            disponible -= asignado


def _convertir_a_paquetes(filas: list[FilaReposicionMLA]) -> None:
    """`cantidad_enviar`/`sugerido` se calculan en unidades reales del SKU
    (necesario para conciliar y repartir correctamente contra Ecom/
    Táctica, que llevan el stock en unidades reales) -- pero lo que la
    persona prepara y carga para ESTA publicación es en la unidad que la
    publicación vende, y Full cuenta el inventario de esa publicación en
    esa misma unidad (un pack "X2" descuenta 1 de a 1 en Full, no 2).

    Confirmado con Maxx (2026-08-26), con un caso real: la publicación
    `MLA1607512661` ("X2 EMERLIGHT-30LED", factor 2) mostraba "205" como
    cantidad a enviar en unidades reales -- si la persona preparaba 205
    PAQUETES (la unidad con la que arma el envío), mandaba el doble de lo
    necesario (410 unidades reales). Se convierte a paquetes recién ACÁ,
    después de `_repartir_sugerido` -- nunca antes, porque el reparto
    necesita las unidades reales para comparar contra el disponible físico
    compartido. Redondea para arriba (nunca manda de menos por
    redondeo)."""
    for f in filas:
        f.cantidad_enviar = math.ceil(f.cantidad_enviar / f.factor)
        f.sugerido = math.ceil(f.sugerido / f.factor)


def calcular_reposicion_mla(
    ml: MLFullClient, ecom: EcomFullAdapter, tactica: TacticaStockSheetAdapter,
    cuentas: list[str] | None = None, dias_ventas: int = 30, semanas_objetivo: float = 3,
    fecha_llegada: date | None = None, hoy: date | None = None,
) -> ResultadoReposicionMLA:
    """Orquesta el simulador por publicación: reutiliza `conciliar()` para
    el stock/factor de pack ya resuelto de las dos cuentas (sin volver a
    pegarle a ML ni a la vinculación de Ecom), y en vez de sumar por SKU
    calcula cada publicación por separado -- ver el docstring del módulo
    para las fórmulas exactas."""
    cuentas = cuentas or list(SELLERS.keys())
    hoy = hoy or date.today()
    fecha_llegada = fecha_llegada or hoy
    dias_hasta_llegada = max(0, (fecha_llegada - hoy).days)
    # Tope real de `stock/fulfillment/operations/search` (confirmado contra
    # la cuenta real: pedir más de 60 días tira 400 "Date range can't be
    # greater than 60 days") -- se clampea acá, no se deja fallar el job
    # entero por un valor cargado a mano en el frontend.
    dias_ventas = min(dias_ventas, 60)
    desde = (hoy - timedelta(days=dias_ventas)).isoformat()
    hasta = hoy.isoformat()

    resultado_conciliacion = conciliar(ml, ecom, cuentas)

    ventas_por_inventory: dict[str, dict] = {}
    for cuenta in cuentas:
        # inventory_id es único globalmente (no solo por cuenta) -- no hay
        # colisión al combinar los diccionarios de las dos cuentas.
        inventory_ids = sorted({
            pub["inventory_id"]
            for fila in resultado_conciliacion.filas
            for pub in fila.publicaciones
            if pub["cuenta"] == cuenta and pub.get("inventory_id")
        })
        if inventory_ids:
            ventas_por_inventory.update(ml.ventas_full_por_inventory(cuenta, inventory_ids, desde, hasta))

    filas: list[FilaReposicionMLA] = []
    for fila_sku in resultado_conciliacion.filas:
        stock_ecom = ecom.stock_disponible_por_sku(fila_sku.sku, fila_sku.parent_sku)
        stock_tactica = tactica.stock_por_sku(fila_sku.sku)
        for pub in fila_sku.publicaciones:
            stock_full_mla = pub["disponible"] * pub["factor"]
            venta_inv = ventas_por_inventory.get(pub["inventory_id"]) if pub.get("inventory_id") else None
            ventas_total = (venta_inv["unidades"] * pub["factor"]) if venta_inv else 0
            primera = venta_inv["primera"] if venta_inv else None
            ultima = venta_inv["ultima"] if venta_inv else None

            dias_sin_vender = (hoy - date.fromisoformat(ultima)).days if ultima else dias_ventas
            censurado = stock_full_mla == 0 and ventas_total >= 5 and dias_sin_vender >= 3
            if censurado and primera and ultima:
                ventana = max((date.fromisoformat(ultima) - date.fromisoformat(primera)).days, 1)
                ventas_diarias = ventas_total / ventana
            else:
                ventas_diarias = ventas_total / dias_ventas

            stock_objetivo = ventas_diarias * semanas_objetivo * 7
            # max(0, ...) -- confirmado con Maxx (2026-08-26) sobre un caso
            # real: el stock físico no puede ser negativo. Si la resta da
            # negativo es que el MLA se agota ANTES de que llegue el envío
            # y se queda en 0 el resto del tránsito -- no sigue "vendiendo"
            # a la tasa diaria en números negativos. Sin este piso,
            # `cantidad_enviar` contaba ventas fantasma que nunca podían
            # pasar (quebró, no hay stock que vender) y sugería mandar de
            # más -- cargo extra de Full por sobre-stockear sin necesidad.
            stock_a_llegada = max(0.0, stock_full_mla - ventas_diarias * dias_hasta_llegada)
            cantidad_enviar = max(0, round(stock_objetivo - stock_a_llegada))

            filas.append(FilaReposicionMLA(
                item_id=pub["item_id"], inventory_id=pub["inventory_id"], cuenta=pub["cuenta"],
                sku=fila_sku.sku, sku_ml=pub.get("sku_ml"), titulo=pub.get("titulo", ""),
                stock_full=stock_full_mla, ventas_periodo=ventas_total, dias_periodo=dias_ventas,
                primera_venta=primera, ultima_venta=ultima, censurado=censurado,
                ventas_diarias=round(ventas_diarias, 2), stock_objetivo=round(stock_objetivo, 1),
                stock_a_llegada=round(stock_a_llegada, 1), factor=pub["factor"],
                cantidad_enviar=cantidad_enviar, sugerido=0,
                stock_ecom=stock_ecom, stock_tactica=stock_tactica,
            ))

    _repartir_sugerido(filas)
    _convertir_a_paquetes(filas)

    return ResultadoReposicionMLA(
        filas=filas, incidencias_sku=resultado_conciliacion.incidencias_sku,
        incidencias_sin_vincular=resultado_conciliacion.incidencias_sin_vincular,
        skus_no_en_ecom=resultado_conciliacion.skus_no_en_ecom,
    )


# ── Job en background — mismo patrón que ml_full.py (jobs propios, no
# compartidos con main.py ni con ml_full.py). ──

_jobs: dict[str, dict] = {}


def iniciar_job(
    job_id: str, ecom_email: str | None = None, ecom_password: str | None = None,
    dias_ventas: int = 30, semanas_objetivo: float = 3, fecha_llegada: date | None = None,
) -> None:
    from rentabilidad.ingesta_ecom_api import EcomApiClient

    _jobs[job_id] = {"status": "running", "log": ["Iniciando simulación de reposición..."], "result": None}
    try:
        ml = MLFullClient()
        ecom = EcomFullAdapter(EcomApiClient(email=ecom_email, password=ecom_password))
        tactica = TacticaStockSheetAdapter()
        resultado = calcular_reposicion_mla(
            ml, ecom, tactica, dias_ventas=dias_ventas, semanas_objetivo=semanas_objetivo,
            fecha_llegada=fecha_llegada,
        )
        _jobs[job_id]["result"] = {
            "filas": [f.__dict__ for f in resultado.filas],
            "incidencias_sku": resultado.incidencias_sku,
            "incidencias_sin_vincular": resultado.incidencias_sin_vincular,
            "skus_no_en_ecom": resultado.skus_no_en_ecom,
        }
        _jobs[job_id]["status"] = "done"
        _jobs[job_id]["log"].append(f"Listo: {len(resultado.filas)} publicaciones calculadas.")
    except Exception as e:
        _jobs[job_id]["status"] = "error"
        _jobs[job_id]["log"].append(f"Error: {e}")


def estado_job(job_id: str) -> dict | None:
    return _jobs.get(job_id)
