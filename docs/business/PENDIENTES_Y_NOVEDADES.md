# Pendientes y novedades — para revisar y cerrar cuando se pague Railway

> Actualizado: 25/11/2026. Lista viva: se va sumando lo nuevo. Marcá con `[x]` a medida que se confirma.
> **Situación:** la suscripción de Railway está impaga y no hace deploys nuevos. Lo que cambia solo la pantalla (GitHub Pages) se ve apenas se mergea; **todo lo que toca el backend o la tarea de las 06:00 no está en línea** hasta que Railway despliegue. El último deploy activo es el de #186 (19/11).

## 1. Orden para cuando se pague Railway
- [ ] Pagar / regularizar en Railway (View Details del aviso rojo → plan).
- [ ] Servicio **Ayala-s-ERP**: Deployments → **Deploy latest commit** (o Redeploy). Lo mismo para la tarea **illustrious-imagination** (corrida diaria 09:00 UTC = 06:00 Argentina, usa el mismo repo): que tome el último commit.
- [ ] Comprobar que está en línea: abrir `<backend>/openapi.json` y buscar `rechequeo`, `relampago`, `costos-envio/lote` y `ecom-br` (si aparecen, ya está el código nuevo).
- [ ] Refrescar el ERP con Ctrl+F5.
- [ ] Mergear los PR abiertos (sección 2).

## 2. PR abiertos
| PR | Qué es | ¿Necesita Railway? |
|---|---|---|
| #195 | **Verificar Ecom BR — etapa 1 (solo lectura)**: bajar base de stock y simular un Excel. Incluye el arreglo del panel de rechequeo que se veía en todas las pantallas. | Sí (endpoints `/ecom-br/*`) |
| #194 | «Jugar mi precio»: el precio escrito a mano es el final de venta, sin sumarle el envío contra los rivales | No (solo pantalla) |
| #173 | Top Categorías: columna de margen en pesos | No (solo pantalla) |
| #134 | Frávega: estimación con el plan y el envío de cada SKU + aviso de 7 días (de octubre) | A revisar: ¿sigue vigente? |
| #116 | Frávega: ficha de precios, ofertas y cuotas del Seller Center (de octubre) | A revisar: ¿sigue vigente? |
| #60 | Documentación: inventario y orden de rotación de credenciales (incidente de Railway) | No |

## 3. Ya mergeado pero SIN desplegar (se activa con el deploy)
- **#187** Ventas reales Ecom: comisión y envío **sin IVA desde el 18/11** + 4 columnas nuevas en el reporte del Historial. *Hoy las ventas del 18/11 en adelante se siguen calculando con el criterio viejo.*
- **#188 / #191** Precios y ofertas ML: link a la publicación, **SKU madre** (vinculación de Ecom → variantes en vivo → color de la publicación, con «Cómo se buscó el costo»), botón **⚡ Relámpago Group/Arg**.
- **#189** Carga de ofertas por Excel: ajustes que pide ML tildables (precio que acepta, % máximo, margen).
- **#190** Precios y ofertas ML: el PM esperado suma el envío desde $33.000 (real de la última venta) + encabezado fijo de la tabla.
- **#192** **Rechequeo de ventas contra Ecom** (agrega solo las que faltan al ERP y al Sheet) + cierre de Frávega con comisión real que **pisa** sus filas del Sheet sin duplicar.
- **#193** Motor de Precios: un cupón del vendedor («Fieles Global») ya no deja el precio actual en $0.
- (Ya estaban hasta #186: comisiones sin IVA en todos los módulos de precios y márgenes; Verificar Ecom con márgenes al precio puesto; Full ML y reporte de Natalia con tolerancia a 403.)

## 4. Variables de Railway a cargar / revisar
- [ ] `ECOM_BR_EMAIL`, `ECOM_BR_PASSWORD` — Ecom de Brasil (opcional `ECOM_BR_DEPOSITO_DISPONIBLE`, por defecto «Good Storage Jaguaré»).
- [ ] `ERP_ADMIN_USER`, `ERP_ADMIN_PASSWORD` (mínimo 8 caracteres), `ERP_SESSION_SECRET` — usuarios y accesos por módulo (#174). Sin usuarios creados el ERP sigue abierto.
- [ ] `FRAVEGA_SELLER_AUTH`, `FRAVEGA_SELLER_ID`, `FRAVEGA_SELLER_APP` — renovar las cookies del Seller Center (vencen) para cerrar Frávega con comisión real.
- [ ] Rotar `ERP_API_KEY` y `RENT_REPORTE_TOKEN` (pendiente de antes; ver #60).
- [ ] Opcional: `RENT_HISTORIAL_SHEET_ID` si el Historial de Automatizaciones cambia de Sheet.

## 5. n8n (hay que ubicar la instancia)
- [ ] **Encontrar el n8n que manda los reportes.** No está en Railway ni en `ayalaserp.app.n8n.cloud` (esa cuenta no tiene ejecuciones). Ideas: gestor de contraseñas de Chrome (buscar «n8n»), «olvidé mi contraseña» con cada correo, facturas de n8n / tarjeta, cuenta de Google conectada (`myaccount.google.com/connections`).
- [ ] Agregar al **final** de la hoja de ventas del Historial las 4 columnas nuevas (títulos exactos) y mapearlas en el nodo que escribe: `Comision Venta SIN IVA`, `Costo Envio SIN IVA`, `IVA de cargos recuperable`, `Criterio de cargos`.
- [ ] Confirmar que el flujo de Táctica sigue publicado (`0 10 * * 1-5`, zona horaria Argentina) y el de sincronización de Frávega.

## 6. Qué hacer apenas esté desplegado
1. **Rechequeo** (Ventas & Rentabilidad → «🔄 Rechequear ventas contra Ecom»): «Último período cerrado» (23/10 → 22/11) → Revisar → si cierra, Agregar. Con «También cerrar Frávega» tildado. Revisar de nuevo: tiene que dar 0 faltantes. Comparar con los números de Mercado Libre.
2. **Decisión abierta:** las filas del Sheet de las ventas del 18/11 en adelante van a quedar con el cálculo viejo (el rechequeo solo agrega, no pisa salvo Frávega). Si se quiere, se agrega una opción «pisar» para esas fechas.
3. Motor de Precios: «Precio actual» ya no debe dar $0 (las que tienen el cupón «Fieles Global»).
4. Precios y ofertas ML: buscar `MLA1130272651` (SKU madre → mirar «Cómo se buscó el costo» si no resuelve), probar «⚡ Relámpago», la diferencia vs PM con envío, y el lote por Excel con ajustes.
5. Posventa ML: «Ver Group/Arg» (reclamos) y «Respuestas» con período 2; contrastar con la Central de reclamos de ML.
6. Verificar Ecom: márgenes de ML / Web (3 cuotas) / Frávega al precio puesto.
7. Full ML → Actualizar: debe terminar aunque haya publicaciones con 403 (ver las omitidas en el log).
8. Accesos: crear usuarios (Sistema → Accesos) y tildar módulos (incluye los nuevos: «Posventa ML», «Verificar Ecom BR»).

## 7. Verificar Ecom BR (stock Brasil)
- [x] Etapa 1 (solo lectura) hecha: #195.
- [ ] **Subir al repo el script `stock_masivo_ecom.py`** (no está en el repo ni en el entorno) para contrastar la lógica antes de escribir.
- [ ] Confirmar con el script cómo se calcula «Disponible» en los depósitos que no son el de disponible (hoy se muestra igual al stock).
- [ ] **Decidir la compuerta de escritura** (`docs/business/COMERCIAL/00_LEEME.md` §5): escribir stock en Ecom no está habilitado; hace falta una excepción escrita y fechada, con escritura apagada por defecto.
- [ ] Etapa 2: «Confirmar y aplicar» en segundo plano, respaldo previo, verificación por producto (frenar al primer desvío), historial, «Deshacer corrida», permisos de operador.

## 8. Pendientes de antes (siguen abiertos)
- [ ] Accesos, etapa 2: filtrar los datos **en el servidor** por usuario / PM (hoy solo se ordena qué pantallas ve cada uno). Necesita tu aprobación.
- [ ] Comparar el ERP contra los números de referencia (Ecom 23/10–16/11, PM Laura) una vez publicado todo.
- [ ] Revisar las 32 órdenes «canceladas en Frávega pero cobradas en Ecom»; confirmar que la hoja de Frávega tiene 1008 filas.
- [ ] Reporte de Natalia: recuperar 5–11/11 y revisar `publicaciones_sin_acceso`.
- [ ] Validar la regla de pagos (REGLAS_PAGO) y la regla «por PM».
- [ ] Decidir si el espejo de márgenes del backend (envío real) debe igualarse con el del front.
- [ ] Limpiar nodos de Tailscale y la `TS_AUTHKEY` efímera; probar el reinicio de la PC con el puente de Táctica.
- [ ] Diferidos: app de stock con código de barras, módulo de competencia (lo que quede).

## 9. Cosas que conviene recordar
- Todo lo de comisiones y envío de las plataformas se toma **sin IVA (÷ 1,21)** (criterio del 17/11; ver `CRITERIOS_MARGEN.md` §8). Las ventas reales usan ese criterio **desde el 18/11/2026** (lo anterior no cambia).
- Comisión de la Web: 6,05 % (5 % + IVA) y cuotas × 1,21; el envío de la Web se carga a mano (el precio publicado no lo incluye).
- No borrar el servicio **illustrious-imagination** (tarea de las 06:00) ni los volúmenes de Railway.
