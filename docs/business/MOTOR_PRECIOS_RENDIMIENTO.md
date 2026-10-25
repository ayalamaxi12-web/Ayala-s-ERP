# Motor de Precios: rendimiento de «Calcular» (Bloque 2, PR 1)

## Dónde se iban los ~40 s (leído del código; **no medido contra tu Táctica real**)
«Calcular» con «Todos» hacía **un pedido por SKU piloto, uno detrás de otro** (`ayalaCoreCalcular`, 9 SKU hoy). Cada pedido (`/ayala-core/sku/{sku}/motor`) armaba sus proveedores de cero con `proveedores_de_costo_e_iva()`, y el IVA salía de un `IvaProvider()` nuevo que **consultaba por SQL todo el catálogo de Táctica en cada pedido** (con hasta 5 intentos y 2-4-8-16 s de espera si el túnel está caído). Es decir: **9 consultas SQL a Táctica por cada «Calcular»**, y con la VPN apagada, 9 × ~30 s de reintentos. El resto es barato:

| Parte | Antes | Ahora |
|---|---|---|
| Costos de Ecom | foto en memoria/base (ya era rápido) | igual |
| IVA de Táctica | **1 consulta SQL al catálogo completo por SKU** (9 por «Calcular») | **0 en el cálculo**: foto en memoria, se lee 1 vez por arranque o con «Refrescar costos» (hilo aparte) |
| TC del BNA | cache de 1 h; al vencer, lectura en vivo (hasta 10 s) dentro del pedido | memoria o último guardado, sin esperar; refresca en un hilo aparte |
| Pedidos del navegador | 9 en serie | 1 por lote (`GET /ayala-core/motor-lote`) |
| Cuenta de precios | `calcular_precios_todas_condiciones` | **la misma**, sin tocar una fórmula |
| Render | local | local |

Medición después (backend, 9 SKU × 6 condiciones, fotos cargadas, 20 repeticiones): **mediana 4 ms, máximo 39 ms** de punta a punta con el servidor de pruebas; el endpoint devuelve `tiempos_ms` (`fotos`, `tc`, `calculo`, `total`) para que lo veas con tus datos reales. En el navegador, con respuestas simuladas, la primera carga tardó ~0,1 s y un cambio de porcentaje se recalcula en ~0,35 s (incluye la pausa de 300 ms antes de pedir).

**Lo que no pude medir:** el tiempo real de tu Táctica y de tu Ecom. Si después de este PR «Calcular» sigue lento, mirá `tiempos_ms` en la pestaña Red del navegador y decime qué parte es.

## Qué cambia
- **`GET /ayala-core/motor-lote`**: los SKU pedidos (vacío = todos los piloto) en una sola respuesta, con `calculado_con` (edad de los costos, origen y edad del IVA, TC y su origen) y `tiempos_ms`. Un SKU sin costo/IVA devuelve su error sin tumbar a los demás. No lee Ecom, Táctica ni el BNA en vivo.
- **Foto del IVA de Táctica** (`costos_ecom.IvaTacticaFoto`, `refrescar_iva_tactica`): una consulta por arranque o por «Refrescar costos»; pasadas 24 h se refresca sola en segundo plano sirviendo la foto vieja. Si no hay foto o Táctica no respondió, el IVA sale de Ecom (como ya hacía `IvaConRespaldoEcom`) y la pantalla dice en texto «IVA tomado de Ecom: Táctica no respondió: no se pudo conectar (¿VPN apagada o túnel caído?)». Los mensajes de error no llevan servidor ni IP.
- **«Refrescar costos»** ahora también vuelve a leer el IVA de Táctica, y la barra muestra «IVA Táctica: hace X».
- **TC sin esperar a la red** (`TcBnaClient.obtener_info_rapido`).
- **Pantalla**: «Calcular» (Todos) hace un pedido; muestra «Calculado con costos de hace X · IVA de … · TC … · N ms»; cada cambio de % de renta, SKU, envío o TC recalcula solo (pausa de 300 ms; las respuestas viejas se descartan). El pedido por SKU puntual (con costo manual) sigue igual.
- Las otras pantallas que usan `proveedores_de_costo_e_iva()` (Ofertas ML, simulador, Precios & Márgenes) también leen la foto del IVA en vez de consultar Táctica cada vez; si la foto no existe usan el IVA de Ecom.

## Paridad (test incluido)
`backend/test_ayala_core_lote.py`: para **cada SKU piloto, cada condición de pago** (contado, reducida, 3, 6, 9, 12), 3 juegos de rentas × 4 envíos × con/sin Envío a Bodega (24 combinaciones), el precio del lote es **igual al peso** al de `calcular_precios_todas_condiciones` y al del endpoint por SKU de siempre. Más: ningún cálculo toca Táctica/Ecom/BNA (las funciones en vivo se reemplazan por una que falla), un SKU sin costo no tumba al resto, el TC vencido no espera, y un error de Táctica conserva la foto anterior con causa clara.

## Decisiones tomadas / pendientes
- El IVA de Táctica puede tener hasta 24 h de antigüedad dentro de los cálculos (se refresca en el arranque y con «Refrescar costos»). Es una foto, igual que los costos de Ecom.
- Si el backend se reinicia con la VPN apagada, hasta la próxima lectura el IVA sale de Ecom (con aviso). No cambia ningún precio salvo que el IVA de Ecom difiera del de Táctica para un SKU.
- La unificación con Precios & Márgenes y la foto guardada con «Actualizar» (PR 6) siguen en sus PR.
