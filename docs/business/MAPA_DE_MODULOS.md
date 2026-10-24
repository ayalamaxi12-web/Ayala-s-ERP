# Mapa de módulos del ERP (menú lateral)

Estado: **propuesta para decidir** (solo documentación; no cambia código). Base: `main` `a80b0c1` (20/10/2026 + #37 y #40 mergeados; con #42 pendiente).
Fuentes: `docs/index.html` (cada página y sus funciones), `backend/main.py` y routers, y los docs de `docs/business/`. **Lo que no se puede ver desde el repo** está marcado «a confirmar»: quién usa cada módulo en la práctica y los flujos de **n8n** (todavía no revisados: no se retira ningún endpoint hasta hacerlo).

Leyenda de la columna «Escribe»: ✎ ML = cambia precios u ofertas en Mercado Libre · ✎ Ecom = cambia precios en Ecom · ✎ Sheet/DB = escribe en un Sheet o en la base del backend · — = solo lectura.

## 1. Tabla de módulos

### Ventas
| Módulo (menú) | Qué hace | Quién lo usa | Endpoints | Sheets / pestañas | Escribe | Se superpone con | Propuesta |
|---|---|---|---|---|---|---|---|
| **Ventas & Rentabilidad** | Dashboard de ventas y rentabilidad: consulta en vivo (Táctica + Ecom), cierres guardados, gráficos y filtros | Dirección y PMs (a confirmar) | `/rentabilidad/historico/tactica`, `/rentabilidad/historico/ecom`, `/cierres*`, `/reporte*` (n8n) | `DASH_SHEET_ID` (pestañas mensuales) | ✎ DB (guarda cierres) | Histórico, Cobranzas, Brasil (mismas barras de filtros) | **Madre «Ventas»** con pestañas |
| **Histórico de Unidades** | Unidades vendidas por SKU / categoría / PM en el tiempo | PMs (a confirmar) | — (lee Sheets) | `HIST_ID` | — | Ventas & Rentabilidad | Se **une** a «Ventas» (pestaña) |
| **Cobranzas** | Cobranzas desde la planilla de ventas | Administración (a confirmar) | — | `DASH_SHEET_ID` | — | Ventas | Se **une** a «Ventas» |
| **Brasil** | Ventas de Brasil desde la planilla | Dirección (a confirmar) | — | `DASH_SHEET_ID` | — | Ventas | Se **une** a «Ventas» |

### Precios
| Módulo | Qué hace | Quién lo usa | Endpoints | Sheets | Escribe | Se superpone con | Propuesta |
|---|---|---|---|---|---|---|---|
| **Motor de Precios** (Ayala Core) | Motor propio de reverse-markup por SKU y forma de venta, con costo/IVA reales de Táctica y TC del BNA; puede **aplicar el precio a una publicación de ML** | Maxx / PMs (a confirmar) | `/ayala-core/*` (20 rutas, incl. `/ayala-core/item/{id}/aplicar-precio`) | — | **✎ ML** (`aplicar-precio`) | Precios & Márgenes, Verificar ML (calculan «el precio que debería ser») | Se **une** a Precios & Márgenes (madre «Precios»). ⚠ su encabezado dice «no escribe nada a ML todavía»: **está desactualizado** |
| **Precios & Márgenes** | Motor unificado: margen proyectado por canal (Web, ML, Frávega, OnCity) con costo/IVA de Táctica; sincroniza y carga las planillas PM a la base | PMs (a confirmar) | `/rentabilidad/pricing/*` (skus, sync-pm, carga-pm…) | planillas PM | ✎ DB (carga PM) | Motor de Precios | Madre «Precios» |
| **Verificar Ecom** | Compara los precios de las listas de Ecom (ML, Web, Frávega) con el **PM** (planilla del price manager, la fuente de verdad) y los corrige en Ecom. **También conecta las planillas PM** (las usan Táctica y ML) | PMs (pm1–pm4) (a confirmar) | `/ecom/login`, `/ecom/update-price` | `ECOM_PUB_ID` («Ecom publicaciones»), planillas PM | **✎ Ecom** | Verificar Táctica y Verificar ML (misma idea, otro canal) | **Se queda** como «Verificar precios» con pestañas por canal; mover «Planillas PM» a Configuración |
| **Verificar Táctica** | Compara costos y listas 1–5 de Táctica con el PM; exporta Excel de precios y de costos para corregir | PMs / Maxx (a confirmar) | — (lee Sheet) | `TACTICA_ID` («Articulos Tactica») | — (exporta Excel) | Verificar Ecom | Pestaña de «Verificar precios» |
| **Verificar ML** | Compara el precio **publicado en ML** (lo lee con el token de ML) con el **esperado**: precio ML del PM × cantidad del combo × la **regla** de la publicación (+ envío si pasa el umbral); y lo corrige en ML | PMs / Maxx (a confirmar) | `/ml/token`, `/ml-proxy` (`PUT items/{mla}`) | `ECOM_PUB_ID`, planillas PM | **✎ ML** (`mlPut`, «Corregir todos en ML») | Motor de Precios y Ofertas ML (tres formas de decidir el precio de ML) | Madre «Precios ML» junto con Reglas de Precio |
| **Reglas de Precio** | Edita la tabla de reglas de ML (nombre de regla → multiplicador: cuotas, kits, packs). **Solo la usa Verificar ML** (`getRulePct` / `calcExp`) | PMs (a confirmar) | — (se guarda en el navegador) | — | — (`localStorage`) | Motor de Precios (lo reemplazaría) | Pestaña de «Precios ML» |

### Mercado Libre
| Módulo | Qué hace | Quién lo usa | Endpoints | Sheets | Escribe | Se superpone con | Propuesta |
|---|---|---|---|---|---|---|---|
| **Full ML** | Conciliación de stock Full (ML vs Ecom) y simulación de reposición; sube el PDF de envío pendiente | Logística / Maxx (a confirmar) | `/ml-full/*` (conciliar, reposicion) | — | — (solo lectura) | Ninguno | **Se queda** (madre) |
| **Ofertas ML** (margen) | Gestiona ofertas y campañas propias y de ML en las dos cuentas (IT/MT) con **margen real** (costo de Táctica): simula, **activa y saca** ofertas, alertas y costos de envío; registra un historial | **Operadores: Natalia, Maxi A., Maxi I., Macarena** (selector del módulo) | `/ml-ofertas/*` (24 rutas) | pestaña `Historial Ofertas ML` | **✎ ML** (activar / sacar / aplicar) | Campañas ML (ambas sobre promociones de ML) | Madre «Ofertas y campañas ML» |
| **Campañas ML** | Sube el Excel de la Central de Promociones, calcula el margen con el aporte de ML y exporta el Excel con la hoja «ERP Análisis». **No escribe en ML** | Maxx / comercial (a confirmar) | `/campanas-ml/analizar`, `/simular`, `/exportar`; `/campanas/calendario` (n8n) | — (Excel) | — | Ofertas ML | Pestaña de «Ofertas y campañas ML» |
| **Análisis de Competencia** | Por SKU, histórico, «Jugar mi precio», por categoría y eventos, sobre `Historial_Precios` | Maxx / comercial (a confirmar); **Maca carga las referencias en su planilla** | `/competencia/*` (18 rutas) | `Referencias_Mercado`, `Historial_Precios`, `Eventos_Competencia`, `Tiendas_*`, `Categoria_Competidores`; stock y ventas (`CTX_*`) | — (solo lectura, hoy) | Competidores ML | **Madre de competencia** |
| **Competidores ML** | Lista todas las publicaciones de cada competidor (`V-*`: título, precio, ventas…) con mi precio, diferencia, precio sugerido y margen; botón «Refrescar historial» y **«✏ Ecom»** | Maxx / comercial (a confirmar) | `/competidores/refresh`, `/ecom/update-price`, `/tc/bna` | `COMP_SHEET_ID` (`V-*`) | **✎ Ecom** (lista «Mercado Libre») | Análisis de Competencia (usa su panel de márgenes) | Se **une** a Análisis de Competencia (plan de 4 etapas; no se jubila antes de la etapa C) |

### Inteligencia comercial, compras y distribución
| Módulo | Qué hace | Quién lo usa | Endpoints | Sheets | Escribe | Se superpone con | Propuesta |
|---|---|---|---|---|---|---|---|
| **Entidades** | Alta, edición y baja de entidades (Distribuidor, Competencia, Cuenta Propia, Mayorista) | Maxx / Maca (a confirmar) | `/intel-comercial/entidades` (POST/PUT) | `Entidades` | ✎ Sheet | Referencias, Mix | Madre «Entidades y referencias» (pestañas) |
| **Referencias** | Listado de todas las referencias (todos los tipos, PVP, tolerancia, activo) — 5000 filas (PR pendiente) | Maxx (a confirmar) | — | `Referencias_Mercado` | — | Análisis de Competencia (solo Competencia) | Pestaña de «Entidades y referencias» |
| **Mix** | Carga masiva «SKU,link» por línea: resuelve o crea la entidad por Seller_ID y **crea referencias** | Maxx / Maca (a confirmar) | `/intel-comercial/mix/cargar` | `Referencias_Mercado`, `Entidades` | ✎ Sheet | Planilla de Maca (otra vía de carga) | Pestaña de «Entidades y referencias» |
| **Proyección 2027** | Tablero de compras e inversión 2027 (snapshot versionado, tránsito desde Táctica) | Dirección / compras; **Marcelo** (Excel de tránsito, a validar con Comex) | `/proyeccion-2027/*` | base del backend | ✎ DB (sube snapshot) | Ninguno | **Se queda** |
| **Distribuidores** | Red de distribuidores autorizados: cumplimiento de PVP y monitor de publicaciones | Comercial (a confirmar) | `/distribucion/*` | `COMP_SHEET_ID` (`Distribuidores`, `Monitor_Lecturas`) | ✎ Sheet | Entidades / Referencias (tipo Distribuidor) | **Se queda** |

### Sistema
| Módulo | Qué hace | Quién lo usa | Endpoints | Sheets | Escribe | Se superpone con | Propuesta |
|---|---|---|---|---|---|---|---|
| **Configuración** | URL y clave del backend, tolerancias, umbral y costo de envío, categorías (`GRAL CATEGORIAS`) | Maxx | prueba de conexión al backend | `CATS_ID` | — (`localStorage`) | «Planillas PM» (hoy en Verificar Ecom) | **Se queda**; sumarle «Planillas PM» |
| **ML Tools** | Dispara dos jobs del backend que **alimentan los datos viejos de competencia**: *ML Tracker* (actualiza la pestaña «ML Competencia») y *ML Vendedor* (scrapea tiendas a `V-*`) | Maxx (a confirmar) | `/ml/tracker/run`, `/ml/vendedor/run`, `/jobs*` | «ML Competencia», `V-*` | ✎ Sheet | Scraper de la PC (reemplaza al vendedor para la competencia nueva); Competidores ML | **No es específico de ML**: es competencia. Pasa a Análisis de Competencia («Actualizar datos») cuando se una Competidores ML |

### Fuera del menú
| Módulo | Qué hace | Escribe | Propuesta |
|---|---|---|---|
| **Ofertas ML (vieja)** (`page-ofertas-ml`) | Verifica precios de oferta contra el PM, fija tachado = PM × 1,25, actualiza y borra ofertas en bloque. Sacada del menú el 27/08; el código sigue en el DOM | **✎ ML** (`PUT items`) | Jubilar (código muerto), pero **recién cuando Ofertas ML (margen) cubra el «tachado = PM × 1,25»**: confirmar con los operadores |

## 2. Para qué sirven Verificar ML y Verificar Ecom, y en qué se diferencian
El circuito de precios hoy es una cadena de tres eslabones, y cada «Verificar» controla uno:

1. **PM → Ecom (Verificar Ecom).** El PM (price manager) escribe el precio que quiere por SKU en su planilla. Verificar Ecom compara ese precio con lo que dice **Ecom** en cada lista (ML, Web, Frávega) y, si hay diferencia, la corrige **en Ecom**. Es el control de «Ecom está alineado con lo que decidió el PM». No habla con Mercado Libre.
2. **Ecom/PM → ML (Verificar ML).** Toma el **precio ML del PM**, lo multiplica por la cantidad del combo y por la **regla** de la publicación (cuotas, kit, pack: la tabla de Reglas de Precio), suma el envío si pasa el umbral, y lo compara con el **precio realmente publicado en ML** (lo lee con el token de las dos cuentas, incluida la oferta vigente). Si difiere, lo corrige **en ML**. Es el control de «ML muestra lo que debería».
3. **Táctica (Verificar Táctica).** Compara costos y listas de Táctica con el PM; no corrige solo: exporta Excel para cargarlo.

**Diferencias con los demás:**
- **Ofertas ML** no verifica el precio normal: gestiona **promociones** (activar, sacar, simular) con el margen real calculado con el costo de Táctica, no con el PM. Trabaja sobre el precio de oferta, no sobre el precio de lista.
- **Campañas ML** es el simulador previo: se sube el Excel de una campaña de ML y se ve el margen; no escribe en ML.
- **Reglas de Precio** no es un módulo operativo: es la **tabla de configuración** de Verificar ML (nadie más la lee).
- **ML Tools** no tiene que ver con precios propios: dispara los jobs que traen datos de **competidores**.
- **Motor de Precios** es el reemplazo a futuro: calcula el precio «correcto» desde el costo y el margen objetivo (no desde la planilla del PM ni de reglas fijas) y puede aplicarlo en ML.

**Hallazgo:** hay **tres formas de decidir el precio de ML** conviviendo (PM × regla en Verificar ML, costo y margen en el Motor de Precios y en Ofertas ML) y **tres módulos que pueden escribir precios u ofertas en ML** además de los de Ecom (Verificar ML, Motor de Precios y Ofertas ML; la «Ofertas ML vieja» sin menú es una cuarta vía).

## 3. Quién escribe en Mercado Libre hoy (para el plan de «Jugar mi precio»)
| Módulo | Cómo escribe |
|---|---|
| Verificar ML | `PUT items/{mla}` vía `/ml-proxy` (precio) |
| Ofertas ML (margen) | `/ml-ofertas/item/{id}/activar`, `/activar-campana`, `/sacar` |
| Motor de Precios | `/ayala-core/item/{id}/aplicar-precio` (precio y tachado) |
| Ofertas ML (vieja, sin menú) | `PUT items` vía `/ml-proxy` (precio y tachado) |
| Competidores ML / Verificar Ecom | **No** escriben en ML: escriben en **Ecom** (lista «Mercado Libre») |

Ninguno de estos se jubila hasta que «Jugar mi precio» (etapa C) esté listo, como pidió Maxx.

## 4. Propuesta: módulos madre finales
**Sección «Mercado Libre» (4 módulos madre):**
1. **Precios ML** = Verificar ML + Reglas de Precio (pestañas). A mediano plazo se decide si el Motor de Precios lo reemplaza.
2. **Ofertas y campañas ML** = Ofertas ML + Campañas ML (pestañas «Campañas (simulador)» y «Ofertas (gestionar)»).
3. **Full ML** (sin cambios).
4. **Análisis de Competencia** = Análisis + Competidores ML (etapas A–D) + los botones de ML Tools («Actualizar datos»).

**Resto del menú:**
- **Verificar precios** = Verificar Ecom + Verificar Táctica (pestaña por canal); «Planillas PM» pasa a Configuración.
- **Precios** = Precios & Márgenes + Motor de Precios.
- **Ventas** = Ventas & Rentabilidad + Histórico + Cobranzas + Brasil (pestañas).
- **Entidades y referencias** = Entidades + Referencias + Mix (pestañas).
- **Proyección 2027**, **Distribuidores** y **Configuración**: se quedan.

Resultado: de 22 ítems a **11 módulos**, sin perder ninguna función. Nada de esto se ejecuta sin OK de Maxx, módulo por módulo, y con los pasos de siempre (sin borrar datos ni pestañas; endpoints solo tras revisar n8n).

## 5. Preguntas abiertas (a confirmar)
1. ¿Quiénes usan en la práctica Ventas, Histórico, Cobranzas, Brasil, Distribuidores y Verificar *? El repo no lo dice.
2. ¿Se sigue usando «tachado = PM × 1,25» de la Ofertas ML vieja? Define si se puede borrar.
3. ¿El Motor de Precios va a reemplazar a Verificar ML + Reglas? Define si «Precios ML» es permanente o transitorio.
4. Flujos de n8n pendientes de revisar.
