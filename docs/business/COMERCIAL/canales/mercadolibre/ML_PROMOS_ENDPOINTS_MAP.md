# Mapa de endpoints internos — Precios y Promociones de Mercado Libre (Central de Vendedores)

> Capturado por inspección de red sobre la cuenta IT (seller_id `115764017`), publicación de prueba **MLA852181648** ("Resma A4 Papel Autor 75grs"), el 28/08/2026.
> Base de todos los endpoints internos: `https://vendedores.mercadolibre.com.ar`
>
> ⚠️ **Naturaleza de estos endpoints:** son rutas **internas del frontend**, NO la API pública oficial (`api.mercadolibre.com`). Funcionan para replicar desde el ERP pero **pueden cambiar sin aviso**. Varias operaciones exigen tokens firmados por ML (`signature`, `jwtEvent`, `cardIdApplied`) que NO se pueden fabricar: hay que leerlos primero de la propia respuesta de ML. Documentar con fecha y revalidar periódicamente.

---

## Resumen ejecutivo (para el diseño del "un solo botón" del ERP)

| # | Acción | Método | Endpoint | Replicable desde ERP |
|---|--------|--------|----------|----------------------|
| 0 | Leer promos/candidatos de un ítem | GET | `/publicaciones/listado/promos/api/items/refresh` | ✅ Sí (fuente de ids y tokens) |
| 1 | Cambiar precio de lista | PUT (wrapper) | `/publicaciones/app/modificar/omni/api/event-request` | ⚠️ Frágil — **usar API pública** |
| 2/3 | Crear descuento propio / participar en campaña | POST | `/publicaciones/listado/promos/api/confirm-from-modal` | ✅ Sí (requiere `signature`) |
| 4 | **Sacar de UNA promoción específica** | DELETE | `/publicaciones/listado/promos/api/delete-from-modal` | ✅ Sí (por `promoId`) |

**Conclusión clave del punto 4:** la baja **es selectiva por promoción**. Se puede dar de baja UNA sola promo sin tocar las demás, indicando su `promoId` (+ `offerId`).

---

## 0) LECTURA — Promos y candidatos de un ítem

Es la fuente de la que el ERP saca `promo_id`, `promo_type`, `suggestedPercentage`, `signature`, `offerId`, etc.

```
GET /publicaciones/listado/promos/api/items/refresh?viewId=promos&search=MLA852181648&filters=&sort=&page=1
```

Devuelve, por cada promoción candidata/activa del ítem, entre otros:

- `promo_id` — ej. `C-MLA1410487`
- `promo_type` — `seller_campaigns` (campaña propia) | `lightning` (oferta relámpago automática de ML)
- `promo_sub_type` — ej. `FLEXIBLE_PERCENTAGE`, `AUTOMATIC`
- `suggestedPercentage` — el % **mínimo/forzado** por la campaña
- `signature`, `offerId` — tokens necesarios para confirmar/dar de baja

### Convención de IDs de promoción
- **`C-MLA…`** → campaña **propia** del vendedor (seller campaign). Ej: `C-MLA1410487` = "Oferta tradicional Agosto".
- **`P-MLA…`** → campaña de **Mercado Libre** (marketplace). Ej: `P-MLA17907074` = "Descuentazos".

El mismo endpoint de alta/baja maneja ambos tipos, diferenciándolos por el prefijo del id.

---

## 1) PRECIO DE LISTA — cambio de precio

**Recomendación: NO replicar este endpoint interno. Usar la API pública oficial.**

El editor "omni" manda el cambio dentro de un wrapper genérico:

```
PUT /publicaciones/app/modificar/omni/api/event-request
```

Body (resumido):
```json
{
  "method": "PATCH",
  "path": "update/MLA852181648/115764017-update_omni-<SESSION>/user_product_item_detail_form/price-default",
  "jwtEvent": "<JWT firmado, ~295 chars>",
  "body": {
    "output": {
      "value":        { "marketplace": { "currency": "ARS", "price": 21119 } },
      "initialValue": { "marketplace": { "currency": "ARS", "price": 15118 }, "itemId": "MLA852181648" },
      "isSync": false,
      "pricingAttributes": [
        { "id": "VALUE_ADDED_TAX", "name": "IVA", "valueId": "48405909", "valueName": "21 %" },
        { "id": "IMPORT_DUTY", "name": "Impuesto interno", "valueId": "49553239", "valueName": "0 %" }
      ]
    }
  }
}
```
Respuesta: `200`.

**Por qué NO replicarlo:** el `path` lleva un id de sesión del editor (`update_omni-<SESSION>`) y el `jwtEvent` es un JWT firmado; ambos se generan vivos en cada sesión del navegador. Fabricarlos desde el ERP implicaría scrapear una sesión del editor cada vez → frágil.

### ✅ Alternativa oficial recomendada para precio
```
PUT https://api.mercadolibre.com/items/MLA852181648
Authorization: Bearer <access_token OAuth>
Body: { "price": 21119 }
```

---

## 2/3) DESCUENTO PROPIO / PARTICIPAR EN CAMPAÑA ("precio tachado")

Flujo real de "precio tachado": **primero se infla el precio de lista** (paso 1) y **después se aplica el descuento vía la campaña** (este paso). El % se aplica sobre el precio de lista actual.

El flujo dispara 3 requests; el que **aplica** es el tercero.

### a) Abrir modal (trae datos + tokens del candidato)
```
POST /publicaciones/listado/promos/api/modal-ondemand
Body: { "itemId": "852181648", "viewId": "promos", "actionType": "create", "urlCallback": "…" }
```

### b) Simulador de costos (recalcula al mover el %)
```
POST /publicaciones/listado/promos/api/visibility-charges
Body: {
  "itemId": "MLA852181648", "price": 15628.06, "consumerId": "promotions-marketplace",
  "meliRebateContribution": null, "priceType": null, "cumulativeDiscount": false, "isOptined": true
}
```

### c) ⭐ CONFIRMAR — aplica el descuento
```
POST /publicaciones/listado/promos/api/confirm-from-modal
Body:
{
  "itemId": "MLA852181648",
  "actionType": "create",
  "viewId": "promos",
  "impersonalized": false,
  "urlCallback": "… (≈104 chars) …",
  "resource_elements": {
    "promotionId": "C-MLA1410487",         // ← qué promo
    "title": "Oferta tradicional Agosto",
    "suggestedPercentage": 26,             // ← % (mínimo forzado por ML)
    "listPrice": 21119,                    // ← precio de lista (ancla)
    "standardPrice": 21119,
    "price": 15628.06,                     // ← precio final al comprador
    "startDate": "2026-07-30T00:00:00",
    "finishDate": "2026-08-29T23:59:59",
    "signature": "… (66 chars, firmado por ML) …",   // ← obligatorio, viene del refresh/modal
    "cardIdApplied": "… (34 chars) …",
    "itemCbt": false, "totalStock": false, "position": 1, "candidateQuantity": 9,
    "tycChecked": false, "addItemToCampaignCheck": false,
    "couponDetails": {}, "tags": [], "eventIds": [],
    "pricePercentage": null, "pricePrimePercentage": null, "pricePrime": null, "recoCampaignId": null
  }
}
```
Respuesta `200`: *"¡Listo! Tu publicación participa en la promoción."*

> **Importante:** `signature` y `cardIdApplied` NO se inventan. El ERP debe leerlos del `refresh`/`modal-ondemand` del candidato ANTES de confirmar (mecanismo anti-manipulación de ML).

---

## 4) SACAR DE UNA PROMOCIÓN ESPECÍFICA (baja selectiva) — el punto crítico

**Verificado:** saca de UNA sola promo. En la prueba, la publi estaba en 2 promos a la vez (`C-MLA1410487` activa + `P-MLA17907074` programada); al ejecutar la baja de `C-MLA1410487`, esa quedó como "Participar" (fuera) y `P-MLA17907074` siguió intacta. Mensaje de ML: *"…ya no participa en **esta** promoción"* (singular).

```
DELETE /publicaciones/listado/promos/api/delete-from-modal
Body:
{
  "itemId": "MLA852181648",
  "actionType": "delete",
  "viewId": "promos",
  "impersonalized": false,
  "urlCallback": "<URL con los parámetros de abajo>"
}
```

**El "cuál promoción" NO va como campo suelto — va codificado dentro del `urlCallback`:**
```
scope          = mla
view_id        = promos
promotionType  = price_discount
promoId        = C-MLA1410487                    ← acá se elige la promo puntual
offerId        = OFFER-MLA852181648-11409044257  ← id de oferta (ítem + promo)
```
Respuesta `200`: *"¡Listo! Tu publicación ya no participa en esta promoción."*

### Procedimiento ERP para baja selectiva
1. `GET …/promos/api/items/refresh?…&search=MLA<ítem>` → obtener, de cada promo activa, su `promoId` y su `offerId`.
2. Armar el `urlCallback` con el `promoId` + `offerId` de la promo a sacar.
3. `DELETE …/delete-from-modal` con ese callback → baja **solo** esa promoción; las demás quedan igual.

> Nota: al hacerlo por UI aparece antes un `modal-ondemand` con `actionType: "modify"` — es solo la apertura del modal; la baja real la ejecuta el `delete-from-modal`.

---

## Reglas de negocio a implementar en el ERP

1. **Alerta por descuento forzado ≠ 25% lineal.** Cada campaña impone un `suggestedPercentage` mínimo (ej: obligó **26%**). El ERP debe leerlo del `refresh`/`modal` ANTES de confirmar, compararlo con el 25% lineal objetivo, y si difiere → **frenar y avisar** para que el operador decida si va o no.

2. **Cálculo del ancla (precio inflado) según el descuento real.** Para que el precio final quede clavado en el precio real de venta `F` con un descuento forzado `d%`:
   `listPrice = F / (1 − d/100)`
   Ej: F=$15.839 con d=25% → $21.119. Si ML fuerza 26%, para mantener F=$15.839 el ancla debería ser $21.404 (= 15.839 / 0,74).

3. **Orden de operaciones (evitar exposición).** El "precio tachado" requiere 2 guardados (inflar precio + aplicar descuento). Entre ambos hay una ventana donde el ítem puede quedar visible al precio inflado sin descuento. El ERP debe minimizar/gestionar esa ventana (ej. aplicar el descuento inmediatamente después del cambio de precio).

4. **Tokens firmados obligatorios.** `signature` (confirm), `offerId`/`promoId` (delete), `jwtEvent` (precio): siempre leídos de ML en el mismo flujo, nunca fabricados.
