# Auditoría de agrupación de la información (todo el ERP)

Estado: **solo documento. No se implementó nada.** Espera el OK de Maxx antes de empezar cualquier módulo.
Base: `main` después de #46; con #47, #49, #50 y #51 todavía abiertos (se indica dónde ya hay un PR).
Cómo se hizo: lectura de `docs/index.html` (HTML de cada página y su función `render*`), conteo de tablas/paginadores/buscadores/filtros por página, y Chromium con datos sintéticos para Ofertas ML (599 ofertas), Análisis de Competencia, Campañas ML y Verificar ML. **Lo que depende de datos reales** (cuántas filas tiene hoy cada hoja) está marcado «a confirmar con datos reales».

## 1. El patrón que se propone replicar
Es el que ya se aplicó a Ofertas ML (#50) y al filtro de vendedores de Análisis (#47):
1. **Tabla compacta**: una fila por registro, título en una línea, 25 por página con «Anterior», «Siguiente» y «N–M de T».
2. **Búsqueda predictiva** (combobox accesible): lista de coincidencias al escribir (sin mayúsculas ni tildes, con la coincidencia resaltada); Enter filtra la tabla.
3. **Resumen como filtros**: los números de arriba son botones que filtran; no cambian al filtrar.
4. **Filtros como chips** con × y «Limpiar filtros».
5. **Parámetros en una sola franja, colapsable, con resumen visible** (ya en #49 para Ofertas ML y Competidores ML).
**Hoy el patrón está copiado a mano en el HTML** (cada pantalla tiene su propio `render*`, su propia paginación y su propio buscador). Antes de replicarlo conviene un PR chico de **componente compartido** (funciones puras `filtrar / paginar / buscarPredictivo` + el HTML de chips y paginador) para no tener 8 copias.

## 2. Módulo por módulo
Leyenda de la columna «Problema»: **T** = grilla/lista larga sin tabla compacta · **B** = lista fija de botones o chips · **P** = tabla sin paginar · **S** = sin búsqueda o filtros · **R** = resumen que no filtra · **K** = panel de parámetros desordenado o largo.

| Módulo | Qué hay hoy | Problema | Propuesta |
|---|---|---|---|
| **Ventas & Rentabilidad** | Filtros (fecha, canal, categoría, PM, SKU) y muchos gráficos; tablas de «top» con cortes fijos (top 5/10/15) | **R** (las tarjetas de KPI no filtran), **K** (filtros en dos filas) | Parámetros en una franja colapsable con resumen («Mayo–Oct · Todos los canales»); KPI como filtros donde tenga sentido. Gráficos, no tocar |
| **Histórico de Unidades** | Selector de SKU con chips ya existentes (`sku-tags`) y una tabla con **todos** los SKU/meses (los títulos se cortan a 50–60 caracteres; las filas no se cortan) | **P**, **S** (solo filtros de selector) | Tabla compacta con paginación y búsqueda predictiva de SKU (reutiliza los chips que ya tiene) |
| **Cobranzas** | Tabla única sin filtros ni paginación | **P**, **S** | Tabla compacta + búsqueda + paginación |
| **Brasil** | KPIs, tabla y «top 12» fijo | **P**, **R** | Tabla compacta; KPI como filtros |
| **Motor de Precios** (Ayala Core) | 13 campos de parámetros + lista de publicaciones del SKU con casillas «tildar» + comparación de un MLA; **escribe en ML** | **K** (13 inputs en filas), **P** (la lista de publicaciones no pagina), **T** | **Último de la fila** (es el que escribe): franja de parámetros colapsable con resumen; lista como tabla compacta con búsqueda. La confirmación de escritura ya existe y no se toca |
| **Precios & Márgenes** | 5 campos + 3 selectores, una tabla con paginación propia y búsqueda | **K** | Franja única colapsable con resumen |
| **Verificar Ecom** | 5–6 tarjetas de resumen, buscador, filtro de estado, paginado a 50 | **R** | **No tocar (indicación de Maxx).** Queda anotado por si más adelante se decide |
| **Verificar Táctica** | Igual que Verificar Ecom | **R** | **No tocar (indicación de Maxx)** |
| **Verificar ML** | Dos tarjetas de conexión largas, 5 KPI, tabla paginada a 50, buscador; escritura apagada en #51 | **R**, **K** (conexión de Sheets y de ML ocupa media pantalla) | A decidir junto con la estructura final de la sección ML (sección 3). Mientras tanto, solo conexión colapsable |
| **Reglas de Precio** | 21 reglas en cuadrícula de 4 columnas, cada una con su input | **K** | A decidir con Verificar ML (no se retira ni se cambia hasta el OK) |
| **Full ML** | Dos tarjetas con botón, tablas de resultados de conciliación y de reposición con orden pero **sin búsqueda ni paginación** | **P**, **S**, **K** (parámetros del simulador sueltos) | Tablas compactas con búsqueda y paginación; parámetros en franja |
| **Ofertas ML** | Tabla compacta y búsqueda predictiva en **#50**; parámetros colapsables en **#49** | — (resuelto en PR abiertos) | Esperan el merge |
| **Campañas ML** | Fila de 5 controles, 5 tarjetas de resumen, buscador, 4 casillas de filtro, tabla paginada a 50 | **R**, **K** (casillas sueltas) | Resumen como filtros, las 4 casillas pasan a chips, parámetros en franja |
| **Análisis de Competencia** | Buscador, categoría, PM, 3 casillas, orden, TC, tarjetas de resumen; vendedores en **#47** | **R** (resumen no filtra), **K** | Resumen como filtros; franja de filtros colapsable con resumen |
| **Competidores ML** | **botones fijos de vendedores** (uno por cada vendedor de las pestañas `V - …`, todos tildados por defecto: la cantidad real depende de los datos; en Análisis eran ~35; mismo problema que tenía Análisis), 15 campos de parámetros, tabla paginada a 50 con buscador | **B** (lista de vendedores), **K** (panel de 15 campos; colapsable en #49) | Buscador predictivo de vendedores + chips (igual que #47), reutilizando la misma función. **Va con la etapa A/B del plan de Competidores ML**, no antes |
| **ML Tools** | 3 tarjetas con botón y registro de ejecución | — | Sin cambios |
| **Entidades** | Buscador, filtro de tipo, tabla **sin paginar** (se dibujan todas) | **P** | Tabla compacta con paginación; búsqueda predictiva |
| **Referencias** | Tabla de **todas** las referencias (hasta 5.000 desde #43), **sin buscador, sin filtros y sin paginar**; cada fila busca su entidad con `find` (costo cuadrático) | **P** (la más grave: hasta 5.000 filas en el DOM), **S** | **Prioridad 1.** Tabla compacta con paginación de 25, búsqueda predictiva por SKU/entidad/link y chips de filtro. Es solo lectura: riesgo bajo |
| **Mix (carga masiva)** | Resultado de la carga en una tabla larga, sin filtros | **P**, **S** | Resultado con filtros por estado (creado, error, duplicado) y paginación. **Crea referencias**: se prueba con cuidado |
| **Distribución** | **11 tarjetas de resumen**, buscador, filtro de estado, dos tablas (distribuidores y monitor) **sin paginar** | **R** (11 tarjetas que no filtran), **P** | Resumen como filtros, tablas compactas, paginación |
| **Proyección 2027** | Tablero de solo lectura con su propio script | — | Se ordena en el PR 6 (estilo interno) |
| **Configuración** | 6 tarjetas (backend, tolerancias, categorías, 4 hojas PM, etc.) | **K** | Tarjetas colapsables con resumen del estado («4 hojas PM conectadas · backend OK») |

## 3. Cuántos son los grandes problemas (resumen)
- **Tablas sin paginar (P): 9** — Referencias (la peor), Entidades, Mix, Distribución (2), Cobranzas, Brasil, Histórico, Full ML (2) y la lista del Motor de Precios.
- **Listas fijas de botones (B): 1 pendiente** — vendedores de Competidores ML (la de Análisis ya está en #47).
- **Resúmenes que no filtran (R): 8 módulos** — Ventas, Brasil, Campañas, Análisis, Distribución, y las tarjetas de Verificar Ecom/Táctica/ML (estas tres no se tocan).
- **Paneles de parámetros largos (K): 9** — Ventas, Motor de Precios, Precios & Márgenes, Full ML, Campañas, Análisis, Competidores ML (en #49), Verificar ML (conexión) y Configuración.

## 4. Orden de PR propuesto (un PR por módulo o grupo; función y estética separadas)
0. **Componente compartido** (función pura, sin cambiar ninguna pantalla): `filtrar`, `paginar`, `buscarPredictivo`, HTML de chips y paginador; Ofertas ML y Análisis pasan a usarlo cuando se mergeen #47 y #50.
1. **Referencias + Entidades** (solo lectura, la mayor mejora por esfuerzo).
2. **Campañas ML** (resumen como filtros + chips).
3. **Distribución** (11 tarjetas → filtros; 2 tablas paginadas).
4. **Competidores ML** (vendedores predictivos + chips) — **después de la etapa A y con el OK de la B**.
5. **Full ML** (tablas con búsqueda y paginación).
6. **Ventas, Histórico, Cobranzas, Brasil** (grupo de dashboards; sin tocar los gráficos).
7. **Configuración, Precios & Márgenes** (parámetros colapsables).
8. **Mix** (con prueba cuidadosa por escribir referencias).
9. **Motor de Precios** (el último: escribe en ML; solo agrupación visual, sin tocar la confirmación ni el registro).
Cada PR con capturas antes/después a 1440, 1024 y 390 con datos cargados, 0 textos bajo 4,5:1, tests en verde y paridad de márgenes en 0.

## 5. Riesgos a tener en cuenta
- Estas pantallas **usan estilo viejo oscuro** (las de módulos propios): para no dejar un módulo a medias, cada PR de agrupación va **junto con el estilo interno** de ese módulo (PR 6), no antes.
- Verificar Ecom, Verificar Táctica y las pantallas que **escriben en ML o en Ecom** (Motor de Precios, Mix) no se tocan sin pedido expreso.
- Las cantidades reales de filas (Referencias, Entidades, Distribución) **no se pueden ver desde el repo**: antes de cada PR se prueba con un volumen sintético de al menos el tamaño real (a confirmar con datos reales).
- Los módulos que se **unan o jubilen** (propuesta de «módulos madre» en `MAPA_DE_MODULOS.md`) no deberían recibir este trabajo antes de decidir su destino.

**No empiezo ninguno de estos PR hasta tu OK.**
