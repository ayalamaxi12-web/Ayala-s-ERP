# RENTABILIDAD_FUNCIONAL.md

## Especificación Funcional Oficial — Módulo de Rentabilidad · ERP Ayala

**Versión 2.0** · 29/07/2026
**Estado: LISTO PARA CONGELAR — sujeto a 3 verificaciones contra el libro (§16)**

**Origen del relevamiento:** libro *Nuevo Reporte Facturacion* (Google Sheets, ID `1CqUTqbDMwRL4SCyh9qkgh5xhQrnxfJR_eQbNEAMnksc`), hojas vigentes al 29/07/2026.

**Autoridad:** este es el único documento funcional oficial del módulo. `RENTABILIDAD_IMPLEMENTACION.md` le está subordinado. **Ante cualquier conflicto, prevalece este documento.**

---

## 1. Propósito y regla de oro

Este documento **define el motor de Rentabilidad del ERP**. No explica el Excel. Su objetivo es que la implementación produzca exactamente los mismos resultados que el proceso vigente, celda por celda y total por total.

**Regla de oro: primero se replica, después se mejora.** Toda inconsistencia, duplicación o fórmula sospechosa detectada durante el relevamiento está documentada en §14 como observación y **no se corrige en esta versión**. Ninguna regla puede ser "mejorada" durante la implementación sin una decisión funcional explícita posterior.

**Criterio único de aceptación:** cargados los mismos períodos, el ERP reproduce línea por línea y total por total los valores de §13. Cualquier diferencia, **incluso favorable**, es un defecto.

---

## 2. Principio de separación de motores

Existen **dos motores de cálculo independientes** que conviven y se consolidan únicamente por agregación.

| | TACTICA | ECOM |
|---|---|---|
| Alcance | Facturación tradicional, con comprobantes fiscales | Marketplaces y tienda propia |
| Unidad de cálculo | comprobante + SKU | orden (puede contener varios SKU en un registro) |
| Régimen de comprobante | Sí | No existen comprobantes |
| Notas de crédito | Sí | No |
| IVA | Factor usado para grossing-up | Solo informativo |
| Impuesto al cheque | Sí | Sí |
| Retenciones (IIBB) | Sí | Sí |
| Costo financiero | **Sí** | **No, y no debe tenerlo** |
| Comisiones y envíos | No | **Sí** |
| Convención de signos | descuentos negativos, se suman | imp. cheque e IIBB positivos, se restan |
| Resultado | Margen real (`AA`) | Rentabilidad (`AB`) |

**No comparten fórmulas, no comparten columnas y no deben unificarse.** La conciliación es por agregación (§11), nunca por unificación de esquema.

---

## 3. Glosario

| Término | Definición operativa |
|---|---|
| **Venta** | Evento comercial único. Reemplaza los términos Pedido y Orden. Es una fotografía histórica. |
| **Línea de venta** | Unidad mínima de cálculo. TACTICA: comprobante + SKU. ECOM: orden. |
| **Comprobante** | Tipo de documento fiscal (FEA, FEB, FEE, FAE, CEA, CEB, CEE, CVA, CVB, CVE, MLA). Clave funcional de toda la lógica fiscal. |
| **Cuenta 1** | Régimen completo: descuenta IVA (implícito), impuesto al cheque, retenciones, costo del producto y costo financiero 1. |
| **Cuenta 2** | Régimen reducido: descuenta únicamente costo del producto y costo financiero 2. |
| **Pérdida definitiva** | Régimen en el que el costo y las cargas no se recuperan nunca (prefijos de comprobante 00007 y 05007). |
| **Costo vigente** | Costo unitario en USD tomado de Táctica/Importaciones **al momento del cálculo**, no al momento de la venta. |
| **TC** | Tipo de cambio de la operación, almacenado por línea. Fotografía histórica. |
| **Margen real / Rentabilidad** | Resultado final del motor. *Margen real* en TACTICA, *Rentabilidad* en ECOM. Conceptos equivalentes, cálculo distinto. |

### Principio de fotografía asimétrica

Deliberado y a replicar: **el precio y el tipo de cambio son históricos; el costo no lo es.** La rentabilidad se recalcula siempre contra el costo vigente del sistema.

---

## 4. Fuentes de verdad

| Fuente | Rol | Autoridad |
|---|---|---|
| **Facturación** | Ventas, comprobantes, cantidades, precios, TC | Fuente oficial de ventas |
| **Importaciones** | Determinación del costo y del FOB | Fuente oficial del costo |
| **Táctica** | Almacena y publica el costo vigente y la alícuota de IVA por SKU | Fuente oficial del costo vigente y del IVA |
| **ECOM** | Órdenes, comisiones, envíos, precios netos y finales del canal ecommerce | Fuente funcional del canal ecommerce |

**El ERP nunca reconstruye FOB, ni costos de importación, ni alícuotas de IVA.** Consume el costo oficial y el IVA informado.

---

## 5. Reglas normativas transversales

**Estas reglas se enuncian aquí una sola vez y no se repiten en el resto del documento.** Las fórmulas por columna viven exclusivamente en los diccionarios de datos (§6.4 y §7.7).

### 5.1 Convención de signos

| Motor | Convención |
|---|---|
| TACTICA | Los descuentos se **almacenan en negativo** (`T`, `U`, `W`, `Y`, `Z`) y el resultado se obtiene **sumando**. |
| ECOM | El impuesto al cheque y el IIBB se **almacenan en positivo** (`S`, `T`) y se **restan** en `Z`. |

Ambas convenciones deben conservarse. Es lo que garantiza que cualquier agregado —incluido `SUM(Costo Total Pesos)`, que hoy da negativo— coincida con el reporte actual.

### 5.2 Bases imponibles

**Asimetría intencional, idéntica en ambos motores, a replicar tal cual:**

| Concepto | Base |
|---|---|
| Impuesto al cheque | **Bruto** (TACTICA: `P + S` · ECOM: `U`) |
| Retenciones (IIBB) | **Neto** (TACTICA: `P` · ECOM: `Q`) |
| Costo financiero 1 | **Bruto** (`P + S`) |
| Costo financiero 2 | **Neto** (`P`) |

### 5.3 Tasas

| Concepto | Tasa | Motores |
|---|---|---|
| Impuesto al cheque | 1,2 % | TACTICA y ECOM |
| Retenciones (IIBB) | 5 % | TACTICA y ECOM |
| Costo financiero 1 y 2 | 3 % | Solo TACTICA |
| Tasas AGIN | 0,90 % y 0,40 % | Solo agregación TACTICA (§11.3) |

Todas paramétricas.

### 5.4 Tratamiento del IVA

**El ERP nunca calcula IVA manualmente y nunca reconstruye alícuotas.** Consume el factor informado por Táctica/Importaciones.

Resolución del factor, por lookup del SKU sobre el régimen textual del producto:

| Valor informado | Factor |
|---|---|
| `IVA Debito 21%` | 1,21 |
| `IVA Debito 10.5%` | 1,105 |
| cualquier otro valor / no encontrado / error | `""` (vacío) |

La comparación original usa `IGUAL` (**sensible a mayúsculas y minúsculas**). Debe replicarse con comparación exacta de cadena, **sin normalizar**.

**Uso por motor:**

- **TACTICA:** `S = (P * Q) - P`. `S` **no se resta del margen**: existe únicamente para (a) el grossing-up del impuesto al cheque y del costo financiero 1, y (b) informar `AG = P + S`. El descuento de IVA de Cuenta 1 es **implícito**: el ingreso considerado ya es el neto. **No existe una línea de descuento de IVA y no debe crearse.**
- **ECOM:** el factor se usa **únicamente** para `AP = U * AO` (informativo). El neto (`Q`) llega del origen.

**Comportamiento ante factor vacío:**

| Motor | Comportamiento |
|---|---|
| TACTICA | La fórmula original propaga error hacia `S`, `T`, `Y`, `AG` y `AA`: la línea no aporta un número válido. El ERP replica ese efecto marcando la línea como incidencia bloqueante y excluyéndola del resultado hasta su corrección manual. **No asumir 21 %, no asumir 0.** En el período vigente todas las líneas TACTICA resolvieron factor, por lo que el caso **no está probado en producción**. |
| ECOM | Solo invalida `AP`. `Z`, `AA` y `AB` se calculan normalmente. Hay **137 órdenes** en esa situación. |

### 5.5 Tipo de cambio

Cada línea conserva su propio TC (`V` en TACTICA, `AM` en ECOM). **Nunca se recalcula una venta histórica con el dólar actual**, ni al reprocesar, ni al reconstruir un período cerrado.

El TC **no es función de la fecha**: se fija por lote de carga. Comportamiento observado en el período vigente — TACTICA usa 1500 y 1520; ECOM usa 1500 en todas las órdenes; el 27/07/2026 registra 1500 en 47 líneas y 1520 en 90.

El TC se toma del día de la operación **al momento de la carga**, y es **obligatorio e inmutable a nivel de línea**. Ningún proceso posterior puede modificarlo.

### 5.6 Costo vigente

**Resolución del costo unitario USD — cascada exacta:**

1. Buscar el SKU en `Global`, **columna S** (costo vigente).
2. Si el valor obtenido es **0**, buscar el mismo SKU en `Global`, **columna R**.
3. Si la búsqueda falla o devuelve error, usar `Global` columna R.
4. Si también falla, el costo queda vacío y la línea se marca como incidencia bloqueante.

> **El 0 se trata como "sin costo", no como costo cero.** Esta distinción es funcionalmente relevante y debe replicarse tal cual.

**Decisión funcional explícita:** la rentabilidad reemplaza el costo histórico por el costo vigente del sistema. Cada vez que se recalcula un período, el costo utilizado es el que Táctica tiene publicado **en ese momento**.

Consecuencia aceptada y deliberada: **la rentabilidad de un período cerrado puede cambiar** si el costo del SKU cambió, aun cuando precio, cantidad y TC sean inmutables. No es un error: es la forma en que hoy trabaja el negocio.

**Prohibido:** derivar, estimar, promediar o recomponer costos. Si no se resuelve costo, la línea es incidencia y **no se asume 0**.

**Costo en pesos:**

| Motor | Costo USD | Costo en pesos |
|---|---|---|
| TACTICA | `O = L * N` (por línea, desde el costo unitario) | `W = -((L * V) * N)` |
| ECOM | `G` (dato del origen, **total de la orden**) | `AA = G * AM` |

Esta diferencia es estructural y **no debe homogeneizarse**.

### 5.7 Precisión y redondeo

- El cálculo se realiza **sin redondeos intermedios**, con precisión completa.
- El redondeo a 2 decimales se aplica **solo en la presentación y en la comparación** contra los casos de aceptación.
- Los valores esperados de §13 están expresados redondeados a 2 decimales. Tolerancia de comparación: **0,01**. Diferencias de signo: **0**.

### 5.8 Vacío y cero

| Situación | Almacenamiento |
|---|---|
| Cuenta 2 → `S`, `T`, `U` | vacío |
| Cuenta 2 → `Y` | **0** (valor literal, no fórmula) |
| Cuenta 1 → `Z` | **0** |
| Pérdida definitiva → `S`, `T`, `U`, `W`, `Y`, `Z` | vacío (todas) |

En la suma de `AA`, todo vacío se trata como 0. En la condición disparadora de `Z`, **vacío y cero son equivalentes**, tal como lo hace Sheets.

---

## 6. Motor TACTICA

Estructura idéntica en `Borrador Diario Tactica`, `Junio - Julio TACTICA` y `Julio - Agosto TACTICA`. El borrador tiene algunas etiquetas distintas en `Q`, `S`, `AF` y `AG`, con la misma lógica.

### 6.1 Régimen — se resuelve primero

**El régimen se resuelve antes de cualquier cálculo.**

La clasificación de Cuenta 1 / Cuenta 2 se basa **exclusivamente en el tipo de comprobante (columna `I`)**, nunca en el prefijo del número de factura, aunque hoy ambos coincidan. **El prefijo se usa únicamente para determinar la pérdida definitiva**, y esa determinación tiene **prioridad absoluta** sobre el tipo de comprobante.

| Condición | Régimen |
|---|---|
| El prefijo del Nº de comprobante es `00007` o `05007` | **PÉRDIDA DEFINITIVA** |
| Comprobante es nota de débito | **EXCLUIDO** (§10) |
| Comprobante ∈ {FEA, FEB, FEE, CEA, CEB, CEE} | **CUENTA 1** |
| Comprobante ∈ {FAE, CVE} | **CUENTA 2** |
| Comprobante = MLA | **NO DEFINIDO** — pendiente P-01 (§15). La línea no se calcula |
| Comprobante no reconocido | La línea no se calcula |

| Comprobante | Descripción | Régimen |
|---|---|---|
| FEA | Factura de Venta A – Electrónica | Cuenta 1 |
| FEB | Factura de Venta B – Electrónica | Cuenta 1 |
| FEE | Factura de Venta E – Electrónica | Cuenta 1 |
| FAE | Factura de Venta E (no electrónica) | Cuenta 2 |
| CEA / CEB / CEE | Notas de crédito electrónicas A / B / E | Cuenta 1 (reverso) |
| CVE | Nota de crédito E no electrónica | Cuenta 2 (reverso) |
| CVA / CVB | Notas de crédito A / B no electrónicas | En el libro relevado aparecen **exclusivamente** con prefijo de pérdida definitiva, por lo que su régimen fuera de ese caso no es observable en la evidencia disponible |
| MLA | Multipropósito (Factura) | Pendiente P-01 |
| Notas de débito | — | Excluidas del cálculo |

### 6.2 Orden de cálculo determinístico

**El orden es parte de la especificación.**

| Paso | Acción |
|---|---|
| 1 | Resolver el régimen (§6.1). Si es EXCLUIDO, NO DEFINIDO o no reconocido, la línea no se calcula. |
| 2 | Si el régimen es **PÉRDIDA DEFINITIVA**: `S`, `T`, `U`, `W`, `Y`, `Z` quedan vacías · `AA = P` · fin del cálculo. |
| 3 | Resolver `L` = costo vigente USD del SKU (§5.6). |
| 4 | `O = L * N` |
| 5 | Resolver `Q` = factor de IVA del SKU (§5.4). |
| 6 | **Cuenta 1:** `S = (P * Q) - P` · `AG = P + S` · `T = -((P + S) * 1,2%)` · `U = -(P * 5%)` · `Y = -((P + S) * 3%)` · `Z = 0`<br>**Cuenta 2:** `S`, `T`, `U` vacías · `Y = 0` · `Z = -(P * 3%)` |
| 7 | `W = -((L * V) * N)` |
| 8 | `AA = P + T + U + W + Y + Z` (los vacíos cuentan como 0) |
| 9 | `AB = AA / P` |

**Precedencias obligatorias:** `S` antes de `T` y de `Y` · `Y` antes de `Z` · `Z` antes de `AA`.

**Resultado esperado:** `AA` idéntico al Excel al centavo · `Z = 0` para toda Cuenta 1 · `S`, `T`, `U` vacías para toda Cuenta 2.

### 6.3 Notas de crédito — el reverso es automático

Las notas de crédito llegan con **cantidad y precio negativos**. Al aplicar exactamente las mismas fórmulas del régimen correspondiente, la nota recupera exactamente lo que la factura había descontado: `W` se vuelve positivo (recupera costo), `S` negativo (recupera IVA), `T`, `U`, `Y`/`Z` positivos (recuperan cargas). `AA` resulta negativo: es la reversión del margen.

**No existe ni debe existir lógica especial de reverso.** La única regla es: mismo régimen, signo invertido en el dato de entrada.

| Régimen | Qué recupera |
|---|---|
| Cuenta 1 (CEA, CEB, CEE) | IVA, impuesto al cheque, retenciones, costo y costo financiero 1 |
| Cuenta 2 (CVE) | Costo y costo financiero 2 |
| Pérdida definitiva (prefijos 00007 / 05007) | **Nada.** `AA = P`, negativo. Aplica incluso cuando `O` tenga valor |

La pérdida definitiva corresponde a RMA, destrucción y producto irrecuperable.

### 6.4 Diccionario de datos — TACTICA

`D` = dato de entrada · `F` = calculado · `I` = informativo

| Col | Nombre | Tipo | Definición |
|---|---|---|---|
| A | Fecha | D | Fecha de la operación |
| B | Empresa | D | Cliente |
| C | Codigo | D | SKU. Clave de todos los lookups |
| D | Descripción | D | Descripción del producto |
| E | Fabricante | D | Proveedor / fabricante |
| F | Tipo de Producto | D | `Productos para la venta`, `Preventa`, `Mercaderia Nacional A La Venta` |
| G | Familia | D | Familia de producto |
| H | Vendedor | D | Vendedor asignado en Facturación |
| I | Tipo de Factura | D | **Comprobante. Determina el régimen (§6.1)** |
| J | Nº Factura | D | `PREFIJO-NUMERO`. El prefijo determina la pérdida definitiva (§6.1) |
| K | Precio de Compra de Lista | I | Informativo |
| L | Costo de Lista | F | Costo vigente USD según cascada de §5.6 |
| M | Precio de Venta de Lista | I | Informativo |
| N | Cantidad | D | Negativa en notas de crédito |
| O | Costo Total En Dolares | F | `= L * N` |
| P | Precio de Venta | D | **Neto sin IVA. Base de todo el cálculo.** Negativo en notas de crédito |
| Q | IVA PRODUCTO | F | Factor `1,21` / `1,105` / `""` (§5.4) |
| R | Margen | I | Margen informado por Táctica. **No se usa** — observación O-01 |
| S | IVA | F | `= (P * Q) - P` |
| T | imp ch | F | `= ((P + S) * 1,2%) * -1` |
| U | IIBB | F | `= (P * 5%) * -1` |
| V | TC | D | Tipo de cambio de la operación (§5.5) |
| W | Costo Total Pesos | F | `= ((L * V) * N) * -1` |
| X | Margen | I | `= P - W`. Columna informativa incoherente — observación O-02 |
| Y | COSTO FINANCIERO 1 | F | `= ((P + S) * 3%) * -1` |
| Z | COSTO FINANCIERO 2 | F | `= SI(Y <> 0; 0; (P * 3%) * -1)` — ver §16, verificación V-03 |
| AA | **Margen real** | F | `= P + T + U + W + Y + Z` ← **resultado del motor** |
| AB | Margen % | F | `= AA / P` |
| AC | SKU MARGEN NEGATIVO | F | Bandera de gestión (§8.3) |
| AD | PM | F | Lookup de PM (§8.1) |
| AE | Canal Tactica | D | Constante `"Canal Tactica"` |
| AF | Subcategoria | F | Lookup de subcategoría (§8.1) |
| AG | Precio de Venta IVA | F | `= P + S` (precio bruto) |
| AH | Responsable | F | Lookup por empresa (§8.2) |
| AI / AJ / AK | Margen L3 / L4 / L5 | I | Márgenes objetivo por SKU (§9) |

---

## 7. Motor ECOM

Hoja `Julio - Agosto ECOM`. **Una fila = una orden.** El campo `Sku's Vendidos` puede contener varios SKU separados por coma.

### 7.1 Orden de cálculo

| Paso | Acción |
|---|---|
| 1 | Tomar del origen: `Q` (neto), `U` (bruto), `G` (costo USD total de la orden), `M` (comisión venta), `O` (costo envío), `AM` (TC) |
| 2 | `S = U * 1,2%` (positivo) |
| 3 | `T = Q * 5%` (positivo) |
| 4 | `Z = Q - M - O - S - T` |
| 5 | `AA = G * AM` |
| 6 | `AB = Z - AA` ← **resultado del motor** |
| 7 | `AE = AB / AM` · `AF = U / AM` · `AV = 1 - (AA / Z)`, con 0 ante error |

### 7.2 Prohibición explícita — no recalcular Q

**El ERP no debe recalcular `Q` a partir de `U` dividiendo por el factor de IVA.**

Evidencia del período vigente: las **242 órdenes** con régimen 10,5 % traen `U / Q = 1,10` exactamente, mientras que el factor de IVA del SKU es 1,105; y **137 órdenes multi-SKU** tienen ratios mixtos (1,1011 … 1,1941). Recalcular introduciría desvíos y rompería la conciliación.

**`Q` y `U` son datos, no resultados.** — observación O-05.

### 7.3 Diferencias estructurales con TACTICA

Todas deliberadas:

1. **No hay costo financiero.** El costo financiero aplica únicamente a TACTICA.
2. **No hay régimen de cuentas ni notas de crédito.** No existen comprobantes en esta base.
3. `S` y `T` se almacenan como **positivos** y se restan en `Z` (convención inversa a TACTICA).
4. `N` (Comisión Cobro) y `P` (Impuestos/retenciones) **no entran** en `Z`.
5. El IVA se excluye por trabajar sobre `Q` (neto), que llega ya calculado desde el origen.

### 7.4 Casos especiales del canal

| Caso | Comportamiento |
|---|---|
| **Posventa** | Órdenes de reposición sin ingreso. `Q = 0`, `U = 0`, `G > 0` → `Z = 0`, `AB = -AA`. Pérdida total por costo. |
| **Canal vacío** | Existen órdenes sin canal asignado. El reporte las agrupa bajo `Total` y **participan del cálculo**. No se descartan. |

### 7.5 Comisión de cobro

Permanece en cero y **no participa del cálculo**. Existe en el modelo de datos y se persiste, pero está excluida de la fórmula de `Z`. **No debe incorporarse aunque llegue con valor distinto de cero**: en ese caso se registra como incidencia informativa y el cálculo la ignora.

### 7.6 Promociones

**Situación vigente: prácticamente no existen.** La única mecánica encontrada es el SKU `PROMOS-*` (*Aportes Promociones 21%*), que se registra como nota de crédito **CVA con prefijo 00007**, cantidad −1, costo 0 y precio negativo.

Resultado: cae automáticamente bajo el régimen de **pérdida definitiva** (§6.1), por lo que `AA = P` y el importe completo impacta como pérdida, sin recupero de costo ni de cargas.

**Ninguna regla especial de promociones.** Se replica exactamente el circuito actual. Mientras existan reglas en el Excel se replican; no se simplifican todavía.

### 7.7 Diccionario de datos — ECOM

| Col | Nombre | Tipo | Definición |
|---|---|---|---|
| A | Número Orden | D | Identificador de la orden |
| B | Sku's Vendidos | D | SKU o lista de SKU separados por coma |
| C / E | FechaCreaciónVenta / FechaPago | D | Fechas |
| D / F | EstadoVenta / EstadoPago | D | `Abierta`/`Cerrada`; `Cobrado`/`Cobro Parcial`. **No se filtran** (§10) |
| G | Costo Sin Iva (total de productos) | D | Costo vigente **total de la orden**, en USD |
| H | IVA A Favor | I | Informativo, del origen — pendiente P-02 |
| I | Canal De Venta | D | `Mercadolibre Carrito`, `Mercadolibre`, `Fravega`, `Woocommerce`, `Posventa`, vacío |
| J / K / L | Usuario Integración / Medio De Cobro / Entrega-Envío | D | Descriptivos |
| M | Comisión Venta | D | Comisión del canal, en pesos. **Se deduce íntegra en `Z`, no se recalcula** |
| N | Comisión Cobro | D | Siempre 0. **No participa del cálculo** (§7.5) |
| O | Costo Envío | D | Costo logístico en pesos. **Se deduce íntegro en `Z`** |
| P | Impuestos (retenciones) | D | Informado por el origen y **NO deducido** — observación O-03 |
| Q | Precio SIN IVA | D | **Neto de la orden. Base del cálculo. Dato del origen, no se recalcula** (§7.2) |
| R | Total Impuestos | D | IVA contenido (`= U - Q` en el origen) |
| S | imp ch | F | `= U * 1,2%` (base bruta) |
| T | IIBB | F | `= Q * 5%` (base neta) |
| U | Precio Final | D | Precio bruto cobrado |
| V | Dif IVA | I | `= R - H`, verificado numéricamente |
| W | Cash | I | Informativo del origen — pendiente P-02 |
| X | Utilidad Venta | I | Informativo del origen, en % — pendiente P-02 |
| Y | Utilidad Costo | I | Informativo del origen, en % — pendiente P-02 |
| Z | Neto | F | `= Q - M - O - S - T` |
| AA | Costo Total | F | `= G * AM` |
| AB | **Rentabilidad** | F | `= Z - AA` ← **resultado del motor** |
| AC / AD / AH / AI | PM / Subcategoria / Categoria / Subcategoria2 | F | Lookups de clasificación (§8.1) |
| AE | Rentabilidad USD | F | `= AB / AM` |
| AF | Facturacion USD | F | `= U / AM` |
| AG | Responsable De Ventas | D | Vacío en el período vigente |
| AJ / AK | Periodo / Semana | D | Etiquetas manuales |
| AL | Sku Negativo | F | Bandera de gestión (§8.3) |
| AM | TC | D | Tipo de cambio de la orden (§5.5) |
| AN | Vinculacion | F | Lookup por Nº de orden; **default `"OK"`** (§8.4) |
| AO | IVA | F | Factor `1,21` / `1,105` / `""`. **Solo se usa en `AP`** |
| AP | Facturacion +IVA | F | `= U * AO` (informativo) |
| AQ | Stock | F | Lookup en `Global` |
| AR | Ventas 30 Dias | F | Lookup en `Global` |
| AS | Dias de Stock | F | `= SI.ERROR(AQ / (AR / 30); "Sin ventas")` (§8.5) |
| AT | Precio De Venta | F | `= SI.ERROR(BUSCARV(B; Worksheet!G; 7; 0); 0)`. **La hoja `Worksheet` no existe: devuelve 0 siempre** — observación O-04 |
| AU | Rentabilidad Real | I | Margen esperado por PM (§9). **No interviene en el cálculo** |
| AV | % Rentabilidad | F | `= SI.ERROR(1 - (AA / Z); 0)`, equivalente a `AB / Z` |

---

## 8. Clasificación y enriquecimiento

Estas columnas **no alteran el resultado por línea**, pero determinan la agregación de todos los reportes, por lo que su fidelidad es obligatoria.

### 8.1 PM, Subcategoría, Categoría — cascada de tres intentos

Lógica idéntica en TACTICA (`AD`, `AF`) y ECOM (`AC`, `AD`, `AH`, `AI`):

1. Si el SKU está vacío → `"SIN PM"`.
2. Buscar el **SKU completo** en `GRAL CATEGORIAS!A` (col. 4 = PM, col. 5 = subcategoría).
3. Si falla, tomar el **primer SKU de la lista** — `ESPACIOS(IZQUIERDA(sku; ENCONTRAR(","; sku) - 1))` — y repetir la búsqueda en `A`.
4. Si falla, repetir con el primer SKU sobre el rango alternativo `GRAL CATEGORIAS!U`.
5. Si todo falla → error / vacío.

El paso 3 es crítico en ECOM, donde una orden puede contener varios SKU: **la clasificación de toda la orden se toma del primer SKU, aunque el costo (`G`) corresponda a todos los SKU de la orden.**

### 8.2 Responsable

TACTICA `AH`: lookup por empresa/cliente (`B`) en `BASE GENERAL`, con búsquedas anidadas de respaldo. ECOM `AG` está vacío en el período vigente.

**Consecuencia a replicar:** las líneas cuya empresa no resuelve responsable quedan sin responsable y **desaparecen del bloque AGIN** del reporte, generando una diferencia de totales conocida (§11.3) — observación O-06.

### 8.3 SKU Margen Negativo — bandera de gestión

Lookup en la hoja `SKU Margen Negativo`; **default `"MARGEN POSITIVO"`**.

Es una **lista curada manualmente** (PM / SKU / Margen), no un cálculo. Un SKU puede estar marcado como negativo y tener margen positivo en la línea, y viceversa. **No interviene en el cálculo.**

### 8.4 Vinculación (ECOM `AN`)

Lookup del número de orden en el archivo de vinculación; si no encuentra, devuelve **`"OK"`**.

Es decir: **el valor por defecto es el estado bueno**, y solo se marca lo que está explícitamente informado como problemático. Replicar exactamente — **no invertir el default**.

### 8.5 Stock y días de stock (ECOM)

`AS = SI.ERROR(AQ / (AR / 30); "Sin ventas")`

`AS` es **un número o el texto `"Sin ventas"`**, en la misma columna. El ERP debe exponer ambos estados sin convertirlo a 0.

### 8.6 Defaults textuales — parte del contrato funcional

`"SIN PM"` · `"MARGEN POSITIVO"` · `"OK"` · `"Sin ventas"` · `"NO ENCUENTRO SKU"`

Estos textos **se usan hoy como criterio de filtrado en los reportes**, por lo que son parte del contrato funcional y deben reproducirse literalmente.

---

## 9. Fuera del motor

Explícitamente **no intervienen** en `Z`, `AA`, `AB` ni en ningún total:

| Elemento | Qué es |
|---|---|
| **Rentabilidad Real** (ECOM `AU`) | Rentabilidad esperada por el Product Manager para ese SKU, tomada de su lista de precios. Se resuelve por **título de columna** (`Margen / Ganancia actual`), no por posición. Default `"NO ENCUENTRO SKU"`. Su única función es comparar la rentabilidad obtenida (`AV`) contra la esperada (`AU`) |
| **Margen L3 / L4 / L5** (TACTICA `AI`/`AJ`/`AK`) | Márgenes objetivo por nivel de lista. Doble `COINCIDIR` (fila por SKU, columna por título `L3 usd SIN IVA`, `L4 usd SIN IVA`, `L5 usd SIN IVA`), con cascada por PM: **primero Verónica, si falla Matías, si falla Cristian**. Informativos, se completan de forma dispersa |
| **SKU Margen Negativo** | Bandera de gestión (§8.3) |
| **Columnas informativas** | `K`, `M`, `R`, `X` en TACTICA · `H`, `V`, `W`, `X`, `Y`, `AT` en ECOM |

El indicador de desvío (`AV` contra `AU`) es **una vista, no una regla**.

### Fuera de alcance del módulo

- "Vuelve a stock"
- Brasil (hoja `0Base Brasil`)
- Lógica basada en colores o formato de celda
- Reglas propias de los reportes personales

---

## 10. Exclusiones

Existen registros que **deliberadamente no participan** de la rentabilidad. Si hoy el operador los elimina del Excel, el ERP debe excluirlos del cálculo.

| Concepto | Tratamiento | Evidencia |
|---|---|---|
| **Notas de débito** | Excluidas completamente, **bajo ninguna circunstancia** participan | No existe ninguna fila de nota de débito en las bases vigentes: se eliminan antes de la carga |
| **Fixture** | Excluido | Eliminado manualmente por el operador |
| **Envíos (como SKU de venta)** | Excluido | Eliminado manualmente por el operador |
| **SKU auxiliares** | Excluidos | Eliminados manualmente por el operador |

La exclusión es **lógica y auditable**, nunca borrado físico. Las filas se conservan, se muestran y no se suman. Todo total debe poder desglosarse en *incluido / excluido* para que la conciliación con el Excel sea demostrable.

La regla de exclusión de notas de débito es **automática y no configurable**.

### Lo que NO se excluye

Fuente habitual de error, debe confirmarse en la implementación:

| Concepto | Volumen en el período vigente |
|---|---|
| **Estado de venta** — `Abierta` y `Cerrada` se calculan por igual | 484 / 948 |
| **Estado de pago** — `Cobrado` y `Cobro Parcial` se calculan por igual | 1.391 / 41 |
| **Canal vacío** — participa y se agrupa como `Total` | 3 órdenes |
| **Preventa** (`Tipo de Producto = Preventa`) — participa con costo y régimen normales | 41 líneas Junio-Julio · 10 Julio-Agosto |
| **Posventa** — participa con ingreso 0 y costo completo | — |

**Prohibido: filtrar por estado de venta o de pago.**

El listado exacto de fixture, envíos y SKU auxiliares **no está documentado en el archivo** y debe cargarse con el operador — pendiente P-05.

---

## 11. Agregación y reportes

**El resultado por línea es la unidad de verdad.** Los reportes son agregaciones puras: no aplican reglas de negocio adicionales, no recalculan nada y no corrigen nada.

El porcentaje se calcula **siempre sobre el neto**, en ambos bloques, y **sobre los totales agregados** — nunca como promedio de porcentajes de línea.

### 11.1 Bloque ECOM (por Canal De Venta)

| Medida | Origen |
|---|---|
| SUM de Precio Final | `SUM(U)` |
| SUM de Precio SIN IVA | `SUM(Q)` |
| SUM de Costo Total | `SUM(AA)` |
| SUM de Rentabilidad | `SUM(AB)` |
| % (Valorizado) | `SUM(AB) / SUM(Q)` |

### 11.2 Bloque TACTICA (por Canal Tactica)

| Medida | Origen |
|---|---|
| SUM de Precio de Venta IVA | `SUM(AG)` |
| SUM de Precio de Venta | `SUM(P)` |
| SUM de Costo Total Pesos | `SUM(W)` — **negativo por convención de signos** |
| SUM de Margen real | `SUM(AA)` |
| % | `SUM(AA) / SUM(P)` |

### 11.3 Bloque CON AGIN (por Responsable)

**AGIN pertenece al módulo de reportes, no al motor de cálculo.** No condiciona el congelamiento del motor.

Sobre el neto TACTICA por responsable se aplican dos tasas fijas:

```
AGIN_1 = SUM(P por responsable) * 0,90%
AGIN_2 = SUM(P por responsable) * 0,40%
```

Este bloque **excluye las líneas sin responsable resuelto**, por lo que sus totales no coinciden con el bloque principal. En el período relevado: `48.598.004,80` (bloque TACTICA) contra `47.246.368,25` (bloque AGIN), diferencia `1.351.636,55`. **Esta diferencia debe reproducirse, no corregirse** — observación O-06.

Los importes de este párrafo son valores del período relevado, no invariantes del motor: como referencia de conciliación corresponden a ese **snapshot fechado**.

**Definición conceptual de AGIN: pendiente documental P-06.** El libro no documenta qué representa cada tasa ni si se aplican en paralelo o alternativamente; se replica el comportamiento observado.

### 11.4 Reportes personales

`Reporte Matias`, `Reporte Cris`, `Reporte Lau` son **vistas** del mismo negocio: cruzan ECOM y TACTICA por subcategoría y período para un PM. **No contienen reglas funcionales propias y no son fuente de verdad.** Se implementan como filtros sobre las vistas de agregación.

---

## 12. Validaciones y controles

Los **bloqueantes** impiden publicar el período. Los **informativos** se muestran y no detienen el cálculo. **Ningún control puede corregir un dato de forma silenciosa.**

| # | Control | Severidad | Comportamiento |
|---|---|---|---|
| V-1 | Comprobante no reconocido | Bloqueante | La línea no se calcula. Único caso hoy: MLA (P-01) |
| V-2 | Nota de débito presente | Informativo | Se excluye automáticamente y se informa |
| V-3 | IVA no resuelto en TACTICA | Bloqueante | No asumir 21 % ni 0. Excluir hasta corrección |
| V-4 | IVA no resuelto en ECOM | Informativo | `AP` inválido; `Z`/`AA`/`AB` se calculan normalmente |
| V-5 | Costo vigente inexistente o 0 en ambas columnas | Bloqueante | No asumir costo 0 |
| V-6 | TC ausente o ≤ 0 | Bloqueante | Sin TC no hay costo en pesos |
| V-7 | Precio de Venta (`P`/`Q`) vacío en una línea no anulada | Informativo | Revisar; puede ser Posventa legítima |
| V-8 | Cuenta 1 con `Z <> 0`, o Cuenta 2 con `S`/`T`/`U`/`Y` distintos de vacío/0 | Bloqueante | Indica régimen mal aplicado |
| V-9 | Comprobante 00007/05007 con `AA <> P` | Bloqueante | La pérdida definitiva no se aplicó |
| V-10 | Nota de crédito con `N > 0` o `P > 0` | Bloqueante | Signo invertido: rompería el reverso |
| V-11 | Comisión Cobro `<> 0` en ECOM | Informativo | Se ignora en el cálculo; se informa |
| V-12 | Retenciones ECOM (`P`) con valor | Informativo | Confirmar que no se deduce (O-03) |
| V-13 | Clasificación sin PM (`SIN PM`) o sin responsable | Informativo | Afecta agregación y bloque AGIN |
| V-14 | Vinculación distinta de `OK` | Informativo | Control operativo de órdenes |
| V-15 | Cuadre de período | Bloqueante | `SUM(AB)` ECOM y `SUM(AA)` TACTICA deben coincidir con los totales de §13.3 |
| V-16 | Duplicados | Informativo | TACTICA: comprobante + SKU. ECOM: número de orden |

---

## 13. Casos de aceptación

**Datos reales del libro vigente.** Tolerancia 0,01 en importes, 0 diferencias de signo, sin redondeos intermedios (§5.7).

La comparación se hace **columna por columna**, no solo sobre el resultado final: dos errores compensados producen el `AA` correcto con columnas incorrectas.

### 13.1 TACTICA

| # | Caso | Entradas | Resultado esperado |
|---|---|---|---|
| T-1 | Cuenta 1 (FEA, 00003-00127071, SKU CF217ACOMP) | `N=6`, `L=2,65`, `V=1500`, `P=31.153,50`, `Q=1,21` | `O=15,90`; `S=6.542,235`; `AG=37.695,735`; `T=-452,35`; `U=-1.557,675`; `W=-23.850,00`; `Y=-1.130,87`; `Z=0`; `AA=4.162,60`; `AB=13,36%` |
| T-2 | Cuenta 1 (FEA, SKU CF230ACOMP) | `N=3`, `L=2,14`, `V=1500`, `P=13.138,65`, `Q=1,21` | `O=6,42`; `S=2.759,12`; `T=-190,77`; `U=-656,93`; `W=-9.630,00`; `Y=-476,93`; `Z=0`; `AA=2.184,01`; `AB=16,62%` |
| T-3 | Cuenta 2 (FAE, 05001-02057831) | `N=3`, `O=189,90`, `V=1500`, `P=363.439,95` | `S`,`T`,`U` vacíos; `W=-284.850,00`; `Y=0`; `Z=-10.903,20`; `AA=67.686,75`; `AB=18,62%` |
| T-4 | Cuenta 2, producto con IVA 10,5 % | `O=17,60`, `V=1500`, `P=65.291,80` | `W=-26.400,00`; `Z=-1.958,75`; `AA=36.933,05`; `AB=56,57%` |
| T-5 | NC Cuenta 1 (CEA, 00003-00009750) | `N=-2`, `O=-5,28`, `V=1500`, `P=-14.208,00`, `Q=1,21` | `S=-2.983,68`; `T=+206,30`; `U=+710,40`; `W=+7.920,00`; `Y=+515,75`; `Z=0`; `AA=-4.855,55` |
| T-6 | NC Cuenta 2 (CVE, 05001-19036008) | `N=-1`, `O=-2,69`, `V=1500`, `P=-4.315,75` | `S`,`T`,`U`,`Y` vacíos; `W=+4.035,00`; `Z=+129,47`; `AA=-151,28` |
| T-7 | Pérdida definitiva (CVA, 00007-00000014) | `P=-299.325,00`, `O=0` | Todo anulado; `AA=-299.325,00` |
| T-8 | Pérdida definitiva con costo (CVA, 00007-00000008) | `N=-6`, `O=-18,12`, `P=-42.450,00` | `W` anulado aunque `O` tenga valor; `AA=-42.450,00` |
| T-9 | Preventa Cuenta 2 (FAE, 05001-02057757) | **Pendiente de verificación contra el libro — §16, verificación V-02** | — |

*Los casos T-1 a T-8 fueron verificados aritméticamente contra las fórmulas de §6.2 y cierran exactos.*

*Nota sobre T-4: el rótulo "IVA 10,5 %" describe el producto, no una condición del cálculo. En Cuenta 2 el factor de IVA es irrelevante porque `S` queda vacío.*

### 13.2 ECOM

| # | Caso | Entradas | Resultado esperado |
|---|---|---|---|
| E-1 | ML Carrito, IVA 10,5 % (orden 1405031) | `G=130,27`; `M=98.898,56`; `O=7.821`; `Q=620.053,636`; `U=682.059`; `AM=1500`; `AO=1,105` | `S=8.184,708`; `T=31.002,6818`; `Z=474.146,686`; `AA=195.405,00`; `AB=278.741,686`; `AE=185,83`; `AF=454,71`; `AV=58,79%`; `AP=753.675,195` |
| E-2 | ML Carrito, IVA 21 % (orden 1405030) | `G=4,98`; `M=7.456,35`; `O=0`; `Q=24.387,603`; `U=29.509`; `AM=1500` | `S=354,108`; `T=1.219,38015`; `Z=15.357,765`; `AA=7.470,00`; `AB=7.887,765`; `AV=51,36%` |
| E-3 | Frávega sin retenciones | `G=2,96`; `M=2.249,85`; `O=0`; `Q=12.395,868`; `U=14.999`; `AM=1500` | `S=179,988`; `T=619,7934`; `Z=9.346,2366`; `AA=4.440,00`; `AB=4.906,2366` |
| E-4 | Posventa | **Pendiente de verificación contra el libro — §16, verificación V-02** | — |

*Los casos E-1 a E-3 fueron verificados aritméticamente contra las fórmulas de §7.1 y cierran exactos. En E-3 las entradas `O` y `AM` no estaban declaradas en el relevamiento; se verificó con `O=0` y `AM=1500` y debe confirmarse.*

### 13.3 Totales de período

**Pendiente de verificación contra el libro — §16, verificación V-02.** El control V-15 depende de estos totales.

---

## 14. Observaciones

Inconsistencias detectadas durante el relevamiento. **Documentadas, no corregidas.** Ninguna se resuelve en esta versión.

| # | Observación | Ubicación |
|---|---|---|
| O-01 | La columna `Margen` informada por Táctica no se usa en ningún cálculo | TACTICA `R` |
| O-02 | La columna `Margen` calculada como `P - W` es incoherente con el margen real y solo es informativa | TACTICA `X` |
| O-03 | Las retenciones informadas por el origen **no se deducen** en ningún cálculo. Se conservan por trazabilidad | ECOM `P` |
| O-04 | La fórmula referencia la hoja `Worksheet`, **que no existe en el libro**: la columna devuelve 0 siempre | ECOM `AT` |
| O-05 | El neto (`Q`) y el bruto (`U`) del origen no guardan la relación del factor de IVA del SKU: 242 órdenes al 10,5 % traen ratio 1,10 y 137 órdenes multi-SKU traen ratios mixtos entre 1,1011 y 1,1941 | ECOM `Q` / `U` |
| O-06 | El bloque AGIN excluye las líneas sin responsable resuelto, produciendo una descuadratura de `1.351.636,55` respecto del bloque TACTICA en el período relevado | §8.2 y §11.3 |
| O-07 | El TC no es función de la fecha: se fija por lote de carga, por lo que una misma fecha puede registrar dos TC distintos | §5.5 |

*El relevamiento original numeraba observaciones hasta O-13. Las siete anteriores son las descritas con evidencia en el informe recibido; las restantes no fueron entregadas y no se reconstruyen.*

---

## 15. Pendientes

Únicamente los casos donde **no existe evidencia suficiente en el libro**.

| # | Pendiente | Alcance | Quién resuelve |
|---|---|---|---|
| P-01 | Régimen del comprobante **MLA** (multipropósito). Es el único comprobante presente en el libro cuyo régimen no está determinado, y el único caso que hoy impide calcular una línea | Cálculo de esas líneas | Funcional |
| P-02 | Significado y origen de las columnas informativas de ECOM: `IVA A Favor`, `Cash`, `Utilidad Venta`, `Utilidad Costo`. No intervienen en el cálculo | Documental | Origen ECOM |
| P-04 | Confirmación del contenido de las **hojas ocultas** del libro (prefijo `0`) | Completitud del relevamiento | Operador |
| P-05 | Listado exacto de **fixture, envíos y SKU auxiliares** que el operador elimina manualmente. No quedó rastro en el archivo | Paridad de totales | Operador |
| P-06 | Definición conceptual de **AGIN**: qué representa cada tasa. **No bloquea el motor**: pertenece al módulo de reportes | Documental | Funcional |

*La numeración conserva la del relevamiento original, que no incluía P-03.*

**Ante duda no resuelta: marcar como pendiente, no inventar.**

---

## 16. Verificaciones abiertas contra el libro

Tres puntos requieren consulta directa al libro y **no pueden resolverse por interpretación ni por recálculo**. Son las únicas condiciones para el congelamiento.

| # | Verificación | Qué hay que obtener | Efecto sobre el documento |
|---|---|---|---|
| **V-01** | Existencia de las secciones 19 a 22 del relevamiento original | Confirmar si existen observaciones y pendientes adicionales a los de §14 y §15 | Si existen, se incorporan. Si no, §14 y §15 quedan como están y la numeración se cierra |
| **V-02** | Valores reales de T-9, E-4, E-5 y totales de período | Fila `05001-02057757` completa (`N`, `L`, `V`, `P`, `O`, `W`, `Y`, `Z`, `AA`) · orden Posventa completa · totales `SUM(AA)` TACTICA y `SUM(AB)` ECOM por período | Completa §13.1, §13.2 y §13.3, y habilita V-15 |
| **V-03** | Comportamiento real del disparador de `Z` | ¿Existe al menos una fila con régimen **Cuenta 1**, `Y = 0` o vacío, y **sin** prefijo de pérdida definitiva? Si existe: qué valor tiene `Z` en esa fila | Si no existe: la regla funcional es **por régimen** (§6.2 paso 6) y la condición `Y <> 0` de la fórmula queda documentada como consecuencia del comportamiento del Excel, sin conflicto. Si existe: se documenta el comportamiento observado exactamente como es |

Ninguna de las tres altera las reglas ya especificadas. Resueltas, este documento queda congelado.

---

*Fin de la especificación funcional. El diseño técnico está en `RENTABILIDAD_IMPLEMENTACION.md`, subordinado a este documento.*
