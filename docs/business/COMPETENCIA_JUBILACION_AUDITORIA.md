# Etapa 3.4 — Auditoría para jubilar los módulos viejos de competencia

Estado: **auditoría y propuesta, sin cambios de código** (paso 1 y 2); abajo, las decisiones de Maxx (§7). Un módulo por PR; no se borra nada sin su aviso.
Alcance: **Competidores ML**, **Intel. Competitiva** y **SKUs & Referencias** frente a la pantalla nueva **Análisis de Competencia** (Por SKU, Por categoría, Jugar, Histórico).
Fuente: lectura de `docs/index.html`, `backend/main.py` y los docs de competencia en `main` (commit `dadcbcc`). Los flujos de n8n **no están en el repo** (ver §4).

## 1. Qué hace cada módulo viejo y si la pantalla nueva lo cubre
Leyenda: ✅ cubierta · 🟡 parcial · ❌ no cubierta (no se jubila hasta resolverla).

### 1.1 Competidores ML (`page-competidores`, `loadCompetidores` / `renderCompetidores`)
| Función | En la pantalla nueva | Estado |
|---|---|---|
| Lee **todas** las pestañas `V - <tienda>` (cada publicación de cada competidor: título, precio, tachado, descuento, cuotas, **ventas**, SKU, cantidad) | Solo las referencias activas de `Referencias_Mercado` + `Historial_Precios`; no muestra título, tachado, descuento, cuotas ni ventas del competidor | ❌ (publicaciones sin referencia y **ventas / título del competidor**; los datos solo viven en `V-*`) |
| Filtro por vendedor (botones) | Cuadritos de vendedores | ✅ |
| Buscador de producto / SKU / MLA con autocompletado | Buscador de SKU predictivo (también vendedor y link) | 🟡 (no busca por título) |
| Filtros PM y Categoría | Iguales | ✅ |
| Orden: precio ↑↓, nombre, **ventas ↓** | SKU, ventas propias, cambio, más barato, menor margen | 🟡 (no hay ventas del competidor) |
| Mi precio (PM × cantidad + envío) y Diff % | Igual, por referencia, kits incluidos | ✅ |
| P. Sugerido (competencia − baja %) y margen al sugerido, con desglose por cuotas (▾) | Jugar: margen por forma de pago, «1 % bajo el más barato», igualar, margen objetivo | ✅ |
| **Panel de parámetros de margen** (baja, comisión, extra fijo, IVA, IIBB, cheque, envío, TC; guarda `comp_cfg` en localStorage) | **La pantalla nueva lo usa** (`acCtx` lee `cfg-*` y `COMPDESC`; avisa si algo está desactivado) pero no tiene panel propio | ❌ **dependencia**: hay que mover el panel y `compMargenAt`/`COMPDESC` antes de retirar la página |
| «⚡ Refrescar historial de precios» (`POST /competidores/refresh` + status) | No existe; la pantalla nueva solo relee el Sheet que llena el scraper de la PC | ❌ |
| **«✏ Ecom»: cambia el precio del SKU en la lista «Mercado Libre» de Ecom** (`compModEcom` → `POST /ecom/update-price`) | No existe (Jugar no escribe nada) | ❌ **envía precio** (a Ecom, lista ML): es la etapa posterior |
| Chip de costos de Ecom + «Refrescar costos» | Igual | ✅ |

**Quién lo usa:** menú (`goPage('competidores')`); `COMP.data` lo lee también Intel. Competitiva (contador de vendedores); `compMargenAt`/`COMPDESC`/`cfg-*` los usan Análisis de Competencia, Jugar y Mix; `ML_COSTO_FIJO` y los costos de Ecom son compartidos.
**Backend:** `POST /competidores/refresh` + `GET /competidores/refresh/status/{id}` solo los llama este módulo (más `test_erp_auth.py`). `V-*` es lo que escribe `/ml/vendedor/run` (ML Tools, no se retira).

### 1.2 Intel. Competitiva (`page-intel-competitiva`, `intel*`)
| Función | En la pantalla nueva | Estado |
|---|---|---|
| **Cambios de precio**: lee `V-*`, compara las dos últimas fechas, clasifica (baja fuerte > 10 %, baja, sube, desapareció, sin cambio; umbral 2 %), tarjetas, filtros vendedor/tipo/texto, **export CSV** | Δ % y «desde cuándo» por referencia, «solo con cambios», histórico por SKU y `eventos` (Bajó / Subió / publicación caída) en `/competencia/analisis` | 🟡 **falta**: la franja/lista de eventos del plan 3.1 (nunca se construyó), el umbral «baja fuerte», el export CSV y la cobertura de toda la tienda (hoy solo referencias) |
| **Detector de Ads**: busca una keyword en `sites/MLA/search` vía `/ml-proxy` con el token de ML; no detecta ads (el propio texto dice «próximamente»: marca como ads los 3 primeros resultados) | No existe | ❌ (aunque casi no hace nada útil: decidir si se descarta) |
| **Alertas**: texto fijo («alertas activas», «próximas features»), sin lógica | — | ➖ nada que cubrir (placeholder) |
| Historial local `intel_price_history` / `intel_last_scan` (localStorage) | — | ➖ solo caché del navegador |

**Quién lo usa:** menú; lee `V-*` desde el navegador (API key) y `COMP.data`; el Detector usa `/ml-proxy` (genérico, no se retira).
**Backend:** ningún endpoint propio. **No envía nada a ML.**

### 1.3 SKUs & Referencias (`page-intel-comercial`, `loadIntelComercial` / `renderIntelComercial`)
| Función | En la pantalla nueva | Estado |
|---|---|---|
| Lista de SKU con # de referencias y detalle (Tipo, Entidad, PVP, Activo, Origen, link) leído de `Referencias_Mercado` + `Entidades` | Referencias de tipo **Competencia** y **activas**, con rol Rey/Media/Barato | 🟡 |
| Referencias de tipo **Distribuidor, Cuenta Propia, Mayorista** y referencias **inactivas**, PVP oficial / override, Origen | No se ven | ❌ (la página **Referencias** — `intel-referencias` — muestra el listado plano con esas columnas) |
| Contadores por tipo | — | 🟡 |

**¿Es la forma en que Maca carga referencias hoy? No: es solo lectura** («Fase 1: solo lectura»; no tiene alta ni edición). Maca carga en **su planilla** (`B-SKU-COMPETENCIA` / `A-CATEGORIAS`) y el scraper de la PC sincroniza `Referencias_Mercado` y `Entidades` (`scraper/sincronizar.py`). El backend tiene `POST/PUT/DELETE /intel-comercial/referencias` pero **el front no los llama**: quién los use (n8n, Postman, un script) no se puede ver desde el repo. **A confirmar con Maca.**
**Quién lo usa:** menú; el objeto `INTEL` y `_rowsToObjs`/`fetchSheet` que define este bloque lo reutilizan **Entidades** y **Referencias** (hay que mover el cargador antes de borrar código).
**Backend:** ningún endpoint propio de lectura (lee el Sheet directo). **No envía nada.**

## 2. Qué módulos permiten hoy enviar precios u ofertas a Mercado Libre
| Módulo | Qué envía | ¿Se toca en 3.4? |
|---|---|---|
| **Competidores ML** | «✏ Ecom»: precio a la lista «Mercado Libre» de **Ecom** (no a ML directo) | Está en la lista a jubilar → **NO se jubila** hasta la etapa «Jugar mi precio» con envío |
| Ofertas ML | `PUT items/{mla}` (price + original_price) y baja de promociones, vía `/ml-proxy` | No se toca |
| Verificar ML | `mlPut` (corrige precio de una publicación) y «fixAllML» | No se toca |
| Verificar Ecom | `ecomUpd` (precios en Ecom) | No se toca |
| Campañas ML | No envía: exporta el Excel | No se toca |
| Intel. Competitiva, SKUs & Referencias | **Nada** | — |

## 3. Quién usa los endpoints del backend
| Endpoint | Quién lo llama (repo) | Se puede retirar |
|---|---|---|
| `POST /competidores/refresh`, `GET …/status/{id}` | solo Competidores ML | **No ahora** (el módulo no se jubila todavía) |
| `POST /ml/tracker/run`, `POST /ml/vendedor/run` (+ status, `/jobs`) | ML Tools (queda) | No |
| `POST /intel-comercial/init`, `…/bridge-*`, `…/monitor/run`, `POST/PUT/DELETE …/referencias` | **ningún caller en el front** | **No** (duda: podrían usarlos n8n o scripts) |
| `POST/PUT …/entidades`, `POST …/mix/cargar` | Entidades y Mix (quedan) | No |
| `/ml-proxy*` | muchos módulos | No |
Pestañas del Sheet: `V-*`, `Historial Competidores`, `ML Competencia`, `Referencias_Mercado`, `Entidades`: **no se borra ninguna**.

## 4. n8n
En el repo, n8n consume solo `GET /campanas/calendario`, los reportes de Rentabilidad / motor de precios (`RENT_REPORTE_TOKEN`) y el export de ventas Ecom. **Ninguno es de los endpoints a retirar.** Pero las definiciones de los flujos de n8n **no están en el repositorio**, así que no puedo asegurar que ningún flujo llame a `/competidores/*`, `/intel-comercial/*` o `/ml/vendedor|tracker`. **Hace falta que Maxx exporte los flujos de n8n (o pase la lista de nodos HTTP)** antes de borrar cualquier endpoint. El Cron de Railway solo corre `scripts/ecom_diario.py`.

## 5. Propuesta (paso 2) — espera OK de Maxx
Un módulo por PR, en este orden:
1. **SKUs & Referencias** (el más simple): jubilar; antes, mover el cargador `INTEL` para que Entidades y Referencias sigan andando; **Referencias** queda como visor de los otros tipos. Confirmar con Maca que carga en su planilla.
2. **Intel. Competitiva**: antes, construir en la pantalla nueva la **vista de cambios/eventos** (franja Subió/Bajó/caída, filtro por vendedor y tipo, umbral «baja fuerte», CSV). El Detector de Ads y las Alertas no tienen función real: proponer descartarlos (decisión de Maxx).
3. **Competidores ML**: **no se jubila ahora.** Antes hay que (a) mover el panel de parámetros de margen y `compMargenAt`/`COMPDESC` a la pantalla nueva (hoy la pantalla nueva depende de ellos), (b) decidir qué pasa con las **ventas y títulos de las publicaciones del competidor** (solo existen en `V-*`), (c) resolver «Refrescar historial», y (d) esperar la etapa **«Jugar mi precio» con envío**, porque «✏ Ecom» envía precio.
En cada PR de jubilación: tag `pre-jubilacion-competencia` en `main`, sacar del menú y de las rutas, el link viejo lleva a Análisis de Competencia, no borrar datos ni pestañas, borrar código solo si esta auditoría muestra que nadie lo usa, y actualizar `docs/00_LEEME_PRIMERO.md` y el mapa de módulos.

## 6. Nota para la etapa «Jugar mi precio» con envío
Para elegir la publicación a la que se envía el precio u oferta hay que mostrar **ventas y días de publicada** de cada publicación. Hoy `GET /competencia/publicaciones-propias` y `/competencia/precio-ml` no devuelven ni `sold_quantity` ni la fecha de alta (`start_time`/`date_created`): hay que agregarlos (a revisar contra ML real).

## 7. Decisiones de Maxx (20/10/2026)
- **SKUs & Referencias:** OK al paso 3, con tres condiciones: (1) antes se mueve el cargador `INTEL` que comparten Entidades y Referencias; (2) la página **Referencias** (Distribuidor, Mayorista y Cuenta Propia) **NO se jubila**; (3) Maxx confirma con Maca que solo lee y **avisa** antes de borrar nada.
- **Intel. Competitiva:** primero se construye en la pantalla nueva la lista de eventos, el umbral de «baja fuerte» configurable y el export a CSV. El **Detector de Ads y las Alertas se descartan** (no hacen lo que dicen). Después se jubila el módulo, en su PR.
- **Competidores ML: no se jubila ahora.** De él depende el **panel de parámetros de margen** (`compMargenAt`, `COMPDESC` y los campos `cfg-*`): la pantalla nueva, Jugar y Mix los usan. **Migrarlo es parte de la etapa «Jugar mi precio» con envío**, que va después; recién ahí se puede jubilar (junto con «✏ Ecom», «Refrescar historial» y la decisión sobre las ventas/títulos de `V-*`).
- **n8n:** Maxx pasa los flujos exportados. **No se borra ningún endpoint hasta revisarlos.**
- Antes de borrar código: tag `pre-jubilacion-competencia` en `main`.
