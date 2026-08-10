"""Orquestación de un período: fuente ya traducida por su adaptador
(`FilaTactica`/`FilaEcom`) -> motor ya probado -> lookups de clasificación ->
`VentaTactica`/`VentaEcom` en memoria.

Ni `calculators.py` ni `adapters.py` se tocan, esto solo los orquesta.

**Dos modos, deliberadamente separados** (ajuste de arquitectura pedido por
Maxx, 2026-08-10 — "no quiero que cada consulta quede guardada"):

- `construir_filas_*()` — el motor corre, devuelve objetos `VentaTactica`/
  `VentaEcom` en memoria, **nunca se agregan a la sesión ni se comitean**.
  Es lo que usa la consulta en vivo: se muestra y se descarta.
- `guardar_cierre_*()` — llama a `construir_filas_*()` y además reemplaza
  el período en la base (`db.add` de cada fila + borrado de las anteriores
  de ese período). Es lo único que persiste, y solo corre cuando el
  usuario hace clic en "Guardar cierre" — nunca como efecto secundario de
  una consulta.

**"Guardar cierre" recarga el período entero, no hace upsert.** Los modelos
no tienen UniqueConstraint por comprobante/orden a propósito (duplicados son
INFORMATIVO — control V-16, no un error de esquema). Sin clave natural para
upsert, volver a guardar el mismo cierre borra sus filas anteriores y
vuelve a insertar — decisión técnica: no cambia ningún número, solo qué pasa
si guardás el mismo cierre dos veces.

Clasificación resuelta para TODAS las filas, incluidas las de régimen sin
cálculo (`LINEAS_SIN_CALCULO`) — PM/subcategoría/responsable son lookups por
SKU/empresa independientes del régimen, y el control V-13 ("línea sin PM")
necesita que se hayan intentado igual.

GAP señalado a Maxx, no resuelto acá: `MotivoExclusion` no tiene un valor
para "excluido por estado de pago" (Reembolsado/Sin cobro/Mediación) — se
usa `MANUAL` como placeholder hasta que confirme si agrega un valor dedicado
(requeriría una migración de Alembic chica)."""
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from .adapters import (
    ClasificacionProvider,
    CostoVigenteProvider,
    IvaProvider,
    MargenObjetivoProvider,
    ResponsableProvider,
    StockProvider,
    VinculacionProvider,
)
from .calculators import (
    LineaEcomInput,
    LineaTacticaInput,
    RentabilidadEcomCalculator,
    RentabilidadTacticaCalculator,
    ResultadoEcom,
    ResultadoTactica,
    calcular_facturacion_iva,
    resolver_ao_orden,
)
from .config import ConfiguracionFaltante
from .ingesta_ecom import FilaEcom, ResultadoIngestaEcom
from .ingesta_tactica import FilaTactica
from .models import CierreRentabilidad, MotivoExclusion, SkuExcluido, VentaEcom, VentaTactica


def _primer_sku(skus_vendidos: str) -> str:
    """Mismo criterio que `resolver_ao_orden`/§8.1 paso 3: una orden ECOM
    puede traer varios SKU separados por coma, se usa el primero."""
    return skus_vendidos.split(",")[0].strip()


def _opcional(fn, default):
    """Corre un lookup de clasificación (informativo — PM, subcategoría,
    responsable, márgenes objetivo, stock, vinculación...) y si su fuente no
    está configurada, degrada a `default` en vez de abortar la fila entera.
    Solo el cálculo del motor (costo/IVA, mandatorio) debe poder frenar una
    fila — el resto es INFORMATIVO/CALCULADO-clasificación, no el resultado."""
    try:
        return fn()
    except ConfiguracionFaltante:
        return default


def _exclusion_por_sku(db: Session, sku: str) -> tuple[bool, MotivoExclusion | None]:
    """`sku_excluido` (§1.3 RENTABILIDAD_IMPLEMENTACION.md) está vacía por
    defecto (P-05 pendiente del funcional) — esta consulta no tiene ningún
    efecto hasta que Maxx la complete; no es una regla nueva, es el
    mecanismo ya previsto para esa tabla."""
    fila = db.get(SkuExcluido, sku)
    if fila is not None and fila.activo:
        return True, fila.motivo
    return False, None


# ── TACTICA ──

def construir_venta_tactica(
    fila: FilaTactica,
    resultado: ResultadoTactica,
    periodo: str,
    pm: str | None,
    subcategoria: str | None,
    responsable: str | None,
    margen_l3: Decimal | None,
    margen_l4: Decimal | None,
    margen_l5: Decimal | None,
    excluido: bool = False,
    motivo_exclusion: MotivoExclusion | None = None,
) -> VentaTactica:
    """Une lo que trae el adaptador SQL (`fila`, columnas DATO) con lo que
    resuelve el motor (`resultado`, columnas CALCULADO) y la clasificación
    (columnas F). Las columnas INFORMATIVO/ROTO que ningún adaptador
    relevado resuelve (K, M, R, X, Familia, SKU Margen Negativo) quedan en
    `None` — no se inventan (mismo criterio que el resto de `rentabilidad/`)."""
    return VentaTactica(
        periodo=periodo,
        excluido=excluido,
        motivo_exclusion=motivo_exclusion,
        regimen=resultado.regimen,
        fecha=fila.fecha,
        empresa=fila.empresa or "",
        codigo=fila.codigo,
        descripcion=fila.descripcion,
        fabricante=fila.fabricante,
        tipo_producto=fila.tipo_producto,
        familia=None,
        vendedor=fila.vendedor,
        tipo_factura=fila.tipo_factura,
        nro_factura=fila.nro_factura,
        precio_compra_lista=None,
        costo_lista=resultado.costo_lista,
        precio_venta_lista=None,
        cantidad=fila.cantidad,
        costo_total_dolares=resultado.costo_total_dolares,
        precio_venta=fila.precio_venta,
        iva_producto=resultado.iva_producto,
        margen_informado=None,
        iva=resultado.iva,
        imp_cheque=resultado.imp_cheque,
        iibb=resultado.iibb,
        tc=fila.tc,
        costo_total_pesos=resultado.costo_total_pesos,
        margen_x=None,
        costo_financiero_1=resultado.costo_financiero_1,
        costo_financiero_2=resultado.costo_financiero_2,
        margen_real=resultado.margen_real,
        margen_pct=resultado.margen_pct,
        sku_margen_negativo=None,
        pm=pm,
        canal_tactica="Canal Tactica",
        subcategoria=subcategoria,
        precio_venta_iva=resultado.precio_venta_iva,
        responsable=responsable,
        margen_l3=margen_l3,
        margen_l4=margen_l4,
        margen_l5=margen_l5,
    )


@dataclass
class ResultadoPersistenciaTactica:
    filas: list[VentaTactica] = field(default_factory=list)
    config_faltante: list[str] = field(default_factory=list)  # nro_factura de líneas que no se pudieron clasificar/calcular por config


def construir_filas_tactica(
    db: Session,
    filas: list[FilaTactica],
    costo_provider: CostoVigenteProvider,
    iva_provider: IvaProvider,
    clasificacion_provider: ClasificacionProvider,
    responsable_provider: ResponsableProvider,
    margen_provider: MargenObjetivoProvider,
) -> ResultadoPersistenciaTactica:
    """Corre el motor + clasificación sobre cada `FilaTactica` y devuelve
    objetos `VentaTactica` **en memoria** — no los agrega a la sesión ni
    escribe nada (`db` solo se usa para leer `parametro_tasa` y
    `sku_excluido`). Es la función que usa tanto la consulta en vivo
    (se descartan) como `guardar_cierre_tactica` (se persisten, abajo)."""
    calculador = RentabilidadTacticaCalculator(db, costo_provider, iva_provider)
    resultado = ResultadoPersistenciaTactica()

    for fila in filas:
        try:
            r = calculador.calcular(fila.a_linea_input())
        except ConfiguracionFaltante:
            resultado.config_faltante.append(fila.nro_factura)
            continue

        pm, subcategoria = _opcional(lambda: clasificacion_provider.pm_y_subcategoria(fila.codigo), (None, None))
        responsable = _opcional(lambda: responsable_provider.obtener(fila.empresa), None) if fila.empresa else None
        l3, l4, l5 = _opcional(lambda: margen_provider.l3_l4_l5(fila.codigo), (None, None, None))
        excluido, motivo = _exclusion_por_sku(db, fila.codigo)

        venta = construir_venta_tactica(
            fila, r, "", pm, subcategoria, responsable, l3, l4, l5,
            excluido=excluido, motivo_exclusion=motivo,
        )
        resultado.filas.append(venta)

    return resultado


def guardar_cierre_tactica(
    db: Session,
    periodo: str,
    filas: list[FilaTactica],
    costo_provider: CostoVigenteProvider,
    iva_provider: IvaProvider,
    clasificacion_provider: ClasificacionProvider,
    responsable_provider: ResponsableProvider,
    margen_provider: MargenObjetivoProvider,
) -> ResultadoPersistenciaTactica:
    """**Única función que escribe `venta_tactica`.** Construye igual que
    `construir_filas_tactica` y reemplaza el período completo (ver docstring
    del módulo). No hace commit — eso lo decide quien tiene la sesión."""
    resultado = construir_filas_tactica(
        db, filas, costo_provider, iva_provider,
        clasificacion_provider, responsable_provider, margen_provider,
    )
    db.query(VentaTactica).filter(VentaTactica.periodo == periodo).delete(synchronize_session=False)
    for venta in resultado.filas:
        venta.periodo = periodo
        db.add(venta)
    return resultado


# ── ECOM ──

def construir_venta_ecom(
    fila: FilaEcom,
    resultado: ResultadoEcom | None,
    periodo: str,
    pm: str | None,
    subcategoria: str | None,
    vinculacion: str,
    ao: Decimal | None,
    facturacion_iva: Decimal | None,
    stock: Decimal | None,
    ventas_30d: Decimal | None,
    dias_de_stock: str | None,
    rentabilidad_real,
    excluido: bool,
    motivo_exclusion: MotivoExclusion | None,
) -> VentaEcom:
    """`resultado` es `None` para las líneas que el adaptador ya separó como
    `incidencias_costo` (costo no resuelto) — el motor nunca corrió sobre
    ellas (mismo criterio que `EcomExcelAdapter`, no se inventa un cálculo).
    Columnas INFORMATIVO pendientes P-02 (`iva_a_favor`, `cash`,
    `utilidad_venta`, `utilidad_costo`), `responsable_de_ventas` (vacío en
    el período vigente, según el propio modelo) y `precio_de_venta_roto`
    (ROTO, O-04) quedan en `None` — no hay adaptador que las resuelva."""
    rentabilidad_real_num = rentabilidad_real if isinstance(rentabilidad_real, Decimal) else None
    return VentaEcom(
        periodo=periodo,
        excluido=excluido,
        motivo_exclusion=motivo_exclusion,
        numero_orden=fila.numero_orden,
        skus_vendidos=fila.skus_vendidos,
        fecha_creacion_venta=None,
        estado_venta=None,
        fecha_pago=None,
        estado_pago=fila.estado_pago,
        costo_sin_iva=fila.costo_sin_iva,
        iva_a_favor=None,
        canal_de_venta=fila.canal_de_venta,
        usuario_integracion=None,
        medio_de_cobro=None,
        entrega_envio=None,
        comision_venta=fila.comision_venta,
        comision_cobro=Decimal(0),
        costo_envio=fila.costo_envio,
        impuestos_informados=None,
        precio_sin_iva=fila.precio_sin_iva,
        total_impuestos=None,
        imp_cheque=resultado.imp_cheque if resultado else None,
        iibb=resultado.iibb if resultado else None,
        precio_final=fila.precio_final,
        dif_iva=None,
        cash=None,
        utilidad_venta=None,
        utilidad_costo=None,
        neto=resultado.neto if resultado else None,
        costo_total=resultado.costo_total if resultado else None,
        rentabilidad=resultado.rentabilidad if resultado else None,
        pm=pm,
        subcategoria=subcategoria,
        rentabilidad_usd=resultado.rentabilidad_usd if resultado else None,
        facturacion_usd=resultado.facturacion_usd if resultado else None,
        responsable_de_ventas=None,
        categoria=None,
        subcategoria2=None,
        periodo_excel=None,
        semana=None,
        sku_negativo=None,
        tc=fila.tc,
        vinculacion=vinculacion,
        iva=ao,
        facturacion_iva=facturacion_iva,
        stock=stock,
        ventas_30_dias=ventas_30d,
        dias_de_stock=dias_de_stock,
        precio_de_venta_roto=None,
        rentabilidad_real=rentabilidad_real_num,
        pct_rentabilidad=resultado.pct_rentabilidad if resultado else None,
    )


@dataclass
class ResultadoPersistenciaEcom:
    filas: list[VentaEcom] = field(default_factory=list)
    config_faltante: list[str] = field(default_factory=list)


def _clasificar_fila_ecom(
    db: Session,
    fila: FilaEcom,
    iva_provider: IvaProvider,
    clasificacion_provider: ClasificacionProvider,
    vinculacion_provider: VinculacionProvider,
    stock_provider: StockProvider,
    margen_provider: MargenObjetivoProvider,
    excluido_por_estado: bool,
) -> VentaEcom:
    primer_sku = _primer_sku(fila.skus_vendidos)

    # Costo/IVA del motor son mandatorios (§7): si no resuelven, se propaga
    # ConfiguracionFaltante y `persistir_ecom` salta la fila entera. Todo lo
    # demás de acá abajo es clasificación/informativo — degrada a `None`.
    resultado = None if fila.incidencia else RentabilidadEcomCalculator(db).calcular(LineaEcomInput(
        numero_orden=fila.numero_orden, costo_sin_iva=fila.costo_sin_iva,
        comision_venta=fila.comision_venta, costo_envio=fila.costo_envio,
        precio_sin_iva=fila.precio_sin_iva, precio_final=fila.precio_final, tc=fila.tc,
    ))

    pm, subcategoria = _opcional(lambda: clasificacion_provider.pm_y_subcategoria(primer_sku), (None, None))
    vinculacion = _opcional(lambda: vinculacion_provider.estado(fila.numero_orden), "OK")
    ao = _opcional(lambda: resolver_ao_orden(iva_provider, fila.skus_vendidos), None)
    facturacion_iva = calcular_facturacion_iva(fila.precio_final, ao)
    stock = _opcional(lambda: stock_provider.stock(primer_sku), None)
    ventas_30d = _opcional(lambda: stock_provider.ventas_30d(primer_sku), None)
    dias_de_stock = _opcional(lambda: stock_provider.dias_de_stock(primer_sku), "Sin ventas")
    rentabilidad_real = _opcional(lambda: margen_provider.rentabilidad_real(primer_sku), None)
    excluido_sku, motivo_sku = _exclusion_por_sku(db, primer_sku)

    excluido = excluido_por_estado or excluido_sku
    motivo = MotivoExclusion.MANUAL if excluido_por_estado else motivo_sku

    return construir_venta_ecom(
        fila, resultado, "", pm, subcategoria, vinculacion, ao, facturacion_iva,
        stock, ventas_30d, dias_de_stock, rentabilidad_real, excluido, motivo,
    )


def construir_filas_ecom(
    db: Session,
    resultado_ingesta: ResultadoIngestaEcom,
    iva_provider: IvaProvider,
    clasificacion_provider: ClasificacionProvider,
    vinculacion_provider: VinculacionProvider,
    stock_provider: StockProvider,
    margen_provider: MargenObjetivoProvider,
) -> ResultadoPersistenciaEcom:
    """Igual que `construir_filas_tactica`: devuelve `VentaEcom` en memoria,
    sin agregarlas a la sesión. Cubre las tres listas que ya separa el
    adaptador (`lineas`, `excluidas_por_estado_pago`, `incidencias_costo`) —
    ninguna se descarta, todas se construyen con su `excluido` correspondiente."""
    resultado = ResultadoPersistenciaEcom()
    todas = (
        [(f, False) for f in resultado_ingesta.lineas]
        + [(f, True) for f in resultado_ingesta.excluidas_por_estado_pago]
        + [(f, False) for f in resultado_ingesta.incidencias_costo]
    )

    for fila, excluido_por_estado in todas:
        try:
            venta = _clasificar_fila_ecom(
                db, fila, iva_provider, clasificacion_provider,
                vinculacion_provider, stock_provider, margen_provider, excluido_por_estado,
            )
        except ConfiguracionFaltante:
            resultado.config_faltante.append(fila.numero_orden)
            continue
        resultado.filas.append(venta)

    return resultado


def guardar_cierre_ecom(
    db: Session,
    periodo: str,
    resultado_ingesta: ResultadoIngestaEcom,
    iva_provider: IvaProvider,
    clasificacion_provider: ClasificacionProvider,
    vinculacion_provider: VinculacionProvider,
    stock_provider: StockProvider,
    margen_provider: MargenObjetivoProvider,
) -> ResultadoPersistenciaEcom:
    """**Única función que escribe `venta_ecom`.** Construye igual que
    `construir_filas_ecom` y reemplaza el período completo, para que la
    conciliación con el Excel siga siendo demostrable."""
    resultado = construir_filas_ecom(
        db, resultado_ingesta, iva_provider, clasificacion_provider,
        vinculacion_provider, stock_provider, margen_provider,
    )
    db.query(VentaEcom).filter(VentaEcom.periodo == periodo).delete(synchronize_session=False)
    for venta in resultado.filas:
        venta.periodo = periodo
        db.add(venta)
    return resultado


# ── Metadata del cierre (§3 del ajuste de arquitectura, 2026-08-10) ──

def registrar_cierre(
    db: Session,
    periodo: str,
    desde: date,
    hasta: date,
    tactica_guardado: bool | None = None,
    ecom_guardado: bool | None = None,
    ecom_origen: str | None = None,
) -> CierreRentabilidad:
    """Upsert por `periodo`: Táctica y Ecom pueden guardarse en llamadas
    separadas (Ecom hoy vía Excel, API pendiente) sin perder lo ya
    registrado — por eso los flags son `None` = "no tocar" en vez de
    sobrescribir siempre a `False`. `generado_en` se actualiza en cada
    llamada: es "cuándo se guardó por última vez algo de este cierre", no
    la fecha del primer guardado."""
    cierre = db.get(CierreRentabilidad, periodo)
    if cierre is None:
        cierre = CierreRentabilidad(periodo=periodo, desde=desde, hasta=hasta)
        db.add(cierre)
    cierre.desde = desde
    cierre.hasta = hasta
    cierre.generado_en = datetime.now(UTC)
    if tactica_guardado is not None:
        cierre.tactica_guardado = tactica_guardado
    if ecom_guardado is not None:
        cierre.ecom_guardado = ecom_guardado
    if ecom_origen is not None:
        cierre.ecom_origen = ecom_origen
    return cierre
