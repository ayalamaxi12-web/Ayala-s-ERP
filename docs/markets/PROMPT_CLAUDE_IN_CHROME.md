# Prompt para Claude in Chrome (copiar y pegar)

Estoy logueado en el portal de vendedor de **<MARKET: Frávega Seller Center / OnCity / Megatone>**. Necesito documentar cómo traer, orden por orden, **la comisión y el costo de envío reales** que cobra la plataforma, para conectar mi ERP. No hagas ningún cambio en el portal: solo mirar.

1. Abrí la pestaña de red del navegador (DevTools → Network, filtro Fetch/XHR) y navegá: listado de órdenes → buscar una orden por su número → abrir el detalle → abrir cualquier pantalla de liquidaciones/pagos/facturación si existe.
2. Para cada llamada relevante anotá: método, URL (con parámetros), qué header o cookie la autentica (**solo el nombre**, nunca el valor), y un ejemplo de respuesta recortado. **No copies tokens, claves ni cookies.**
3. Ubicá en el detalle de una orden: número de orden, fecha, estado, SKU, cantidad, precio, **comisión (monto y %)**, **envío (quién lo paga y cuánto)**, otros cargos, IVA y neto a cobrar.
4. Probá con 3 órdenes distintas (una entregada, una pendiente, una cancelada/devuelta si hay) y decime si la comisión y el envío están desde que se crea la orden o aparecen recién al entregar o liquidar.
5. Anotá paginación, filtros de fecha y si hay límite de pedidos.
6. Respondé completando la plantilla `docs/markets/_PLANTILLA_FICHA_API.md` (copiala tal cual y llenala), y agregá una sección «Dudas» con todo lo que no pudiste confirmar.

Datos para el cruce con mi sistema: en mi ERP la orden figura como `FVG-v94246555frvg-01` y en el portal se busca como `v94246555frvg-01` (es el mismo número sin el prefijo `FVG-`).
