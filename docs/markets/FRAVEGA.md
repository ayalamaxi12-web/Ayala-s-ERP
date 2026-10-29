# Ficha de market: FRÁVEGA

Relevado con Claude in Chrome sobre el Seller Center el 27/10/2026. Seller: `fravegasellerprod1266`. **Acá no hay claves ni tokens**: van a variables de Railway.

## 1. De dónde sale la comisión y el envío reales
- **No están en el detalle de la orden.** `/_next/data/<buildId>/orders/<orden>-<id>.json` trae precio (`productsTotal`), envío que pagó el comprador (`deliveriesTotal`, casi siempre 0), tipo de entrega y estado. No trae comisión ni fee.
- **Sí están en Estado de cuenta → «Próxima liquidación»** (https://seller-center.fravega.com/settlements/future), orden por orden, **desde el momento en que se factura la venta** (no hace falta esperar al cierre de la quincena).

## 2. Endpoint
```
GET https://seller-center.fravega.com/api/v1/seller-center-service/api/v1/settlement
    ?filter={"page":1,"perPage":200,"sortField":"nroOrden","sortOrder":"desc"}
```
(el JSON del `filter` va URL-encoded)

Respuesta:
```json
{
  "items": [{
    "fechaVenta": "2026-10-27T11:32:49.829Z",
    "nroOrden": "v94246555frvg-01",
    "estado": "Facturada",
    "totalProductos": 72440,
    "totalComision": -18544.64,
    "totalEnvio": 0,
    "totalFeeLogistico": -6159,
    "totalDescuentos": 0,
    "totalLiquidacion": 47736.36
  }],
  "totalCount": 122
}
```

Notas de comportamiento (probado):
- `perPage: 200` devuelve todo de una vez (hoy son 122 órdenes). Si `totalCount` > `perPage`, paginar con `page`.
- Los filtros `nroOrden` y `estado` existen en el front pero **el servidor los ignora**: se trae todo y se filtra en el conector.
- Estados vistos: `Pendiente`, `Facturada`, `Devuelta`. Arrastra órdenes viejas no liquidadas (la más antigua es del 30/08/2026).
- Los montos vienen **en negativo** (descuentos al seller) y ya con decimales.
- Comisión observada: 15,0 % / 21,8 % / 25,6 % sobre `totalProductos` (depende de la categoría).
- `totalEnvio` y `totalDescuentos` hoy vienen en 0 en todas las órdenes; el costo real de envío es `totalFeeLogistico`.

## 3. Cierre de quincena (lo que ya usa el ERP)
- «Liquidación actual»: `/_next/data/<buildId>/settlements/last.json` → solo totales del período (`commission`, `cancellationCommission`, `logisticFee`, `cancellationLogisticFee`, `shipping`, `penaltiesTotal`, `adjustmentsTotal`, `netTotal`) + `settlementId` y `period.from/to`. El detalle por orden está en «Descargar liquidación» (archivo), que es lo que hoy se carga en `POST /rentabilidad/fravega/liquidacion`.
- `<buildId>` cambia en cada deploy de Frávega: **no usar `/_next/data/` para el conector**, sí el endpoint `/api/v1/...` de arriba.

## 4. Autenticación
- Por **cookies de sesión** del Seller Center (no header `Authorization`). Las relevantes: `X-SELLER-AUTH`, `X-FVG-SELLER-ID`, `X-SELLER-APP` (+ `AWSALB` de balanceo).
- Variables de Railway sugeridas: `FRAVEGA_SELLER_AUTH`, `FRAVEGA_SELLER_ID`, `FRAVEGA_SELLER_APP`.
- **Riesgo:** es una sesión de usuario web, vence. Falta confirmar cuánto dura y si Frávega ofrece credenciales de API para sellers (preguntar al ejecutivo de cuenta). Mientras tanto, el conector tiene que detectar 401/redirección a login y avisar, y seguir funcionando la carga manual de la liquidación como respaldo.

## 5. Mapeo al formato común del conector
| Campo común | Frávega |
|---|---|
| `orden_externa` | `nroOrden` (= `venta_ecom.orden_externa` sin `FVG-`) |
| `comision` | `abs(totalComision)` |
| `envio` | `abs(totalFeeLogistico)` (+ `abs(totalEnvio)` si algún día deja de ser 0) |
| `otros_cargos` | `abs(totalDescuentos)` |
| `neto` | `totalLiquidacion` |
| `fecha` | `fechaVenta` (UTC → AR) |
| `estado` | `estado` |

Control: `totalProductos + totalComision + totalEnvio + totalFeeLogistico + totalDescuentos == totalLiquidacion` (cuadra en las órdenes mostradas).

## 6. Qué hace el ERP con esto
1. Job (p. ej. cada hora) trae «Próxima liquidación» completa y hace upsert por `nroOrden`.
2. Cruza con `venta_ecom.orden_externa` y **reemplaza la comisión y el envío estimados** por los reales. Nada más cambia en la renta.
3. Las `Devuelta` se marcan; los montos de cancelación definitivos siguen llegando con la liquidación quincenal, que queda como conciliación final.

## Pendiente
- Duración de la sesión / credenciales oficiales.
- Ver si al cerrar la quincena las órdenes salen de «Próxima liquidación» y en qué endpoint quedan con detalle (Liquidaciones anteriores).

## Implementado (ERP)
- `backend/rentabilidad/fravega_seller.py` trae «Próxima liquidación» y `persistencia.sincronizar_proxima_liquidacion` guarda comisión y fee logístico reales en `liquidacion_fravega` (marca `archivo = "API Seller Center · próxima liquidación"`) y recalcula la rentabilidad de las ventas de Ecom (misma regla que la liquidación quincenal: + IVA de cargos).
- Endpoint: `POST /rentabilidad/fravega/proxima-liquidacion/sync` (correrlo cada hora desde n8n, o a mano). Variables de Railway: `FRAVEGA_SELLER_AUTH`, `FRAVEGA_SELLER_ID`, `FRAVEGA_SELLER_APP`.
- La liquidación quincenal (Excel) **manda siempre**: al cargarla borra las filas provisorias de sus órdenes y las sincronizaciones siguientes ya no las vuelven a cargar (nunca se suman).
- `Devuelta` y órdenes sin comisión no se cargan (siguen estimadas hasta la liquidación, que trae las cancelaciones).
- Si Frávega rechaza la sesión (401/403/redirección/HTML) el endpoint responde 502 con el aviso y no toca nada; sin variables, 503.


## 7. Precios, ofertas, cuotas y campañas — Frávega Marketplace

> Relevado el 29/10/2026 en Seller Center (`seller-center.fravega.com`), solo lectura. No se guardó ningún precio, plan ni estado.
> Todo lo de abajo es la **API interna del portal** (la que usa el front). La **API oficial** está aparte (ver 7.0) y no se pudo leer.

### 7.0 API oficial

- Documentación: **https://developers.fravega.io/** (link desde Centro de Ayuda → Integraciones → Seller Center → "APIs de Seller Center").
- La página está protegida con una clave que figura publicada en esa misma página del Centro de Ayuda. No la ingresé, así que **el contenido de la doc oficial no está relevado**.
- Las credenciales de integración se piden al Centro de Atención Frávega Marketplace (Jira Service Desk: `fravega-it.atlassian.net/servicedesk/customer/portal/25/group/83`).
- Integradores homologados listados: VTEX, Producteca, Fulljaus, EcomExperts, Grow2on, Sincroshops.

### 7.1 Autenticación (portal)

| Elemento | Detalle |
|---|---|
| Login | OAuth2 vía `https://seller-auth.production.fravega.com/v2/oauth2/signin?sellerApp=seller-center&rd=<url>` (sin sesión las `/api/...` devuelven 503 y redirigen ahí) |
| Headers en cada llamada | `authorization`, `x-fvg-seller-id` (no se leyeron valores) |
| Cookies | `X-SELLER-AUTH`, `X-SELLER-APP`, `X-FVG-SELLER-ID`, `AWSALB`/`AWSALBCORS` (balanceo) |
| Base | `https://seller-center.fravega.com/api/v1/seller-center-service/api/{v1|v2}/...` |
| Seller ID | `sellerId: "fravegasellerprod1266"` |

### 7.2 Lecturas

| Pantalla | Llamada | Notas |
|---|---|---|
| Listado de productos | `GET /api/v1/seller-center-service/api/v2/item?page=1&size=10&preview=...` | Paginado: `{currentPage, items[], total: 205, totalPages: 21}` |
| Detalle/edición | `GET /api/v1/seller-center-service/api/v2/item/{id}` | `{id}` = id interno (Mongo), no el SKU |
| Item completo | `GET /api/v1/seller-center-service/api/v1/item/complete/{id}` | Visto en el código del front |
| Datos del seller + planes habilitados | `GET /api/v1/seller-center-service/api/v1/seller?wh=true` | De acá sale `sellerPlansInfo` (planes elegibles) |
| Estado de tienda | `GET /api/v1/seller-center-service/api/v1/seller/shopStatus` | `blockedShopToSale` |
| Financiación (planes) | `GET /_next/data/<buildId>/plans.json` (SSR de Next.js) | `{plans[], page, total, hasError}` |
| Atributos de categoría | `GET /api/attributes/{categoryId}` | |
| Gestión masiva: generar plantilla | `GET /api/v1/xlsx-service/api/v1/report/processxlsx/{tipo}?active=...` | Devuelve el Excel (arraybuffer) |
| Gestión masiva: historial | `GET /api/v1/xlsx-service/api/v1/report/list` | |

Ejemplo recortado de un ítem (listado `v2/item`):

```json
{
  "id": "6abebcc4f922a07fdf15b958",
  "sku": "23090664",
  "refId": "PINMKV2-CIRC-58MM-W",
  "sellerId": "fravegasellerprod1266",
  "title": "Máquina Para Hacer Pines Rotativa 58 Mm Blanca Global",
  "active": true,
  "itemState": "Published",
  "status": { "code": "published", "message": "Ok" },
  "origin": "China",
  "price": { "list": 303599, "sale": 303599, "net": 250908.26 },
  "stock": { "quantity": 50 },
  "associatedPlan": {
    "from": "2026-10-02T13:00:00Z",
    "to": "2027-05-31T18:00:00Z",
    "plan": { "_id": "67169f60e7602bbe4bfacb8d",
              "name": "IMPORTADOS: 6 cuotas sin interés v6",
              "commission": 10.6, "origin": "Todos", "categories": ["…1048…"] },
    "userId": "<mail del usuario que lo aplicó>"
  }
}
```

Ejemplo recortado de un plan (`plans.json`):

```json
{ "_id": "67169e3c970472fdae99a8b8", "financialGroupId": 1032,
  "name": "IMPORTADOS: 9 cuotas sin interés v5", "commission": 13.7,
  "origin": "Todos", "allSellers": true,
  "validity": { "start": "2024-10-21T18:00:00.000Z", "expiration": "2027-05-31T18:00:00.000Z" },
  "paymentPlans": [ { "name": "Planes sin interes", "installmentName": "9 sin interés.", "quantity": 9, "…": "…" } ] }
```

Planes visibles hoy (4): 3 cuotas (6,8 %), 6 cuotas (10,6 %), 9 cuotas (13,7 %), 12 cuotas (16,6 %), todos "IMPORTADOS … sin interés", vigentes hasta el 31/05/2027.

### 7.3 Escrituras (NO ejecutadas; llamadas sacadas del código del front)

| Acción | Botón en la UI | Llamada |
|---|---|---|
| Cambiar precio / tachado / stock / encendido | Listado → ⋮ → **Editar valores** → "Guardar cambios" | `PUT /api/v1/seller-center-service/api/v1/item/{id}/partial` con body `{ "price": {"list", "sale", "net"}, "stock": {"quantity"}, "active": bool }`. 200 = OK; **409** = parcial, devuelve `error.fields` con los campos rechazados (`price`/`stock`/`active`) |
| Encender/apagar | Toggle "Estado" del listado | Mismo `PUT .../partial` (campo `active`) |
| Asignar plan de cuotas a una publicación | ⋮ → **Editar producto** → paso 5 "Financiación" → "Guardar y pedir aprobación" | `POST /api/v1/seller-center-service/api/v1/item/{id}/plan` con body `{ "plan": {<objeto plan completo>}, "from": ISO, "to": ISO }`. Valida días hábiles (`to_date_holiday_error`). El front suma 3 h a la hora local para pasarla a UTC |
| Edición completa de ficha | Editar producto → "Guardar y pedir aprobación" | `PUT /api/v1/seller-center-service/api/v1/item/complete/{id}` (pasa por aprobación) |
| Alta de producto | Nuevo producto | `POST /api/v1/seller-center-service/api/v1/item/complete` |
| Masivo: precio / stock / financiación / estado | Catálogo → **Gestión masiva** → tipo de actualización → "Subir plantilla" | `POST /api/v1/xlsx-service/api/v1/{price|stock|plans|state}` (multipart, campo `excelFile`) |
| Masivo: tabla completa | Ídem, "Tabla completa" | `PUT /api/v1/xlsx-service/api/v1/products/xlsx/import` (multipart `excelFile`) |

Validaciones de precio que tiene el front: lista y venta obligatorios y > 0; **venta ≤ lista**; sin impuestos ≤ lista/venta; si "sin impuestos" queda vacío, se calcula como lista − 21 %.

### 7.4 Respuestas

| Pregunta | Respuesta | Evidencia |
|---|---|---|
| ¿Hay API oficial documentada para precios y ofertas? | **Sí existe; contenido: no sé** | Centro de Ayuda → "APIs de Seller Center" → `developers.fravega.io` (con clave). Credenciales vía Centro de Atención. No se leyó la doc |
| ¿Precio por SKU o por publicación? | **Por SKU** (1 ítem = 1 SKU) | Cada ítem tiene un `sku` y su propio `price`; el `PUT .../partial` va por `{id}` del ítem. No se vieron variantes agrupadas |
| ¿Precio tachado o solo final? | **Sí, hay tachado** | `price.list` (tachado) + `price.sale` (final) + `price.net` (sin IVA). El listado muestra la columna "Descuento" calculada |
| ¿Cuotas por publicación o acuerdo general? | **Por publicación**, eligiendo entre los planes que habilita Frávega | Paso 5 "Financiación" en Editar producto, `associatedPlan` por ítem, `POST /item/{id}/plan`; masivo por Excel "Financiación". El catálogo de planes y su comisión los define Frávega |
| ¿Hay campañas (tipo Cyber) con propuestas del market? | **No** (en el portal) | No hay menú, pantalla ni llamada de promociones/campañas/ofertas en todo el front (rutas: orders, settlements, invoice, plans, products, admin, profile). Si existen, se manejan fuera del Seller Center (mail/KAM) |
| ¿Mínimos/máximos de descuento? | **No sé** (no hay en el front) | Las únicas validaciones son venta ≤ lista y > 0. Puede haber reglas del lado del servidor o de la doc oficial |
| ¿Carga masiva por Excel? | **Sí** | Gestión masiva: plantillas Stock, Precio, Completa, Financiación, Estado ("Procesar" → descargar → subir) |

### 7.5 Cruce con el sistema

- **Tu SKU de Ecom = campo `refId`** ("Código de referencia" en la UI). Ej.: `refId: "PINMKV2-CIRC-58MM-W"`. En el listado aparecen `PLANCHA-SU…`, así que `PLANCHA-SUB-GORRA` debería estar ahí.
- `sku` = código de Frávega (numérico, ej. `23090664`), es el que va en la URL pública `fravega.com/p/...-23090664`.
- `id` = id interno (Mongo) que piden los endpoints de escritura. Mapeo necesario: `refId → id`, resolviéndolo desde el listado (`v2/item`), que admite búsqueda por código.

### Dudas

1. **API oficial vs. interna:** la integración prolija es con credenciales de `developers.fravega.io`. La interna depende de la sesión del portal (OAuth + cookies) y puede cambiar sin aviso. Conviene pedir credenciales y leer la doc antes de construir.
2. **¿El cambio de precio por "Editar valores" impacta directo o pasa por aprobación?** La edición completa dice "pedir aprobación"; el `PUT /partial` parece directo, pero no lo verifiqué. Para confirmarlo hace falta una prueba real (ver abajo).
3. **Demora de financiación:** por Excel se aplica en días hábiles a las 10:00 y 15:00 (Centro de Ayuda). Por publicación "puede demorar en impactar". Hay que contemplarlo en el sistema.
4. **Planes de "cuota simple":** según la ayuda, solo aplican a productos de origen Argentina. Los nuestros figuran como `origin: "China"`.
5. **Campañas/eventos:** no hay módulo. Hay que confirmar con el KAM cómo se proponen (Cyber, Hot Sale) y si traen exigencias de descuento.
6. **Comisión según plan:** la comisión depende del plan (6,8 % a 16,6 %). El cálculo de margen tiene que leer `associatedPlan.plan.commission` por SKU.
7. **Integradores (Producteca/VTEX):** si algún día se integra por ahí, la gestión individual de financiación queda deshabilitada y solo funciona el masivo.

**Prueba propuesta (solo con tu OK):** en un SKU de prueba, "Editar valores" → cambiar el Precio de venta en $1 → guardar, capturar la llamada y la respuesta, revisar si queda "pendiente de aprobación" y volver al valor original.
