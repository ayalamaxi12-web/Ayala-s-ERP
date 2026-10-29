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

### 7.6 Escritura de precios: lo confirmado en vivo (29/10/2026)
- `PUT /api/v1/seller-center-service/api/v1/item/{id}/partial` con `{"price":{"list","sale","net"},"stock":{"quantity"},"active":true}`. **El portal manda siempre los tres bloques**, aunque se cambie solo el precio: sin `stock` y `active` Frávega responde 500 y no guarda. El ERP manda los valores actuales de stock y estado para no pisarlos.
- La respuesta es 200 con `error:{message:"",fields:null}` y el **ítem anterior al cambio**: no sirve para verificar. Se verifica con un `GET /v2/item` aparte.
- El cambio llega enseguida al Seller Center, pero la **publicación en la tienda tarda unos 10 minutos** en mostrar el precio nuevo (medido por Maxx). El ERP tolera la demora: si Frávega acepta y todavía muestra el anterior, queda «pendiente» y se relee con «Releer».
- Cuotas (`POST /item/{id}/plan`): sin capturar en vivo todavía.
- El listado (`GET /v2/item`) falla con 500 (error interno de su base) si se piden páginas de 100; el ERP pide de a 25 y reintenta con 10.
