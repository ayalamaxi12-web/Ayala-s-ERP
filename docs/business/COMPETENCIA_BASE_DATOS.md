# Base de datos de competencia (Etapa 1)

Parte de `MODULO_COMPETENCIA_SPEC.md`. Código: `backend/competencia_db.py`, migración en
`backend/scripts/migrar_competencia.py`, tests en `backend/test_competencia_db.py`.

## Esquema (mismo Spreadsheet, `SPREADSHEET_ID`)
- **`Referencias_Mercado`** (Tipo=`Competencia`): único registro de links. SKU resuelto una sola vez al migrar
  (SKU de la fila `V-*` → `General` por link → vacío; nunca por título). Se agrega al final la columna
  `Cantidad` (unidades por publicación). La **categoría no se toca**: la define Maca a mano en el Excel.
- **`Historial_Precios`**: único histórico, una fila por lectura:
  `Referencia_ID, SKU, Entidad, Fecha, Hora, Precio, Precio_Tachado, Descuento, Cuotas, Estado, Metodo, Fuente, Link`.
  En vivo es idempotente por `(Referencia_ID, Fecha)`.
- **`Migracion_Huerfanos`**: lecturas que no se pudieron atar a una referencia o fecha (nada se descarta).
- Un solo lector: `main.leer_precio_publicacion`. Catálogo (`/p/`) sin `wid` = estado `Sin lectura` (no se guarda
  fila; se resuelve en la Etapa 2).

## Migración
`python scripts/migrar_competencia.py` = dry-run (solo lectura + informe). `--ejecutar --plan-hash <hash>` escribe
solo si el hash coincide con el informe aprobado. No borra ni edita nada existente; es idempotente; al terminar
re-lee el Sheet y verifica que todo cierre exacto (origen = nuevas + fusionadas + ya existían + huérfanas).

## Endpoint de migración (Railway)
`POST /competencia/migracion/run` con header `X-ERP-Key` (falla cerrado: sin `ERP_API_KEY` en el servidor devuelve 503,
aunque el middleware esté en modo permisivo). Body `{}` = dry-run; `{"ejecutar": true, "plan_hash": "<hash aprobado>"}`
= migración real, solo si el hash calculado en ese momento coincide. Corre en un hilo; un solo job a la vez (409).
Seguimiento: `GET /competencia/migracion/status/{job_id}` (también con clave). Al terminar re-lee el Sheet y verifica
que las filas de `Historial_Precios`, `Referencias_Mercado`, `Entidades` y `Migracion_Huerfanos` sean las esperadas.
Las lecturas SIN precio no se migran (se cuentan aparte en el informe); antes de escribir se respalda
`Historial Competidores` en la pestaña `Respaldo_Hist_Competidores_<fecha>`.

## Doble escritura (transitoria)
Los monitores, `/competidores/refresh` y `/ml/tracker/run` siguen escribiendo a los históricos viejos (el front
todavía los lee) y además a `Historial_Precios`. Se cortan los viejos en la Etapa 3, cuando la pantalla lea el nuevo.

## Etapa 2: scraper automático (carpeta `scraper/`)
Lee la **planilla de Maca** (`PLANILLA_MACA_ID` en `scraper/config.py`; pestañas `A-CATEGORIAS` y `B-SKU-COMPETENCIA`, encabezados en la
fila 3) en lugar de la pestaña `Vendedores`. Sincroniza `Entidades` y `Referencias_Mercado` (columna nueva `Rol_Competidor`), scrapea
perfiles de tienda y publicaciones puntuales con Selenium (perfil de Chrome persistente) y escribe en `Historial_Precios` con las mismas
reglas de la Etapa 1. Eventos en `Eventos_Competencia`; tiendas con publicaciones que no son referencias, en `Discovery_Sugerencias`.
Instalación, modo prueba y tarea de las 17:30: `scraper/README_WINDOWS.md`.

Pendiente: alertas de **stock bajo** (< 5) — lógica lista pero desactivada hasta que la columna de stock de B-SKU tenga el dato real.

Cambios masivos reversibles (`backend/competencia_referencias.py`): `POST /competencia/referencias/desactivar-entidad` (dry-run por defecto;
la real exige `esperado` = cantidad del dry-run y registra cada valor anterior en `Cambios_Referencias`) y
`POST /competencia/referencias/revertir-lote`. Misma clave `X-ERP-Key` estricta que la migración.

### Etapa 2 — catálogo y precio ganador
`Historial_Precios` suma dos columnas al final: `Precio_Ganador` y `Vendedor_Ganador` (lo que ML muestra primero en un `/p/`). El precio del
competidor que sigue Maca (`Precio`) y el de la ganadora son datos separados; los eventos de cambio de precio miran solo `Precio`.
Un link de catálogo con `wid` se resuelve buscando la tarjeta de esa oferta en la página (o en "Más opciones de compra"), por API si está
configurada, o en el ítem directo (que solo existe para ofertas que no son de catálogo).

### Etapa 2 — Fase 1 del diseño B: `Tiendas_Conteo`
Una fila por (Fecha, Entidad_ID): `Leidas, Declaradas_ML, Paginas, Completa, Motivo, Nuevas, Desaparecidas, Mediana_7d, Var_vs_Mediana_Pct,
Estado_Debilidad, Fuente`. `Nuevas`/`Desaparecidas` se completan en la Fase 2 (`Tiendas_Estado`/`Tiendas_Cambios`) y `Estado_Debilidad` en la Fase 3.
Solo las lecturas `Completa = Si` forman la línea base. Esquema pensado para Postgres (`comp_tienda_conteo`, clave `(fecha, entidad_id)`).
Medidor: `scraper/celdas.py` (límite de Google Sheets: 10M celdas por archivo, cuentan también las vacías).

### Limpieza (Etapa 2) — endpoints protegidos, dry-run por defecto
- `POST /competencia/historial/borrar-lecturas-entidad` `{"entidad": "GLOBAL ELECTRONICS GROUP", "ejecutar": false, "esperado": N}`: borra de `Historial_Precios`
  las lecturas de esa entidad (somos nosotros, no es competencia). **Irreversible**; la real exige `esperado` = la cantidad del dry-run, registra el lote en
  `Cambios_Referencias`, borra por tandas de filas consecutivas y verifica. No correrlo mientras el scraper está escribiendo.
- `POST /competencia/pestanas/borrar-respaldo` `{"nombre": "Respaldo_Hist_Competidores_AAAAMMDD", "ejecutar": false, "confirmar": "<mismo nombre>"}`: borra
  **solo** pestañas con ese patrón de nombre (el respaldo de la migración de la Etapa 1).
- Pendiente de OK puntual, después de la Etapa 3: `Historial Competidores` y las `V-*` (las leen dos pantallas y guardan títulos/ventas que la base nueva no tiene).

### Etapa 2 — corrida desatendida
Si Chrome se cae, el scraper lo reabre y reintenta esa lectura; recicla Chrome cada 60 navegaciones; tope de 60 s por página y de 180 min por corrida;
`--reanudar` retoma el día sin repetir lo ya leído; código de salida 3 = corrida cortada (lo leído ya se escribió). La paginación de tiendas prueba, en orden:
botón "Siguiente" (con clic por JavaScript si algo lo tapa) → botón "Ver más" → URL por offset (`_Desde_n`) cuando ML declara más publicaciones de las leídas.

### Etapa 2 — captcha / verificación de ML
- Un captcha en una tienda o publicación NO corta la corrida: se saltea, se escribe lo leído (conteo `Completa = No`, motivo "ML pidió captcha en la página N")
  y se emite `Tienda_bloqueada`. Cortan: login pedido, 2 tiendas seguidas (`MAX_BLOQUEOS_SEGUIDOS_TIENDAS`) o 3 publicaciones seguidas bloqueadas, con pausa de 60 s tras cada captcha.
- El bloqueo se detecta al abrir la tienda **y en cada página siguiente** (antes solo al abrir: GEOTEK 48/122 era probablemente un captcha en la página 2).
- `--configurar-login`: Chrome común + perfil del scraper, espera `LISTO`; limpia Chrome huérfanos del perfil. `--esperar-captcha [MIN]`: corrida asistida.
- No se incluye resolución automática de captchas ni evasión. Alternativas a evaluar: leer los listados vía API de búsqueda de ML por `/ml-proxy`.

### Etapa 3.0 — base de la pantalla "Análisis de Competencia"
- **Costo fijo de ML (decisión de Maxx):** 1.330 / 2.740 / 3.320 (menos de $16k / $16–24k / $24–33k); desde $33.000 ML no cobra cargo fijo. Fuente única: el motor
  (`pricing_tramo.ml_costo_fijo`), expuesto en `GET /rentabilidad/pricing/ml-costo-fijo`. El front (`ML_COSTO_FIJO` en `docs/index.html`) lo trae del backend, con el
  seed como respaldo si no responde, y lo usan **Competidores** y **Ofertas ML**. Se sacaron los inputs `cfg-e1..e4` y los 1.255/2.500/3.030 (también los guardados en `localStorage`).
  Los márgenes que se ven hoy en esas pantallas cambian (los viejos estaban mal).
- **Paridad de márgenes:** `python backend/scripts/paridad_margenes.py` compara `compMargenAt` del front con `motor_precios.precio_a_margen` (30 casos) y el costo fijo
  de `ofmMargenAt` (10 precios). Resultado: **0 casos fuera de tolerancia**. Correrlo después de tocar cualquiera de las dos fórmulas.
  Ofertas ML mantiene su propia cuenta de envío por tramos y de cuotas (`OFM.envioTramos`, `OFM.cuotasPct`): NO está en la paridad, queda para revisar aparte.
- **`GET /competencia/analisis?dias=30&refrescar=false`** (`backend/competencia_analisis.py`): requiere `X-ERP-Key`. Una lectura del Sheet servida a todos (caché 10 min; `refrescar`
  relee, máx. 1 cada 30 s; si la relectura falla se sirve lo cacheado). Devuelve por referencia de competencia activa {sku, entidad, rol, cantidad, último precio, precio anterior,
  `delta_pct`, `desde` (desde cuándo rige el precio actual), `ganador`, última lectura (estado/días), `serie`}, `eventos` de la ventana, `tiendas` (conteo y completitud),
  `categorias` y `avisos`. No calcula márgenes ni categorías/PM: eso lo une el front por SKU.
- **`Categoria_Competidores`** (escribe el scraper, `scraper/categorias_competidores.py`): `Subcategoria, Rol, Entidad_ID, Entidad, Slug, SKUs_Nuestros, Actualizado`. Upsert por
  (Subcategoria, Rol, Slug); nunca borra: lo que Maca saque de A-CATEGORIAS queda con `Actualizado` viejo y el endpoint lo marca `desactualizada`. Requiere actualizar el scraper
  en la PC y correr una vez (`python scraper.py --solo perfiles --sin-descubrimiento` alcanza para sincronizar).

### Etapa 3.1 — pantalla "Análisis de Competencia" (por SKU, modo reciente)
Sidebar → **Análisis de Competencia** (`page-analisis-competencia`, en `docs/index.html`; funciones `ac*`). Convive con Competidores ML / Intel. Competitiva (no se jubila nada).
- Una fila por SKU: nuestro precio (PM, columna ML) con su margen, y columnas **Rey / Media / Barato** (según `Rol_Competidor`; refs sin rol van a "Otros"). Cada competidor: último precio,
  variación vs. la lectura anterior (▼/▲ y desde cuándo rige), `Precio_Ganador` si difiere, diferencia % vs. nuestro precio, y **margen si igualamos** (`compMargenAt`, costo de Ecom × cantidad × TC).
- Kits (`Cantidad` > 1): se compara contra nuestro precio × cantidad (+ envío desde $33.000, igual que Competidores) y el costo × cantidad.
- Filtros: vendedores (cuadritos, uno/varios/todos), categoría (`GRAL CATEGORIAS`), PM (planillas PM), buscador (SKU / vendedor / link), "solo con cambios", "solo donde nos ganan", orden y TC.
- Los márgenes usan los parámetros del panel de Competidores (la pantalla avisa si ahí hay algo desactivado). Sin costo o sin TC muestra "—", no inventa.
- Tests: `backend/test_front_analisis.py` (lógica pura extraída del HTML, corre en node). Verificado además en Chromium con datos de prueba (filtros, ▲▼, kits, caídas).

### Costo de Ecom guardado + tabla única de cuotas + resolver SKU → publicaciones (A y B0)
- **Costo cacheado (A):** el catálogo de costos de Ecom (~80 s) se baja UNA vez por día y queda guardado en la base (`costo_ecom_snapshot`, migración `h2c3d4e5f6a7`, últimas 7 fotos).
  Un request nunca baja de Ecom: lee la foto más reciente (memoria → base, se vuelve a mirar la base cada 5 min). Quién baja: el cron de las 06:00 (`scripts/ecom_diario.py`, primer paso, no fatal),
  el arranque del backend si no hay foto de las últimas 24 h, o el botón. Si una foto tiene más de 24 h se dispara un refresco en segundo plano mientras se sigue sirviendo la vieja. Si Ecom falla se conserva
  la foto anterior y el error queda en el estado. Única excepción: la primera vez de la historia (sin ninguna foto) se baja dentro del request.
  Endpoints: `GET /rentabilidad/costos/ecom` (ahora con `estado`), `GET /rentabilidad/costos/ecom/estado`, `POST /rentabilidad/costos/ecom/refrescar` (X-ERP-Key; en segundo plano, uno a la vez).
  Front: "💲 Costos Ecom: hace 3 h  ⟳ Refrescar costos" en Competidores, Análisis, Ofertas ML, Motor de Precios (Ayala Core) y Precios & Márgenes; amarillo si pasó de 36 h o hubo error.
  Todo lo que usa costo pasa por `costos_ecom.obtener_catalogo()`: motor, Ofertas, Ayala Core, `/costos/ecom` (Competidores y Análisis).
- **Cuotas de ML (B0):** una sola tabla, la del motor (`pricing_cuotas`): reducida 5 % · 3c 8,9 % · 6c 13,4 % · 9c 17,8 % · 12c 21,6 % (datos oficiales de ML confirmados por Maxx). `GET /rentabilidad/pricing/ml-cuotas`.
  **Se edita en un solo lugar:** `POST /rentabilidad/pricing/ml-cuotas` (X-ERP-Key) `{"planes": {"3": 9.1}, "cargado_por": "maxx", "confirmar": false}`: sin `confirmar` muestra qué cambiaría; con `confirmar: true` agrega filas
  con `vigente_desde` (hoy por defecto) y queda el historial. Competidores y Ofertas ML la leen de ahí (se sacaron los recargos ×1,15/1,20/1,25/1,35 y los % propios de Competidores, y `OFM.cuotasPct`).
  La paridad (`backend/scripts/paridad_margenes.py`) ahora también compara el margen por cuota de Competidores y de Ofertas contra el motor.
- **SKU → nuestras publicaciones (B0):** `GET /competencia/publicaciones-propias?sku=` (X-ERP-Key): busca en las cuentas IT y MT (`users/{seller}/items/search?seller_sku=`) y confirma el SKU exacto
  (`seller_custom_field` o atributo `SELLER_SKU`). Un error en una cuenta no corta la otra. **Sin verificar contra ML real** (probado con respuestas simuladas).

### Etapa B1 — simulador "Jugar mi precio" (Análisis de Competencia; no escribe nada)
En cada SKU, botón **🎯 Jugar** → panel con: campo "mi precio" (por unidad, con IVA; arranca en el de PM), pasos ±1 % / ±5 %, atajos **= Rey / = Media / = Barato**, **1 % bajo el más barato** y **↺ volver a PM**.
Muestra el margen en vivo por forma de pago (contado, reducida 5 %, 3c, 6c, 9c, 12c; cuotas de la tabla única del motor), el desglose del contado (venta sin IVA − comisión − costo fijo ML − envío − IIBB − cheque − costo),
la diferencia contra el PM (precio y puntos de margen) y la tabla de rivales (su precio, mi precio comparable y quién es más barato). Kits: se compara contra nuestro precio × cantidad (+ envío desde el umbral) y "igualar" calcula el precio por unidad.
No bloquea por margen bajo (CRITERIOS §8): solo colorea. Sin costo o sin TC no inventa margen. `backend/test_front_jugar.py` compara el margen de cada forma de pago contra `precio_a_margen` del motor.

### Ajustes de UX de Análisis de Competencia (solo presentación; los cálculos no cambian)
- **Panel "Jugar" lateral y pegado (sticky):** ya no se abre abajo de la fila; vive en un costado y acompaña el scroll de la tabla, así se juega el precio mirando a los rivales. La fila del SKU queda resaltada. En pantallas angostas (<1100 px) el panel pasa arriba de la tabla.
  Un solo panel a la vez; cambiar de SKU lo redibuja; mientras se tipea el precio solo se actualiza la salida (no pierde el foco).
- **Diseño del panel:** márgenes por forma de pago en tarjetas (3×2), desglose del contado plegable, rivales en una lista compacta (rol, vendedor, "yo $X", su precio, chip ▼/▲ con la diferencia) y chip de posición ("2 de 3 rivales más baratos" / "sos el más barato").
- **Buscador de SKU predictivo:** desplegable con hasta 10 sugerencias mientras se tipea (SKU, categoría, PM, cantidad de rivales); ↑/↓ + Enter, clic, Esc. Ignora mayúsculas, espacios y guiones ("pv12" encuentra "PV-120"), y el filtro de la tabla usa el mismo criterio para el SKU.

### Simulador "Jugar mi precio" — tanda 2 (precio por forma, cantidad, combos, Otros plegable, vendedores únicos)
Los márgenes siguen saliendo de `compMargenAt` (paridad con el motor); `backend/test_front_jugar.py` los compara contra `precio_a_margen` / `margen_a_precio`.
- **Precio por forma de venta:** una fila por forma (Contado, Reducida, 3c, 6c, 9c, 12c) con su casillero de precio, el margen y un solo desplegable **«fijar ▾»** con las 3 maneras: a mano (el casillero), **igualar a un rival** (o «1 % bajo el más barato») y
  **margen objetivo** (10/15/20/25/30 % u «otro %…»: calcula el precio MÁS BAJO que deja ese margen, tramo por tramo, usando `compMargenAt`; si no hay precio posible o falta costo, avisa). Una forma sin precio propio sigue al contado; «↺ volver» la suelta.
- **Cantidad:** selector **Unid.** (auto, ×1…×12). «auto» = como antes (cada rival a la cantidad de SU publicación). Con N fijo: mi precio y mi costo se multiplican por N (el margen es el del pack) y el precio del rival se escala a N unidades
  (supuesto: precio lineal por unidad); se compara a igual cantidad. Con «×1» una publicación ×2 de $52.000 se ve como $26.000 la unidad.
- **Combos:** botón **＋ SKU** (busca entre los SKU de la planilla PM): suma precio (PM por defecto, editable), costo y cantidad de cada SKU; el margen del combo usa el IVA ponderado (venta sin IVA = suma de las de cada SKU). Los rivales se ven por SKU suelto, así que
  para comparar un combo se carga a mano **«Combo del rival»** (chip ▼/▲ con la diferencia; «igualar» ajusta el precio de este SKU para igualarlo).
- **Otros plegable:** la columna «Otros» de la tabla (rivales sin rol) viene cerrada («▸ 15 sin rol · 4 vendedores») y se expande por fila; en el panel, «Otros vendedores (n)» también viene cerrado.
- **Rivales = vendedores únicos:** se cuenta por vendedor (nombre normalizado), no por publicación: «6 de 7 vendedores más baratos». De cada vendedor se muestra su publicación más barata (y «12 pub.») con el rol más alto que tenga.
