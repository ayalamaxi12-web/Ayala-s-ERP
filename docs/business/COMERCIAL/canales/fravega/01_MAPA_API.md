# 01 — MAPA API · FRÁVEGA (VTEX)

## Relevamiento del 13/08/2026 · Alcance: Rentabilidad

> Nota de método: cada afirmación indica su fuente y URL. Cuando el dato surge de mi propia deducción (combinando dos fuentes) y no de una lectura directa, está marcado explícitamente como **[INFERENCIA]**. Cuando algo no pude confirmarlo, dice **NO ENCONTRADO** y por qué.

---

## 1. Sobre qué corre y cómo se autentica

Confirmado: el marketplace de Frávega corre sobre **VTEX**. Frávega es el "marketplace" (dueño de la tienda VTEX) y cada seller (como Workent) se integra como vendedor externo.

Para dar de alta la integración VTEX, Frávega pide ([Centro de ayuda · Integraciones/VTEX](https://sites.google.com/fravega.com.ar/marketplace/integraciones/vtex)):
- Seller ID, razón social, CNPJ/CUIT, email del administrador
- Fulfillment endpoint y Catalog endpoint (URLs que expone el seller para que VTEX/Frávega le hable)
- **Dos pares de credenciales VTEX** (AppKey + AppToken): una para actualizar precio/stock, otra para configurar la logística vía Envío Pack

Autenticación estándar de la API de VTEX (leído en [developers.vtex.com/docs/api-reference/orders-api](https://developers.vtex.com/docs/api-reference/orders-api)):
- Headers `X-VTEX-API-AppKey` + `X-VTEX-API-AppToken` (clave de aplicación), o
- Header `VtexIdclientAutCookie` (token de usuario, válido 24 h)

Aparte de la API de VTEX, Frávega tiene **tres portales propios con login separado** (no son la API de VTEX, son paneles web):
- **Seller Center** — `https://seller-center.fravega.com/` (alta/edición de productos, procesar facturación, módulo de órdenes, descarga de liquidación, cuotas)
- **Portal de Proveedores** — `https://portalproveedores.fravega.com/interaction/` (fechas de pago, datos impositivos, seguimiento de siniestros, email de facturación)
- **Envíopack** — `https://app.enviopack.com/login` (gestión de envíos/etiquetas, un tercero logístico)

EcomExperts (ECOM) se describe en la propia página de Frávega como un ERP nativo de e-commerce que sincroniza stock, precio, ventas y adjunta facturas automáticamente ([Integraciones/EcomExperts](https://sites.google.com/fravega.com.ar/marketplace/integraciones/ecomexperts)), pero el detalle técnico de cómo ECOM lee las órdenes (si vía API de VTEX directamente o vía un middleware propio) no está documentado en esa página.

---

## 2. Identificadores de orden y vinculación con ECOM

**Esta es la sección más importante y la que menos pude cerrar del todo — ver el punto 4 más abajo.**

### 2.1 Identificadores que expone la orden de VTEX

Leído directamente del esquema de respuesta de `GET /api/oms/pvt/orders/{orderId}` (especificación OpenAPI oficial, `https://developers.vtex.com/api/openapi/orders-api`):

| Campo | Tipo | Descripción (traducida literal) |
|---|---|---|
| `orderId` | string | ID del pedido (interno de VTEX). Ejemplo real de la doc: `1172452900788-01` |
| `sequence` | string | Número de secuencia, parte del `orderId`. En el ejemplo `v70530116str-01`, la secuencia es `70530116` |
| `marketplaceOrderId` | string | **ID del pedido del Marketplace** (o sea, de Frávega) |
| `sellerOrderId` | string | **ID del pedido del vendedor** (el que el seller — en este caso, vía VTEX, potencialmente ECOM — le asigna) |
| `marketplaceServicesEndpoint` | string | Endpoint que provee el marketplace para comunicación post-compra |
| `origin` | enum | `Marketplace` \| `Fulfillment` \| `Chain` |
| `affiliateId` | string | Código de 3 letras configurado por el seller para identificar un marketplace |
| `salesChannel` | string | ID del canal de ventas / política comercial |
| `merchantName` | string\|null | Nombre del comerciante (en tienda VTEX propia es igual al nombre de cuenta; en seller externo puede diferir) |

Además, a nivel `sellers[]` (array): `id`, `name`, `logo`, `fulfillmentEndpoint` (URL que usa el marketplace para hablarle al seller).

### 2.2 ¿Cuál ve el vendedor en el panel de Frávega?

**NO ENCONTRADO como lectura confirmada.** El Centro de ayuda de Frávega dice que el "Módulo de Órdenes" de Seller Center permite "descargar detalle de las órdenes y su estado, ver información del cliente para poder facturar" ([Integraciones/Seller Center](https://sites.google.com/fravega.com.ar/marketplace/integraciones/seller-center)), pero no especifica qué identificador exacto se muestra en pantalla. No tengo credenciales para entrar al Seller Center real y confirmarlo con una orden viva.

**[INFERENCIA]** Por arquitectura estándar de un marketplace VTEX: lo más probable es que Frávega, como dueño de la cuenta VTEX, muestre el `orderId` (o el `marketplaceOrderId`, que en un pedido de marketplace suele coincidir con el `orderId` de la cuenta del marketplace) como "número de orden" visible al vendedor. El `sellerOrderId` es el que, en teoría, el propio vendedor (o su integrador, acá ECOM) le devuelve a VTEX — así que si ECOM ya está seteando ese campo, ahí mismo tendrías tu propia referenciaande vuelta. Esto hay que confirmarlo mirando una orden real en Seller Center.

### 2.3 ¿La documentación de VTEX indica cuál se comparte con el sistema del vendedor cuando hay integrador?

Confirmado por lectura: sí, hay dos campos pensados exactamente para esto — `marketplaceOrderId` (ID que pone el marketplace) y `sellerOrderId` (ID que pone el vendedor/su sistema). El campo `sellers[].fulfillmentEndpoint` es el canal por el que VTEX/Frávega notifican al sistema del seller. Cuál de los dos círculos (marketplaceOrderId o sellerOrderId) ya "sabe" ECOM depende de cómo esté armada la integración VTEX↔ECOM, que no pude ver.

### 2.4 Punto 4: ¿ECOM tiene un campo con el número de orden de Frávega?

**NO ENCONTRADO — no pude verificarlo.** No tengo acceso al panel de ECOM (requiere credenciales de la cuenta de Workent que no me diste, y no debo intentar loguearme). Esto es exactamente lo que dijiste que ya sabías resolver "a mano" — necesito que alguien con acceso al panel de ECOM mire una orden y me diga si existe un campo tipo "referencia externa" / "número de canal" / "orden externa", y qué valor tiene (para poder cruzarlo contra `orderId`, `marketplaceOrderId` o `sellerOrderId` de VTEX). **Esta es la pregunta que más espero que resuelvas vos o alguien con ese acceso, tal como pediste.**

---

## 3. Comisión del canal

### 3.1 Tarifario general (tasa)

Leído en el [Cuadro Tarifario Marketplace Frávega](https://sites.google.com/fravega.com.ar/marketplace/tarifario):

> **Comisión Base: 15% + impuestos**

No hay, en esa página, una tabla de comisión desagregada por categoría de producto — solo aparece esta tasa base única. **No pude confirmar si existen tasas especiales por categoría** (el documento no las muestra; puede que no existan, o que estén en otro lado no enlazado desde ahí).

### 3.2 A nivel API (por orden/ítem)

Leído del esquema de la Orders API (mismo spec OpenAPI):

| Campo | Nivel | Tipo | Descripción |
|---|---|---|---|
| `items[].commission` | **Ítem** (no orden) | integer (centavos) | "Commission value registered for the seller" |
| `items[].freightCommission` | **Ítem** | integer (centavos) | "Value of the freight commission" (comisión sobre el envío, separada) |

Es decir: la API **sí** trae un monto de comisión, pero es un **monto ya calculado en centavos por ítem**, no un porcentaje, y hay que sumarlo entre todos los ítems de la orden para tener el total. La documentación no aclara si ese monto ya incluye impuestos o no.

### 3.3 ¿Antes o después de impuestos? ¿Estimado o definitivo?

**[INFERENCIA]** Cruzando tres fuentes:
- La [Liquidación](https://sites.google.com/fravega.com.ar/marketplace/administración/liquidación) muestra una fila **"Total Comisiones"** explícitamente aclarada como "importes... sin impuestos".
- La [Facturación](https://sites.google.com/fravega.com.ar/marketplace/administración/facturación) muestra que ese monto de comisión se factura después, con **IVA 21% + Percepción IIBB** agregados encima, en una factura separada de **Frávega Tech S.A.** (concepto "USO DE PLATAFORMA WEB" = la comisión base).
- La Liquidación **se descarga únicamente desde Seller Center**, por período (no vi ninguna mención de que exista vía API).

Conclusión razonable (pero no 100% verificada empíricamente): el campo `items[].commission` de la orden es probablemente una **estimación** calculada por VTEX/Frávega en el momento de la venta (usando la tasa del tarifario), sin impuestos todavía. El monto **definitivo** — el que de verdad se cobra — solo se confirma en la Liquidación al cierre del período, y ahí es donde se agregan los impuestos vía la factura de Frávega Tech S.A. Si hay ajustes entre la venta y la liquidación (por ejemplo por una promo, un cambio de tasa, o una corrección), no encontré un campo específico que documente esa diferencia — la Liquidación tiene una pestaña "Ajustes" que probablemente la contenga, pero no pude ver su contenido en detalle.

**Recomendación concreta para tu automatización:** no confíes ciegamente en `items[].commission` de la API como el número final — necesitás correr un experimento real (comparar ese valor contra la Liquidación de la misma orden una vez cerrado el período) antes de dar por buena la comisión "de la API".

---

## 4. Costo de envío

Acá hay una distinción importante que probablemente explica por qué hoy lo corrigen a mano: **el costo de envío que ve la API de VTEX no es el mismo concepto que el "Fee Logístico" que le cobra Frávega al vendedor.**

### 4.1 Lo que trae la orden de VTEX (leído del esquema)

| Campo | Nivel | Descripción |
|---|---|---|
| `totals[]` (con `id: "Shipping"`) | Orden | Total de envío como componente del total de la orden — **es lo que paga el comprador**, no lo que se le cobra al vendedor |
| `shippingData.logisticsInfo[].price` / `.listPrice` / `.sellingPrice` | Ítem | Precio de envío por ítem, también de cara al comprador |

Es decir: estos campos reflejan el envío **cobrado al comprador** en el checkout, no el costo real que Frávega le descuenta al vendedor.

### 4.2 El costo real al vendedor (Fee Logístico) — solo en el Centro de ayuda / Liquidación

Leído en [Fee Logístico](https://sites.google.com/fravega.com.ar/marketplace/envíos/fee-logístico) (página fechada "Válido desde el 6/03/2026") y en el Tarifario:

- El Fee se calcula por **"kilo aforado"**: el mayor valor entre el peso real del producto con su packaging y el peso volumétrico (cm³/4000).
- Hay dos tablas de escalas: **"Con colecta"** y **"Sin colecta" (Fee 2, para Fulfillment)**, cada una con un descuento especial para **órdenes menores a $35.000**.
- Las tarifas están expresadas **sin impuestos** (excluyen IVA/IIBB/percepción de IVA).
- Existe además un fee de **Logística Inversa** (devoluciones), calculado con la misma escala de peso pero variando según la **zona de entrega** (Amba, Nordeste, Noroeste, Pampeana, Patagonia).

Este Fee Logístico **no aparece como campo en el JSON de la orden de VTEX** — es una tabla comercial propia de Frávega, aplicada y facturada aparte (ver Liquidación/Facturación abajo).

### 4.3 ¿Disponible en el momento de la venta o recién en la liquidación?

Mismo patrón que la comisión: la Liquidación tiene una fila **"Total Servicios logísticos - Fee"**, separada de "Total valor de envío" (que es lo cobrado al comprador), y se factura aparte por **Frávega S.A.C.I. e I.** con IVA 21% + percepciones. No encontré un campo de la API que devuelva directamente "esto es lo que te vamos a descontar por fee logístico" — la única fuente confiable que vi es la tabla de tarifario (para estimar vos mismo el fee según peso/zona) combinada con la Liquidación real al cierre.

**[INFERENCIA]:** para estimar el fee logístico al momento de la venta (sin esperar la liquidación), tu sistema tendría que calcularlo vos mismo aplicando la tabla de escalas del Tarifario/Fee Logístico sobre el peso aforado del producto — VTEX no te lo devuelve calculado.

### 4.4 ¿Diferencia entre estimado y cobrado?

No encontré un campo o reporte específico que muestre "estimado vs. real" lado a lado. La pestaña **"Ajustes"** de la Liquidación es la candidata más probable para reflejar correcciones, pero no pude ver su contenido.

---

## 5. Tarifas, penalidades y liquidaciones

### Tarifario
[sites.google.com/fravega.com.ar/marketplace/tarifario](https://sites.google.com/fravega.com.ar/marketplace/tarifario) — Comisión Base 15%+impuestos, tabla de Fee Logístico (con/sin colecta), tabla de Logística Inversa por zona, resumen de penalidades, link a cuadro de localidades (no lo abrí).

⚠️ Nota: existe una segunda página, [Fee Logístico](https://sites.google.com/fravega.com.ar/marketplace/envíos/fee-logístico), con valores algo distintos y fechada "Válido desde el 6/03/2026" (valores sin IVA). El Tarifario general no muestra fecha de vigencia. Si vas a automatizar el cálculo, usá la página de Fee Logístico como fuente porque está versionada.

### Costos Fee Logístico
Ver punto 4.2 arriba. Fórmula del peso aforado y tablas confirmadas.

### Penalidades
[sites.google.com/fravega.com.ar/marketplace/envíos/penalidades](https://sites.google.com/fravega.com.ar/marketplace/envíos/penalidades):
- **Despacho tardío:** recargo del 7% sobre el valor del producto despachado, si el despacho ocurre desde el 2do día hábil posterior al plazo pactado (excluye reenvíos por cambios). Tope **$20.000** por incumplimiento.
- **Cancelaciones excesivas:** si las cancelaciones atribuibles al seller (falta de stock, error de precio/publicación) superan el 3% del total de ventas, recargo del 20% sobre el valor de las ventas canceladas. Tope **$40.000**.
- Estos topes rigen desde el 1/1/2025 (antes eran distintos, según nota en la misma página).

### Liquidaciones
[sites.google.com/fravega.com.ar/marketplace/administración/liquidación](https://sites.google.com/fravega.com.ar/marketplace/administración/liquidación):
- Se descarga **desde Seller Center**, no encontré mención de una vía API.
- Requisito: la orden debe estar en estado **"FACTURADO"** para ser liquidada.
- Es un archivo tipo planilla con pestañas: **Totales, Detalle Ventas, Detalle Cancelaciones, Penalidades, Ajustes**.
- La pestaña Totales incluye: total valor de productos, total valor de envío, total cancelaciones, total devolución envío, total facturado c/IVA neto de cancelaciones, **Total Comisiones**, **Total Servicios logísticos - Fee**, total penalidades, total ajustes, total sin impuestos — y el desglose de cuánto factura cada razón social de Frávega.
- Periodicidad: parece ser quincenal (el ejemplo de la doc mostraba un período "1/5/2023 al 15/5/2023"), a confirmar con tu propio calendario de liquidaciones real.

### Facturación
[sites.google.com/fravega.com.ar/marketplace/administración/facturación](https://sites.google.com/fravega.com.ar/marketplace/administración/facturación) — por cada período liquidado se reciben (al menos) dos facturas:
1. **Frávega S.A.C.I. e I.** (CUIT 30-52687424-9): comisiones especiales (cuotas sin interés) + Fee Logístico MKP, con IVA 21% + Percepción IVA 3% + Percepción IIBB.
2. **Frávega Tech S.A.** (CUIT 33-71448380-9): "Uso de plataforma web" = la comisión base, con IVA 21% + Percepción IIBB.

No encontré mención de que estas facturas se puedan bajar por API — se reciben por correo y/o se consultan en Portal de Proveedores.

### Envío Pack
[sites.google.com/fravega.com.ar/marketplace/envíos/envío-pack](https://sites.google.com/fravega.com.ar/marketplace/envíos/envío-pack): es la plataforma **Envíopack** (`app.enviopack.com`), un tercero logístico que "reúne todos los servicios logísticos, simplificando los costos y agilizando los tiempos". Es un panel de login aparte, no forma parte de la API de VTEX ni de Frávega directamente.

### Legajos Impositivos
Aparece en el menú de Administración pero **no llegué a abrir esa página** — pendiente.

---

## 6. Lectura de órdenes: consulta o notificaciones

Confirmado en la Orders API de VTEX ([developers.vtex.com/docs/api-reference/orders-api](https://developers.vtex.com/docs/api-reference/orders-api)), hay **tres mecanismos**, no uno solo:

1. **Consulta directa (polling):** `GET /api/oms/pvt/orders` (lista, con filtros), `GET /api/oms/pvt/orders/{orderId}` (detalle), `GET /api/oms/pvt/orders/order-group/{orderGroup}`.

2. **Feed v3 (cola de cambios):** `GET /api/orders/feed/config` (config), `GET /api/orders/feed` (trae los ítems de órdenes modificadas pendientes de leer), `POST /api/orders/feed` (confirma/"consume" esos ítems, tipo ack). Pensado para no perder eventos y no tener que hacer polling constante de todo. También existe `POST /api/orders/expressions/jsonata` para probar expresiones de filtro antes de usarlas.

3. **Webhooks (Order hook):** `POST /api/orders/hook/config` registra una URL a la que VTEX empuja notificaciones. Se configura con un `filter`:
   - `FromWorkflow`: dispara solo cuando cambia el **estado** de la orden (hay que indicar qué estados te interesan).
   - `FromOrders`: dispara ante **cualquier cambio** en la orden, filtrado por una expresión **JSONata** sobre cualquier propiedad del JSON de la orden (por ejemplo, que se agregue o quite un producto).
   - El body de configuración incluye la `url` de destino y `headers` (Content-Type, Accept, etc.), y un flag `disableSingleFire` que controla si una orden puede disparar el hook más de una vez cuando se modifica repetidamente.

**NO ENCONTRADO:** el formato exacto del payload que VTEX efectivamente envía por POST a la URL configurada (la documentación de configuración solo explica cómo registrar el hook, no el body de la notificación en sí), ni una política de reintentos documentada ante fallos de entrega.

---

## 7. Límites y reglas técnicas

Confirmado, tal cual aparece en la página de "Obtener pedido":
> "Limitación de ancho de banda: Cada cuenta VTEX puede realizar hasta **6000 solicitudes por minuto**."

También confirmado: **solo se puede acceder a información de pedidos creados en los últimos 2 años** (mismo período aplica a consultas vía Mi Cuenta).

**NO ENCONTRADO:** headers de rate limit en las respuestas (tipo `X-RateLimit-Remaining` o similar) — no aparecen documentados en ninguna de las páginas de referencia que revisé.

Permisos: para llamar a Get Order hace falta una API key/rol con el recurso **"OMS - Ver pedido"** o **"Checkout Resources - Pedidos Acceso completo"** (hay roles predefinidos con esos nombres, o se puede armar un rol custom).

---

## 8. Lo que NO está en la API y solo se ve en el panel

Esta es la frontera real entre lo que se puede automatizar hoy y lo que va a seguir necesitando entrar a un navegador:

- **El monto definitivo de comisión y de Fee Logístico por período** — solo en la Liquidación, descargable desde Seller Center.
- **Las facturas** (con impuestos ya aplicados) — Portal de Proveedores / correo.
- **El Fee Logístico "de tarifa"** (tabla de escalas por peso/zona) — vive en el Centro de ayuda, no en el JSON de la orden.
- **Las penalidades aplicadas** — solo se reflejan en la Liquidación, no vi un campo de orden que las anticipe.
- **Gestión de siniestros** (reclamos por daño/pérdida) — Portal de Proveedores, carga manual de comprobantes.
- **Datos impositivos, fecha de pago, email de facturación** — Portal de Proveedores.
- **Gestión de envíos/etiquetas** — plataforma Envíopack, aparte.
- **Alta/edición de productos, cuotas/financiación, gestión masiva** — Seller Center.
- **La vinculación exacta con ECOM** (si existe el campo de referencia externa) — no pude verificarla, requiere entrar al panel de ECOM.

---

## 9. MCP disponible

**No pude confirmarlo ni descartarlo.** La herramienta de búsqueda web que uso normalmente estuvo caída durante toda esta sesión (la API de búsqueda devolvió error 403 en cada intento), así que no pude hacer una búsqueda amplia tipo "VTEX MCP server". Tampoco until ahora until encontré una mención a esto navegando developers.vtex.com directamente (ni en la sección de Guías, ni en la referencia de API, ni en notas de versión, aunque no revisé esas secciones exhaustivamente).

**Esto queda como pregunta abierta, no como "no existe".** Recomiendo: (a) volver a intentar la búsqueda web en otra sesión donde el buscador funcione, o (b) preguntarle directamente al soporte/Developer Relations de VTEX, o (c) revisar puntualmente `developers.vtex.com/docs/guides` buscando "MCP" o "AI assistant".

---

## 10. Preguntas abiertas

1. **¿Existe el campo de referencia externa en ECOM?** — No pude entrar al panel de ECOM. Es la pregunta que más te interesa y la más importante de resolver primero.
2. **¿Qué identificador de orden se ve realmente en el Módulo de Órdenes de Seller Center?** — No tengo credenciales del Seller Center real; lo que puse en 2.2 es inferencia arquitectónica, no una lectura de pantalla.
3. **¿`items[].commission` y `items[].freightCommission` reflejan un valor ya definitivo al momento de la venta, o es una estimación que después cambia en la Liquidación?** — No documentado; requiere una prueba empírica (comparar el valor de la API en una orden recién creada contra el valor final de esa misma orden en su Liquidación).
4. **¿La comisión base del 15% varía por categoría de producto?** — El Tarifario que vi solo muestra una tasa única; no encontré una tabla por categoría, pero tampoco puedo asegurar que no exista en otro lado.
5. **¿Existe un servidor MCP oficial de VTEX?** — Ver sección 9, inconcluso por falla de la herramienta de búsqueda.
6. **Formato del payload de los webhooks (Order Hook) y política de reintentos** — no documentado en lo que revisé.
7. **Alcance exacto del límite de 6000 req/min** (¿por cuenta VTEX en total, o por endpoint?) y si hay headers de cupo restante — no documentado.
8. **Contenido de "Legajos Impositivos"** — no llegué a abrir esa página.
9. **Contenido real de la pestaña "Ajustes" de la Liquidación** — no pude ver su detalle, es la candidata más probable para explicar diferencias entre estimado y cobrado.
10. **Cuadro de localidades** (enlazado desde el Tarifario) — no lo abrí.

### Lo que encontré que no pediste y me parece que importa

- Hay **dos versiones del Fee Logístico** con valores distintos (el Tarifario general, sin fecha visible, con montos "con impuestos"; y la página dedicada de Fee Logístico, fechada 6/03/2026, con montos "sin IVA"). Si vas a automatizar el cálculo del fee estimado, convendría confirmar con Frávega cuál de las dos tablas es la vigente — parecen no coincidir exactamente en los montos.
- El Fee Logístico y la Comisión Base se facturan por **dos razones sociales distintas de Frávega** (S.A.C.I. e I. vs. Tech S.A.), cada una con su propio tratamiento impositivo — puede ser relevante para cómo registrás el gasto contablemente, más allá de la rentabilidad por orden.
- La comisión y el fee logístico, tal como los vi documentados, ya **excluyen impuestos** en el momento del cálculo/tarifario, pero se facturan **con** impuestos — así que al construir tu "rentabilidad real" por orden vas a tener que decidir si comparás todo neto de impuestos o todo con impuestos, de forma consistente.
