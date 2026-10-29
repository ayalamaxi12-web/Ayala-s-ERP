# Prompt para Claude in Chrome: precios, ofertas, cuotas y campañas (copiar y pegar)

Estoy logueado en el portal de vendedor de **<MARKET: Frávega Seller Center / OnCity / Megatone>**. Necesito documentar cómo **cambiar el precio de una publicación, ponerle una oferta (precio tachado), elegir las cuotas y participar en campañas** desde mi sistema, igual que ya lo hago en Mercado Libre. **Solo observá: no cambies ningún precio, oferta ni cuota por tu cuenta.**

1. En DevTools → Network (filtro Fetch/XHR) navegá las pantallas donde se ven y editan: el listado de publicaciones, el detalle de una publicación (precio, precio de lista/tachado, stock), las promociones/ofertas, las cuotas/financiación y las campañas del market.
2. Para cada pantalla anotá cómo se **lee** (método, URL con parámetros, qué header o cookie autentica: **solo el nombre**, nunca el valor, y un ejemplo de respuesta recortado).
3. Para cada acción de **escritura** (guardar precio, crear/sacar oferta, cambiar cuotas, sumarse a una campaña) decime cuál es el botón y cuál sería la llamada, **pero no lo aprietes**. Si hace falta ver la llamada real, avisame cuál es el caso más inofensivo (un SKU de prueba que después se vuelve al valor original) y esperá mi OK.
4. Contestá estas preguntas con «sí / no / no sé» y evidencia: ¿hay API oficial documentada para precios y ofertas? ¿el precio es por SKU o por publicación? ¿hay precio tachado o solo precio final? ¿las cuotas se eligen por publicación o son un acuerdo general del market? ¿hay campañas (como el Cyber) con propuestas del market? ¿hay mínimos/máximos de descuento? ¿se puede cargar masivo por Excel?
5. Respondé completando la sección **7** de `docs/markets/_PLANTILLA_FICHA_API.md` y agregá «Dudas».

Datos para el cruce con mi sistema: mi SKU es el de Ecom (ej. `PLANCHA-SUB-GORRA`); decime en qué campo el market guarda ese SKU.
