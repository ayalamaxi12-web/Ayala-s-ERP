# Full ML: foto guardada, lectura de a poco y alertas

## Diagnóstico del 429 (`stock/fulfillment/operations/search`)
Lo que hace el código de `main` (antes de este PR), sin inventar límites de ML:
- **Solo el simulador de reposición usa ese endpoint.** La conciliación no lo toca: pide `items/search` (⌈ítems/100⌉ pedidos por cuenta), `items?ids=` (⌈ítems/20⌉), `inventories/{id}/stock/fulfillment` (**uno por inventario único**) y, del lado de Ecom, una consulta de vinculación por publicación y una de stock por SKU.
- **El simulador repite toda la conciliación** (`calcular_reposicion_mla` llama a `conciliar()`): todos esos pedidos se hacen otra vez, y recién después viene `operations/search`.
- `operations/search`: por cuenta, ⌈inventarios/20⌉ lotes × **2 tipos** (`SALE_CONFIRMATION` y `INBOUND_RECEPTION`) × las páginas `scroll` de cada uno. Con ~250 publicaciones son unos 26 lotes por cuenta como mínimo. Todo **en serie** (no hay paralelismo), pero con una pausa de 0,4 s que **no existía entre el último pedido de ventas y el primero de envíos**, ni al cambiar de cuenta.
- **Ningún otro proceso del ERP usa ese endpoint** (búsqueda en el repo: solo `ml_full.py`). Si Ofertas, Campañas o Verificar ML comparten cuota con él, **no se puede saber desde el código**: ML no documenta ese límite.
- Los reintentos eran 3 (2, 4, 8 s, o `Retry-After`). Si fallaban, el error subía y **el job entero moría perdiendo todo lo leído** (varios minutos de trabajo).
- Las dos secciones mostraban "corriendo… (0 líneas)" a la vez por un **bug del frontend, no por estado compartido**: el estado de cada job es independiente en el backend. Cuando el backend se reinicia (los jobs viven en memoria), `/status` responde `not_found`; `pollFullJob` lo trataba como "sigue corriendo" y reintentaba para siempre, con el botón trabado. Los errores de red también se ignoraban sin límite.

## Qué cambia
- **Foto guardada** en la base Postgres existente (`ml_foto`, `ml_alerta`, `ml_lote_cache`, migración `j4e5f6a7b8c9`). Al abrir Full ML se muestra la última lectura exitosa sin leer ML, con "Última actualización: hace X" y "Actualizar".
- **Lectura de a poco**: una sola actualización a la vez (lock), una consulta por vez, pausa 1,0 s en `operations/search` y 0,15 s en el resto (valores nuestros, no límites de ML: `ml_full.PAUSA_OPS_SEG` / `PAUSA_GENERAL_SEG`), 6 intentos con espera creciente 2-4-8-16-32 s o el `Retry-After` de ML (tope 60 s).
- **Sin repetir**: cada lote de `operations/search` ya leído se guarda (3 h) y no se vuelve a pedir, ni al reintentar tras un corte. Actualizar la reposición lee la conciliación una vez (o reutiliza la foto de conciliación si tiene menos de 30 min) y deja guardadas las dos fotos.
- **Parcial**: si un lote o un inventario falla, se guarda lo leído y se avisa "datos incompletos para N SKU". Esos SKU se completan con la lectura anterior marcada "dato anterior" (conciliación) o "datos incompletos" (reposición: el cálculo no es confiable). Si falla todo, se conserva la foto y se muestra "Falló la última actualización, mostrando datos de [fecha y hora]" con "Reintentar" y el mensaje sin URL. El job siempre termina; el botón no queda trabado (también si el servidor se reinició).
- **Retención**: una foto exitosa por módulo, cuenta y parámetros (`dias_ventas`, `semanas_objetivo`; la fecha de llegada se guarda dentro de la foto). La nueva reemplaza a la anterior **en la misma transacción que migra las alertas**: si algo falla, queda la anterior.

## Alertas (inventario de lo que hoy muestra Full ML) y su ciclo
| Módulo | Tipo | Clave |
|---|---|---|
| Conciliación | `diferencia_stock` (stock ML ≠ Ecom) | SKU |
| Conciliación | `sin_sku` | publicación |
| Conciliación | `sin_vincular` (factor 1 asumido) | publicación + motivo |
| Conciliación | `sku_no_en_ecom` | SKU |
| Reposición | `venta_censurada` (quebró en Full) | publicación |

Guardan primera vez, última vez vista y estado: `activa`, `ya_no_aparece` (ya no está en la última lectura) y `vista`. Con cada foto: las que siguen se actualizan, las nuevas se crean, las que dejaron de aparecer pasan a `ya_no_aparece` **sin borrarse**; en una foto parcial no se marca "ya no aparece" lo que no se pudo leer. Solo la persona las marca `vista` ("Marcar vista"); las vistas se borran a los 90 días. Una vista que reaparece sigue vista.

## Endpoints nuevos (solo lectura sobre ML/Ecom)
`GET /ml-full/foto/{conciliacion|reposicion}` · `POST /ml-full/foto/{…}/actualizar` · `GET /ml-full/foto/estado/{job_id}` · `POST /ml-full/foto/alertas/{id}/vista`. Los endpoints viejos (`/ml-full/conciliar/*`, `/ml-full/reposicion/*`) siguen existiendo; el frontend ya no los usa.

## Pendiente / límites conocidos
- No se pudo probar contra Mercado Libre real; las pruebas usan datos sintéticos y respuestas simuladas.
- El historial de conciliación en Sheets (`registrar_historial_conciliacion`) solo lo escribe el flujo viejo; el nuevo no lo escribe todavía (queda para decidir con Maxx).
