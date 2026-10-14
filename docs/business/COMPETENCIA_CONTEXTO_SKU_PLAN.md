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
