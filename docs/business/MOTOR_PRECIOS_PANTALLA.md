# Motor de Precios: SKU y pantalla (Bloque 2, PR 2)

Solo presentación y selección de SKU; no cambia ninguna fórmula ni el cálculo por lote del PR 1.

- **Selector de SKU** con **todos** los SKU de la pestaña «ERP AYALA» (más los piloto): `GET /ayala-core/precios-excel` ahora devuelve también `skus` (todos los SKU de la pestaña, tengan o no precios cargados). Búsqueda predictiva: coincide en cualquier parte del código, sin importar mayúsculas ni tildes, con lo escrito resaltado; teclado (flechas, Enter, Escape, Retroceso quita el último); varios SKU como chips con ×; «Todos los piloto» y «Ninguno».
- **Un solo flujo**: se terminaron los cuatro «(Excel)» como caso aparte. Los SKU elegidos alimentan la calculadora y «Publicaciones»: todos van por el motor (costo de Ecom, IVA de la foto de Táctica o de Ecom). Las funciones del camino «sin Táctica» (`ayalaCoreDescubrirSinTacticaJob`, `ayalaCoreEnriquecerSinTactica`) y los endpoints `/ayala-core/base-mla/*` y `/ayala-core/mla/precio-vivo` **quedan en el código** (los usa también el Apps Script del Excel), pero la pantalla ya no los llama.
- **Calculadora en una tarjeta**: seis rentabilidades en una fila (3 y 2 columnas en pantallas angostas); Envío real, TC, Costo USD y Envío a Bodega en «Opciones avanzadas», colapsada. Textos largos → una línea de ayuda y «Cómo funciona» colapsable.
- **Bloques minimizables** («Referencias de competencia», «Publicaciones de los SKU elegidos», «Comparar un solo MLA», «Ver SKU cargado»): botón real con `aria-expanded` y `aria-controls`, resumen visible al minimizar, «Expandir todo» y «Minimizar todo»; se recuerda la elección durante la sesión (`sessionStorage`).
- Casillas y placeholders sin truncar (la columna «Manual» y los campos de las tablas tienen ancho mínimo de 15 caracteres); la condición corregida a mano lleva la etiqueta de texto **A mano** además del borde amarillo.
- Emojis de la página reemplazados por íconos de trazo. Los que quedan dentro de textos generados por JS (⚠, ✅, ❌ en tablas y mensajes) siguen para la auditoría final.
- «Comparar un solo MLA» usa el SKU elegido (tiene que haber uno solo).

## Pack (Bloque 2, PR 3)
- **Selector «Cantidad por publicación»**: x1 (por defecto), x2 a x6 y «Otro…» con un número entero de 1 a 999.
- **Cuenta**: el costo del SKU se multiplica por la cantidad (`costo_sin_iva = costo_usd × TC × cantidad`) y **todo lo demás es la fórmula de siempre** (`calcular_precio_condicion`, sin cambios). Con x1 el pedido ni siquiera lleva `cantidad` y el resultado es idéntico al de antes (test de paridad). La comisión de ML del motor es un porcentaje fijo (15,32 %), así que no depende de un tramo de precio: lo que sí cambia con el pack, como hoy, es todo lo que depende del precio calculado (comisión, IIBB, financiero, cheque).
- **Envío**: se carga a mano y es **por publicación** (el campo dice «Envío real $ (por publicación)»). No se multiplica por la cantidad.
- **Se muestra**: «Precio de la publicación» y «Precio por unidad» (publicación ÷ cantidad, con 2 decimales) en las tablas, y «Pack xN: costo de la publicación …» en el resumen. Los endpoints `/ayala-core/motor-lote` y `/ayala-core/sku/{sku}/motor` aceptan `cantidad` (422 si no es un entero entre 1 y 999) y devuelven `cantidad` y `precios_unitarios`.
- **No cambia**: el escaneo de «Publicaciones» sigue calculando por SKU (la cantidad de cada publicación real la resuelve Ecom en Full ML, no acá). La cantidad del selector sí se aplica a «Comparar un solo MLA».
