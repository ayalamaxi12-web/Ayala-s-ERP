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
   cuotas).

**Por qué la renta baja en cuotas (concepto clave que no hay que "corregir"):** es intencional.
La renta objetivo baja en las condiciones con más cuotas para que **la ganancia en PESOS quede
pareja** entre todas las formas de pago, aunque el % de margen baje. NO es un error: es el diseño
de Maxx. No lo "optimices" a un % fijo.

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
- Job de costo de envío real: `iniciar_job_costos_envio` / `costo_envio_real_item`.
- Detección de cuotas por tags: `_cuotas_sin_interes` (extender para reconocer Reducida
  `pcj-co-funded`).
- Flujo de campaña/tachado: `activar_en_campana_tradicional` — reapuntado para usar el precio de
  Ayala Core en vez del precio del PM/reglas de Ecom.

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
_(Fecha de última actualización: 2026-09-02)_

- **Etapa en curso:** Etapa 1 (solo lectura) — definición / arranque.
- **Escrito hasta ahora:** _(a completar por Code: qué archivos/funciones ya existen de Ayala Core)_
- **Validación contra planilla:** ❌ pendiente — el motor todavía no se contrastó contra
  "VENTAS POR CANALES MATIAS".

## Research pendiente (no bloquea el diseño, se resuelve al implementar)
- Cómo identificar desde la API/GraphQL de Ecom qué MLA está vinculado a **exactamente un SKU**
  (vs. combos). Es research de implementación, no decisión de producto.
- Confirmar que al cambiar de campaña en ML (de cuotas sin interés a Reducida) la publicación sale
  automáticamente de la otra.
- Definir el endpoint exacto para escribir precio directo a ML por condición (reutilizar el mismo
  patrón PUT que ya existe en `fijar_precio_base`).
- **RESUELTO 2026-09-02 — `CUOTAS_PCT_DEFAULT` estaba desactualizado, ya corregido en los DOS
  lugares.** Confirmado en vivo con Claude in Chrome (simulador de costos real, "Modificar
  publicación" de MLA3655836976): los valores reales subieron a 3→8,9% · 6→13,4% · 9→17,8% ·
  12→21,6% (antes 8,4/12,3/15,7/19,2). La Reducida se verificó en el mismo simulador y **sigue en
  5% fijo, no cambió**. Corregido en `backend/ml_ofertas.py` (`CUOTAS_PCT_DEFAULT`),
  `docs/index.html` (`CUOTAS_PCT_ML` y `OFM.cuotasPct`), `REQ_MODULO_OFERTAS_ML.md` y acá (A.3).
  **Pendiente real:** el ejemplo congelado de A.3.1 puede seguir calculado con las tasas viejas si
  la pestaña "Tasas" de la planilla de Maxx todavía no las tiene actualizadas -- antes de cerrar la
  Etapa 1 contra ese ejemplo, confirmar con Maxx si el Sheet ya refleja 8,9/13,4/17,8/21,6% o si
  hay que re-congelar el ejemplo con los números nuevos.

## Decisiones tomadas (log)
- **2026-09-02**: `CUOTAS_PCT_DEFAULT` corregido de 8,4/12,3/15,7/19,2% a 8,9/13,4/17,8/21,6% (3/6/9/12
  cuotas), confirmado en vivo por Maxx contra el simulador real de ML. Corregido a la vez en
  `backend/ml_ofertas.py`, `docs/index.html` y `REQ_MODULO_OFERTAS_ML.md`. La Reducida (5% fijo) se
  revisó en el mismo simulador y no cambió.
- _(Code agrega acá cada decisión nueva con fecha, para que la próxima sesión no la olvide.)_

## Pendientes / próximos pasos
- Cerrar Etapa 1: motor de cálculo en modo solo-lectura, validado contra la planilla real.
- _(Code mantiene esta lista.)_
