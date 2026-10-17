# Análisis de Competencia — contexto propio por SKU (precio real en ML, stock, ventas) — propuesta (2026-10-14, sin construir)

## Hechos verificados en el código
- **Stock**: el Sheet `1xtD_C07rN9Oesn277mD8x-ERPgsZxup3WqF_c_qXJp8`, pestaña `Global`, ya lo lee el backend en producción (`ml_full.TacticaStockSheetAdapter`, cuenta de servicio): A = SKU, E = "Stock Táctica" (confirmado con Maxx 2026-08-25; no es en vivo, se actualiza a la mañana). F y G (Ecom / total) **no están confirmadas**: el adaptador no las lee.
- **Ventas**: el Sheet `1Wzs3SmmIGcGd_NJGfe5qJRBYkJBbyKjrl4rF7reojIE`, pestaña `CONJUNTO`, ya lo lee el front (Histórico de Unidades, API key) con el rango `A1:BZ3000`, que incluye AY:BB. El encabezado de esas columnas y la clave de SKU (hay `sku` y `skuVar`) **no están confirmados**.
- **Precio real en ML**: `GET /items/{id}` → `price` es el TACHADO cuando hay una campaña/oferta activa (bug real, Maxx 2026-09-15; `ayala_core.resolver_precio_real`). El precio que paga el comprador sale de la promoción activa (`seller-promotions/items/{id}`, la de menor precio entre las `started`). Ya existen `competencia_publicaciones.publicaciones_por_sku` (nuestras publicaciones de un SKU, IT y MT; GET `/competencia/publicaciones-propias`, hoy sin usar en la pantalla) y `resolver_precio_real`.
- Sin credenciales de Google ni de ML en el entorno de desarrollo: nada de esto se pudo leer en vivo.

## Propuesta
Sub-etapas (cada una con el OK de Maxx):
- **E1 — Stock y ventas.** Verificar columnas con `backend/scripts/verificar_sheets_contexto.js`. Backend `GET /competencia/contexto-sku` (X-ERP-Key): lee las dos pestañas una vez, cache 10 min (mismo patrón que `/competencia/analisis`), cruce por SKU normalizado (`pricing_pm.norm_sku`, con respaldo sin prefijo `pv-`), devuelve `{sku: {stock: {tactica, ecom, total}, ventas: {d7, d30, d90, d180}}}` + fecha de lectura. Front: chips compactos junto al SKU y desglose plegable; filtro "ocultar sin stock" y orden por ventas 30 d.
- **E2 — Precio real en ML, bajo demanda por SKU.** Al abrir/expandir un SKU: `publicaciones_por_sku` + `resolver_precio_real` por publicación (precio de lista, precio real con la oferta, campaña activa, estado, stock ML, % vs PM). Cache 5 min por SKU.
- **E3 — Opcional.** Botón "cargar precios ML de esta página" con progreso y concurrencia limitada; aviso "ML ≠ PM" en el chip.

## Por qué el precio de ML no se trae para todos a la vez
Cada publicación pide su propia consulta de promociones (1 llamada) y un SKU puede tener hasta ~6 publicaciones por cuenta. Para el catálogo completo son miles de llamadas (minutos u horas, con riesgo de 429): solo se justifica por SKU o por página.

## Estado: E1 construida (stock + ventas desde los Sheets)

- Se leen en el navegador (API key de Sheets) la pestaña `Global` (E/F/G) y `conjunto` (AY/AZ/BA/BB + BC). Datos no en vivo; se cachean 10 min en la sesión y hay botón ↻.
- Madre → variante: el SKU de la pantalla se busca como madre (suma de sus variantes; filas repetidas no suman dos veces); si no está, como variante; también sin el prefijo `pv-`.
- Máximo mensual (BC) del madre = suma de los máximos de cada variante (es un tope, no el máximo de la suma).
- Pantalla: chips bajo el SKU `📦 total (~N d) · 🛒 30d: N`; clic abre el desglose (Táctica/Ecom/Total, 7/30/90/180, ritmo diario, días de stock y tabla por variante). Amarillo si alcanza para menos de 15 días, rojo si el total es 0.
- Filtro "Ocultar sin stock" (solo cuando G = 0; un SKU que no está en el Sheet no se oculta) y orden "Más vendidos (30 d)".
- Si cambia el encabezado de una columna esperada, se lee igual y aparece un ⚠ con el aviso.
- Tests: `backend/test_front_contexto_sku.py`. Pendiente: E2 (precio real ML al abrir el SKU).

## Estado: E2 construida (precio real en ML por SKU, al abrirlo)

- Backend: `GET /competencia/precio-ml?sku=` (protegido con X-ERP-Key, caché de 5 min por SKU, `refrescar=true` la saltea). Busca NUESTRAS publicaciones del SKU en IT y MT (`publicaciones_por_sku`) y, por cada publicación **activa**, lee sus promociones: el precio real es el de la promoción `started` de menor precio (mismo criterio que `ayala_core.resolver_precio_real`); sin promoción vale el precio de lista. Devuelve también el tachado, el nombre de la campaña (cruzado con `promociones_seller`, una vez por cuenta), estado y stock en ML. Las pausadas/cerradas no consultan promociones. Un resultado con errores no se cachea.
- Costo: ~1 llamada a ML por publicación activa (+1 por cuenta para los nombres), solo al abrir el desglose de ese SKU.
- Front: al abrir un SKU aparece en el chip `ML $30.000` (o rango si hay varias activas con precios distintos) y la sección "Mis publicaciones en ML (precio real)" con tabla (publicación, cuenta, estado, precio real, tachado, campaña, stock ML, % vs PM) y botón ↻. Chip amarillo `≠PM` cuando el precio real de alguna activa se aparta más del 1% del precio ML del PM.
- Si ML falla, se ve el error con botón Reintentar; el SKU sigue mostrando stock/ventas.
- No verificado contra la API real de ML (sin credenciales en el contenedor): la forma de `seller-promotions/items/{id}` (`status`, `price`, `original_price`, `promotion_id`) sigue los supuestos ya usados en Ofertas ML.
- Tests: `backend/test_competencia_publicaciones.py` (precio real, caché) y `backend/test_front_contexto_sku.py` (resumen ≠PM).
- E3 (botón "cargar precios ML de esta página") queda sin hacer, solo si lo pedís.
