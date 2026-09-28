# RENTABILIDAD_IMPLEMENTACION.md

## Diseño Técnico — Módulo de Rentabilidad · ERP Ayala

**Versión 2.0** · 29/07/2026
**Documento subordinado a:** `RENTABILIDAD_FUNCIONAL.md` v2.0

---

## 0. Relación entre los dos documentos

| | `RENTABILIDAD_FUNCIONAL.md` | Este documento |
|---|---|---|
| Contiene | Reglas de negocio, fórmulas, regímenes, validaciones, casos de aceptación | Modelo de datos, nombres de clase, adaptadores, estrategia de persistencia |
| Autoridad | **Normativo.** Ninguna regla se cambia sin decisión funcional | Orientativo. Se puede reorganizar libremente |
| Ante conflicto | **Gana el funcional, siempre** | Cede |

**Regla:** si un desarrollador encuentra que este documento le impide reproducir un número del funcional, **este documento está mal**. Se cambia este, no el otro.

Todo contenido técnico —modelo de datos, adaptadores, servicios, calculadores, validadores, estrategia de persistencia, arquitectura y orden de implementación— vive exclusivamente en este documento. El funcional no contiene ninguna decisión técnica, ningún nombre de clase y ninguna recomendación opcional.

---

## 1. Modelo de datos

### 1.1 Tablas de hechos

Dos tablas separadas. **No unificar esquemas.**

- `venta_tactica` — todas las columnas de `RENTABILIDAD_FUNCIONAL.md` §6.4
- `venta_ecom` — todas las columnas de `RENTABILIDAD_FUNCIONAL.md` §7.4

Incluir **también** las columnas informativas y las que hoy están rotas (ECOM `AT`, TACTICA `R` y `X`), marcadas por origen:

```
origen_columna: DATO | CALCULADO | INFORMATIVO | ROTO
```

Motivo: si no están, no se puede demostrar paridad con el Excel columna por columna.

### 1.2 Campos de control transversales

| Campo | Tipo | Regla |
|---|---|---|
| `periodo` | string | Reemplaza la duplicación de estructura por hojas mensuales. Las hojas actuales tienen nombres con solape (`Junio - Julio`, `Julio - Agosto`); en el ERP es un campo, no una tabla nueva. No altera el cálculo por línea. |
| `tc` | decimal | **Obligatorio e inmutable.** Se toma del día de la operación **al momento de la carga**, no al momento del cálculo. Ningún proceso posterior lo modifica. |
| `excluido` | bool | Exclusión **lógica**, nunca borrado físico |
| `motivo_exclusion` | enum | `NOTA_DEBITO` · `FIXTURE` · `ENVIO` · `SKU_AUXILIAR` · `MANUAL` |
| `regimen` | enum | `CUENTA_1` · `CUENTA_2` · `PERDIDA_DEFINITIVA` · `EXCLUIDO` · `NO_DETERMINADO` (MLA, pendiente P-01) · `NO_RECONOCIDO` |

Las filas excluidas **se conservan, se muestran y no se suman**. Todo total del ERP debe poder desglosarse en *incluido / excluido* para que la conciliación con el Excel sea demostrable.

### 1.3 Tablas paramétricas

| Tabla | Contenido | Valor inicial |
|---|---|---|
| `parametro_tasa` | Tasas de §5.3 del funcional | imp. cheque 1,2 % · IIBB 5 % · CF1 y CF2 3 % · AGIN 0,90 % y 0,40 % |
| `prefijo_perdida_definitiva` | Prefijos de comprobante | exactamente `{00007, 05007}` |
| `regimen_comprobante` | Mapeo comprobante → régimen | tabla de §6.1 del funcional |
| `sku_excluido` | Fixture, envíos, SKU auxiliares | **vacía** — pendiente P-05 del funcional |
| `sku_auxiliar` | SKU promocionales (`PROMOS-*`) para trazabilidad | `PROMOS-*`. **No cambia el cálculo** |

**Ninguna tasa, prefijo ni régimen en código.** Todo en tabla.

### 1.4 Precisión numérica

Usar decimal de precisión fija (`NUMERIC`/`Decimal`), **nunca float**, para importes. El criterio de aceptación es 0,01 y con float binario se pierden centavos en las cadenas de multiplicación de §6.2 del funcional.

Redondeo únicamente en presentación y comparación.

---

## 2. Capa de adaptadores de solo lectura

Hoy las fórmulas del libro dependen de `IMPORTRANGE` contra archivos externos. El ERP los reemplaza por adaptadores, **replicando el comportamiento de fallback y de error de la fórmula original**, incluidos los valores por defecto textuales — esos textos se usan hoy como banderas operativas y son parte del contrato funcional.

### 2.1 Dependencias actuales a reemplazar

| Origen actual | Contenido consumido | Consumido por |
|---|---|---|
| `1xtD_C07…` hoja `Global` | Costo de lista USD (col. S con fallback a col. R), stock, ventas 30 días | Costo, stock |
| `1xtD_C07…` hoja `Importacion Tactica` | Régimen de IVA por SKU | Factor IVA |
| `1pog-ebeT…` hoja `GRAL CATEGORIAS` (rangos `A` y `U`) | PM, categoría, subcategoría por SKU | Clasificación |
| `1tncawBu…` hoja `BASE GENERAL` | Responsable comercial por empresa/cliente | Clasificación |
| `1sePUSUO…` (Verónica), `1aCQx9iQ…` (Matías), `1JrasTbb…` (Cristian) | Márgenes objetivo L3 / L4 / L5 usd SIN IVA | Comparativo |
| `1o2tWmPW…` hoja `Master Compras ML 21%` | Margen / Ganancia actual (rentabilidad esperada por PM) | Comparativo |
| `1mWwT2jw…` hoja `hOJA 1` | Vinculación de órdenes ECOM (default `OK`) | Control |

### 2.2 Adaptadores

| Adaptador | Método | Comportamiento obligatorio |
|---|---|---|
| `CostoVigenteProvider` | `obtener(sku) → Decimal \| None` | Cascada exacta de §5.6 del funcional, **incluido el tratamiento del 0 como "sin costo"**. Si no resuelve, devuelve `None` → incidencia bloqueante. **Prohibido devolver 0 por defecto.** |
| `IvaProvider` | `factor(sku) → Decimal \| None` | Comparación de cadena **exacta y sensible a mayúsculas** (`IGUAL`), sin normalizar. Devuelve `None` ante cualquier valor no reconocido |
| `ClasificacionProvider` | `pm_y_subcategoria(sku) → tupla` | Cascada de 3 intentos de §8.1 del funcional: SKU completo, después primer SKU de la lista, después rango alternativo. Default `"SIN PM"` |
| `ResponsableProvider` | `obtener(empresa) → str \| None` | Búsquedas anidadas de respaldo. Sin default: la ausencia es significativa (afecta el bloque AGIN) |
| `MargenObjetivoProvider` | `l3_l4_l5(sku)` · `rentabilidad_real(sku)` | **Resolución por título de columna, no por índice.** Cascada por PM en orden exacto: Verónica → Matías → Cristian. Default `"NO ENCUENTRO SKU"` |
| `VinculacionProvider` | `estado(nro_orden) → str` | Default **`"OK"`**. No invertir |
| `StockProvider` | `stock(sku)` · `ventas_30d(sku)` | Lookups en `Global` |

Todos de **solo lectura**. Ninguno escribe en los orígenes.

---

## 3. Calculadores

Dos clases separadas. **No unificar, no extraer una clase base que comparta fórmulas.**

```
RentabilidadTacticaCalculator
    resolver_regimen(comprobante, nro_comprobante) → Regimen
    calcular(linea) → ResultadoTactica
        # orden estricto de RENTABILIDAD_FUNCIONAL.md §6.2
        # S antes de T y de Y · Y antes de Z · Z antes de AA

RentabilidadEcomCalculator
    calcular(orden) → ResultadoEcom
        # orden estricto de RENTABILIDAD_FUNCIONAL.md §7.1
```

### 3.1 Convención de signos en el código

No "normalizar" signos por prolijidad. TACTICA almacena descuentos en negativo y **suma**; ECOM almacena imp. cheque e IIBB en positivo y **resta**. Cambiar esto rompe `SUM(Costo Total Pesos)`, que hoy es negativo en el reporte y debe seguir siéndolo.

### 3.2 Suma de AA con nulos

```
AA = P + coalesce(T,0) + coalesce(U,0) + coalesce(W,0) + coalesce(Y,0) + coalesce(Z,0)
```

Vacío y `0` son distintos en almacenamiento (§5.8 del funcional) pero equivalentes en la suma y en la condición disparadora de `Z`.

### 3.3 Disparador de Z

El funcional §6.2 paso 6 especifica `Z` por régimen. La fórmula del libro lo resuelve mediante la condición `Y <> 0`, tratando celda vacía y cero como equivalentes.

Ambas producen el mismo resultado en todo el período relevado. La implementación sigue el funcional (por régimen) salvo que la verificación V-03 del funcional §16 demuestre un caso real que se comporte distinto, en cuyo caso se implementa el comportamiento observado.

---

## 4. Auditoría del costo vigente

El costo **no se persiste como snapshot en la línea de venta a los fines del cálculo**: se resuelve en el momento del cálculo (§5.6 del funcional).

Para poder explicar por qué un período recalculado cambió, registrar en tabla de auditoría:

```
auditoria_costo(linea_id, sku, costo_usd_usado, columna_origen, leido_en, calculo_id)
```

Esta auditoría es **adicional y no interviene en el resultado**. Es la única forma de responder "por qué la rentabilidad de junio cambió si no toqué nada".

---

## 5. Validador

```
ValidadorRentabilidad
    validar(periodo, momento: ANTES | DESPUES) → [Incidencia]

Incidencia(codigo, severidad, linea_id, regla_violada, valores_observados)
```

Ejecutable **antes y después** del cálculo. Los 16 controles de §12 del funcional.

**Ningún control corrige un dato de forma silenciosa.** Un control que "arregla" es un bug.

Tablero de incidencias por período, agrupado por severidad y por código.

---

## 6. Agregaciones

Vistas materializadas o consultas de agregación con las medidas exactas de §11 del funcional, con desglose por: **canal · PM · subcategoría · responsable · período · semana**.

Requisitos:

- Cada total debe ser **trazable a las líneas que lo componen**.
- Todo total debe poder desglosarse en *incluido / excluido*.
- El porcentaje se calcula sobre totales agregados, **nunca como promedio de porcentajes de línea**.
- Las tasas AGIN salen de `parametro_tasa`.
- El bloque AGIN reproduce la exclusión de líneas sin responsable, **incluida la descuadratura resultante**.

Los reportes personales (`Reporte Matias`, `Reporte Cris`, `Reporte Lau`) son **filtros sobre estas vistas**, sin reglas propias.

---

## 7. Suite de regresión

Los casos de §13 del funcional se implementan como test de aceptación automatizado.

| Grupo | Casos | Estado |
|---|---|---|
| TACTICA | T-1 … T-8 | Implementables |
| TACTICA | T-9 | Pendiente de la verificación V-02 del funcional §16 |
| ECOM | E-1, E-2 | Implementables |
| ECOM | E-3 | Implementable. Las entradas `O` y `AM` se asumieron en `0` y `1500`: confirmar |
| ECOM | E-4 | Pendiente de la verificación V-02 |
| Totales de período | — | Pendientes de la verificación V-02. V-15 se habilita al obtenerlos |

Configuración del test: tolerancia `0,01`, cero diferencias de signo, sin redondeos intermedios, comparación por columna y no solo por resultado final.

**Un test que pasa comparando solo `AA` no sirve:** hay que comparar `S`, `T`, `U`, `W`, `Y`, `Z` individualmente, porque dos errores compensados producen el `AA` correcto con columnas incorrectas.

---

## 8. Datos personales

La hoja `Ordenes` (export crudo de marketplace) **incluye datos personales del comprador** y es fuente de conciliación, no de cálculo.

El módulo de Rentabilidad **no necesita ningún dato personal**. No importar nombre, dirección, documento ni contacto del comprador a las tablas de hechos. Si se necesita conciliar por orden, alcanza el número de orden.

---

## 9. Orden de implementación sugerido

| Paso | Contenido | Depende de |
|---|---|---|
| 1 | Tablas de hechos y paramétricas (§1) | — |
| 2 | Adaptadores de solo lectura (§2) | 1 |
| 3 | `resolver_regimen` + tabla de regímenes (§6.1 del funcional) | 1 |
| 4 | `RentabilidadTacticaCalculator` | 2, 3 |
| 5 | Suite de regresión TACTICA (T-1 … T-8) | 4 |
| 6 | `RentabilidadEcomCalculator` | 2 |
| 7 | Suite de regresión ECOM (E-1 … E-3) | 6 |
| 8 | Exclusión lógica y validador (§5) | 4, 6 |
| 9 | Agregaciones (§6) | 8 |
| 10 | Auditoría de costo (§4) | 4, 6 |

El paso 5 es la primera puerta real: **si T-1 a T-8 no pasan al centavo, no se avanza al motor ECOM.**

---

## 10. Prohibiciones técnicas

1. Hardcodear una tasa, un prefijo, un régimen o un mapeo de comprobante.
2. Usar `float` para importes.
3. Devolver 0 cuando un proveedor no resuelve un costo.
4. Recalcular `Q` a partir de `U` en ECOM.
5. Calcular o reconstruir alícuotas de IVA.
6. Normalizar mayúsculas al comparar el régimen textual de IVA.
7. Unificar los dos calculadores o extraer fórmulas compartidas.
8. Normalizar las convenciones de signo entre motores.
9. Modificar el `tc` de una línea existente.
10. Persistir el costo como snapshot **a los fines del cálculo** (la auditoría es aparte).
11. Borrar físicamente una fila excluida.
12. Filtrar por estado de venta, o por estado de pago entre `Cobrado`/`Cobro
    Parcial` (se calculan igual). **No aplica** a `Reembolsado`/`Sin
    cobro`/`En mediación` (u otro estado equivalente): esos sí se excluyen
    — corrección v2.1 de `RENTABILIDAD_FUNCIONAL.md` §10, 31/07/2026.
13. Corregir un dato dentro de un control de validación.
14. Implementar lógica basada en colores o formato de celda.
15. Importar datos personales del comprador.

---

## 11. Ingesta ECOM por API — reglas aprobadas (Maxx, 2026-09-27)

Fuente operativa de ECOM: la API GraphQL de EcomExperts
(`ingesta_ecom_api.py`), no el Excel. Validado el 01/06/2026 contra la
planilla terminada de Maxx (pestaña "16"): mismas 560 órdenes, facturación
idéntica al centavo ($28.782.141,66) y rentabilidad explicada orden por
orden.

| Regla | Implementación |
|---|---|
| Órdenes | Abiertas + cerradas (tabs `active` + `closed`; nunca presupuestos ni eliminadas), siempre por **fecha de creación** (`MtOrder.created`, hora Argentina). El filtro es el estado de pago: participan `Cobrado`/`Cobro Parcial`; `Sin Cobro` (Uso Interno), `Reembolsado`, `En Mediación` se excluyen (Maxx, 2026-09-28). NC / devoluciones: siguen neteando vía Posventa. |
| Costo | `Variant.cost` × cantidad — costo **vigente al correr** (la API no guarda costo histórico por orden). Costo 0 = incidencia (casi siempre SKU madre): no se calcula ni se inventa, se lista para revisar. |
| Precio SIN IVA | Σ `subtotalSinImpuestos` por línea: IVA real de cada línea (21 / 10,5), no el 1,10 fijo del export de Ecom. |
| Comisión ML / Woocommerce | Cargos `fee` que MP le cobra al vendedor (`charges_details`, `from=collector`). En Woocommerce incluye el costo de cuotas que absorbe el vendedor; el `financing_fee` del comprador no cuenta. |
| Envío ML | Cargo `shipping` de MP − lo que pagó el comprador; sin cargo: 0 en Full, `listCost − cost` fuera de Full (coincide en las 527 órdenes ML del día). |
| Envío Woocommerce | 0: lo que paga el comprador no es ingreso ni costo; la mensajería se paga por mes. |
| Frávega | Comisión base estimada (`fravega_comision_base` = 15% × Precio Final, fee 0) hasta cargar la liquidación quincenal; al cargarla se reemplaza por comisión + fee logístico reales y se recalcula (`origen_comision`: `ESTIMADO_FRAVEGA` → `LIQUIDACION_FRAVEGA`). Cruce por el número de orden de Frávega que guarda Ecom (`ownerData.ownerId` sin `FVG-`). |
| Cancelada en Frávega, cobrada en Ecom | Suma como venta, tal como la trae Ecom (Maxx, 2026-09-28), con la comisión estimada y una `observacion` informativa (posible desync). Cuando se conecte la API de Frávega, las canceladas se descuentan en el cierre de mes con el detalle real. |
| OnCity | Canal manual en Ecom (`owner = "OnCity"`), sin dato de comisión: se descuenta una comisión estimada `oncity_comision_estimada` (15% × Precio Final, editable) — `origen_comision=ESTIMADO_ONCITY` (Maxx, 2026-09-29). |
| Posventa | Precio final y sin IVA en 0, se conserva el costo. |
| PM | Cascada de la fórmula real: SKUs completos en `A:D` → primer SKU en `A:D` → primer SKU en `U:V` (sin distinguir mayúsculas, como BUSCARV). |
| TC | Siempre el BNA del día (dólar billete, venta) al correr (Maxx, 2026-09-28); un solo TC para todo el período. Se guarda en el cierre (`cierre_rentabilidad.tc_ecom` + `tc_ecom_origen`) y sale al pie del resumen de la corrida y del informe, para verificarlo. |
| Costo por operación | `costo_operacion_ecom` ($149,12 por orden). |

**Liquidación de Frávega** (`liquidacion_fravega.py`, tabla
`liquidacion_fravega`): se sube el .xlsx de Seller Center
(`POST /rentabilidad/fravega/liquidacion`, o el botón "Cargar liquidación
Frávega" de la página de Rentabilidad). Antes de aplicar se verifica que
el detalle reconstruya los totales de la propia liquidación; si no cuadra,
no se aplica. Se guarda una fila por orden y por liquidación (una venta y
su devolución pueden caer en quincenas distintas; el valor de la orden es
la suma). `GET /rentabilidad/fravega/pendientes` lista las ventas que
siguen estimadas.

**Corrida diaria** (`cierre_ecom_diario.py`, CLI `backend/scripts/ecom_diario.py`):
recalcula el ciclo en curso (23 → 22) desde el día 23 hasta ayer y lo guarda
bajo la etiqueta del ciclo completo (`2026-09-23_2026-10-22`), reemplazando
lo anterior de ese ciclo: sin períodos solapados ni órdenes duplicadas. Corre
en proceso (un ciclo completo no entra en el timeout de un request HTTP).

**Programación en Railway**: servicio Cron aparte, del mismo repo, con
`backend/railway.cron.json` como config (`startCommand`
`./entrypoint.sh python scripts/ecom_diario.py`, `cronSchedule` `0 9 * * *`
= 06:00 ART) y las mismas variables que el backend. `entrypoint.sh` con
argumentos corre el comando en vez de uvicorn.

**ECOM no depende de Táctica** (Maxx, 2026-09-28): el factor de IVA de
"Facturación + IVA" sale del `taxTag` de la propia API de Ecom (coincide
con Táctica en 472/473 órdenes del 01/06/2026 y completa las que Táctica no
encontraba), así que el Cron no levanta el túnel de Tailscale salvo
`TS_EN_JOB=1`. El túnel es siempre opcional y acotado (`TS_UP_TIMEOUT`,
default 20s): si no levanta, se sigue sin él.

**Diagnóstico del Cron "colgado" (2026-09-28)**: sin túnel, cada orden
reintentaba la SQL de Táctica (5 intentos, ~30s de espera) porque el cache
solo guardaba los aciertos — horas sin un error. Ahora los caches de
Táctica y de Sheets recuerdan el error, todas las conexiones tienen timeout
(Ecom 10s/60s, Sheets 10s/60s, Postgres 10s de conexión y 60s de lock) y la
corrida tiene un tope total (`--max-minutos`, default 45). Cada paso deja
una línea con hora en stderr sin buffer (el `fileConfig` de Alembic apaga
los loggers, por eso antes no se veía nada después de las migraciones).

**Reporte diario para mail (n8n)** — `GET /rentabilidad/reporte/ecom/diario`
(`reporte_diario.py`), **solo lectura**: resume lo que la corrida ya guardó
para el ciclo en curso, sin recalcular. Parámetros: `fecha` (default ayer,
hora Argentina), `top` (default 5). Si está `RENT_REPORTE_TOKEN`, exige el
header `X-Reporte-Token` (o `?token=`). Devuelve ayer / acumulado del ciclo,
por PM (con sus 2 SKU que más facturaron), top y pérdidas del día, alertas
(costo 0 / sin SKU, Frávega estimadas, observaciones, TC usado) y el bloque
Full + marketplaces (Frávega, OnCity, Megatone). Facturación = Precio Final
con IVA; rentabilidad % sobre facturación sin IVA; SKU = los de la orden (un
kit cuenta como su combinación, no se guarda el importe por línea). Full se
lee de `venta_ecom.es_full` (migración `d4e5f6a7b8c9`, lo completa la
corrida desde 2026-09-29).

**Pendiente conocido — notas de crédito y cancelaciones**: hoy una nota de
crédito entra en Ecom como Posventa (precio 0, conserva el costo) para
netear la venta original. Cuando se conecten los canales directos (API de
Frávega, ML, etc.), la cancelación / NC se va a manejar con el dato real de
cada canal — no cambiar la regla de Posventa antes de eso.

---

*Fin del diseño técnico.*
