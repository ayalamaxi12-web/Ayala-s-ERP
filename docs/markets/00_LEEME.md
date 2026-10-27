# Markets (Frávega, OnCity, Megatone y los que se sumen)

Objetivo (Maxx, 27/10/2026): para cada venta de un market tomar **solo la comisión y el envío reales** que cobra la plataforma (Ecom los trae aproximados). Todo lo demás (impuestos, cheque, IIBB, costo por orden, forma de calcular la renta) sigue como está.

## Cómo se cruza una venta de Ecom con la orden del market
- Ecom guarda en cada orden del market un identificador externo. En Frávega es `ownerData.ownerId = FVG-v94246555frvg-01`; **sin el prefijo `FVG-` es el número de orden del Seller Center** (`v94246555frvg-01`, se busca en «N° de orden» de https://seller-center.fravega.com/orders). Ya está leído en el ERP como `venta_ecom.orden_externa` (`backend/rentabilidad/ingesta_ecom_api.py`, `_PREFIJO_ORDEN_FRAVEGA`) y cruzó 1:1 con la liquidación quincenal.
- En la factura de Ecom se ve como «Nro Venta #FVG-v94246555frvg-01».
- OnCity se carga en Ecom como canal manual (`owner == "OnCity"`); Megatone: **falta confirmar** dónde guarda Ecom el número de orden de cada uno.

## Qué existe hoy en el ERP
- Comisión de Frávega: estimada por orden y **reemplazada por la real cuando se carga la liquidación quincenal** (`POST /rentabilidad/fravega/liquidacion`, `liquidacion_neta_fravega`). El plan es reemplazar la espera de la liquidación por la consulta orden por orden al Seller Center, apenas haya datos.

## Cómo documentamos cada market
1. Se completa una **ficha** con `_PLANTILLA_FICHA_API.md` (una por market: `FRAVEGA.md`, `ONCITY.md`, `MEGATONE.md`).
2. La ficha la arma Claude in Chrome con `PROMPT_CLAUDE_IN_CHROME.md` mirando la pestaña de red del Seller Center (no se pegan claves ni tokens: van a variables de Railway).
3. Con la ficha completa se arma el conector, que devuelve siempre lo mismo: `{orden_externa, comision, envio, otros_cargos, neto, fecha, estado}`, y el cruce con Ecom por `orden_externa` queda igual para todos.
