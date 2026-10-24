# Estética del ERP de Global Electronics — guía para Code

Estado: propuesta aprobada por Maxx el 19/10/2026 (dirección "B: densa").
Referencias visuales: `mockup_competencia_denso.html` (módulo propio de Global) y `mockup_campanas_ml.html` (módulo de marketplace). Ábrelos en el navegador.

## 1. Objetivo
Que el ERP se vea **lindo, innovador, serio, amigable** y que **todo se lea claro**. Solo cambia la presentación: ninguna función, cálculo ni endpoint cambia por esta tarea.

Principios:
1. El celeste de Global manda. El color real del logo es **`#24A2B9`** (muestreado del logo oficial): contraste de 3,0:1 sobre blanco, así que sirve para logo, gráficos y texto grande, y para texto chico solo sobre la tinta oscura (5,1:1). Para texto y botones sobre fondo claro se usa su versión más oscura: **`--celeste-700` para texto de enlace y de acento** (da 4,5:1 también sobre `--fondo`) y **`--celeste-600` solo para botones** (texto blanco encima), bordes y foco. `--celeste-600` como texto sobre `--fondo` da 4,12:1 y no pasa.
2. Densidad útil: más datos por pantalla sin perder legibilidad (filas de 36 a 40 px, texto de 12 a 14 px).
3. El color de un marketplace aparece **solo dentro de sus módulos** y de forma contenida.
4. Sobrio: sin degradados, sin sombras pesadas, sin emojis como íconos.

## 2. Tokens (variables CSS en `:root`)

### Global
| Token | Valor | Uso |
|---|---|---|
| `--tinta` | `#0B2733` | Texto principal y menú lateral |
| `--tinta-2` | `#25414E` | Texto de apoyo fuerte, encabezados de tabla |
| `--texto-suave` | `#4B6472` | Texto secundario (6,2:1 sobre blanco) |
| `--celeste-50` | `#F0F9FB` | Fondo de pantalla claro |
| `--fondo` | `#EDF5F8` | Fondo del área de contenido |
| `--celeste-100` | `#D9EFF4` | Ítem activo, chips, texto del menú oscuro |
| `--celeste-200` | `#AEDDE7` | Bordes suaves, estados |
| `--celeste-300` | `#7CC7D6` | Texto de acento sobre el menú oscuro (8,1:1 sobre `--tinta`) |
| `--celeste-600` | `#1B8195` | **Solo botones** (texto blanco encima, 4,54:1), bordes y foco. No como color de texto: sobre `--fondo` da 4,12:1 |
| `--celeste-700` | `#146378` | **Texto de enlace y de acento** sobre blanco, `--fondo` y celeste claro (5,7:1 sobre `--celeste-100`) |
| `--celeste-marca` | `#24A2B9` | **Color real del logo de Global.** Barra superior de los módulos propios, logo, gráficos, puntito del ítem activo y texto grande. No para texto chico sobre blanco |
| `--borde` | `#C3DBE1` | Bordes de controles y tablas |
| `--divisor` | `#D8E8EC` | Líneas entre filas |
| `--zebra` | `#F6FBFD` | Filas alternas |
| `--superficie` | `#FFFFFF` | Tarjetas y tablas |

### Semánticos (significan algo: no se reutilizan como decoración)
| Token | Valor | Uso |
|---|---|---|
| `--aviso-fondo` / `--aviso-texto` / `--aviso-borde` | `#FFFBEB` / `#78350F` / `#FCD34D` | Avisos y alertas (8,7:1) |
| `--atencion` | `#B45309` | Números a mirar, margen negativo (5:1 sobre blanco) |
| `--error` | `#DC2626` | Errores reales |
| `--ok` | `#15803D` | Confirmaciones |

### Temas de marketplace (`data-modulo="…"` en el contenedor del módulo)
Cada tema define 3 variables que usan los componentes: `--mod-acento` (banda de cabecera e ítem activo del menú), `--mod-sobre-acento` (texto sobre el acento) y `--mod-primario` (botones primarios).

| `data-modulo` | `--mod-acento` | `--mod-sobre-acento` | `--mod-primario` | Contraste texto/acento | Estado |
|---|---|---|---|---|---|
| `global` (por defecto) | `--tinta` | `#FFFFFF` | `--celeste-600` | 15,5:1 | Definido |
| `ml` (los 6 módulos de la sección Mercado Libre; ML Tools está en Sistema y usa el tema global) | `#FFE600` | `#2D3277` | variante amarilla (ver abajo) | **9,03:1** (verificado con `muestrear_color.py`; el color dominante del logo provisorio sale `#FFE600`) | Definido e implementado (Fase 1: barra superior e ítem de menú) |
| `fravega` | **sacar del logo oficial** | calcular | calcular | — | **A definir**: el entorno de trabajo no pudo bajar el logo (la red bloquea `fravega.com`). Falta el archivo en `docs/assets/logos/fravega.*` |
| `oncity` | **sacar del logo oficial** | calcular | calcular | — | **A definir**: ídem (`oncity.com` bloqueado) |
| `megatone` | **sacar del logo oficial** | calcular | calcular | — | **A definir**: ídem (`megatone.net` bloqueado) |

Cómo se completan: `python docs/assets/logos/muestrear_color.py docs/assets/logos/fravega.png` imprime el color dominante, el contraste con blanco y con la tinta y qué texto pasa 4,5:1; esa salida se pega en esta tabla y en un bloque `[data-modulo="…"]` del `:root` de `docs/index.html`.

Variables de tema agregadas por la implementación (los mockups las necesitan; sin ellas habría hex sueltos): `--mod-barra`, `--mod-sobre-barra`, `--mod-barra-borde` (barra superior), `--mod-encabezado`, `--mod-encabezado-texto`, `--mod-encabezado-borde` (encabezado de tabla), `--mod-segmento-activo` (selector segmentado). Tokens agregados: `--tinta-activo`, `--encabezado-tabla`, `--segmentado`, `--pista`, `--ok-fondo`, `--ok-texto`, `--error-fondo`, `--error-texto`, `--fuente`, `--mk-ml*`.

**Hallazgo de contraste:** `--celeste-600` (`#1B8195`) da 4,54:1 sobre blanco pero **4,12:1 sobre `--fondo`** (`#EDF5F8`): como texto sobre el fondo de la pantalla no pasa. En la implementación el texto de enlace/acento sobre fondo usa `--celeste-700` y `--celeste-600` queda para botones (texto blanco encima) y bordes.

**Variante amarilla de `ml` (decidida por Maxx, vale en los 6 módulos de la sección ML).** El amarillo vivo `#FFE600` va **solo de fondo**: botones primarios (texto `#2D3277`, borde `#C9B300`), pestañas/botones activos y el ítem activo del menú. El texto y los acentos de texto usan el dorado `#7A5F00` (enlaces, precios); botones secundarios con borde `#7A5F00` y texto `#5C4A00`. Chips `#FFF1A8` con texto `#5C4A00`; franjas de filtros y parámetros `#FFF9DB` con borde `#EBDD8A`; encabezado de tabla `#FFF6B8`; checkbox `#8F7A00`; foco: anillo de 2 px `#2D3277`. Nunca amarillo vivo como color de texto sobre fondo claro (1,2:1). Los avisos ámbar y los colores de significado (rojo, verde) no cambian; el aviso se distingue de una franja por el ícono, el borde grueso a la izquierda y el texto marrón. Los valores viven como tokens `--mk-ml-*` y `--mod-*` en el bloque `[data-modulo="ml"]`; los componentes no llevan hex sueltos.

Regla para los marketplaces sin color definido: muestrear el color dominante del logo oficial (script en `docs/assets/logos/`), guardar el hex resultante en esta tabla y **verificar contraste**: el texto sobre el acento debe dar 4,5:1 como mínimo. Si el color de marca es muy claro o muy fuerte, usar tinta o blanco para el texto y limitar el color a la banda de cabecera, el ítem activo y el botón primario. Nunca usar el color de marca como color de texto.

## 3. Tipografía
- Familia única: **Figtree** (Google Fonts), pesos 400, 500, 600, 700 y 800.
- Títulos de módulo: 22 px, peso 600. Texto de apoyo: 12 px. Indicadores grandes: 22 px, peso 500.
- **Tamaños como tokens** (decisión de Maxx, 20/10/2026): `--fs-cuerpo` 14 px, `--fs-campo` 14 px y **`--fs-tabla` 13 px** en escritorio (manda esta guía). **En pantallas de hasta 768 px el cuerpo y los campos pasan a 16 px** (`--fs-cuerpo` y `--fs-campo`; evita el zoom de iOS al enfocar un campo). Las tablas siguen en `--fs-tabla` y scrollean dentro de su caja. Nadie escribe un `font-size` suelto en un componente nuevo.
- Números: `font-variant-numeric: tabular-nums` para que las columnas queden alineadas.
- El wordmark "GLOBAL": peso 800, espaciado de letras 0,08em. Sale del logo oficial cuando esté el archivo.

## 4. Layout
- **Shell:** menú lateral de 208 px con fondo `--tinta` y contenido a la derecha. En pantallas angostas el menú se apila arriba (flex-wrap).
- **Rejilla de 4 px**, radios de 6 a 8 px, bordes de 1 px, sin sombras (o una muy sutil en menús flotantes).
- **Menú lateral:** ítems de 14 px con ícono SVG de 18 px. El ítem activo lleva fondo `--mod-acento` si el módulo es de marketplace, o `#14414F` con un puntito `--celeste-marca` si es propio. Los módulos de marketplace llevan un puntito del color del marketplace.
- **Barra superior de módulo (patrón clave).** Franja de 56 px a todo el ancho, **encima** del menú lateral y del contenido:
  - Módulo **propio de Global:** fondo `--celeste-marca` (`#24A2B9`), logo blanco de Global a la izquierda, "ERP" y un buscador en forma de píldora. Es la misma idea que la barra de la tienda web (ver `referencia/tienda_web_global.png`). Texto chico en tinta, nunca en blanco (el blanco sobre `#24A2B9` da 3,0:1: solo para el logo).
  - Módulo de **marketplace:** fondo del color del marketplace y **"GLOBAL × [logo del marketplace]"**, cada uno con su logo oficial (alto de 28 a 42 px, separador "×"). Ejemplo: Mercado Libre, amarillo `#FFE600` con el logo de Global en tinta y el de ML.
  - El resto de la pantalla mantiene el estilo Global. El color del marketplace aparece solo en la barra, el ítem activo del menú, los botones primarios, el selector de cuenta y el encabezado de la tabla (versión suave).
- **Menú lateral:** ya no lleva logo (está en la barra superior). Va en `--tinta`.
- **Separadores y botón del menú** (decisión de Maxx, 20/10/2026): entre los grupos del menú hay un separador de 1 px (los títulos de sección se mantienen). Un botón en la barra superior (`#menu-toggle`, `<button>` con `aria-controls="sidebar"` y `aria-expanded`) **oculta y muestra** la barra lateral en escritorio y **recuerda la elección** (`localStorage` `erp_sidebar_oculta`; si el navegador lo bloquea, funciona igual pero sin recordar). En pantalla angosta (< 900 px) es **el mismo botón** el que abre y cierra el menú superpuesto; Esc lo cierra y devuelve el foco al botón. Oculto o cerrado, los ítems quedan fuera del orden de tabulación.
- **Detalles amigables tomados de la tienda web:** buscador y chips en forma de píldora, esquinas redondeadas y tarjetas blancas sobre fondo gris claro. En el ERP se usan con moderación para que siga siendo denso.

## 5. Componentes
- **Botón primario:** fondo `--mod-primario`, texto blanco, 44 px de alto, radio 8. **Secundario:** borde `--mod-primario`, fondo blanco.
- **Selector segmentado** (Por SKU / Por categoría, cuentas IT / MT): contenedor `#D3EAF0`, opción activa en tinta (módulo propio) o `--mod-primario` (marketplace).
- **Select e inputs:** 44 px de alto, borde `--borde`, etiqueta visible.
- **Indicadores (KPI):** franja única con celdas separadas por líneas; valor de 22 px. Un valor que pide atención usa `--atencion`.
- **Aviso:** fondo `--aviso-fondo`, borde `--aviso-borde`, ícono de triángulo, texto `--aviso-texto`.
- **Tabla densa:** encabezado `#DFF0F4` (módulo propio) o amarillo suave del marketplace; filas de 36 a 40 px; zebra; scroll horizontal dentro de su caja en pantallas angostas.
- **Barra de cobertura:** 60×6 px, pista `#CBE8EF`, relleno `--celeste-600`.
- **Chips:** pastilla `--celeste-100` con texto `--celeste-700`.
- **Íconos:** SVG en línea, trazo de 1,8, 18 px (estilo Lucide). **Cero emojis como íconos**: hoy el menú y varios botones usan emojis (por ejemplo el 📈 del histórico y el 📅 de Proyección) y hay que reemplazarlos.

## 6. Accesibilidad (criterio de aceptación)
- Contraste de texto de 4,5:1 como mínimo (3:1 para texto de 24 px o más).
- Foco visible en todo lo interactivo (anillo de 2 px `--celeste-600`) y navegación por teclado.
- Botones y enlaces reales (`<button>`, `<a href>`), nunca `div` con clic.
- No depender solo del color para marcar un estado: agregar texto o ícono.
- Respetar `prefers-reduced-motion`. Sin animaciones decorativas.

## 7. Cómo implementarlo en este ERP
- Mantener la arquitectura actual (HTML en GitHub Pages, sin paso de compilación). Si hace falta mover el CSS a un archivo aparte, **proponerlo antes**.
- Los tokens viven en un único bloque `:root`. Los temas de marketplace son `[data-modulo="ml"] { --mod-acento: …; … }`.
- Los componentes usan las variables `--mod-*`, nunca un hex suelto. Un componente nuevo con un hex suelto no se acepta.
- No tocar lógica, cálculos ni endpoints. Si una etiqueta de texto cambia, listarlo en el PR.

## 8. Logos
Están en `docs/assets/logos/`:
- `global-blanco.png`: para fondos oscuros y para la barra superior celeste de los módulos propios.
- `global-tinta.png`: para fondos claros o de color (por ejemplo, la barra amarilla de Mercado Libre).
- `global-celeste.png`: celeste de marca `#24A2B9`, para fondos blancos.
- `mercadolibre-isotipo.png`: isotipo oficial de Mercado Libre (el apretón de manos) con fondo transparente, que pasó Maxx. Es solo el emblema, sin la palabra. En la barra amarilla va **junto al texto "Mercado Libre"** en `#2D3277`, peso 700, con el emblema de 36 px de alto (la guía admite de 32 a 40 px). Sin TODO ni logo provisorio.
Los logos de Global salieron de un PNG de 225 px: alcanzan para el menú y la barra superior, pero cuando exista el SVG oficial hay que reemplazarlos.
Faltan los logos de Frávega, OnCity y Megatone. No hacen falta todavía, porque esos módulos no existen. Cuando existan, se muestrea el color del logo oficial (ver la sección 2) y se agrega acá.
**Ignorar el adorno de Halloween del logo** (la araña), si aparece: es de temporada, no forma parte de la marca.

## 9. Plan por fases (cada una en su rama, sin mergear, con capturas antes y después)
- **Fase 0 — Tokens y temas:** bloque `:root`, temas de marketplace, fuente Figtree. Sin cambios visibles todavía. Mostrar la tabla de tokens aplicados.
- **Fase 1 — Shell y un módulo:** menú lateral, cabecera de módulo y **Análisis de Competencia** completo con el estilo nuevo. Capturas en 1440, 1024 y 390 px.
- **Fase 2 — Módulos de marketplace:** Campañas ML y Ofertas ML con la cabecera "GLOBAL × Mercado Libre" y el tema `ml`. Después, un marketplace por PR a medida que haya logo y color.
- **Fase 3 — Resto de módulos propios:** Proyección 2027, Rentabilidad, Full y los demás, uno por PR.
- **Fase 4 — Pulido:** revisar consistencia, emojis restantes y accesibilidad.

Cada fase termina con: capturas antes y después, resultado de los tests del backend, paridad de márgenes en 0 casos fuera de tolerancia y la lista de archivos tocados. La fase siguiente empieza solo con el OK de Maxx.

## 10. Lo que NO hay que hacer
- No usar `--celeste-marca` como color de texto chico sobre fondo claro (3,0:1): para eso está `--celeste-600`.
- No mezclar la estética con cambios de funciones en el mismo PR.
- No inventar colores de marketplace: salen del logo oficial.
- No agregar librerías ni pasos de compilación sin proponerlo antes.
- No borrar nada de los módulos viejos desde esta tarea: eso es la jubilación y tiene su propio proceso.


## 11. Registro de implementación
- **Fase 0 (hecha):** bloque `:root` con tokens y temas, fuente Figtree cargada. Sin cambios visibles (verificado comparando capturas pixel a pixel).
- **Fase 1 (hecha, pendiente de OK):** barra superior de módulo (propio: celeste `#24A2B9` con logo blanco; marketplace ML: `#FFE600` con «GLOBAL × Mercado Libre»), menú lateral de 208 px con íconos SVG, y Análisis de Competencia completo (Por SKU, Histórico, Jugar y Por categoría). Los demás módulos conservan su estilo oscuro hasta su fase.
- **Pendientes visibles:** colores de Frávega, OnCity y Megatone (arriba; sus módulos todavía no existen); buscador de la barra superior (no se agregó: no existe un buscador global y sería una función nueva).
- **Sin animaciones decorativas:** se sacó la animación del punto del logo (`.logo-dot` / `@keyframes pulse`). Solo quedan las funcionales (el spinner de carga), y todas se apagan con `prefers-reduced-motion`.

## 12. Ideas para después (no están en ninguna fase)
- **Buscador global de SKU y publicación** en la barra superior (la guía y los mockups lo dibujan, pero hoy no existe un buscador global: sería una función nueva, no estética; por eso la barra no lo tiene).
- **Barra lateral (PR «Estética, barra lateral»):** separadores de 1 px entre grupos y botón único para ocultar / mostrar el menú (ver §4).
