# Ayala Core — Constitución del proyecto

> **Para Claude Code (y cualquier sesión futura):** este documento es la fuente de verdad de Ayala Core.
> Leelo COMPLETO al empezar cualquier sesión que toque este módulo, antes de escribir código.
> Tiene dos partes: **A) Constitución** (no cambia sin decisión explícita de Maxx) y
> **B) Estado de avance** (se actualiza al final de cada sesión).

---

# PARTE A — CONSTITUCIÓN (estable)

## A.0 Qué es y por qué existe
Ayala Core es el **módulo flagship** del ERP. Calcula el precio de venta correcto para SKUs de Maxx
usando su propio modelo de rentabilidad, y **lo escribe directo a Mercado Libre sin pasar por Ecom**.

Es el primer paso concreto de la visión de Maxx: **"dejar de depender de sistemas de terceros
(Ecom) y usar el nuestro"**. Hoy es un piloto de 5 SKU; el destino es extenderlo a todo el catálogo.

La regla de oro que ordena todo el proyecto: **Ayala Core NO pasa por Ecom para los precios.**
El costo del producto sí sale de Táctica (como el resto del ERP), pero el precio se calcula acá y
se escribe directo a ML. Ecom deja de ser el intermediario de precios para estos SKU.

## A.1 Alcance v1 — los 5 SKU piloto
```
PLANCHA-SUB-26X26-PORT
PLANCHA-SUB-30X38-10EN1
PLANCHA-SUB-30X38-5EN1
PLANCHA-SUB-GORRA
PLANCHA-SUB-TERMO
```
Diseñado para sumar más SKU después **sin rediseño**. No hardcodear "5" en ningún lado como si
fuera un límite estructural: es una lista extensible.

## A.2 Origen del modelo de precios (NO inventar, viene de Maxx)
El modelo sale de la planilla real de Maxx: **"VENTAS POR CANALES MATIAS"**, pestañas
`Calculadora` / `Motor` / `Tasas`. No es un modelo que Code diseñe: es el que Maxx ya tiene armado
y hay que replicar fielmente.

**Sheet fuente**: "VENTAS POR CANALES MATIAS" — ID `1aCQx9iQoLDoT0G-P0vRfRJ-MV9rH7hBeRxXyacWtdXk`.
Cualquier sesión futura puede abrirlo directo para validar el modelo, sin pedírselo a Maxx de nuevo.

**Fórmula: markup inverso.** Resuelve el precio de venta tal que, descontando comisión ML, IIBB,
costo financiero por cuotas, envío y la renta objetivo, quede cubierto **exactamente** el costo del
producto.

## A.3 Componentes del cálculo (valores actuales — mantenidos por Maxx)
1. **Costo del producto (sin IVA)** → de Táctica, automático. NUNCA se carga a mano.
2. **Alícuota IVA** → de Táctica.
3. **Comisión ML** → 15,32% (tabla "Tasas" de la planilla, la mantiene Maxx a mano).
4. **IIBB/Ganancias** → 6,50%.
5. **Costo financiero por condición de pago** (lo que ML cobra de verdad):
   - Contado: 0%
   - Reducida (tag real de ML `pcj-co-funded`, "3 a 12 cuotas con interés BAJO"): **5% fijo**,
     sin importar cuántas cuotas elija el comprador dentro del rango.
   - Cuotas sin interés: 3→8,9% · 6→13,4% · 9→17,8% · 12→21,6%
     (mismos valores que `CUOTAS_PCT_DEFAULT`, ya en uso en Ofertas ML — corregidos
     2026-09-02, ver Decisiones tomadas).
6. **Costo de envío real** → el job ya construido esta semana (última venta real, NO la tabla de
   tramos por peso de la planilla).
7. **Renta objetivo (%) por condición de pago** → configurable a mano por SKU. Arranca con los
   valores de la planilla (ej. 32 / 32 / 30 / 28 / 26 / 24 para Contado / Reducida / 3 / 6 / 9 / 12
   cuotas). **Confirmado leyendo la fórmula real 2026-09-02**: no son 6 números sueltos — es UN
   valor (renta Contado) más UN diferencial fijo que se resta por escalón (default 2 puntos),
   arrancando desde Reducida (que no cambia respecto a Contado): Reducida = Contado; 3c = Reducida
   − 2; 6c = 3c − 2; 9c = 6c − 2; 12c = 9c − 2. Los dos valores (renta Contado + diferencial) son
   los que hay que exponer editables, no una tabla de 6 celdas independientes.
8. **Envío a Bodega (Full)** → 0,50% adicional sobre el precio, SOLO si el envío es a Bodega (Full)
   en vez de a Casa central (dato de la planilla, `Calculadora!B7`). Componente real encontrado
   leyendo la fórmula 2026-09-02, no estaba en esta lista antes — no es la misma cuenta que "costo
   de envío real" (punto 6): ese es el flete de reposición al depósito propio/Full, este 0,50% es
   un cargo aparte de ML que solo aplica en esa modalidad de despacho.

**Por qué la renta baja en cuotas (concepto clave que no hay que "corregir"):** es intencional.
La renta objetivo baja en las condiciones con más cuotas para que **la ganancia en PESOS quede
pareja** entre todas las formas de pago, aunque el % de margen baje. NO es un error: es el diseño
de Maxx. No lo "optimices" a un % fijo.

**La fórmula exacta** (confirmada leyendo `Motor!B32:G32` de la planilla real, en modo solo-lectura,
2026-09-02 — reproduce el ejemplo congelado de A.3.1 al peso exacto, ver `test_ayala_core.py`):

```
IVA_SERVICIOS_ML = 1,21   # fijo -- el servicio/comisión de ML factura IVA 21% siempre,
                          # sin importar la alícuota del producto vendido
numerador   = costo_sin_iva + envío_real / IVA_SERVICIOS_ML
denominador = 1/(1+iva_producto)
              − (comisión_ML / IVA_SERVICIOS_ML)
              − (IIBB / (1+iva_producto))
              − financiero_pct        # 0 / 5% / cuotas sin interés según condición
              − renta_objetivo_pct    # según condición, ver punto 7
              − (0,50% si envío a Bodega Full, si no 0)
precio_final = ROUND(numerador / denominador; 0 decimales)
```

Implementada en `backend/ayala_core.py` (`calcular_precio_condicion`/`calcular_precios_todas_condiciones`).

## A.3.1 Ejemplo de referencia congelado (test estable — NO depende del Sheet en vivo)
Fila real de **PLANCHA-SUB-26X26-PORT**, tomada de la planilla el 2026-09-02. Este ejemplo queda
**fijo en este documento a propósito**: la Etapa 1 (ver A.9) se valida contra ESTOS números, no
contra el Sheet en vivo (que Maxx sigue editando y puede moverse). Si el motor implementado en el
ERP reproduce estos 6 precios a partir de estos 3 inputs, el cálculo está bien hecho.

**Inputs:**
- Costo sin IVA: $56.105,10
- Alícuota IVA: 10,5%
- Envío: $29.410

**Precios esperados por condición:**
| Condición | Precio |
|---|---|
| Contado | $201.258 |
| Reducida | $230.046 |
| 3 cuotas | $239.645 |
| 6 cuotas | $254.029 |
| 9 cuotas | $265.784 |
| 12 cuotas | $279.649 |

## A.4 Detección de condición de pago (en vivo, sin carga manual)
Se lee del `tags` real de la publicación en ML (mismo mecanismo ya construido en Ofertas ML):
- `cuota-simple-N` o `Nx_campaign` → cuotas sin interés, N cuotas.
- `pcj-co-funded` → Reducida.
- Ninguno de los anteriores → Contado.

**Un MLA = una condición de pago.** No es una publicación con 6 precios simultáneos: cada
publicación de un SKU corresponde a una sola condición en un momento dado.

## A.5 Qué publicaciones entran
Solo MLAs cuya vinculación en Ecom mapea **EXACTAMENTE a uno de los 5 SKU**.
Se **excluyen combos/kits** (un MLA vinculado a este SKU + otros SKU): quedan fuera del modelo de
precio fijo por SKU.

## A.6 Reglas que NO se negocian (heredadas de Ofertas ML)
- **Escritura: una acción, una publicación, nunca masivo.** Cada corrección de precio se hace
  sobre una publicación por vez, con confirmación explícita.
- **QR / verificación facial de ML → bloqueante total.** Si aparece, frena, revierte lo que se
  haya tocado, avisa a Maxx, y NO reintenta solo.
- **El precio final que cobra el cliente es sagrado.** En el flujo de oferta/tachado, el tachado
  es teatro (se infla lo necesario), pero el precio final no se toca salvo que Maxx lo decida.
- **Costo y IVA SIEMPRE desde Táctica**, nunca del PM Sheet ni inventados.
- **Todo por API pública de ML con Bearer OAuth.** Nada de endpoints internos con cookies ni
  Selenium (ya se confirmó en vivo que la API pública alcanza para todo el flujo).

## A.7 Qué se reutiliza tal cual (YA construido, no rehacer)
- Job de costo de envío real: `iniciar_job_costos_envio` / `costo_envio_real_item` (`ml_ofertas.py`).
- Detección de cuotas por tags: `_cuotas_sin_interes` (`ml_ofertas.py`) — ya extendida para Reducida
  (`pcj-co-funded`) en `ayala_core.detectar_condicion_pago`, hecho 2026-09-02.
- Costo/IVA desde Táctica: `CostoVigenteProvider`/`IvaProvider` (`rentabilidad/adapters.py`) — mismo
  patrón que usa `resolver_item_para_gestion` en Ofertas ML.
- Resolución de SKU real del ítem: `_sku_de_item` (`ml_full.py`) — `seller_custom_field` O el
  atributo `SELLER_SKU`, nunca uno solo (bug real encontrado y corregido en Ofertas ML 2026-09-02,
  ver [[project_ml-full-reposicion-fixes]] — reusar esta función siempre, no volver a leer
  `seller_custom_field` directo en ningún código nuevo de Ayala Core).
- Flujo de campaña/tachado: `activar_en_campana_tradicional` — reapuntado para usar el precio de
  Ayala Core en vez del precio del PM/reglas de Ecom.
- Ofertas de un producto de catálogo (todos los vendedores): `MLOfertasClient.items_de_producto`
  (`ml_ofertas.py`, `GET /products/{id}/items`) — **el único camino que funciona** para leer una
  publicación que no es propia (`GET /items/{id}` está gateado por ownership para publicaciones
  ajenas, 403 confirmado en vivo 2026-09-03; scrapear la página pública tampoco sirve, ML bloquea
  ese `requests.get` como tráfico sospechoso). Cualquier función nueva que necesite datos de un
  competidor tiene que pasar por acá, con el ID de la FICHA de producto, no un `item_id` puntual.

## A.8 La pantalla del módulo (lo que ve Maxx)
1. Selector de SKU (arranca con los 5, extensible).
2. Panel por SKU: costo sin IVA (solo lectura, Táctica) · costo real de envío (última venta, con
   fecha) · tabla editable de Renta Objetivo % por condición · precio calculado por el motor para
   cada condición.
3. Lista de MLA de ese SKU (sin combos): cuenta (IT/MT), condición detectada en vivo, precio actual
   en ML vs. precio que debería tener, botón de corrección (**escribe directo a ML, sin Ecom**).
4. Sección "Ofertas" adentro del módulo: mismo flujo de "Oferta Tradicional" (campaña propia +
   tachado) que ya existe en Ofertas ML, pero para estos SKU usa el precio de Ayala Core, ignorando
   el precio del PM/reglas de Ecom.

## A.9 Plan de etapas (el orden importa — no saltear)
1. **Solo lectura:** mostrar SKU, condición detectada, precio actual vs. precio calculado — SIN
   escribir nada. Sirve para **validar el cálculo contra la planilla real de Maxx** antes de tocar
   precios en vivo. Esta etapa se cierra recién cuando los números del motor coinciden con la
   planilla.
2. **Escritura habilitada:** corregir precio, una publicación por vez, con confirmación explícita.
3. **Integración de Ofertas:** sumar el flujo de campaña/tachado dentro de Ayala Core.

---

# PARTE B — ESTADO DE AVANCE (se actualiza cada sesión)

> **Instrucción para Code:** al terminar cada sesión que toque Ayala Core, actualizá esta sección
> con lo que se hizo, lo que quedó pendiente y cualquier decisión nueva. Poné fecha.

## Estado actual
_(Fecha de última actualización: 2026-09-03)_

- **Etapa en curso:** Etapa 2 (escritura) arrancada -- código shippeado, sin el primer test real
  todavía (ver Pendientes). Etapa 1 (motor + pantalla) cerrada salvo validar los 5 SKU piloto.
- **Escrito hasta ahora:**
  - `backend/ayala_core.py` — motor completo (`calcular_precio_condicion`/
    `calcular_precios_todas_condiciones`, la fórmula exacta de A.3), detección de condición de pago
    (`detectar_condicion_pago`, incluye Reducida), `SKUS_PILOTO`. 15 tests en `test_ayala_core.py`,
    todos verdes.
  - `GET /ayala-core/skus` y `GET /ayala-core/sku/{sku}/motor` en `backend/main.py` — el segundo
    resuelve costo/IVA reales de Táctica + TC del BNA + (opcional) un `item_id` real para comparar
    condición detectada/precio actual en vivo contra el precio calculado. Probado en vivo contra
    Táctica real (SKU `PLANCHA-SUB-26X26-PORT`) y contra Railway con un `item_id` real
    (MLA3655836976, detectó "Reducida" correctamente).
  - Pantalla "Ayala Core — Motor de Precios" en `docs/index.html` (sidebar propio): selector de SKU,
    Renta Contado % + diferencial por cuota editables, envío real (manual o auto-resuelto al
    comparar un MLA), tabla de 6 condiciones, y comparador contra una publicación real. Probada en
    vivo (local + Railway), sin errores de consola.
  - **2026-09-03**: `descubrir_publicaciones` (`ayala_core.py`) escanea TODAS las publicaciones
    activas de las dos cuentas (`ml.items_activos`) y se queda con las que tienen un SKU piloto
    exacto -- corre como job de background (`POST /ayala-core/publicaciones/run` + status), con
    selección de SKU por checkboxes en el frontend (uno, varios o todos). Esto **resuelve el gap de
    A.5** sin necesitar Ecom (ver Research pendiente, más abajo).
  - **2026-09-03**: "Referencias de competencia" -- Maxx encontró un competidor vendiendo casi al
    mismo precio que el propio pero en 9 cuotas (lo saca de la venta en cuotas en tickets altos).
    Se puede pegar el MLA de un competidor por SKU (`resolver_referencia_competencia` +
    `GET /ayala-core/referencia/{item_id}`, publicación pública, no hace falta ser el dueño) y se
    muestra al lado de la fila con la misma condición detectada en la tabla de publicaciones. Para
    las condiciones sin referencia, un campo de "margen %" editable recalcula el precio al toque en
    el navegador (mismo motor, portado a JS -- `ayalaCoreCalcularPrecioJS`, debe mantenerse igual a
    `calcular_precio_condicion` si la fórmula cambia algún día).
  - **2026-09-03 — Etapa 2 arrancada**: `POST /ayala-core/item/{item_id}/aplicar-precio` escribe
    precio real a ML (reutiliza `fijar_precio_base`). Frontend: tildar filas + "Aplicar tildadas" +
    confirmación explícita + log secuencial (ver Decisiones tomadas). Sin probar contra una
    publicación real todavía -- ver Pendientes.
- **Validación contra planilla:** ✅ el motor reproduce el ejemplo congelado de A.3.1 al peso exacto
  (los 6 valores, ver `test_ayala_core.py`) — la fórmula se sacó leyendo `Motor!B32:G32` de la
  planilla real, no se adivinó.
- **PAUSADO 2026-09-02** — la sub-sección "Ofertas" (A.7/A.8 punto 4) espera un audio de "la
  encargada de ofertas" con cómo quiere trabajarlo, que Maxx va a pasarle a Desk para armar un MD.
  El resto de Ayala Core (motor + panel de lectura) sigue en curso, no está pausado.

## Research pendiente (no bloquea el diseño, se resuelve al implementar)
- **RESUELTO 2026-09-03 — sin necesitar Ecom.** Cómo identificar qué MLA está vinculado a
  **exactamente un SKU** (vs. combos): `descubrir_publicaciones` escanea TODO el catálogo activo y
  matchea `_sku_de_item` EXACTO contra la lista de SKU pedida -- un combo tiene un SKU distinto/
  concatenado, nunca matchea uno solo, así que la exclusión sale gratis. **Caveat sin confirmar**:
  si algún combo reutiliza el SKU de un componente SIN concatenar nada, esto no lo detectaría --
  no se vio ese caso todavía, pero no está descartado. Si aparece, ahí sí hará falta Ecom.
- **RESUELTO 2026-09-02**: la condición Reducida se detecta en vivo (`detectar_condicion_pago`,
  tag `pcj-co-funded`) — ya no es research pendiente, ver A.7.
- Definir el endpoint exacto para escribir precio directo a ML por condición (reutilizar el mismo
  patrón PUT que ya existe en `fijar_precio_base`). Etapa 2, todavía no arrancó.
- **RESUELTO 2026-09-02 — `CUOTAS_PCT_DEFAULT` estaba desactualizado, ya corregido en los DOS
  lugares.** Confirmado en vivo con Claude in Chrome (simulador de costos real, "Modificar
  publicación" de MLA3655836976): los valores reales subieron a 3→8,9% · 6→13,4% · 9→17,8% ·
  12→21,6% (antes 8,4/12,3/15,7/19,2). La Reducida se verificó en el mismo simulador y **sigue en
  5% fijo, no cambió**. Corregido en `backend/ml_ofertas.py` (`CUOTAS_PCT_DEFAULT`),
  `docs/index.html` (`CUOTAS_PCT_ML` y `OFM.cuotasPct`), `REQ_MODULO_OFERTAS_ML.md` y acá (A.3).
  Maxx ya actualizó la pestaña "Tasas" con estos valores. **Aclaración de Maxx (2026-09-02) sobre
  el rol del Sheet de acá en adelante**: la planilla fue para que Code entendiera el proceso/motor
  de cálculo, no queda como fuente de verdad continua -- una vez que Ayala Core esté construido en
  el ERP, las tasas se gestionan y corrigen directo ahí (no hay que mantener el Sheet sincronizado
  a futuro cada vez que ML cambie un %).

## Decisiones tomadas (log)
- **2026-09-02**: `CUOTAS_PCT_DEFAULT` corregido de 8,4/12,3/15,7/19,2% a 8,9/13,4/17,8/21,6% (3/6/9/12
  cuotas), confirmado en vivo por Maxx contra el simulador real de ML. Corregido a la vez en
  `backend/ml_ofertas.py`, `docs/index.html` y `REQ_MODULO_OFERTAS_ML.md`. La Reducida (5% fijo) se
  revisó en el mismo simulador y no cambió.
- **2026-09-02**: el Sheet "VENTAS POR CANALES MATIAS" **NO es fuente de verdad continua** para
  Ayala Core -- fue para que Code entendiera el motor de cálculo. Una vez construido el módulo en
  el ERP, las tasas (comisión, cuotas, envío) se gestionan y corrigen directo ahí, sin depender de
  mantener el Sheet actualizado a futuro.
- **2026-09-02**: fórmula del motor confirmada leyendo `Motor!B32:G32` real (solo-lectura, API de
  Sheets) en vez de reconstruirla a ojo desde los ejemplos -- reproduce el ejemplo congelado de
  A.3.1 al peso exacto. De paso se encontró un componente real no documentado antes (0,50% extra si
  el envío es a Bodega Full, punto A.3.8) y se confirmó que la renta objetivo es un valor + un
  diferencial por escalón (-2 puntos), no 6 números sueltos -- ver A.3 punto 7.
- **2026-09-02**: Maxx corrigió "NO, pausamos Ofertas ML, seguimos con Ayala Core" -- la pausa es
  SOLO de la sub-sección Ofertas (esperando el audio/MD), no de todo el módulo. Se construyó la
  Etapa 1 (motor + endpoint) en la misma sesión.
- **2026-09-03**: nace la idea de "referencias de competencia" -- Maxx encontró en vivo un
  competidor vendiendo casi al mismo precio propio pero en 9 cuotas, quedando afuera de esas
  ventas. Decisión: en vez de una regla automática de ceiling/floor, el sistema MUESTRA la
  comparación (competencia si hay referencia, margen manual editable si no) y Maxx decide caso por
  caso ("quiero poder jugar") -- no hay un algoritmo de igualar/subcotizar automático todavía.
- **2026-09-03, CONFIRMADO por Maxx** ("me sirve así el tilde"): el compromiso propuesto para
  escribir a ML con selección múltiple queda aprobado -- tildar varias filas, un solo botón
  "Aplicar tildadas", que primero muestra un resumen de confirmación (precio actual → precio a
  aplicar por cada una) y recién con un segundo click ("Confirmar y aplicar N") escribe, publicación
  por publicación, cada una con su propio resultado en un log -- nunca un lote silencioso. **Etapa
  2 arrancada y shippeada la misma sesión**: `POST /ayala-core/item/{item_id}/aplicar-precio`
  reutiliza `fijar_precio_base` (`ml_ofertas.py`) tal cual, sin duplicar la lógica de escritura;
  loguea a "Historial Ofertas ML" con `Accion="Ayala Core -- aplicar precio"` (mismo sheet que
  Ofertas ML, distinguible por esa columna -- no se creó un sheet de historial aparte). El "precio a
  aplicar" por fila es el de la referencia de competencia si existe para esa condición (pedido
  explícito: "desde ese mismo número igualo condiciones"), si no el que calculó el motor, pisable
  con el margen manual. **Probado el flujo completo con `fetch` interceptado (sin red real) --
  DELIBERADAMENTE no se probó contra una publicación real todavía** (es la primera vez que corre
  este endpoint nuevo y escribe precio de verdad en ML; mejor que el primer disparo real lo mire y
  autorice Maxx).
- **2026-09-03 — dos bugs reales corregidos en vivo (encontrados por Maxx usando el módulo)**:
  1. La API bloquea `GET /items/{id}` para publicaciones que no son propias (403 `access_denied`,
     confirmado con y sin auth, pidiendo solo campos públicos) -- la primera versión de
     "referencias de competencia" pedía justo eso y nunca podía leer un competidor real.
     Solucionado usando `GET /products/{id}/items` (ver A.7 actualizado) con el ID de la FICHA de
     producto, no el `item_id` puntual.
  2. `descubrir_publicaciones` mostraba **precio actual $0 en todas las filas** -- reutilizaba
     `detalle_items_ofertas` (`ml_ofertas.py`), que nunca pedía el campo `price` (se armó para un
     caso donde el precio salía de otro lado). Se agregó `price`/`original_price` a esa consulta.
  3. `KeyError: 'list_cost'` rompía tanto el job de publicaciones como la comparación contra un MLA
     puntual -- `costo_envio_real_item` devuelve la clave `costo_envio_real`, nunca `list_cost`;
     estaba mal en dos lugares (`ayala_core.py` y `main.py`). Nunca se disparó en las pruebas
     anteriores porque el único MLA probado no estaba en modo envío gratis en ese momento.
  **Lección para la próxima sesión**: ninguno de estos tres lo agarraron los tests unitarios (los
  fakes devuelven lo que uno les dice, no reproducen el filtro real de campos de la API ni el shape
  real de un dict) -- se encontraron recién corriendo el módulo de verdad. Verificar en vivo sigue
  siendo obligatorio antes de dar por cerrada una función nueva.
  **También revisado y confirmado que NO es un bug**: Maxx comparó el precio Contado del ERP contra
  el de la planilla para PLANCHA-SUB-30X38-5EN1 y no coincidían ($412.758 vs $407.839). Con el
  MISMO envío ($32.090) el motor del ERP reproduce $407.839 exacto -- la diferencia real viene de
  que el ERP usa el envío REAL de la última venta (~$34.590 en ese caso), no la tabla teórica por
  peso de la planilla. Es la diferencia esperada entre "teórico" y "real", no un error de fórmula.
- _(Code agrega acá cada decisión nueva con fecha, para que la próxima sesión no la olvide.)_

## Pendientes / próximos pasos
- **Falta el primer test real de Etapa 2**: nadie corrió `POST /ayala-core/item/{id}/aplicar-precio`
  contra una publicación real todavía -- antes de confiar en el flujo, probarlo una vez con Maxx
  mirando (un MLA de bajo riesgo) y confirmar que el precio realmente cambia en ML.
- **Detección de condición: gap real encontrado 2026-09-03, sin resolver.** Al menos una
  publicación real (MLA3193414376, "6 cuotas" real y confirmado en el simulador de ML) no trae el
  tag `6x_campaign` por ningún endpoint probado (`/items/{id}`, `/products/{id}/items`,
  `/items/{id}/prices`) -- se detecta como Contado en falso. Las otras 5 condiciones del mismo
  producto (3/9/12 cuotas y Reducida) sí traen su tag correcto, así que parece un caso aislado de
  ML, no un fallo del método. Si vuelve a aparecer, inspeccionar con la pestaña de Red del navegador
  la página real de "Modificar publicación" para encontrar qué llamada usa ML internamente (no se
  llegó a probar eso todavía).
- **Cerrar Etapa 1 del todo**: validar los 5 SKU piloto (no solo PLANCHA-SUB-26X26-PORT) contra la
  planilla real, con Maxx mirando.
- _(Code mantiene esta lista.)_
