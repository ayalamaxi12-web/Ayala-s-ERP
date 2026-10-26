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

**"Envíos pendientes" -- conectado 2026-09-01 (pedido de Maxx), ya no es
puramente manual.** `FilaReposicionMLA.envio_pendiente` (paquetes) y
`.envio_pendiente_ids` (los `inbound_id` reales, para que Maxx los pueda
buscar a mano en el panel de Full de ML) se resuelven en vivo vía
`MLFullClient.envios_pendientes_por_inventory` (mismo endpoint que las
ventas, `stock/fulfillment/operations/search`, `type=INBOUND_RECEPTION` --
ver su docstring para el detalle de por qué hay que agrupar por
`inbound_id` y quedarse con el evento más reciente). Este módulo SIGUE sin
restarlo de `cantidad_enviar`/`sugerido` -- ese resto sigue pasando en el
frontend (`_fullRepoRecalcular`), que ahora arranca con este valor real
como default en vez de 0, pero lo deja editable por si el dato de ML
todavía no reflejó un despacho recién hecho.

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
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable

from ml_auth import SELLERS
from ml_full import (EcomFullAdapter, ItemFullML, MLFullClient, TacticaStockSheetAdapter, _resolver_vinculacion, conciliar,
                     extraer_publicaciones_activas)


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
    envio_pendiente: int = 0            # en paquetes -- ver ml_full.envios_pendientes_por_inventory
    envio_pendiente_ids: list[str] = field(default_factory=list)  # inbound_id reales, para verificar a mano
    datos_incompletos: bool = False     # las ventas/envíos de esta publicación no se pudieron leer de ML (cuota): el cálculo NO es confiable
    # Demanda (unidades REALES del SKU, ya con el factor de pack). `ventas_periodo` es la demanda USADA: ventas de Full + (si el interruptor está activado) mi depósito.
    ventas_full: int = 0
    ventas_deposito: int = 0
    # Motivos fijos de la fila: no_full (hay que habilitarla en ML), sin_sku, sin_vincular, sin_ecom (el SKU no existe en Ecom), ecom_negativo, sin_tactica.
    flags: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


@dataclass
class ResultadoReposicionMLA:
    filas: list[FilaReposicionMLA]  # las dos cuentas juntas -- el llamador agrupa por `cuenta` al mostrar
    incidencias_sku: list[dict]
    incidencias_sin_vincular: list[dict]
    skus_no_en_ecom: list[str]
    skus_incompletos: list[str] = field(default_factory=list)  # SKU con datos de ML sin leer (de la conciliación o de las ventas/envíos)
    periodo: dict = field(default_factory=dict)  # {"desde","hasta","dias"}: el rango EXACTO de fechas que se leyó de Mercado Libre
    ordenes_dias_sin_leer: list[str] = field(default_factory=list)  # días de `orders/search` que no se pudieron leer (las ventas de mi depósito quedan incompletas)


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


def _grupo_pub(pub: dict) -> tuple:
    """Dos publicaciones con el mismo `inventory_id` comparten inventario: son UN grupo de ventas. Sin inventario, cada publicación (o variación) es su grupo."""
    if pub.get("inventory_id"):
        return ("inv", pub["inventory_id"])
    return ("pub", pub.get("cuenta"), pub.get("item_id"), str(pub["variation_id"]) if pub.get("variation_id") else None)


def _stocks(ecom, tactica, sku: str, parent_sku: str | None) -> tuple[int | None, int | None, list[str], list[str]]:
    """Stock de Pitec (Ecom) y de Táctica de un SKU. Ecom negativo se muestra como 0 con aviso (un stock negativo restaría disponible de más); Táctica sin dato queda
    en None y se marca «sin dato de Táctica» (no se suma como 0 en silencio)."""
    flags: list[str] = []
    avisos: list[str] = []
    stock_ecom = ecom.stock_disponible_por_sku(sku, parent_sku)
    if stock_ecom is not None and stock_ecom < 0:
        avisos.append(f"Stock negativo en Ecom ({stock_ecom}): se usa 0.")
        flags.append("ecom_negativo")
        stock_ecom = 0
    stock_tactica = tactica.stock_por_sku(sku)
    if stock_tactica is None:
        flags.append("sin_tactica")
        avisos.append("Sin dato de Táctica.")
    elif stock_tactica < 0:
        avisos.append(f"Stock negativo en Táctica ({stock_tactica}): se usa 0.")
        stock_tactica = 0
    if stock_ecom is None:
        flags.append("sin_ecom")
    return stock_ecom, stock_tactica, flags, avisos


def _filas_solo_deposito(ml, ecom, tactica, res_conc, pubs_activas, total_pagado_grupo, grupos_con_fila, dias_ventas, semanas_objetivo, dias_hasta_llegada,
                         progreso_cb) -> list[FilaReposicionMLA]:
    """Publicaciones activas con ventas pagadas que NO tienen fila en la conciliación (no están en Full, o no tienen inventario): sin stock en Full. Stock Full 0 y a la
    llegada 0, y se sugiere el objetivo completo (el reparto contra Pitec y Táctica lo hace el llamador, igual que para el resto)."""
    filas: list[FilaReposicionMLA] = []
    vistos: set[tuple] = set()
    factor_por_item: dict[str, object] = {}
    cache_stock: dict[str, tuple] = {}
    candidatos = [p for p in pubs_activas if _grupo_pub(p) not in grupos_con_fila and total_pagado_grupo.get(_grupo_pub(p), 0) > 0]
    for i, pub in enumerate(candidatos):
        g = _grupo_pub(pub)
        if g in vistos:
            continue
        vistos.add(g)
        if progreso_cb:
            progreso_cb(i, len(candidatos), "Resolviendo publicaciones con ventas de mi depósito")
        if pub["item_id"] not in factor_por_item:
            factor_por_item[pub["item_id"]] = ecom.factor_pack(pub["item_id"])
        fila_ml = ItemFullML(item_id=pub["item_id"], cuenta=pub["cuenta"], sku=pub.get("sku"), inventory_id=pub.get("inventory_id"), titulo=pub.get("titulo", ""),
                             variacion_attrs=pub.get("variacion_attrs"))
        pares, vinculado, _incidencia = _resolver_vinculacion(fila_ml, factor_por_item[pub["item_id"]])
        pagado = total_pagado_grupo[g]
        if not pares:
            pares = [("", 1, None)]
        for sku, factor, parent in pares:
            if sku:
                if sku not in cache_stock:
                    cache_stock[sku] = _stocks(ecom, tactica, sku, parent)
                stock_ecom, stock_tactica, flags_stock, avisos_stock = cache_stock[sku]
            else:
                stock_ecom, stock_tactica, flags_stock, avisos_stock = None, None, ["sin_sku"], []
            deposito = pagado * factor
            diarias = deposito / dias_ventas
            objetivo = diarias * semanas_objetivo * 7
            flags = list(flags_stock) + (["no_full"] if (pub.get("logistic_type") != "fulfillment" or not pub.get("inventory_id")) else []) + (["sin_vincular"] if (sku and not vinculado) else [])
            filas.append(FilaReposicionMLA(
                item_id=pub["item_id"], inventory_id=pub.get("inventory_id"), cuenta=pub["cuenta"], sku=sku, sku_ml=pub.get("sku"), titulo=pub.get("titulo", ""),
                stock_full=0, ventas_periodo=deposito, dias_periodo=dias_ventas, primera_venta=None, ultima_venta=None, censurado=False,
                ventas_diarias=round(diarias, 2), stock_objetivo=round(objetivo, 1), stock_a_llegada=0.0, factor=factor,
                cantidad_enviar=max(0, round(objetivo)), sugerido=0, stock_ecom=stock_ecom, stock_tactica=stock_tactica,
                ventas_full=0, ventas_deposito=deposito, flags=flags, avisos=list(avisos_stock)))
    return filas


def calcular_reposicion_mla(
    ml: MLFullClient, ecom: EcomFullAdapter, tactica: TacticaStockSheetAdapter,
    cuentas: list[str] | None = None, dias_ventas: int = 30, semanas_objetivo: float = 3,
    fecha_llegada: date | None = None, hoy: date | None = None,
    progreso_cb: Callable[[int, int, str], None] | None = None,
    resultado_conciliacion=None,
    contar_deposito: bool = False,
) -> ResultadoReposicionMLA:
    """Orquesta el simulador por publicación: reutiliza `conciliar()` para
    el stock/factor de pack ya resuelto de las dos cuentas (sin volver a
    pegarle a ML ni a la vinculación de Ecom), y en vez de sumar por SKU
    calcula cada publicación por separado -- ver el docstring del módulo
    para las fórmulas exactas.

    `progreso_cb(procesados, total, fase)` opcional -- pedido de Maxx
    2026-08-27, mismo criterio que `conciliar()` (que ya recibe el mismo
    callback, así sus dos fases se ven acá también)."""
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

    # `resultado_conciliacion`: si el llamador ya tiene la conciliación (misma corrida o una foto reciente), no se vuelve a leer nada de ML ni de Ecom.
    if resultado_conciliacion is None:
        resultado_conciliacion = conciliar(ml, ecom, cuentas, progreso_cb=progreso_cb)

    ventas_por_inventory: dict[str, dict] = {}
    envios_pendientes_por_inventory: dict[str, dict] = {}
    for idx_cuenta, cuenta in enumerate(cuentas):
        if progreso_cb:
            progreso_cb(idx_cuenta, len(cuentas), f"Consultando ventas Full ({cuenta})")
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
            # "Envíos pendientes" real -- pedido de Maxx 2026-09-01, ver
            # docstring de envios_pendientes_por_inventory. Antes esto era
            # un campo que la persona cargaba a mano en el frontend; ahora
            # se sugiere solo con el dato real de ML (el frontend lo sigue
            # dejando editable, por si el dato de ML tarda en reflejar un
            # despacho recién hecho).
            envios_pendientes_por_inventory.update(
                ml.envios_pendientes_por_inventory(cuenta, inventory_ids, desde, hasta)
            )

    # Mi depósito: todas las publicaciones activas y sus ventas pagadas (solo si el interruptor está activado).
    pubs_activas: list[dict] = []
    total_pagado_grupo: dict[tuple, int] = {}
    grupos_con_fila: set[tuple] = set()
    ordenes_dias_sin_leer: list[str] = []
    if contar_deposito:
        pubs_activas = list(getattr(resultado_conciliacion, "publicaciones_activas", []) or [])
        if not pubs_activas:     # conciliación guardada antes de este cambio: se leen las publicaciones activas (solo lectura)
            for cuenta in cuentas:
                pubs_activas.extend(extraer_publicaciones_activas(ml.detalle_items(ml.items_activos(cuenta), cuenta), cuenta))
        pagado: dict[tuple, int] = {}
        for idx_cuenta, cuenta in enumerate(cuentas):
            if progreso_cb:
                progreso_cb(idx_cuenta, len(cuentas), f"Consultando ventas de mi depósito ({cuenta})")
            acum, fallidos = ml.ventas_pagadas_por_item(cuenta, desde, hasta)
            for (item_id, var), cant in acum.items():
                pagado[(cuenta, item_id, var)] = cant
            ordenes_dias_sin_leer += [f"{cuenta} {d}" for d in fallidos]
        for pub in pubs_activas:
            k = (pub["cuenta"], pub["item_id"], str(pub["variation_id"]) if pub.get("variation_id") else None)
            cant = pagado.get(k, 0)
            if not pub.get("variation_id"):
                cant = pagado.get((pub["cuenta"], pub["item_id"], None), 0)
            total_pagado_grupo[_grupo_pub(pub)] = total_pagado_grupo.get(_grupo_pub(pub), 0) + cant
        grupos_con_fila = {_grupo_pub(pub) for fila in resultado_conciliacion.filas for pub in fila.publicaciones}

    inventarios_sin_leer = {inv for lote in getattr(ml, "lotes_fallidos", []) for inv in lote["inventory_ids"]}
    filas: list[FilaReposicionMLA] = []
    total_skus = len(resultado_conciliacion.filas)
    for idx_sku, fila_sku in enumerate(resultado_conciliacion.filas):
        if progreso_cb:
            progreso_cb(idx_sku, total_skus, "Consultando stock Ecom/Táctica por SKU")
        stock_ecom, stock_tactica, flags_stock, avisos_stock = _stocks(ecom, tactica, fila_sku.sku, fila_sku.parent_sku)
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
            # Mi depósito (normal y Flex): lo pagado de la publicación menos lo que salió de Full (que ya es parte de lo pagado: no se cuenta dos veces). Esa parte
            # no se censura (mi depósito no se queda sin stock de Full) y se reparte parejo en el período. Apagado, vale 0 y el resultado es el de siempre.
            ventas_deposito = 0
            if contar_deposito:
                venta_full_pub = venta_inv["unidades"] if venta_inv else 0
                ventas_deposito = max(0, total_pagado_grupo.get(_grupo_pub(pub), 0) - venta_full_pub) * pub["factor"]
                ventas_diarias += ventas_deposito / dias_ventas

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

            envio_pend = envios_pendientes_por_inventory.get(pub["inventory_id"]) if pub.get("inventory_id") else None

            filas.append(FilaReposicionMLA(
                item_id=pub["item_id"], inventory_id=pub["inventory_id"], cuenta=pub["cuenta"],
                sku=fila_sku.sku, sku_ml=pub.get("sku_ml"), titulo=pub.get("titulo", ""),
                stock_full=stock_full_mla, ventas_periodo=ventas_total + ventas_deposito, dias_periodo=dias_ventas,
                primera_venta=primera, ultima_venta=ultima, censurado=censurado,
                ventas_diarias=round(ventas_diarias, 2), stock_objetivo=round(stock_objetivo, 1),
                stock_a_llegada=round(stock_a_llegada, 1), factor=pub["factor"],
                cantidad_enviar=cantidad_enviar, sugerido=0,
                stock_ecom=stock_ecom, stock_tactica=stock_tactica,
                envio_pendiente=envio_pend["unidades"] if envio_pend else 0,
                envio_pendiente_ids=envio_pend["inbound_ids"] if envio_pend else [],
                datos_incompletos=bool(pub.get("inventory_id") in inventarios_sin_leer),
                ventas_full=ventas_total, ventas_deposito=ventas_deposito,
                flags=flags_stock + (["sin_vincular"] if not pub.get("vinculado", True) else []), avisos=list(avisos_stock),
            ))

    if contar_deposito:
        filas.extend(_filas_solo_deposito(ml, ecom, tactica, resultado_conciliacion, pubs_activas, total_pagado_grupo, grupos_con_fila, dias_ventas, semanas_objetivo,
                                          dias_hasta_llegada, progreso_cb))
        if ordenes_dias_sin_leer:
            for f in filas:
                f.avisos.append(f"Ventas de mi depósito incompletas: no se pudieron leer {len(ordenes_dias_sin_leer)} día(s) de órdenes.")

    if progreso_cb and total_skus:
        progreso_cb(total_skus, total_skus, "Consultando stock Ecom/Táctica por SKU")

    _repartir_sugerido(filas)
    _convertir_a_paquetes(filas)

    return ResultadoReposicionMLA(
        periodo={"desde": desde, "hasta": hasta, "dias": dias_ventas}, ordenes_dias_sin_leer=ordenes_dias_sin_leer,
        filas=filas, incidencias_sku=resultado_conciliacion.incidencias_sku,
        incidencias_sin_vincular=resultado_conciliacion.incidencias_sin_vincular,
        skus_no_en_ecom=resultado_conciliacion.skus_no_en_ecom,
        skus_incompletos=sorted(set(getattr(resultado_conciliacion, "skus_incompletos", [])) | {f.sku for f in filas if f.datos_incompletos}),
    )


# ── Job en background — mismo patrón que ml_full.py (jobs propios, no
# compartidos con main.py ni con ml_full.py). ──

_jobs: dict[str, dict] = {}


def iniciar_job(
    job_id: str, ecom_email: str | None = None, ecom_password: str | None = None,
    dias_ventas: int = 30, semanas_objetivo: float = 3, fecha_llegada: date | None = None,
) -> None:
    from rentabilidad.ingesta_ecom_api import EcomApiClient

    _jobs[job_id] = {"status": "running", "log": ["Iniciando simulación de reposición..."], "result": None, "progress": None}
    try:
        ml = MLFullClient()
        ecom = EcomFullAdapter(EcomApiClient(email=ecom_email, password=ecom_password))
        tactica = TacticaStockSheetAdapter()

        def _progreso(actual, total, fase):
            _jobs[job_id]["progress"] = {"current": actual, "total": total, "label": fase}

        resultado = calcular_reposicion_mla(
            ml, ecom, tactica, dias_ventas=dias_ventas, semanas_objetivo=semanas_objetivo,
            fecha_llegada=fecha_llegada, progreso_cb=_progreso,
        )
        _jobs[job_id]["progress"] = None
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


# ── PDF de "Instrucciones de preparación" de un envío Full en preparación
# -- pedido de Maxx 2026-09-08: `envio_pendiente` (ver `ml_full.
# envios_pendientes_por_inventory`) solo ve unidades ya RECIBIDAS en el
# depósito (`INBOUND_RECEPTION`); un envío todavía "en preparación" no generó
# ningún evento de recepción todavía, así que es invisible para esa consulta
# aunque Maxx ya lo esté armando -- sin esto, `cantidad_enviar` duplica lo
# que ya va en camino. No hay API pública para esto (la pantalla real del
# envío vive en `vendedores.mercadolibre.com.ar`, autenticada por cookie de
# sesión, no por Bearer OAuth -- confirmado en vivo 2026-09-08, se descartó
# automatizarla por el mismo riesgo de cuenta flagueada que ya se vio con
# ml_vendedor.py ese mismo día). El PDF "Instrucciones de preparación" que
# ML deja descargar por envío es la única fuente sin ese riesgo. ──

def parsear_pdf_envio_pendiente(contenido: bytes) -> dict:
    """Extrae `{inventory_id: unidades}` del PDF de instrucciones de
    preparación de un envío Full ("Código ML: X ... SKU: Y ... título" por
    producto, seguido de la tabla Unidades/Identificación/Instrucciones).

    El extractor de texto de PyMuPDF separa las columnas de la tabla en dos
    bloques (todo el texto de la columna "Producto" primero, después un
    bloque plano con los números de la columna "Unidades") en vez de
    devolver fila por fila -- confirmado leyendo el PDF real de un envío
    (#75982428, 53 productos): emparejar el bloque de producto N-ésimo con
    el número N-ésimo del bloque de unidades (mismo orden de aparición,
    ambos de arriba hacia abajo) reprodujo el total real del encabezado
    ("Total de unidades: 2035") exacto -- no es una suposición, se verificó
    contra el numero declarado por ML en el propio documento.

    Devuelve por `inventory_id` (el "Código ML", clave real que usa
    `FilaReposicionMLA.inventory_id` -- el SKU no alcanza porque un mismo
    SKU puede repetirse en varios `inventory_id`, ver AYALA_CORE.md)."""
    import re
    import fitz

    doc = fitz.open(stream=contenido, filetype="pdf")
    pendientes: dict[str, int] = {}
    marcador = "INSTRUCCIONES DE PREPARACI"
    for pagina in doc:
        texto = pagina.get_text()
        idx = texto.find(marcador)
        if idx == -1:
            continue
        antes, despues = texto[:idx], texto[idx + len(marcador):]
        bloques = [b for b in re.split(r"(?=C.digo ML:)", antes) if "SKU" in b]
        unidades = [int(n.strip()) for n in despues.split("\n") if n.strip().isdigit()]
        for bloque, cantidad in zip(bloques, unidades):
            m = re.search(r"C.digo ML:\s*(\S+)", bloque)
            if m:
                pendientes[m.group(1)] = pendientes.get(m.group(1), 0) + cantidad
    return pendientes
