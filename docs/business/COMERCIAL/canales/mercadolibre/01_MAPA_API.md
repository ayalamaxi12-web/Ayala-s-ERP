# 01 — MAPA API · MERCADO LIBRE

## Qué es este documento y qué no es

**Es un mapa, no una especificación.** Dice **dónde está** cada cosa y **qué endpoint resuelve qué necesidad de negocio**, con el slug exacto de la página de documentación.

**No contiene parámetros ni estructuras de respuesta.** Eso se consulta en vivo con el MCP de documentación (ver `02_MCP.md`) al momento de implementar cada módulo. Esa decisión es deliberada: la API cambia y una transcripción de parámetros envejece mal, mientras que el mapa de áreas es estable.

**Origen:** relevamiento del portal `developers.mercadolibre.com.ar/es_ar/` realizado con navegador, en solo lectura. Los endpoints citados fueron leídos en la documentación real.

**Site de trabajo:** `MLA` (Argentina). Dos cuentas de vendedor propias con OAuth ya funcionando.

> ⚠ **Advertencia de vigencia.** Este mapa refleja el portal al momento del relevamiento. Antes de implementar cualquier módulo, verificar con el MCP. Si un endpoint de este documento no existe o cambió, **manda el MCP**, no este archivo.

---

## 1. Estructura del portal

La documentación se divide en cuatro unidades de negocio y varias verticales.

| Unidad | Aplica al proyecto |
|---|---|
| **Mercado Libre** | **Sí — es la única relevante** |
| Global Selling | No (venta cross-border) |
| Mercado Envíos | No como unidad separada; lo necesario está dentro de Mercado Libre |
| Mercado Pago | No como unidad separada; ídem |

Verticales fuera de alcance: inmuebles, vehículos, servicios, Pharma-Recetados, Proximity.

Dentro de la unidad Mercado Libre: **Recursos de la API** (usuarios, catálogo de referencia, ítems, preguntas, pedidos, atributos, notificaciones, moderaciones, Brand Protection), **Guía para productos** (publicación, precios, catálogo, envíos, promociones, gestión de ventas, facturación, mensajería, reclamos, métricas), **Guía para Mercado Ads**, **MCP** y **FAQs**.

---

## 2. Mapa por necesidad de negocio

### 2.1 Publicaciones, stock y precios

| Necesidad | Endpoint / recurso | Notas |
|---|---|---|
| Listar todos los ítems propios | `/users/{user_id}/items/search` | Filtros por `sku` (seller_custom_field), `seller_sku`, `status`, `listing_type_id`, `missing_product_identifiers`. Para más de 1000 resultados usar `search_type=scan` con `scroll_id` |
| Detectar publicaciones sin ficha técnica completa | mismo endpoint, filtro `missing_product_identifiers` | |
| Detectar ítems perdiendo exposición por reclamos | mismo endpoint, filtro `reputation_health_gauge=unhealthy\|warning\|healthy` | **Exclusivo México, Chile y Brasil al momento del relevamiento. Verificar si ya aplica a MLA** |
| Traer varios ítems de una vez | `/items?ids=ID1,ID2&attributes=...` | Máximo **20 ítems** por request |
| Detalle de un ítem | `/items/{item_id}` | |
| SKU propio del vendedor | campo `seller_custom_field` y atributo `SELLER_SKU` | **Puede vivir en más de un lugar. Determinar el canónico antes de implementar. Necesario detectar con confiabilidad cuándo un ítem NO tiene SKU** |
| Modificar precio | páginas `api-de-precios`, `precio-variacion`, precios por cantidad, precios netos por cantidad, referencias de precios | Detalle por endpoint no relevado |
| Comisión de venta por tipo de publicación | `/sites/MLA/listing_prices?price=X` | Devuelve `sale_fee_amount` por cada `listing_type_id` (gold_pro, gold_special, silver...). **Insumo directo del módulo de rentabilidad** |
| Costos por vender | página `comision-por-vender` | |
| Stock multi-origen | páginas `stock-distribuido`, `stock-multi-origen` | Para conciliar depósito propio contra ML |
| Manejo moderno de stock y variaciones | página `user-products` | Reemplaza el manejo a nivel "ítem" por nivel "producto". **Prioridad de lectura para la Fase 6** |
| Imágenes | `trabajar-con-imagenes` | |
| Otros | identificadores de productos, variaciones, `re-publica`, kits virtuales, guías de talles | |

### 2.2 Catálogo y Buy Box — inteligencia competitiva

**Esta es el área de mayor valor encontrada.**

| Necesidad | Endpoint | Qué devuelve |
|---|---|---|
| ¿Gano o pierdo el catálogo, y por qué? | `/items/{item_id}/price_to_win?version=v2` | Estado `winning` / `competing` / `listed`; array `boosts` con las palancas que faltan (`fulfillment`, `free_installments`, `free_shipping`, `shipping_collect`, `same_day_shipping`, cada una con status `opportunity` o `boosted`); `current_price`; `price_to_win` (precio exacto necesario para ganar); bloque `winner` con los datos del competidor que gana |
| Aviso en tiempo real de cambio de ganador | tópico de notificación `catalog_item_competition_status` | Disponible en Argentina, Brasil y México |
| Sugerencias de nuevos productos de catálogo | tópico `catalog_suggestions` | Brand Central |

> **Hueco confirmado, sin solución nativa:** no existe endpoint de monitoreo de cambios de competidores (precio, título, fotos) para publicaciones **fuera de catálogo**. Eso hay que construirlo con polling propio sobre `/sites/MLA/search` y `/items?ids=...`, comparando snapshots. Esto se confirmó explícitamente en el relevamiento; no hay recurso oficial.

### 2.3 Stock en Fulfillment (FULL)

| Necesidad | Cómo se resuelve |
|---|---|
| Stock real en FULL con detalle por causa | Cadena de dos llamadas: `/items/{item_id}` devuelve un `inventory_id` (uno por variación) → `/inventories/{inventory_id}/stock/fulfillment` devuelve `total`, `available_quantity`, `not_available_quantity` y el detalle por causa: `damage`, `lost`, `withdrawal`, `internal_process`, `transfer`, `noFiscalCoverage` |

**Es el dato exacto que necesita la conciliación de depósito propio contra FULL.**

### 2.4 Envíos y logística

| Necesidad | Recurso |
|---|---|
| Envío gratis obligatorio u opcional | bloque `shipping` del ítem: `shipping.tags` con `mandatory_free_shipping`, `shipping.logistic_type`, `shipping.free_shipping`. El envío gratis obligatorio aplica cuando el ítem supera un umbral de precio que fija ML |
| Identificar FULL | `shipping.logistic_type` |
| Envío de una orden | `/shipments/{shipment_id}` con header obligatorio `x-format-new: true`. **Ya no viene embebido en la orden** |
| Costos y modalidades | páginas `costos-de-envios`, `envios-fulfillment`, Mercado Envíos 1 y 2, flete dinámico, envíos en feriados, Colecta y Places, agrupación de paquetes, Flex, Turbo, personalizados |

### 2.5 Órdenes y ventas

| Necesidad | Endpoint |
|---|---|
| Detalle de una orden | `/orders/{order_id}` — devuelve `status`, `order_items` (con `sale_fee`, `unit_price`, `gross_price`), `payments` (con `installments`, `payment_method_id`, `transaction_amount`), `shipping.id`, `buyer`, `seller`, `feedback`, `tags` |
| Buscar órdenes | `/orders/search?seller={seller_id}` — con `available_filters` por `order.status`, `shipping.status`, `shipping.substatus`, `feedback.status`, `tags`, `mediations.status` |

> **Dato útil para medir promociones:** comparar `gross_price` (precio sin descuentos) contra `unit_price` da el impacto real de las promos por línea de venta.

### 2.6 Facturación, comisiones y liquidaciones

| Necesidad | Endpoint / página |
|---|---|
| Datos fiscales del comprador | obtener `billing_info_id` desde la orden → `/orders/billing-info/{site_id}/{billing_info_id}`. Devuelve `identification`, `taxes.taxpayer_type`, `address` |
| Períodos de facturación | `/billing/integration/monthly/periods` — hasta 12 períodos, con parámetro `group=ML` o `group=MP` |
| Documentos, resumen y detalle del período | `/documents`, `/summary`, `/details` bajo el mismo árbol |
| Otros | envío de datos fiscales, cargar y obtener facturas, descargar facturas MELI, buenas prácticas, provisiones, `reportes-pagos`, descargas, `resumen-percepciones` |

**Área base del módulo de conciliación de comisiones. Detalle de campos no relevado — profundizar con MCP antes de implementar.**

### 2.7 Notificaciones y webhooks

Tópicos confirmados disponibles al momento del relevamiento:

| Tópico | Para qué |
|---|---|
| `orders_v2` | Altas y cambios de ventas confirmadas. **Recomendado sobre `orders`** |
| `items` | Cualquier cambio en una publicación |
| `items_prices` | Cambios de `sale_price` |
| `price_suggestion` | Sugerencias de precio de ML |
| `catalog_item_competition_status` | Cambio de ganador de catálogo |
| `catalog_suggestions` | Sugerencias de producto de catálogo |
| `stock-location` | Cambios de stock por ubicación (user-products) |
| `fbm_stock_operations` | Operaciones de stock FULL |
| `shipments` | Envíos |
| `messages` | Con subtópicos `created` / `read` |
| `questions` | Preguntas |
| `flex-handshakes` | Transferencias entre transportistas Flex |
| `public_offers`, `public_candidates` | Ofertas y candidatos a promoción |
| `orders_feedback` | Feedback |
| VIS Leads | Vertical de servicios — **no aplica** |

**Mecánica:** el callback llega con un payload chico (`resource`, `user_id`, `topic`, `application_id`) y el ERP hace un GET al recurso indicado.

**Canal aparte, no transaccional:** `/communications/notices` entrega comunicados oficiales de ML al vendedor — novedades, alertas de bloqueo inminente, lanzamientos, cambios de política. **Es la fuente del módulo de eventos de plataforma a nivel institucional.**

**Histórico de notificaciones perdidas:** `/missed_feeds?app_id={app_id}`.

**Reemplazar polling por webhooks es prioridad de arquitectura.** Documentar con el MCP el formato exacto del callback, la política de reintentos y los requisitos del endpoint receptor antes de implementar.

### 2.8 Promociones y eventos de plataforma

Central de promociones (`central-de-promociones`) agrupa:

campañas tradicionales (`deals`) · campañas co-fondeadas (`campanas-co-fondeadas`) · campañas con descuento por cantidad · pre-acordado por ítem y liquidación de stock Full · descuento individual · ofertas del día · ofertas relámpago · campañas del vendedor · co-fondeada automatizada y smart price matching · cupones del vendedor · campaña co-fondeada para PIX

Cuotas: página propia `campana-con-cuotas-para-marketplace`.

**Ninguna profundizada a nivel de endpoint. Los slugs están listos para consultar con el MCP.**

### 2.9 Publicidad (Product Ads)

| Necesidad | Endpoint |
|---|---|
| Listar advertisers | `/advertising/advertisers?product_id=PADS\|DISPLAY\|BADS` |
| Campañas, anuncios y métricas | por encima de ese árbol — **no relevado en detalle** |

> ⚠ **Deprecación con fecha ya cumplida.** ML dio de baja permanentemente el **26/02/2026** toda la familia de endpoints legados `/advertising/product_ads/...` y `/advertising/product_ads_2/...`. Esa fecha ya pasó: **esos endpoints ya no existen.** Usar exclusivamente los nuevos y verificar con el MCP cuáles son.

Brand Ads (`ads-bads`) y Display Ads (`display`) son módulos separados de Mercado Ads.

### 2.10 Métricas, reputación y calidad

| Necesidad | Endpoint |
|---|---|
| Reputación del vendedor | `/users/{user_id}` → `seller_reputation` con `level_id`, `power_seller_status`, `metrics.sales` / `.claims` / `.delayed_handling_time` / `.cancellations`, cada una con `rate` de los últimos 60 días y un bloque `excluded` |
| Visitas por vendedor | `/users/{user_id}/items_visits?date_from=X&date_to=Y` — máximo **150 días**. Devuelve `total_visits` y detalle por país/site |
| Visitas por ítem | endpoint a nivel ítem individual |
| Otros | tendencias, más vendidos, opiniones de productos, calidad de publicaciones, experiencia de compra, carga de atributos, programa de despegue |

> **Detalle importante sobre reputación:** el bloque `excluded` contiene el valor real si el vendedor está protegido. **El `rate` mostrado puede no ser el real.** No usar el rate visible sin mirar `excluded`.

### 2.11 Preguntas, mensajería y posventa

| Necesidad | Endpoint |
|---|---|
| Preguntas de un ítem | `/questions/search?item={item_id}` |
| Preguntar | `POST /questions` |
| Responder | `POST /answers` |
| Detalle de una pregunta | `/questions/{question_id}` |
| Todas las preguntas recibidas | `/my/received_questions/search` — con `status` `ANSWERED` / `UNANSWERED` / `BANNED` |
| Bloquear un usuario | `/block-api/search/users/{user_id}` y `DELETE /users/{seller_id}/questions_blacklist/{user_id}` |

**Reclamos:** cuatro tipos diferenciados — **Order** (discrepancias de producto o cantidad), **Shipment** (demoras, daños), **Payment** (cobros incorrectos, disputas) y **Purchase** (producto defectuoso o descripción incorrecta). Las notificaciones se activan en el tópico **Post Purchase** de la aplicación. Detalle de gestión no relevado.

### 2.12 Catálogo de referencia y datos maestros

| Necesidad | Endpoint |
|---|---|
| Sites | `/sites` |
| Árbol de categorías | `/sites/MLA/categories` |
| Settings de una categoría | `/categories/{category_id}` — moneda, `item_conditions`, `max_pictures_per_item`, `minimum_price`, `listing_allowed` |
| Atributos requeridos por categoría | `/categories/{category_id}/attributes` — devuelve `id`, `tags` (`fixed`, `required`, `allow_variations`, `hidden`, `catalog_required`), `value_type` y valores posibles. **Clave para SEO y generación de contenido** |
| Predictor de categoría a partir de un título | `/sites/MLA/domain_discovery/search?q=texto` — devuelve `domain_id`, `category_id` y atributos sugeridos. **Muy útil para carga masiva** |

### 2.13 Usuarios y cuentas

| Necesidad | Endpoint |
|---|---|
| Usuario | `/users/{user_id}` (GET/PUT) — `nickname`, `seller_reputation`, `seller_experience`, `tags`, `status` (con sub-bloques `list` / `buy` / `sell` / `billing`, cada uno con `allow` y `codes`), `mercadopago_account_type`, `credit` |
| Usuario logueado | `/users/me` |
| ¿La cuenta está bloqueada? | `/users/{user_id}?attributes=status` → mirar `status.list.allow` y `status.list.codes` (ej. `rejected_by_regulations`) |
| Direcciones | `/users/{user_id}/addresses` |
| Marcas | `/users/{user_id}/brands` |
| Medios de pago aceptados | `/users/{user_id}/accepted_payment_methods` |
| Aplicación | `/applications/{application_id}` |
| Revocar permisos | `DELETE /users/{user_id}/applications/{application_id}` |

> ⚠ **Los IDs de usuario nuevos exceden Int32. Usar Int64 en el modelo de datos.** Esto ya rompió integraciones ajenas.

### 2.14 Moderaciones y Brand Protection

Gestionar moderaciones, moderaciones con pausado, diagnóstico de imágenes y moderaciones de imágenes — detección automática de problemas en publicaciones propias.

Brand Protection Program — para cuando terceros venden falsificaciones de marcas representadas.

---

## 3. Reglas técnicas obligatorias de integración

**Toda escritura al canal pasa por cola, es idempotente y tiene reintentos con backoff.** No existen llamadas sincrónicas a la API desde la interfaz de usuario.

**Prioridad en la cola:** stock > precio > contenido. Un cambio de stock mal propagado produce sobreventa; un cambio de contenido puede esperar.

**Cada llamada registra** request, response, timestamp y resultado.

**Los tokens se renuevan automáticamente** y su vencimiento se monitorea.

**Rate limits:** existe una página de FAQ dedicada al error 429. Consultarla con el MCP antes de diseñar la cola. Un cambio masivo de lista sobre ~6.500 publicaciones es un proceso de **minutos u horas, no instantáneo** — la expectativa debe ser realista y el diseño debe soportar ventanas planificadas.

---

## 4. Documentación a estudiar por fase

| Fase | Páginas |
|---|---|
| 3 — lectura del canal | `items-y-busquedas`, `producto-sincroniza-modifica-publicaciones`, `productos-recibe-notificaciones`, `rate-limit-error-429` |
| 4 — escritura de precios | `api-de-precios`, `comision-por-vender`, `tipos-de-publicacion-y-actualizaciones-de-articulos`, `costos-de-envios` |
| 5 — ofertas y campañas | `central-de-promociones`, `deals`, `descuento-individual`, `referencias-de-precios`, `promotions-pricing` |
| 6 — stock | `user-products`, `stock-multi-origen`, `stock-multiwarehouse`, `envios-fulfillment` |
| 7 — órdenes | `gestiona-ventas`, `gestion-packs`, `pagos` |
| 8 — envíos y facturación | `envios`, `facturacion`, `descargar-facturas-mla` |

---

## 5. Recursos auxiliares que conviene conocer

**FAQs con troubleshooting curado:** Rate Limit / Error 429 · gestión de stock multiorigen y User Products · ME1/ME2 y envío gratis · costos y cotizaciones de Mercado Envíos · facturación y billing info · imágenes y moderaciones · promotions y pricing · atributos de envío y dimensiones de ítems.

**Son la primera parada cuando una integración falla sin motivo aparente.**

**Guía de seguridad**, separada de "Autenticación y Autorización" básica: infraestructura y TLS, gestión de identidades OAuth, autenticación segura, control de acceso, seguridad de apps, monitoreo, gestión de incidentes. **Relevante porque el backend maneja tokens de dos cuentas de ML: hay riesgo de revocaciones cruzadas y de compartir rate limits.**

**Sandbox / entorno de pruebas:** existencia y uso no confirmados en el relevamiento. Verificar con el MCP antes de asumir que hay dónde probar sin tocar producción.

---

## 6. Áreas mapeadas y no profundizadas

Listas para consultar con el MCP cuando se necesiten. El relevamiento llegó a ubicarlas pero no a extraer su detalle:

User Products · stock distribuido y multiorigen · reportes de facturación (documents, summary, details) · reclamos y devoluciones · Product Ads (la página quedó al 42%) · las once mecánicas de la central de promociones · campañas con cuotas · modalidades de envío individuales · tendencias y más vendidos · calidad de publicaciones.
