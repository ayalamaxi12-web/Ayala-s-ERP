# Ficha de API — <MARKET>

Fecha de la inspección: …  ·  Quién: …  ·  Portal: …

## 1. Acceso
- URL del portal / de la API: …
- Cómo se loguea (usuario y clave, OAuth, API key, token en header, cookie): …
- Nombre del header o cookie de autenticación (**solo el nombre**, nunca el valor): …
- Cuánto dura la sesión/token y cómo se renueva: …
- ¿Hay una API pública documentada o solo el portal? (link): …

## 2. Órdenes
- Llamada que **lista** órdenes: método, URL, parámetros (fechas, estado, página), ejemplo de respuesta recortado: …
- Llamada que da el **detalle de una orden por su número**: método, URL, ejemplo: …
- Paginación y tope por página: …
- Límite de pedidos (rate limit): …

## 3. Campos que nos importan (nombre exacto en la respuesta y un ejemplo)
| Dato | Campo | Ejemplo |
|---|---|---|
| Número de orden (el que figura en Ecom) | | |
| Fecha de creación / de pago / de entrega | | |
| Estado (y cuáles cuentan como venta firme / cancelada) | | |
| SKU y cantidad por producto | | |
| Precio de venta (con y sin IVA) | | |
| **Comisión**: monto y % | | |
| **Envío**: lo que paga el vendedor, lo que paga el comprador | | |
| Otros cargos (financiación, cuotas, fee fijo) | | |
| IVA sobre comisión/envío (¿ya incluido?) | | |
| Neto a cobrar y fecha de acreditación | | |

## 4. Cruce con Ecom
- Cómo figura la orden en Ecom (prefijo, formato): …
- Cómo se transforma para buscarla en el market: …
- Ejemplo real: Ecom `…` → market `…`

## 5. Casos raros
Devoluciones, cancelaciones, órdenes con varios productos (`-01`, `-02`), cambios de comisión por promoción: …

## 6. Cómo reproducir (para verificar)
Pasos y capturas: …

## 7. Precios, ofertas, cuotas y campañas (para tener los módulos de Mercado Libre en este market)
| Acción | ¿Se puede? | Cómo (pantalla / llamada) | Notas |
|---|---|---|---|
| Leer precio y stock de una publicación | | | |
| Cambiar el precio | | | |
| Precio tachado / oferta con vigencia | | | |
| Elegir cuotas por publicación | | | |
| Campañas del market (propuestas, Excel, alta por API) | | | |
| Carga masiva por Excel | | | |
| Mínimos y máximos de descuento | | | |
