# 03 — MÓDULO FULL Y CONCILIACIÓN DE STOCK · MERCADO LIBRE
## Para Claude Code · Agosto 2026

> Este documento es el **detalle de la Fase 6 (stock)** definida en
> `01_MAPA_API.md` §4. No es una fase paralela: es qué construir y en qué orden
> dentro de esa fase.

> **Antes de arrancar, leer en este orden:** `../../00_LEEME`, después
> `01_MAPA_API` para ubicar los recursos, y **consultar el MCP de
> documentación de Mercado Libre** (`02_MCP`) al momento de implementar cada
> endpoint. Si el mapa y el MCP no coinciden, **manda el MCP.**
>
> **Aclaración de alcance sobre ECOM.** El `../../00_LEEME` §5 posterga la implementación
> hasta que Rentabilidad cierre, y §8 excluye la documentación de Táctica y ECOM de la carpeta.
> Ambas siguen vigentes **para escritura**. Este módulo necesita
> **solo lectura** de ECOM: el stock del depósito Full por SKU, y el factor de descuento
> configurado en la vinculación de cada publicación. Leer está habilitado; escribir no.

---

## 1. Qué es esto

Un módulo del ERP para administrar el stock en Mercado Libre Full y la operación de
marketplaces. Hoy vive en una planilla de Excel que se arma bajando reportes a mano. El
objetivo es llevarlo a sistema.

Antes de tocar código: **este documento explica el problema conceptual que hay que resolver.**
No es un problema de integración, es un problema de medición. Si se implementa la integración
sin entender esto, el sistema va a reproducir el error que ya tenemos, con mejor tecnología.

---

## 2. El problema central: la demanda censurada

### Lo que pasa hoy

Se manda mercadería a Full. Se baja el reporte mensual de ventas. Se repone según ese número.

El reporte dice "vendió 30 unidades en 30 días". Se interpreta como una demanda de 1 por día y
se mandan 30 para el mes siguiente. Pero esas 30 unidades se vendieron **en un día**, y los
otros 29 el producto estuvo en cero.

**El reporte no mide la demanda. Mide cuánto le dejamos comprar al cliente.**

Es circular: la venta observada es el resultado de nuestra propia decisión de envío. Mandamos
30, vendemos 30, concluimos que la demanda es 30, mandamos 30. Para siempre. Y el producto
queda subabastecido de forma permanente sin que ningún reporte lo muestre.

### Cómo se detecta

La señal es simple: **si las ventas son iguales a lo enviado, el número es un piso, no una
medición.** Vendió eso o más, y no sabemos cuánto más.

### La corrección

```
Ventas diarias = unidades vendidas / DÍAS QUE TUVO STOCK
```

No dividido por los días del período. Si vendió 30 unidades en 5 días con stock y después
estuvo en cero, la tasa es 6 por día, no 1. La reposición pasa de 30 a 126.

### Qué tan grande es el problema, medido

Sobre la cuenta IT, período de 32 días al 11/08/2026:

| | |
|---|---|
| SKUs en Full | 122 |
| SKUs con dato censurado | 32 |
| Ventas diarias según el reporte mensual | 40,5 u/día |
| Ventas diarias corregidas | 76,1 u/día |
| **Subestimación** | **1,88 veces** |
| SKUs en cero en Full ahora mismo | 45 de 122 |

---

## 3. El alcance concreto del módulo

Dos cosas, y en este orden:

1. **Replicar lo que hace la planilla, pero con datos traídos en vivo por API** en lugar de
   reportes descargados a mano.
2. **Agregar la conciliación de stock** entre Mercado Libre y ECOM, que hoy se hace a mano cada
   quince días.

Traer el armado del envío al ERP viene después. Primero que el dato sea certero.

### 3.1 La conciliación de stock — cómo funciona

**El único sistema que maneja el depósito de Full es ECOM.** En ECOM el stock del depósito Full
está **por SKU**: un número único.

En Mercado Libre, ese mismo SKU puede estar en varias publicaciones, repartidas entre **las dos
cuentas**. Ejemplo real de la estructura:

```
ECOM · depósito Full · SKU TN1060COMP  →  1.000 unidades

Mercado Libre:
  Cuenta ARG    5 publicaciones
  Cuenta GROUP  5 publicaciones
                8 son simples
                2 son packs

  Suma de las 10 debe dar  →  1.000 unidades
```

**Si no da 1.000, el sistema marca diferencia.** No hace falta que la diagnostique: alcanza con
que la muestre, con el número de cada lado y la lista de publicaciones que la componen. La
búsqueda del error la hace una persona.

### 3.2 La trampa de los packs — resolver esto ANTES de escribir la conciliación

**Una publicación de pack informa cantidad de packs, no de unidades.**

Si un pack x2 dice 50 disponibles, son **100 unidades**. Si el sistema suma la cantidad tal como
viene, va a dar diferencia en todos los SKUs que tengan pack, siempre. Y un módulo de
conciliación que da falsos positivos el primer día pierde toda credibilidad y nadie lo vuelve a
usar.

La fórmula correcta:

```
Total del SKU en ML = Σ (cantidad disponible × factor del pack)
                      sobre todas las publicaciones, de las dos cuentas
```

Para las publicaciones simples el factor es 1.

### De dónde sale el factor — decidido

**El factor es la cantidad que la publicación descuenta según la vinculación en ECOM.**

ECOM es el sistema que maneja el depósito Full y es donde se configura cuántas unidades
descuenta cada publicación vinculada. El factor tiene que salir de ahí y no de otro lado, por un
motivo estructural: **el factor tiene que venir del mismo sistema que tiene el stock.** Si
viniera del nombre del SKU en ML, estaríamos comparando dos fuentes de verdad distintas y
cualquier desajuste entre ellas se leería como diferencia de stock.

### El sufijo del SKU es el control, no la fuente

En ML los SKU de pack llevan agregado un `X2`, `X5`, `X10` según la cantidad. **Eso es manual y
se le puede errar, así que no sirve como fuente.** Pero sí es el único control externo
disponible, y hace falta.

El motivo: si el factor sale del descuento de ECOM, la conciliación queda **consistente por
construcción**, y por eso mismo no puede detectar un descuento mal configurado. Si alguien
vinculó un pack x2 con descuento 1, ECOM descuenta 1 por venta, la suma cierra perfecto contra
sí misma, y el stock real se va desviando sin que salte ninguna alerta. Es el peor tipo de
error: una mentira coherente.

**Los tres roles, que no hay que mezclar:**

| Fuente | Rol |
|---|---|
| Descuento configurado en la vinculación de ECOM | **El factor.** Es lo que se usa para calcular |
| Sufijo `X2` / `X5` / `X10` del SKU en ML | **El control.** No calcula, verifica |
| Desacuerdo entre los dos | **Alerta propia.** Vinculación mal cargada o SKU mal nombrado |

El tercero es una alerta de configuración, no de stock, y tiene que aparecer aparte de las
diferencias de inventario. Son problemas distintos con soluciones distintas.

### 3.3 La clave de agregación es el inventario, no la publicación

Verificado sobre los datos actuales: hay 18 SKUs con más de una publicación. En 11 casos cada
publicación tiene stock distinto, o sea inventarios separados, y sumar está bien. En 7 casos
todas las publicaciones muestran el mismo número — pero todas están en cero, así que hoy no
infla nada.

**Sumar por publicación funciona hoy por casualidad, no por diseño.** El mapa (§2.3) confirma
que el `inventory_id` es **uno por variación**, no uno por publicación. Es decir: dos
publicaciones de la misma variación **comparten inventario**, informan el mismo stock, y
sumarlas lo duplica.

**La cadena correcta es:**

```
publicación (item_id)
   → /items/{item_id}          → inventory_id
   → deduplicar por inventory_id
   → /inventories/{inventory_id}/stock/fulfillment
   → mapear inventory_id → SKU
   → aplicar factor de pack
   → sumar por SKU, en las dos cuentas
   → comparar contra el depósito Full de ECOM
```

**La deduplicación por `inventory_id` no es opcional.** Sin ella, todo SKU con publicaciones
duplicadas sobre el mismo inventario va a mostrar diferencia falsa contra ECOM.

### 3.4 Fragmentación — un hallazgo que conviene que el módulo muestre

El SKU `CB435A-436A-CE285AUNIVCOMP` tiene **12 publicaciones activas** con el stock repartido
así: 312, 60, 56, 53, 27, 20, 16, 9, 8, 4, 1 y 0. Son 566 unidades partidas en doce pedazos, y
como cada publicación tiene su propio inventario, ninguna se abastece de las otras.

Las publicaciones de 1 y 4 unidades se agotan el primer día. La de 312 carga toda la venta.

Esto rompe cualquier lógica de reposición por publicación, y es parte de por qué el dato de
ventas viene tan censurado. El módulo tiene que mostrar la dispersión del stock entre
publicaciones de un mismo SKU, no solo el total.

### 3.5 Una publicación muerta que era la que más vendía

En el mismo SKU, la publicación `1432411017 | 614660500` vendió **719 unidades en 30 días**,
tiene stock cero, stock promedio 313, y el campo de estado viene **vacío**.

Vendía más que la publicación principal y hoy no vende nada. Es el caso exacto de "publicación
caída que se lee como falta de demanda". El módulo tiene que detectar esto: una publicación con
historial de venta alto que pasa a cero es una alerta, no un dato.

### 3.6 Cuando hay diferencia, dar el timestamp de cada lado

El sistema no necesita diagnosticar el error, pero sí tiene que acortar la búsqueda. Si ML dice
566 y ECOM dice 520, la diferencia puede ser que ML recibió y ECOM no descontó, o que ECOM
descontó una venta que ML todavía no procesó.

Mostrando **la fecha y hora del último movimiento de cada lado**, la persona resuelve en un
minuto lo que si no le lleva media hora. Es barato de agregar y es lo que hace que la
conciliación sea usable.

### 3.7 Las dos cuentas no son opcional

La operación tiene dos cuentas de Mercado Libre. **La conciliación no funciona con una sola:**
si el SKU está en las dos y solo se lee una, la suma nunca va a dar contra ECOM y todos los
SKUs compartidos van a aparecer como diferencia.

Esto no es una mejora para la fase dos. Es requisito de la fase uno.

---

## 4. Recursos de la API — lo resuelto y lo abierto

**Usá el mapa y el MCP, no supongas.** El documento `01_MAPA_API` ya
tiene ubicados los recursos por necesidad de negocio, con el slug de cada página. Pero el mapa
refleja el portal al momento del relevamiento: **confirmá cada endpoint con el MCP de
documentación antes de implementarlo.** No transcribas parámetros de ejemplos viejos.

Lo que sigue son las **necesidades** de este módulo, en orden de valor. El mapa te dice dónde
buscar cada una.

### 4.1 Prioridad uno: el log de movimientos de inventario en Full

Existe un reporte en el panel de ML que, **por cada SKU**, muestra la fecha y hora exacta en
que ingresó cada envío y la fecha y hora en que se vendió cada unidad. Hoy hay que abrirlo de a
un SKU, lo que lo hace inutilizable a escala.

**Buscá si eso está disponible por API.** Con ese log:

- Se reconstruye la curva de stock de cualquier SKU en cualquier momento del pasado
- Los días con stock se calculan **exactos**, no estimados
- Se sabe cuánto duró cada envío
- Se sabe cuántos días estuvo en cero, que es la venta perdida
- Y se puede calcular hacia atrás, sin esperar a acumular datos nuevos

Esto es lo más valioso de toda la integración. Si esto está disponible, el resto es secundario.

**Términos por los que buscar:** operaciones de inventario, movimientos de stock de
fulfillment, historial de stock, inbound y outbound de fulfillment.

### 4.2 Si el log no está disponible: foto diaria

Plan alternativo. Un proceso automático que guarde todos los días el stock por SKU en Full.

- **A hora fija.** Si una corrida es a las 9 y otra a las 21, el cálculo de días con stock
  queda mal.
- **Con alerta si falla.** Un día sin foto es un día que no se puede calcular. Un proceso
  automático que falla en silencio es igual de malo que una persona que se olvida.
- Es un parche: solo sirve hacia adelante, y hay que esperar semanas para tener datos.

### 4.3 Detección de quiebre anticipado

Esto es una funcionalidad nueva, no existe hoy en ninguna forma.

**El requisito previo, que hoy no se cumple: guardar el pronóstico en el momento del envío.**
Cuando se manda una cantidad, hay que registrar la tasa esperada y la fecha estimada de
agotamiento. Sin ese número guardado no hay contra qué comparar y la detección es imposible
por definición.

Después, comparar el stock real contra el esperado. Hay cuatro desvíos y **son diagnósticos
distintos**:

| Desvío | Qué significa | Qué hay que leer |
|---|---|---|
| Baja más rápido de lo esperado | La demanda es mayor que la modelada. Va a quebrar antes | stock disponible |
| Dejó de bajar | Murió la demanda, o murió la exposición | stock + visitas |
| Publicación pausada o cerrada | Muerte declarada | estado y sub-estado de la publicación |
| **Perdió el catálogo** | Sigue activa, con stock, y vende cero | condición de ganador de catálogo |

**El cuarto caso es el más importante, y resulta que es el más barato de resolver.** En
publicaciones de catálogo se puede dejar de ser el ganador del recuadro de compra sin que la
publicación cambie de estado: queda activa, con stock, todo se ve bien, y vende cero. Ningún
indicador de stock lo detecta.

**Ya está resuelto en el mapa (§2.2) y no requiere consultar periódicamente.** El tópico de
notificación `catalog_item_competition_status` avisa cuando cambia el ganador, y está
disponible en Argentina. Además `/items/{item_id}/price_to_win?version=v2` devuelve el estado
actual, quién gana y a qué precio habría que ir para ganar.

Es la alerta de mejor relación valor/esfuerzo de todo el módulo: explica caídas de venta que
hoy se atribuyen a falta de demanda.

**Para enterarse: dos caminos.**

- **Consultar periódicamente** — pedirle a ML el estado cada X horas. Simple, gasta llamadas.
- **Suscribirse a notificaciones** — ML avisa cuando algo cambia. Es el camino correcto para
  esto: se detecta en el momento, no en la próxima corrida. Verificá qué temas de notificación
  existen hoy para stock de fulfillment, cambios de publicación y órdenes.

### 4.4 Visitas por publicación

Hoy no tenemos este dato y es el que resuelve una ambigüedad crítica.

Un SKU con stock y cero ventas puede ser dos cosas completamente distintas:

- **Cero visitas** → problema de exposición. La publicación está caída, perdió el catálogo, o
  nunca tuvo tráfico
- **Visitas sin venta** → problema de precio o de contenido

Sin visitas, las dos se ven iguales y se tratan igual, que es lo que pasa hoy.

**Ya está en el mapa (§2.10):** `/users/{user_id}/items_visits?date_from=X&date_to=Y`, con tope
de 150 días, más un endpoint a nivel ítem. Las visitas de la competencia no están expuestas,
solo las propias — para este uso alcanza.

### 4.5 Cargos y antigüedad de stock

Ver si están por API o si hay que seguir bajando el reporte a mano. Necesitamos por SKU: las
unidades almacenadas con su antigüedad en días, el cargo por unidad y el cargo total.

Esto importa por un motivo concreto que está en la sección 6.

### 4.6 Dos cuentas

La operación tiene **dos cuentas de Mercado Libre**: IT (seller 115764017) y MT (seller
34801784). Todo lo de arriba tiene que funcionar para las dos, con la cuenta como dimensión.
La planilla actual solo cubre IT, y eso es una limitación que hay que resolver.

---

## 5. Lo que la planilla ya calcula y el sistema tiene que replicar

La planilla `FULL_TABLA_OPERATIVA.xlsx` es la especificación funcional. Está toda en fórmulas,
así que la lógica se puede leer directo de las celdas. Lo esencial:

```
Ventas diarias simple      = ventas 30 días / 30
Estado del dato            = CENSURADO si (stock = 0 y unidades ≥ 5 y días sin vender ≥ 3)
                             o si (rotación ≥ 3 y unidades ≥ 10)
Ventas diarias corregida   = si CENSURADO: unidades / ventana con stock
                             si no: unidades / días del período
Rotación                   = ventas 30 días / stock promedio 30 días
Stock objetivo             = ventas diarias corregida × semanas objetivo × 7
Falta enviar               = máx(0, stock objetivo − stock en Full − envíos pendientes)
Disponible                 = stock Táctica + stock ECOM
Enviar posible             = mín(falta enviar, disponible)
Cobertura en días          = (stock en Full + envíos pendientes) / ventas diarias corregida
Quiebre estimado           = fecha de corte + cobertura
```

**La "ventana con stock" es hoy una estimación:** días entre la primera y la última venta del
período, asumiendo que la última venta es el día en que se agotó. Con el log de movimientos de
la sección 4.1 pasa a ser exacta. **Ese es el reemplazo más importante que tiene que hacer el
sistema.**

---

## 6. El límite de los 180 días

El cargo por stock antiguo en Full sube por tramos de antigüedad. Los valores actuales:

| Antigüedad | Cargo por unidad |
|---|---|
| Hasta 4 meses | $0 |
| 4 a 6 meses | $470 |
| Más de 6 meses | **$4.485** |

**Nueve veces más al cruzar los 180 días.** Es un salto, no una progresión.

Hoy hay 875 unidades en la franja de 4 a 6 meses. Pero la mayoría está en SKUs que van a
vender antes del corte, así que se resuelven solas. Las que importan son las que **no** venden
a tiempo: 108 unidades, con un aumento evitable de $433.620. Y las más urgentes están a 10
días del corte.

**Lo que tiene que hacer el sistema:** por cada SKU con unidades en la franja de 4 a 6 meses,
comparar los días que faltan para los 180 contra la cobertura actual. Si la cobertura es mayor
que los días restantes, esas unidades no se van a vender antes del salto. Eso es una alerta con
fecha, y hay que dispararla con anticipación suficiente para poder actuar.

Las tarifas cambian: tienen que ser configurables, no constantes en el código.

---

## 7. El límite que no está en Full

De 2.628 unidades que faltan enviar para cubrir el objetivo de tres semanas, **solo 1.314 se
pueden enviar**. El resto no existe en Táctica ni en ECOM.

Y hay 6 SKUs en cero en Full, con demanda comprobada, y **sin una sola unidad disponible en
ningún depósito**.

**Eso significa que la mitad del problema de Full no se resuelve en Full: se resuelve en
compras.** El sistema tiene que mostrar esa distinción explícitamente, porque son dos
decisiones de dos personas distintas. Cuando la falta de stock propio es el límite, la alerta
no es de logística: es de abastecimiento, y tiene que escalar a otro lado.

Por eso el stock de Táctica y de ECOM tiene que estar **en vivo** en este módulo. Armar un
envío de algo que no tenemos es trabajo perdido, y hoy pasa.

---

## 8. Hacia dónde va el rol

El puesto hoy mantiene la operación sincronizada y concilia diferencias. Hacia donde apunta:
**decidir qué merece estar en Full.**

Esa decisión hoy no la toma nadie de forma explícita: se hereda de lo que se mandó en su
momento. Y es la más importante, porque Full es el único lugar donde equivocarse cuesta dos
veces — se paga almacenamiento por lo que no debería estar, y se pierden ventas por lo que
debería estar y no está.

Tres cosas que se derivan de eso:

**La conciliación es un síntoma, no una tarea.** Si hay que reconciliar cada quince días es
porque la sincronización no es confiable. Una de las causas ya está identificada: doble
descuento por órdenes viejas cerradas. Si el sistema arregla la causa, la tarea desaparece.

**Hay que poder probar productos nuevos de forma continua.** Rotar qué se manda a Full,
medir qué funciona y qué no, con reglas de corte definidas. El sistema tiene que registrar cada
prueba y su resultado. Y algo que hay que tener claro: **que un producto de prueba se agote
rápido es el mejor resultado posible, no un error de cálculo.** Lo que no puede pasar es que se
agote y se repong la misma cantidad — que es exactamente el círculo de la sección 2.

**La pregunta que nadie hace: ¿este SKU vende más *por estar* en Full?** Todo el sentido de
Full es que convierte mejor. Si un producto vende lo mismo con Full que sin Full, se está
pagando depósito por nada. Comparar la conversión del mismo SKU en Full contra su publicación
sin Full es el dato que decide qué merece estar ahí, y hoy no lo tenemos.

---

## 9. Lo que sí es información y no una tarea pendiente

Dos cosas que aparecieron midiendo y que conviene que estén en el sistema:

**El reporte de cargos y el de stock tienen cortes de fecha distintos.** Puede haber SKUs con
más unidades con cargo que unidades en stock. No es un error: son fotos de momentos
diferentes. Si el sistema los cruza sin tener en cuenta la fecha de cada fuente, va a producir
inconsistencias que parecen bugs.

**Un SKU puede tener varias publicaciones.** El stock se suma pero las ventas se miden por
SKU. Hay que manejar esa relación explícitamente y no asumir uno a uno.

---

## 10. Orden de construcción — Fase 6

Los puntos 1 a 4 son la conciliación y **se validan solos**: dan o no dan. Esa es la razón por
la que este módulo va primero y no el de competencia.

| # | Qué | Depende de |
|---|---|---|
| 1 | Leer el **factor de pack** desde la vinculación de ECOM, y el sufijo `X2`/`X5`/`X10` del SKU en ML como control. El desacuerdo entre los dos es una alerta de configuración, aparte de las de stock | Pregunta abierta 3 |
| 2 | Traer publicaciones de **las dos cuentas** → `inventory_id` → **deduplicar** → stock de fulfillment con detalle por causa | §2.3 del mapa |
| 3 | Mapear inventario a SKU, aplicar el factor de pack, sumar por SKU | 1 y 2 |
| 4 | **Conciliar contra el depósito Full de ECOM**, con el timestamp del último movimiento de cada lado y el desglose por causa cuando hay diferencia | 3 |
| 5 | **Ventas con fecha** por publicación (§2.5) para calcular el diario y marcar el dato censurado | — |
| 6 | Averiguar el **log de movimientos de inventario** (pregunta abierta 1). Si existe, reemplaza la ventana estimada por el dato exacto y funciona hacia atrás | Pregunta abierta 1 |
| 7 | Suscribir **`fbm_stock_operations`** y **`orders_v2`** para dejar de consultar periódicamente | §2.7 |
| 8 | Suscribir **`catalog_item_competition_status`** — detección de pérdida de catálogo | §2.2 |
| 9 | **Visitas** por ítem, para separar problema de exposición de problema de precio | §2.10 |
| 10 | **Cargos y antigüedad**, con la alerta del límite de 180 días | Pregunta abierta 2 |
| 11 | Guardar el **pronóstico al momento del envío**, que habilita la detección de quiebre anticipado | 5 |
| 12 | **Stock de Táctica y ECOM en vivo** dentro del módulo |  |

**Nota sobre el punto 7 y las reglas del mapa (§3):** toda escritura pasa por cola, idempotente,
con reintentos y backoff. Este módulo es de **lectura**, así que no escribe al canal — pero sí
tiene que respetar los rate limits al leer las dos cuentas, que comparten límite por app.
