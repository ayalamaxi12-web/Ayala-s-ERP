# Auditoría del ERP — mapa, basura, competencia, automatización y criterios

Fecha: 2026-10-04 · Solo lectura: no se modificó, borró ni movió nada (este archivo es el único agregado).
Método: lectura de código + chequeos con grep. **No se ejecutó la app ni se llamó a ninguna API**; todo lo dicho sobre "qué hace" sale del código. Las referencias `archivo:línea` son del estado actual de la rama.

> Aviso previo: `CLAUDE.md` está desactualizado respecto del repo real. Dice "dos archivos, sin tests, ~4500 líneas, sin Postgres". Hoy hay `index.html` de 7321 líneas, `main.py` de 2431, 6 módulos Python más, un paquete `rentabilidad/` con Postgres + Alembic + ~25 archivos de tests, un cron de Railway y un túnel Tailscale. Ver §2.

---

## 1. MAPA DE MÓDULOS

### 1.1 Frontend — `docs/index.html` (SPA, sin framework)

| Página (div / sidebar) | Qué hace | Fuente de datos | Funciones clave |
|---|---|---|---|
| **Ventas & Rentabilidad** (`dashboard`, + sub-pestaña `dashboard-vivo`) | KPIs, gráficos, consulta en vivo por período, cierres mensuales, validación manual con CSV | Backend `/rentabilidad/*` (histórico, periodo, cierres, agregaciones), `/tc/bna`; llama además a `api.anthropic.com` desde el navegador (`pedirAnalisis` 5229) | `loadDashboard` 4886, `rentConsultar` 7055, `rentGuardarCierre` 7174 |
| **Histórico** | Unidades por mes y SKU | Sheet `HIST_ID` | `loadHistorico` 5272 |
| **Cobranzas** | Cobranzas | Sheet `DASH_SHEET_ID`, tab `Cobranza` | `loadCobranzas` 5466 |
| **Brasil** | Ventas Brasil | Sheet `DASH_SHEET_ID`, tab `Base Brasil` | `loadBrasil` 5541 |
| **Motor de Precios** (`ayala-core`) | Motor reverse-markup por SKU/condición, publicaciones ML, aplicar precio a ML, referencias de competencia por ficha | Backend `/ayala-core/*`, `/tc/bna` | `ayalaCoreLoad` 4032, `ayalaCoreCalcular` 4305, `ayalaCoreConfirmarAplicar` 4744 |
| **Precios & Márgenes** (`pricing`) | Precios por SKU desde el motor unificado; sync de planillas PM | Backend `/rentabilidad/pricing/*` | `pricingSync` 3928, `pricingLoad` 3863 |
| **Verificar Ecom / ML / Táctica** | Compara precio del canal vs precio PM; botones de "corregir" que escriben al canal | Sheets (`ECOM_PUB_ID`, `TACTICA_ID`, PM1-4), CSV, backend `/ecom/*`, `/ml-proxy` | `renderEcom` 1806, `renderML` 1862, `renderTactica` 2019, `fixAllEcom/ML` |
| **Full ML** | Conciliación de stock Full vs Ecom + simulador de reposición por MLA | Backend `/ml-full/*` | `runFullConciliar` 2895, `runFullReposicion` 2925 |
| **Ofertas ML** (`ofertas-margen`, la vigente) | Margen real de cada promo/campaña activa, activar/sacar ofertas | Backend `/ml-ofertas/*` | `ofmRun` 3235, `ofmMargenAt` 3144 |
| **Competidores ML** | Precios de competidores (tabs `V - *`) + simulador de margen | Sheet `COMP_SHEET_ID` | `loadCompetidores` 2117, `compMargenAt` 2224, `compRefreshHistorial` 5601 |
| **Intel. Competitiva** | Detecta cambios de precio entre fechas en `V - *` | Sheet `COMP_SHEET_ID` | `intelRunAnalysis` 5787 |
| **SKUs & Referencias / Entidades / Referencias / Mix** (`intel-*`) | Capa "Inteligencia Comercial": entidades (competidores, distribuidores), links de referencia por SKU, carga masiva | Sheet `COMP_SHEET_ID` + backend `/intel-comercial/*` | `loadIntelComercial` 2232, `mixProcesar` 2517 |
| **Distribuidores** (+ Monitor) | Auditoría de PVP de distribuidores, monitor de precio en vivo | Sheet `COMP_SHEET_ID`, backend `/distribucion/monitor/run` | `loadDistribucion` 2578, `runMonitor` 2762 |
| **Configuración** | URL backend, tokens ML, Sheets API key, PM sheets, tolerancias | `localStorage` (`global_erp_v1`, `erp_backend_url`) | `saveStor` 1743, `connectSheet` 1789 |
| **Reglas de Precio** | Edita la tabla `RULES` (multiplicadores) | `localStorage` | `renderRules` 2856 |
| **ML Tools** | Botones ML Tracker y ML Vendedor | `/ml/tracker/run`, `/ml/vendedor/run` | `runTracker`, `runVendedor` |

Navegación: `goPage` 1695 (ramas 1706-1722), sidebar 208-263. Las 22 entradas de sidebar tienen su div y no hay ramas rotas.

### 1.2 Backend

**`backend/main.py`** (FastAPI, secciones por banner `# ═══`)

| Sección | Endpoints | Qué hace |
|---|---|---|
| ML token | `GET /ml/token` | Refresca/cachea OAuth de las cuentas IT y MT (lógica en `ml_auth.py`) |
| ML proxy | `/ml-proxy` (GET/POST), `PUT /ml-proxy/{mla}`, `/ml-proxy/all-ids/{seller}`, `/ml-proxy/visits` | Passthrough a api.mercadolibre.com |
| ML auth | `POST /ml/exchange` | Canje de código OAuth |
| ML Tracker | `POST /ml/tracker/run` + status | Lee links de tab `ML Competencia`, escribe precio/desc/cuotas |
| ML Full | `/ml-full/conciliar/*`, `/ml-full/reposicion/*` | Delega en `ml_full.py` / `ml_reposicion.py` |
| ML Vendedor | `POST /ml/vendedor/run` + status | Scraper Selenium de tiendas de competidores → tabs `V - *` |
| Jobs | `/jobs`, `/jobs/{id}/log` | Estado en memoria |
| Ecom | `/ecom/login`, `update-price`, `find-listing`, `apply-price-rule`, `set-price-rule`, `debug-html` | Login a app.ecomexperts.com y escritura de precios por scraping de HTML |
| Competidores refresh | `POST /competidores/refresh` + status | Snapshot fechado de precios en tab `Historial Competidores` |
| TC | `GET /tc/bna` | Dólar BNA scrapeado, cache 1 h |
| Distribución | `/distribucion/init`, `/distribucion/monitor/run` | Monitor de precios de distribuidores |
| Intel Comercial | `/intel-comercial/init`, `entidades` (POST/PUT), bridges, `referencias` (POST/PUT/DELETE), `monitor/run`, `mix/cargar` | Capa unificada Entidades/Referencias_Mercado |
| Ofertas ML | `/ml-ofertas/run`, `alertas/run`, `costos-envio/run`, `item/{id}/promociones|costo-envio|buscar|activar|sacar|activar-campana` | Delega en `ml_ofertas.py` |
| Ayala Core | `/ayala-core/skus`, `sku/{sku}/motor`, `publicaciones/run`, `base-mla/run`, `mla/precio-vivo`, `precios-excel`, `producto/{id}/competencia`, `item/{id}/aplicar-precio` | Delega en `ayala_core.py` |

**Módulos Python de `backend/`**: `ml_auth.py` (OAuth, cuentas IT=115764017 / MT=34801784), `ml_full.py` (conciliación Full), `ml_reposicion.py` (simulador de reposición por MLA + parser de PDF), `ml_ofertas.py` (margen de promos, activar/sacar campañas — el más grande, 98 KB), `ayala_core.py` (motor de precios reverse-markup para SKUs piloto).

**`backend/rentabilidad/`** (Postgres + SQLAlchemy + Alembic, router `/rentabilidad`): `calculators.py` (motores Táctica y ECOM), `motor_precios.py` + `pricing_pm.py` + `reportes_pricing.py` (motor unificado de precios por canal), `ingesta_tactica.py` / `ingesta_ecom*.py` / `liquidacion_fravega.py` / `importar_historico.py` (ingesta), `persistencia.py`, `agregaciones.py`, `validador.py`, `auditoria.py`, `regimen.py`, `tc_bna.py`, `cierre_ecom_diario.py`, `reporte_diario.py`, `export_ventas_ecom.py`, `seed.py`, `models.py`, 12 migraciones, ~25 archivos de tests. Endpoints: tactica/ecom (calcular, periodo), cierres, fravega, agregaciones, incidencias, importar-historico, pricing (carga-pm, sync-pm, skus), reportes.

**`backend/scripts/`**: `ecom_diario.py` (corrida diaria, es el cron), `informe_rentabilidad.py`, `ts_sql_bridge.py` y `ts_pc_relay.py` (puentes Tailscale hacia SQL Server de Táctica).

**Infra**: `Dockerfile` (python:3.11-slim + Tailscale), `entrypoint.sh`, `railway.json` (servicio web), `railway.cron.json` (cron `0 9 * * *` → `scripts/ecom_diario.py`).

**Docs** (`docs/`, no código): constitución y especificaciones (`00_LEEME_PRIMERO.md`, `RENTABILIDAD_FUNCIONAL.md.md`, `business/COMERCIAL/**`), Apps Script `base_mla.gs`, planillas xlsx.

---

## 2. POSIBLE BASURA (no se borró nada)

| # | Qué | Por qué parece descartable / a revisar |
|---|---|---|
| 1 | **Ofertas ML "vieja"** — `page-ofertas-ml` (HTML 1159-1230) + JS `ofertas*` (6047-6586), `OFERTAS_ID`, `OFERTAS_TABS`, `OFERTAS_BASE_URL`, `SHEETS_BR`, rama `goPage` 1718, listeners en `init()` | Sacada de la sidebar el 2026-08-27 ("Código intacto, sigue en el DOM", comentario 237-239). Inalcanzable. Además calcula con criterio viejo (tachado ×1.25, envío plano 8500, sin cuotas). ~540 líneas |
| 2 | `intelSaveHistory` (5781), `intelHistory` (5763), `localStorage intel_price_history` | Nadie escribe jamás el historial; `intelLoadHistory` siempre lee vacío. Funcionalidad a medias/muerta |
| 3 | Pestaña "Alertas" de Intel. Competitiva (1127+) y "Detector de Ads" | Texto hardcodeado sin lógica; el detector tiene aviso propio de que no detecta ads reales |
| 4 | Funciones nunca referenciadas: `getSubcat` 1679, `getCatLabel` 1680, `getPM` 1681, `pn` 1688 | 0 usos (verificado por conteo de ocurrencias sobre 335 funciones) |
| 5 | Constantes sin uso: `ECOM_PUB_GID` 1510, `S.cPage` 1503, `window._brDChart/_brCChart` (solo se escriben) | Residuos |
| 6 | Endpoints de `main.py` que el frontend nunca llama: `GET /`, `/ml-proxy/all-ids/{seller}`, `/ml-proxy/visits`, `POST /ml/exchange`, `/jobs`, `/jobs/{id}/log`, `/ecom/find-listing`, `/ecom/apply-price-rule`, `/ecom/set-price-rule`, `/ecom/debug-html`, `/distribucion/init`, `/intel-comercial/init`, los dos `bridge-*`, `/intel-comercial/monitor/run`, `/intel-comercial/referencias` (POST/PUT/DELETE) | Pueden ser herramientas manuales (init, bridges, exchange OAuth, debug) y no basura. Los realmente sospechosos: `ecom/find-listing`, `apply-price-rule`, `set-price-rule` (¿reemplazados por `update-price`?) y **`/intel-comercial/monitor/run`** (monitor unificado sin botón) |
| 7 | Endpoints `/rentabilidad/*` sin llamador en el front: `cierres/ecom/excel`, `fravega/pendientes`, `reporte/ecom/diario`, `incidencias`, `importar-historico`, `reporte/pricing/desvio-precios`, `reporte/pricing/ofertas`, `reporte/ecom/ventas` | No verifiqué si los usan scripts/cron externos. `reporte/ecom/diario` y `ventas` probablemente los usa `ecom_diario.py`/informes |
| 8 | `docs/business/COMERCIAL/canales/fravega/liquidacion actual.xlsx` | Archivo de trabajo con datos reales de venta, con espacio en el nombre. `ECOM_EXCEL_RELEVAMIENTO.md` dice expresamente que esos archivos "se eliminan después de validar" |
| 9 | `FULL_TABLA_OPERATIVA.xlsx`, `PLANTILLA_CARGA_FULL_ML.xlsx` | `ml_full.py` dice que el módulo "reemplaza la planilla `FULL_TABLA_OPERATIVA.xlsx`". Probable archivo histórico |
| 10 | `docs/00_LEEME_PRIMERO.md` lista 6 archivos (`01_TRASPASO_ERP.md`, `02_RENTABILIDAD_FUNCIONAL.md`, `03_…IMPLEMENTACION.md`, `04_MAPA_API…`, `05_MCP…`, `Motor_Pricing_Componentes.xlsx`) | **Ninguno existe en `docs/`** con esos nombres → referencias rotas. Los equivalentes tienen otros nombres/ubicaciones (`business/RENTABILIDAD_FUNCIONAL.md.md`, `architecture/RENTABILIDAD_IMPLEMENTACION.md.md`) |
| 11 | Extensión `.md.md` en `RENTABILIDAD_FUNCIONAL.md.md` y `RENTABILIDAD_IMPLEMENTACION.md.md` | Nombre erróneo (y rompe la referencia anterior) |
| 12 | `CLAUDE.md` | Describe un repo de dos archivos sin tests/DB/cron. Desactualizado; además dice que "Verificar Ecom" tiene Web y Fravega "built in" y menciona `RULES`/`calcExp` (siguen vigentes), pero omite Motor de Precios, Pricing, Full ML, Rentabilidad v2, `ml_*`, `ayala_core`, Postgres, cron |
| 13 | Raíz: `ECOM_EXCEL_RELEVAMIENTO.md`, `TACTICA_SQL_RELEVAMIENTO.md`, `TECH_DEBT.md` | Docs sueltos en la raíz en vez de `docs/`. No basura, pero desordenado. `TECH_DEBT.md` documenta observabilidad pendiente |
| 14 | **Duplicado**: lanzamiento de Chrome/Selenium copiado en `vendedor_job` (main.py:488-494) y `_monitor_launch_driver` (1140-1153) | Dos copias casi idénticas |
| 15 | **Duplicado**: cuatro lectores de precio-por-link (`tracker_job`, `refresh_job`, `leer_precio_publicacion`, `precio_vivo_mlas`) | Cada uno parsea precio/tachado a su manera (ver §3) |
| 16 | `backend/test_*.py` en la raíz de `backend/` (4 archivos, ~160 KB) + `rentabilidad/tests/` | Dos ubicaciones de tests; `main.py` no tiene tests. No es basura, es inconsistencia |
| 17 | `.claude/settings.json` | Permite `mcp__Gmail__send_message` sin pedir confirmación. No es basura pero conviene que lo sepas |
| 18 | **Seguridad** (no basura, pero lo vi): `API_KEY` de Google Sheets hardcodeada en el HTML público (`index.html:1531`); CORS `allow_origins=["*"]` sin autenticación en `main.py:24` — cualquiera con la URL del backend puede llamar `/ml-proxy` (PUT), `/ecom/update-price`, `/ayala-core/item/*/aplicar-precio`, `/ml-ofertas/item/*/activar` | A decidir por vos |

---

## 3. ANÁLISIS DE COMPETENCIA

### 3.1 Hallazgos que cambian el planteo

1. **El `ml_vendedor.py` que corrés con el `.bat` NO está en el repo.** Se lo cita en `ML_INTEGRACION_MAPA.md:23` ("⚠️ A medias, 2 pasadas, corre local, 1×día por anti-bot"), `index.html:2118` y `ml_reposicion.py:371`. Tampoco hay ningún `.bat`, `.cmd` ni `.ps1` versionado. Según el comentario de `index.html:2118-2123`, ese script agrega, a la derecha de A:I de cada tab `V - *`, un bloque de 4 columnas por fecha (`Precio ($) dd/mm/yyyy`, `Tachado…`, `Desc…`, `Cuotas…`). **Ese es hoy el único histórico que realmente lee la UI**, y lo escribe un script que no está versionado.
2. **El endpoint `/ml/vendedor/run` del repo es otra cosa** (versión vieja, solo crea la pestaña y la **salta si ya existe**, main.py:578-582) y **no puede correr en Railway**: `requirements.txt` no incluye `selenium` ni `webdriver-manager` y el Dockerfile no instala Chrome. `00_LEEME_PRIMERO.md:76` lo asume: el scraping con navegador es local.
3. **No existen fotos/capturas.** Cero imágenes, screenshots ni thumbnails de competencia en backend o frontend (el scraper no lee `img src`). Lo que llamás "fotos" hoy son **columnas de precio con fecha** en las tabs `V - *`. Si querés imágenes reales (captura de la publicación), **hay que construirlo** (`01_MAPA_API.md:64` lo reconoce como hueco). Ojo: el campo `thumbnail`/`pictures` sí viene en la API de ML (`/items`), pero hoy nadie lo guarda.
4. **No hay ningún scheduler de competencia** (ni apscheduler, ni loops, ni n8n; `n8n` no aparece en el repo). El único cron real es `ecom_diario.py` (Rentabilidad). Todo lo de competencia es manual.
5. **Tres históricos paralelos que no se leen entre sí** (ver 3.3).

### 3.2 Inventario de piezas

| # | Pieza | Dónde | Qué hace | Fuente | Vivo / guardado | Disparo |
|---|---|---|---|---|---|---|
| C1 | **`ml_vendedor.py` local** (fuera del repo) | tu PC / `.bat` | Scrapea tiendas de competidores; agrega bloque de columnas por fecha en cada `V - *` | Selenium sobre ML | Guardado, **con histórico** (columnas fechadas) | **Manual** (`.bat`), 1×día si te acordás |
| C2 | Scraper `/ml/vendedor/run` | main.py:458-597 | Crea `V - <vendedor>` (A:I) desde tab `Vendedores`; **salta pestañas existentes** | Selenium | Guardado, sin histórico | Manual (botón ML Tools); solo anda local |
| C3 | **ML Tracker** | main.py:352-401, botón ML Tools | Lee links de tab `ML Competencia` col A y escribe B:H (título, vendedor, precio, tachado, desc, cuotas, fecha) | ML API (`fetch_item/product/seller`) | Guardado **sobrescribiendo** (sin histórico) | Manual |
| C4 | **Refresh de histórico** | main.py:791-948, botón "⚡ Refrescar historial" en Competidores | Para todos los MLA de `V - *`, pide precio actual por lotes y agrega snapshot fechado a tab `Historial Competidores` (12 cols, máx. 10 fechas) | ML API (`/items?ids=`) con token del front | Guardado, histórico largo. **Ningún lector en el front lee esta tab** | Manual |
| C5 | **Competidores ML** (UI) | index.html 627-682, 2117-2225 | Muestra precios `V - *` (última columna `Precio ($)`), cruza `General!A:D` por link → SKU/cantidad, cruza PM+categoría, simula margen (`compMargenAt`), "Modificar en Ecom" | Sheets | Guardado (lo que dejó C1) | Carga manual |
| C6 | **Intel. Competitiva** (UI) | index.html 1034-1160, 5787-6016 | Compara última fecha vs anterior en bloques de columnas de `V - *`: sube/baja/desapareció (umbral 2 %, baja fuerte 10 %) | Sheets (formato de C1) | Guardado | Manual |
| C7 | **Intel Comercial: Entidades / Referencias_Mercado / Discovery_Sugerencias / Intel_Config** | main.py:1240-1850; UI "SKUs & Referencias", "Entidades", "Referencias" | Modelo nuevo: quién (entidad) y qué link (referencia) por SKU, con PVP y tolerancia. Referencias en UI es **solo lectura** | Sheet `COMP_SHEET_ID` | Guardado | Manual (CRUD) |
| C8 | **Mix** | main.py:1857-1962, UI "Mix" | Carga masiva (SKU, link) → crea entidad+referencia, **lee precio en el momento** y muestra margen. No guarda lectura | ML API/Selenium | Vivo (solo al cargar) | Manual |
| C9 | **Monitor unificado** | main.py:1579-1630 | Recorre `Referencias_Mercado` tipo Competencia/Cuenta Propia/Mayorista, lee precio vivo, calcula diferencia vs PVP, **agrega a `Monitor_Lecturas`** (histórico append-only) | ML API → fallback Selenium | Vivo + guardado | **Sin botón en la UI; sin cron** |
| C10 | **Monitor de Distribuidores** | main.py:1026-1239, UI Distribuidores > Monitor | Igual que C9 pero sobre `Distribuidor_SKU` | ML API → Selenium | Vivo + guardado (`Monitor_Lecturas`) | Manual (botón) |
| C11 | **Competencia por ficha de catálogo** | main.py:2376, `ayala_core.py:454`, UI Motor de Precios "Referencias de competencia" | Lista ofertas de todos los vendedores de una ficha `/p/` (excluye cuentas propias) | ML API `/products/{id}/items` | **Vivo, nada guardado** | Manual |
| C12 | **Referencia de competencia por SKU/condición** | `AC_REFERENCIAS` (index.html 4068-4105) | Oferta elegida para comparar contra el precio calculado | C11 | **Solo en memoria JS; se pierde al recargar** | Manual |
| C13 | **Precio vivo de MLA** | main.py:2342, `ayala_core.py:418` | Precio/tachado/desc de MLAs | ML API con token de la cuenta | Vivo | Manual. **Solo publicaciones PROPIAS** (por ownership ML da 403 en ítems ajenos) |
| C14 | Base MLA | main.py ~2325, `base_mla.gs` | Mapa SKU↔MLA de publicaciones **propias** | ML API | Guardado en Excel "VENTAS POR CANALES MATIAS" | Manual (menú Apps Script) |

**Dónde están los links de competidores guardados** (todos en Google Sheets, nada en DB ni localStorage): `V - <vendedor>` col G · `ML Competencia` col A · `General` A:D (link→SKU/cantidad/vendedor) · `Historial Competidores` col G · `Referencias_Mercado.Link_Publicacion` · `Distribuidor_SKU.Link_Publicacion` · `Monitor_Lecturas.Link` · `Entidades.Link_ML`.

### 3.3 Solapamientos / problemas estructurales

- **Tres históricos que no se hablan:** (a) bloques de columnas fechadas en `V - *` (lo escribe C1, lo leen C5 y C6); (b) `Historial Competidores` formato largo (lo escribe C4, **no lo lee nadie**); (c) `Monitor_Lecturas` append-only (lo escriben C9/C10; la UI de Distribuidores lee solo las primeras 10 columnas y no las 6 extendidas de Intel).
- **Dos modelos de "link de competidor" desconectados:** legado (`V - *` + `General` + `ML Competencia`) vs. nuevo (`Referencias_Mercado`). Los vendedores `V - *` **no están puenteados** a `Entidades`/`Referencias_Mercado` (solo existe bridge para Distribuidores).
- **El SKU de la fila de `V - *` se completa a mano** (cols H/I del scraper quedan vacías, o se cruzan por `General`). Si falta, la fila queda "Sin categoría", sin PM y sin margen. Es el cuello de botella del filtro por PM/categoría.
- **Contradicción con la constitución:** `00_LEEME_PRIMERO.md:136` dice "no construir un módulo separado de Inteligencia Competitiva: está absorbido en el CGCC". Hoy existen ~8 páginas de competencia.
- **Observabilidad:** los logs de `tracker_job`/`vendedor_job`/`refresh_job` viven solo en memoria y no llegan ni a Railway ni a la UI (`TECH_DEBT.md`). Pausado "hasta definir prioridades CGCC / Inteligencia Competitiva".

### 3.4 Lo que querés vs. lo que ya existe

| Requerimiento | ¿Existe? | Detalle |
|---|---|---|
| Histórico con "fotos" (último precio tomado, ver cuándo subió/bajó) | **Parcial** | El histórico de **precios** existe (a), (b), (c) pero fragmentado y el principal depende de un script no versionado. **No existen capturas/imágenes.** C6 compara solo las dos últimas fechas; no hay línea de tiempo ni gráfico por competidor/SKU |
| Precio EN VIVO de un link guardado, por fila, al mirar el histórico | **No** | Hay piezas sueltas: C9 (lo haría en lote para `Referencias_Mercado`, pero sin botón), C10 (solo distribuidores), C8 (solo al cargar links nuevos), C4 (lote completo, no por link), C13 (solo propios). Falta un "precio actual de este link ahora" por fila |
| Filtro por categoría/PM en histórico | **Sí, solo en Competidores ML (C5)** | Multi-select PM (`ms-comp-pm`) y categoría (`ms-comp-cat`), resueltos por SKU vía `S.pmData` y `getCat`. Intel. Competitiva (C6) y toda la capa `intel-*`/Distribuidores **no** tienen filtro de PM ni categoría |
| Filtro por categoría/PM en vivo | **No** | Ninguna vista en vivo lo tiene |

### 3.5 Cómo se podrían unificar (conceptual, sin construir)

**Una sola entidad de dominio y una sola tabla de lecturas:**

1. **Registro único de links** = `Referencias_Mercado` (ya tiene SKU, Tipo, Entidad, Link, PVP, tolerancia, Activo, Origen). Migrar a él, por única vez, lo que hoy vive en `V - *` + `General` + `ML Competencia`, y definir que **toda alta nueva (Mix, scraper de tienda) termine ahí**. El SKU deja de ser "columna H a mano": se resuelve una vez por link y queda guardado. Categoría y PM se **derivan por SKU** (no se guardan), igual que hoy.
2. **Un único histórico de lecturas** (formato largo, append-only, un registro por link por toma): `link/item_id · fecha_hora · precio · tachado · descuento · cuotas · vendedor · estado · origen_de_lectura (scraper_local | api | vivo) · (opcional) thumbnail_url`. Es lo que ya es `Monitor_Lecturas`; absorbe a (a) y (b). Esto responde a la pregunta de "cuándo subió/bajó": es una serie de tiempo, no dos fotos.
3. **Un único lector de precio por link** (hoy son cuatro con parseos distintos) con orden: API de ML si el ítem lo permite; catálogo `/p/` vía `products/{id}/items`; y como último recurso lo que traiga el scraper local. Ojo con el límite documentado: **los ítems ajenos dan 403 por ownership** en `/items/{id}` — por eso existe el Selenium. Esto condiciona el "precio en vivo": para links de competidores solo es confiable (a) vía ficha de catálogo `/p/`, o (b) vía scraping. El scraping no corre en Railway; entonces "en vivo" para un link no-catálogo requiere o un worker con navegador (fuera del tier gratis) o un endpoint que **la PC local** exponga/consulte. **Esto es una decisión de arquitectura tuya**, no un detalle.
4. **Una sola pantalla** (absorbe Competidores ML + Intel. Competitiva + Referencias + Mix + Monitor), con dos modos sobre los mismos filas:
   - **Histórico:** línea de tiempo por link/SKU/competidor con "última toma", delta y fecha del último cambio (qué subió/bajó y cuándo). Si querés imagen real, la toma guarda `thumbnail_url` (ML la devuelve) o una captura; si no, la "foto" es la fila de la última lectura.
   - **En vivo:** botón por fila (y por selección) "pedir precio ahora" → dispara el lector único, muestra precio actual vs. última toma con diferencia, y **opcionalmente** lo guarda como una lectura más (`origen=vivo`) para que quede en el histórico.
   - **Filtros comunes** a ambos modos: PM, categoría, competidor, SKU, tipo de entidad, "cambió desde la última toma". Salen del mismo mapeo SKU→PM/categoría ya existente.
5. **Automatización:** la toma masiva diaria pasa a un disparador programado (hoy: tu `.bat`). Opciones a decidir, sin construir: tarea programada de Windows (cron local) que ejecute el scraper, o mover a un worker con Chrome. Ver §4.

**Qué se reutiliza tal cual:** `Referencias_Mercado`/`Entidades` (modelo), `Monitor_Lecturas` (histórico), `leer_precio_publicacion` (lector), `compMargenAt`/filtros PM+categoría de Competidores ML (UI), `GET /products/{id}/items` (precio vivo de catálogo), `Mix` (alta masiva).
**Qué falta:** versionar el scraper local; migración de links legados a `Referencias_Mercado` con SKU resuelto; una sola serie de lecturas; botón de precio vivo por fila; vistas con línea de tiempo; filtros PM/categoría en las vistas nuevas; (si lo querés) captura de imagen; scheduler.

---

## 4. ESTADO DE AUTOMATIZACIÓN

Lo único automatizado en el repo es **un cron**: `railway.cron.json` → `0 9 * * *` → `entrypoint.sh python scripts/ecom_diario.py` (cierre Ecom diario; sincroniza PM antes). No hay n8n, apscheduler ni loops periódicos. Los jobs en background (`BackgroundTasks`/threads) los dispara siempre un botón y su estado vive en memoria (`job_status`), así que se pierde si Railway reinicia.

| Módulo | Estado | Nota |
|---|---|---|
| Cierre/Rentabilidad Ecom diaria | ✅ **Automático** (cron 9:00) | Es lo único que corre solo |
| Rentabilidad Táctica (SQL Server vía Tailscale) | 🟡 A pedido desde la UI | El túnel depende de `TS_AUTHKEY`; si no levanta, Táctica queda vacío |
| Rentabilidad: carga de cierres mensuales, Fravega liquidación | ✋ Manual (botones/archivos) | |
| Sync de planillas PM → DB | 🟡 Semi: corre dentro del cron Ecom y desde botón en Precios | |
| **Scraper ml_vendedor (histórico de competidores)** | ⚠️ **Manual, útil, sin terminar** | Corre en tu PC con `.bat`; **no versionado**; "A medias" según `ML_INTEGRACION_MAPA.md`. Es el eslabón más frágil: si te olvidás, el histórico tiene huecos |
| ML Tracker | ✋ Manual | Sobrescribe, sin histórico: puede quedar redundante con C4/C9 |
| Refresh de histórico competidores | ✋ Manual | Escribe una tab que nadie lee |
| Monitor unificado `/intel-comercial/monitor/run` | ⚠️ **Útil pero sin terminar** | Backend completo, **sin botón ni scheduler** |
| Monitor Distribuidores | ✋ Manual (botón) | Fallback Selenium no corre en Railway |
| Intel Comercial init / bridges | ✋ Manual por API | Sin UI |
| Ofertas ML (lectura/alertas/costos de envío) | ✋ Manual | Alertas de margen se calculan cuando las pedís, no avisan solas |
| Full ML conciliación / reposición | ✋ Manual | El PDF "instrucciones de preparación" se sube a mano |
| Motor de Precios (Ayala Core), base MLA | ✋ Manual | Aplicar precio a ML es siempre manual (y deliberadamente "puerta de escritura" cerrada por doc) |
| Verificar Ecom/ML/Táctica | ✋ Manual | Sin cron de verificación |
| Tipo de cambio BNA | 🟡 Cache 1 h, a demanda | Hay **dos** implementaciones: `main.py /tc/bna` y `rentabilidad/tc_bna.py` |
| Histórico / Cobranzas / Brasil | ✋ Carga manual desde Sheets | |

---

## 5. DEUDA / CRITERIOS INCONSISTENTES (margen, cargos y descuentos)

Esto responde por qué "no siempre dan los mismos números". Hay **siete lugares** que calculan margen o precio esperado con criterios distintos: `compMargenAt` (Competidores), `ofmMargenAt`+`ml_ofertas.calcular_margen_oferta` (Ofertas), motor Ayala Core (`ayala_core.py` + espejo JS 4111-4176), `rentabilidad/calculators.py` (Táctica y ECOM), `rentabilidad/motor_precios.py` (motor unificado), KPIs del Dashboard, y `informe_rentabilidad.py`. Más `calcExp`/`RULES` para precio esperado.

### 5.1 Base del margen % (la fuente de discrepancia más seria)

| Lugar | Fórmula | Base |
|---|---|---|
| `calculators.py` Táctica (`AA/P`) | rentabilidad / precio | **neto** |
| `calculators.py` ECOM `AV` = `1 − AA/Z` | | **Z** = neto − comisión − envío − cheque − IIBB − OP |
| `ofmMargenAt` / `calcular_margen_oferta` / `motor_precios` | `margen / baseSinIva` | **neto** |
| `compMargenAt` (index.html:2224) | `mars/(mars+costo)` | **neto − cargos** (distinto de todos) |
| Ayala Core (`renta/precio`, ayala_core + JS 4165) | | **bruto (con IVA)** |
| Dashboard Ventas (5141-5199) | `rent / Σ precioFinal` | **bruto** |
| `informe_rentabilidad.py` | `rent / fact sin IVA` | **neto** |

El propio `RENTABILIDAD_FUNCIONAL` se contradice: §11 dice "siempre sobre el neto", §7.7 define `AV` sobre `Z`. **El Dashboard muestra un % sobre bruto y el informe sobre neto del mismo negocio.**

### 5.2 Cargos y valores distintos para el mismo concepto

| Concepto | Valores (archivo:línea) |
|---|---|
| **Comisión ML general** | 16 % (`index.html:640`, Competidores) · 15,5 % (`index.html:3130`, `ml_ofertas.py:157`, `seed.py:119`) · **15,32 %** (`ayala_core.py:42`, `index.html:4111`, AYALA_CORE) |
| Comisión ML por categoría | Por `domain_id` de ML (14,3–15,5) en Ofertas vs. por categoría de GRAL CATEGORIAS (14–16) en `seed.py:133`. Tablas no comparables 1 a 1 |
| **IIBB** | 5 % en todo **salvo Ayala Core: 6,50 %** (`ayala_core.py:43`, `index.html:4111`) |
| **Impuesto al cheque** (1,2 % s/bruto) | Lo restan Competidores, Ofertas, `motor_precios`, `calculators`. **Ayala Core no lo resta** |
| **IVA sobre comisión/envío** | Ayala Core lo **netea** (`/1.21`, crédito fiscal). Ofertas, Competidores y `motor_precios` (`iva_cargos=0`, decisión Maxx 2026-09-29) lo restan **completo**. Fravega/Web usan `iva_cargos=0,21` |
| **Costo fijo ML** | 1255 / 2500 / 3030 (`index.html:2223`, 3131, `ml_ofertas.py:161`) vs. **1330 / 2740 / 3320** (`seed.py:157-159`) vs. ninguno en Ayala Core |
| **Cuotas ML (% costo)** | 8,90 / 13,40 / 17,80 / 21,60 en Ofertas, backend, `seed.py`, `CUOTAS_PCT_ML` — **Competidores usa 4,08 / 9,48 / 15,12 / 18,24 / 26,52 y un plan de 18 cuotas** (`index.html:650-654, 2225`) que el REQ §1.2.b pide eliminar |
| **Multiplicador de cuotas en precio** | `RULES` (1,15/1,20/1,25/1,35; mayorista 1,15/1,25/1,35/1,50) y Competidores (…/1,45) vs. `1+cuotas%/100` (1,089/1,134/1,178/1,216) en `ml_ofertas.py:958` y `index.html:3285`. **Dos criterios para lo mismo.** `index.html:1525-1528` reconoce que `RULES` es un margen propio |
| **Envío** | Plano **8500** desde 33.000 (`S.shippingCost`, `calcExp`, Competidores, Ofertas legacy) vs. **tramos 0/7000/7470** (`ml_ofertas.py:189`, `OFM`) vs. **envío real por publicación** (Ayala Core, `motor_precios`, ECOM). El umbral 33.000 coincide en todos |
| **Tipo de cambio fallback** | 1465 (`index.html:2185`) · 1455 (6620) · **1** (`main.py:2075`, `ml_ofertas.py:1324/1375/1685`) |
| **Costo del producto** | Planilla PM en Competidores; **Táctica** en Ofertas, Ayala Core y `motor_precios` (el REQ dice "nunca la planilla PM") |
| **IVA del SKU si falta** | `pm.iva\|\|1.21` (Competidores), `Decimal("1.21")` (`pricing_pm.py:465`, `reportes_pricing.py:123`); el RF §5.4 dice no asumir 21 % |
| **Financiación Táctica** | cf1/cf2 = 3 % (`seed.py:45-46`); el RF dice que ECOM no debe tener costo financiero |
| **Fravega estimado** | `precio_final*0.15*1.21` (`persistencia.py:396-409`) vs. `motor_precios` (comisión 0,15 + fee logístico 8500 + escala 35.000) |
| **Redondeo de precio** | `motor_precios`: hacia abajo a decena + 9. Ayala Core: redondeo a entero |

### 5.3 Reglas de descuentos / ofertas / umbrales definidos en más de un lugar

| Regla | Valores |
|---|---|
| **Descuento de "Oferta Tradicional" / tachado** | `RULES` = 1,25; tachado **legacy = precio × 1,25** (20 % visible) en `index.html:6178/6315/6535`; tachado **nuevo = precio / (1 − 25 %)** (`ml_ofertas.py:978`, `index.html:3679`; tachado ×1,333). **Tres criterios** |
| **Precio esperado de una oferta** | `calcExp`: `base×qty×RULES (+8500 si ≥33000)` · Legacy: `pm (+8500)` sin cuotas · `ofmPrecioEsperadoPM`/`activar_en_campana_tradicional`: `pm×(1+cuotas%) + envío real si "free"` · `reportes_pricing.control_ofertas`: compara oferta vs. `precio_web × %ML` **sin cuotas ni envío** (no marca ofertas por encima con cuotas) |
| **Umbral de margen mínimo** | `OFM.umbral=10` solo en el front; backend sin piso, solo registra `bajo_umbral`. `01_COMERCIAL_FUNCIONAL` nombra "piso de margen", "precio mínimo absoluto" y "variación máxima" **sin ningún valor** |
| **Colores de margen** | Competidores: verde >25, amarillo >15 · Ofertas: verde >20 · Táctica por PM: verde ≥25, amarillo ≥15 |
| **Tolerancia de precio** | `tolGreen=0.5`/`tolYellow=2` (`index.html:1502`) · `||1.5` (3357/3377/3393) · `TACTICA_TOL=1.5` · backend `tolerancia_pct=1` y `_TOLERANCIA_PRECIO=0.01` · monitor competencia `0.05` (¿5 % o 0,05 %? la UI no muestra la unidad) |
| **Descuento mín/máx permitido por ML** | `PRICE_DISCOUNT` 5–<80 %; `SELLER_CAMPAIGN` 10–80 % (`ml_ofertas.py`); sin validación en el front. Piso propio del ERP: no hay |
| **Desvío margen real vs. proyectado** | `umbral_pts=5` solo en backend |

### 5.4 Otras contradicciones documentales
- `index.html:3113-3115` dice IIBB e Imp. Cheque sobre bruto; el código (3153-3154) pone IIBB sobre neto.
- REQ §1.2.b tabla de envío "<33.000 → 9.800" contradice su propia fórmula (0 si <33k); `ml_ofertas.py` lo trata como error de transcripción.
- `motor_precios.py` dice que `ayala_core.py` "sigue igual hasta migrarlo": **conviven dos motores** de precio con criterios distintos.
- RF §7.6 usa terminología de Táctica (CVA, 00007) dentro del motor ECOM; el propio código lo señala (`calculators.py:130-138`).
- `seed.py` mapea CVA/CVB como `NO_RECONOCIDO` y MLA como `NO_DETERMINADO` (pendiente P-01 del RF).

### 5.5 Qué conviene decidir para unificar (decisiones tuyas, no del código)
1. **Base única del %**: ¿neto, bruto, o neto de cargos? Hoy conviven las tres.
2. **¿Comisión ML 15,32 %, 15,5 % o por categoría/dominio?** y **¿IIBB 5 % o 6,5 %?**
3. **¿IVA de la comisión y del envío es crédito fiscal (se netea) o costo completo?**
4. **¿El impuesto al cheque entra siempre?** (Ayala Core no lo resta.)
5. **Cuotas: ¿multiplicador comercial (`RULES`) o costo real de ML (`1+cuota%`)?** y **¿existe el plan de 18 cuotas?**
6. **Envío: ¿plano 8500, tramos, o real por publicación?**
7. **Un solo costo (Táctica) y un solo TC** (con fallback explícito, no `1`).
8. **Un solo descuento/tachado para "Oferta Tradicional"** y un solo piso de margen con valor.
9. **Qué motor manda**: `rentabilidad/motor_precios.py` (config en DB, es el declarado como objetivo) vs. `ayala_core.py` / fórmulas JS, que deberían leer de él en lugar de copiar constantes.

---

## Apéndice — Lo que NO verifiqué
- Nada se ejecutó: ni la app, ni el backend, ni llamadas a ML/Sheets. No sé qué hay realmente en las hojas (tabs `V - *`, `Historial Competidores`, `Monitor_Lecturas`) ni su volumen.
- Contenido real de las planillas PM, valores reales de `pm.costo`/`pm.iva`, y cómo se guarda la tolerancia de monitoreo en las hojas.
- Si `ml_vendedor.py` + `.bat` en tu PC coinciden con lo que describen los comentarios (no están en el repo).
- Si scripts o cron externos usan los endpoints "sin llamador" del §2.
- Detalle de Histórico, Cobranzas y Brasil; `adapters.py`, `persistencia.py` (fuera de las líneas citadas), `api.py`, `importar_historico.py`, `ingesta_*`, `cierre_ecom_diario.py`; los tests; los xlsx.
- El análisis fue distribuido en tres sub-lecturas; los números de línea son del estado actual de la rama y pueden desfasarse en pocas líneas.
