# Etapa 3 — Pantalla "Análisis de Competencia" (PLAN, sin construir)

Estado: propuesta para revisión. Nada de esto está implementado. Leído: `MODULO_COMPETENCIA_SPEC.md`, `CRITERIOS_MARGEN.md`,
`AUDITORIA_ERP.md` §3 (rama vieja, commit 13aaaf1), `COMPETENCIA_BASE_DATOS.md`, y el código actual de las pantallas.

## 1. Datos que ya existen (Etapas 1-2) y lo que falta
| Dato | Dónde | Estado |
|---|---|---|
| Links por SKU + `Rol_Competidor` (Rey/Media/Barato) | `Referencias_Mercado` | OK (de B-SKU-COMPETENCIA) |
| Lecturas (precio, tachado, `Precio_Ganador`, `Vendedor_Ganador`) | `Historial_Precios` | OK, una fila por referencia y día |
| Eventos Bajó / Subió / Publicación_caída / Vendedor_sin_resultados | `Eventos_Competencia` | OK |
| Cantidad de publicaciones por tienda y día, completitud | `Tiendas_Conteo` | OK (Fase 1) |
| **Subcategoría → tienda Rey/Media/Barato (A-CATEGORIAS)** | solo en la planilla de Maca; el scraper lo lee en cada corrida pero **no lo guarda** en el Sheet del ERP | **FALTA** |
| Publicaciones de tienda que no son referencias | solo `Discovery_Sugerencias` (sin precio histórico) | Falta `Tiendas_Estado` (Fase 2 pendiente) |
| Competidor "débil" / recuperado / expandiendo | — | Falta (Fase 3 pendiente); la pantalla lo mostrará cuando exista |
| Categoría y PM de un SKU | `GRAL CATEGORIAS` y planillas PM (ya cargadas en el front: `S.catData`, `S.pmData`) | OK, se reutiliza |
| Costo | `/rentabilidad/costos/ecom` (fuente única) | OK |

## 2. Cómo leer los datos: endpoint (recomendado)
`GET /competencia/analisis?dias=30` (clave `X-ERP-Key`), con caché en memoria ~10 min y `refrescar=1`. El backend lee el Sheet con la cuenta de
servicio y devuelve JSON compacto: por referencia {sku, entidad, rol, link, cantidad, último precio, precio anterior, fecha del último cambio,
precio_ganador, serie de N días}, los eventos del período y el conteo de tiendas.
Por qué y no leer el Sheet desde el navegador como hoy:
- `Historial_Precios` crece todos los días (28 mil filas migradas + las de cada corrida): leerla entera por la API key en cada carga se vuelve lenta y pesada.
- Cuando migremos a Postgres, el front no cambia (solo cambia de dónde lee el endpoint).
- Una sola lectura servida a todos los usuarios, en vez de que cada navegador baje el histórico.
Costo/riesgo: más carga en Railway y cuota de lectura de Sheets (se mitiga con la caché); si el backend está caído, la pantalla no carga
(las demás sí). Categoría, PM y costos NO van en este endpoint: el front ya los tiene y los une por SKU (`normSku`), igual que hoy.

## 3. Pantalla
Una página `page-analisis-competencia`, dos pestañas sobre los mismos filtros.
- **Por SKU:** una fila por SKU con nuestro precio (PM) y las 3 columnas Rey / Media / Barato: último precio, Δ% vs lectura anterior (▲/▼), `Precio_Ganador`
  cuando es catálogo, y margen que nos quedaría si igualamos ese precio. Al abrir la fila: gráfico de línea por competidor (7/30/90 días), fecha del último cambio y
  los eventos de ese SKU.
- **Por categoría:** una fila por subcategoría: tienda Rey/Media/Barato (A-CATEGORIAS), cantidad de nuestros SKU, en cuántos estamos por encima del Rey,
  precio mediano del más barato, y por tienda su conteo de publicaciones (vs. mediana de 7 días, `Completa = Si`) — ahí aparece el "débil" cuando exista la Fase 3.
- **Filtros (iguales en ambas):** cuadritos de vendedor (uno / varios / todos), categoría, PM (el del SKU, desde `S.pmData`), buscador por SKU, y "solo con cambios".
  Modo **reciente** (último precio + Δ) y modo **histórico** (series).
- **Eventos:** franja con Subió / Bajó / caída / débil del período, clic para filtrar.
- La categoría la define Maca: no se clasifica nada, se usa lo que traen A-CATEGORIAS y `GRAL CATEGORIAS`.

## 4. Márgenes (CRITERIOS_MARGEN)
Margen % = rentabilidad / precio sin IVA; comisión 15,5% sobre precio con IVA; IIBB 5% sobre sin IVA; cheque 1,2% sobre con IVA (por separado); envío
$8.500 desde $33.000; costo de Ecom; TC BNA del día; sin plan de 18 cuotas; margen negativo se muestra, no se bloquea. Se usa `compMargenAt` (ya unificado en
`bb5fb14`) en una sola función compartida, para que dé lo mismo que Competidores/Ofertas. Verificación: un script que compara esa función contra
`rentabilidad/motor_precios.precio_a_margen` en ~20 casos (precios bajo/sobre el umbral, con y sin costo). **No verifiqué todavía que ambos coincidan**;
el spec pide que los números cierren antes de construir, así que esa prueba va primero en 3.1. Kits: costo × `Cantidad` de la referencia.

## 5. Qué reemplaza y qué queda
Se jubilan (recién cuando la pantalla nueva dé lo mismo y des el OK): **Competidores ML**, **Intel. Competitiva**, **SKUs & Referencias** y **Referencias** (solo lectura).
Quedan: **Ofertas ML** (no se toca), **Entidades** y **Mix** (altas; la pantalla nueva solo lee), **Distribuidores** (Etapa 4), **Motor de Precios** y su "Referencias de competencia".
Backend viejo (`/ml/vendedor/run`, tracker, `refresh`) y pestañas `Historial Competidores` / `V-*`: no se borran sin OK puntual. Ojo: los títulos y ventas de ~5.340 filas
existen solo en `V-*`; hay que copiarlos antes de borrarlas.

## 6. Sub-etapas (revisás cada una antes de la siguiente)
- **3.0 Base:** endpoint `/competencia/analisis` + prueba de paridad de márgenes + pestaña `Categoria_Competidores` (el scraper guarda subcategoría→tienda/rol).
  Sin pantalla; se valida mirando el JSON contra el Sheet.
- **3.1 Por SKU, modo reciente** con todos los filtros y márgenes. Convive con los módulos viejos.
- **3.2 Histórico:** series por competidor/SKU, fecha del último cambio, eventos por SKU.
- **3.3 Por categoría** (+ conteo de tiendas). Recomiendo hacer antes la Fase 2 (`Tiendas_Estado`); la Fase 3 (débil) puede llegar después y se enchufa.
- **3.4 Jubilación** de los 4 módulos viejos, con tu OK, tras una semana de uso en paralelo.
