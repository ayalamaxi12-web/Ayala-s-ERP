# Verificar Ecom BR — stock del Ecom de Brasil

Pantalla del ERP (sidebar, entre «Verificar Ecom» y «Verificar Táctica») para actualizar stock en el **Ecom de Brasil**: otra instancia del mismo sistema (EcomExperts / EcomGestión),
mismas llamadas y otras claves. Backend: `backend/ecom_br_stock.py` + endpoints `/ecom-br/*` en `backend/main.py`.

## Etapas
| Etapa | Qué incluye | Estado |
|---|---|---|
| **1 — solo lectura** | «Bajar base» (Excel) y «Subir Excel» con vista previa por fila. No existe ninguna llamada que escriba en Ecom. | Hecha |
| **2 — escritura** | «Confirmar y aplicar» (segundo plano, respaldo previo, relectura y verificación por producto), historial de corridas, «Deshacer corrida», permisos de operador. | **Bloqueada** (ver compuerta) |

## Credenciales
Variables de Railway `ECOM_BR_EMAIL` y `ECOM_BR_PASSWORD` (separadas de `RENT_ECOM_*` de Argentina). Login `POST https://api.ecomexperts.com/users/users/doLogin.json`, ÚLTIMA cookie `CAKEPHP`
en `https://api.ecomexperts.com/graphql`; la cookie vence a las 00:06 UTC y se reloguea ante 401/403 o error de sesión (se reutiliza `EcomApiClient`).

## Reglas implementadas (las de `stock_masivo_ecom.py`, según la especificación)
- **Catálogo:** `products.find(page: N, filters: [{filter:"status", values:["1"]}])`, de a 30, hasta que una página no trae IDs nuevos; campos `id sku title active variants { id sku qty cost availableQty commited variantPrices{title price} variantWarehouses{warehouse_title warehouse_qty} }`.
- **Disponible:** la API no resta lo reservado (`availableQty` = stock del depósito); la pantalla de Ecom sí (Disponible = Stock total − Reservado `commited`). En el **depósito con disponible**
  (configurable en la pantalla / `ECOM_BR_DEPOSITO_DISPONIBLE`, por defecto «Good Storage Jaguaré») la cantidad del Excel es DISPONIBLE y se escribiría `cantidad + commited`; en los demás depósitos, el valor tal cual.
- **Validaciones del Excel:** SKU como texto (sin «.0»); cantidades enteras y no negativas; «1.000» / «1,000» se rechazan por ambiguas; cantidad vacía = no se toca, 0 = poner en cero; SKU duplicado con
  cantidades distintas, SKU inexistente (con sugerencia si difiere en mayúsculas), SKU ambiguo y depósito inexistente se rechazan; aviso si el stock nuevo queda menor al reservado.

## Compuerta de escritura (docs/business/COMERCIAL/00_LEEME.md §5)
- **Lectura, conciliación y diagnóstico: habilitadas.** La etapa 1 solo lee y simula → no la afecta.
- **Escritura al canal (incluye «mover stock») está bloqueada**; la única excepción vigente es el módulo de Ofertas ML (2026-08-27) y el propio texto dice que cualquier otra escritura —«Full, Táctica, Ecom,
  WooCommerce, etc.»— «sigue bloqueada y requiere su propia evaluación: no hereda esta», y que «Leer está habilitado. Escribir en [Táctica y ECOM], no». Por eso la **etapa 2 necesita una habilitación expresa**:
  una excepción escrita y fechada en ese documento (como la de Ofertas ML), con la escritura **apagada por defecto** hasta activarla (como «Enviar a Ecom» de «Jugar mi precio»), cola idempotente con reintentos
  (stock > precio > contenido) y modo sombra.

## Pendiente antes de la etapa 2
- El script de referencia `stock_masivo_ecom.py` **no está en el repositorio**: hay que subirlo para contrastar línea por línea (login, paginado, mutación `update` con el `input` anidado por variante, agrupación por producto,
  verificación posterior) antes de escribir una sola cantidad.
- Confirmar con el script cómo se calcula «Disponible» en los depósitos que no son el de disponible (en la etapa 1 se muestra igual al stock).
