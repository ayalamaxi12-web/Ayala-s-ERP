# Módulo CAMPAÑAS / OFERTAS de ML (Excel de la Central de Promociones) — PLAN, sin construir

## Flujo pedido
ML entrega un Excel por campaña (hoja **Promociones**: TITLE, ITEM_ID, SKU, ORIGINAL_PRICE, SELLER_AMOUNT, SELLER_PERCENTAGE [única columna editable], MELI_AMOUNT, MELI_PERCENTAGE,
DISCOUNT_PERCENTAGE, FINAL_PRICE, NEW_RECEIVES, LOYALTY_*, STATUS, ACTION). Se sube al ERP; el backend agrega **una hoja nueva** al MISMO archivo (la hoja Promociones no se toca);
en la hoja nueva, por publicación: precio PM + costo, margen real al precio de oferta (con el aporte de ML), margen por cuota, jugar el descuento y el valor a copiar a la columna de ML.

## Lo que verifiqué en el código (y se reutiliza)
- **Motor de márgenes:** `rentabilidad/motor_precios.precio_a_margen` (y `margen_a_precio`) con `plan` = contado / reducida / 3 / 6 / 9 / 12; cuotas y costo fijo ML ya salen de las tablas únicas (`pricing_cuotas`, `ml_costo_fijo`). Es el que tiene paridad 60/60 con el front. No se reescribe ninguna fórmula.
- **Precio PM por SKU:** ya está en Postgres (`pricing_sku`, sincronizado desde los Sheets de los 4 PM: Verónica, Laura, Cristian, Matías). El precio ML del PM = `precio_ml(web, %ML)` (decena, terminado en 9); `reportes_pricing.control_ofertas` ya hace el cruce SKU → precio PM (`vigentes`, `_precio_pm`, `_pm_de`) y calcula `descuento_que_cuadra_pct` (el % que deja la oferta en el precio PM = criterio de Oferta Tradicional, CRITERIOS §8).
- **Costo:** catálogo de Ecom guardado en la base (`costos_ecom`, foto diaria), IVA con respaldo de Táctica; TC del BNA. `ratio de uso` de `pricing_pm._datos_sku_fn` (DatosSku: costo USD, IVA, PM, categoría).
- **Excel:** `openpyxl 3.1.5` ya está en `requirements.txt`; LibreOffice disponible para pruebas de ida y vuelta.

## Diferencias con lo planteado (a confirmar)
1. **El costo NO sale del Sheet del PM:** el ERP lee del PM solo PRECIOS (web, % ML, Frávega, OnCity); el costo sale del catálogo de Ecom (CRITERIOS §7, fuente única). Es "el mismo lugar que alimenta el ERP". Si la planilla del PM tiene una columna de costo, no se usa (a lo sumo, cruce informativo).
2. **PM y cuenta:** el PM de un SKU sale de quién cargó su precio en `pricing_sku` ("Sheet Verónica") y de GRAL CATEGORIAS; **no depende de la cuenta ML**. La cuenta (IT / MT) se deduce del ITEM_ID: o se elige al subir el archivo, o el backend consulta los ítems con el token de cada cuenta (las publicaciones propias sí se pueden leer) y verifica a quién pertenecen. La cuenta importa para validar y para el envío real, no para el margen.
3. **Aporte de ML (MELI_PERCENTAGE / MELI_AMOUNT):** hoy el ERP no lo modela en ningún cálculo. **Hace falta la regla de Maxx** (ver preguntas).

## Cómo se lee y se agrega la hoja sin romper el formato de ML
- **Escritura "solo agregar" a nivel del ZIP del .xlsx (no openpyxl para guardar):** openpyxl al guardar reescribe el libro entero y puede perder cosas de la plantilla de ML (validaciones, formatos condicionales extendidos, estilos de celdas celestes, hojas ocultas, protección). En cambio se copia el ZIP byte a byte y solo se (a) agrega el XML de la hoja nueva (celdas con texto en línea y números, estilos nuevos al final de `styles.xml`), (b) se registra en `workbook.xml`, `workbook.xml.rels` y `[Content_Types].xml`. La hoja Promociones y todas las demás partes quedan **idénticas byte a byte** (se verifica por hash en cada archivo generado y en los tests).
- **Lectura:** con openpyxl en solo lectura; las columnas se ubican por NOMBRE de encabezado (no por posición), igual que la planilla de Maca; si falta una esperada, falla fuerte.
- **Riesgo #1 a probar antes de construir más:** que ML acepte al subir un archivo con una hoja extra (no puedo verificarlo desde acá). Plan B si la rechaza: entregar los cálculos en un Excel acompañante y copiar el valor a mano.

## Cálculo (todo con el motor)
Por publicación: precio PM (ML) y costo → margen al precio de oferta (contado) y por cuota (contado/3/6/9/12) con `precio_a_margen`; sin PM / sin costo / sin IVA → fila marcada, no se inventa. Envío: estimación de CRITERIOS §6 ($8.500 desde $33.000) salvo que se pida el real por publicación (etapa posterior). Descuento "que cuadra" = el que deja el precio en el PM (reuso de `control_ofertas`) y "descuento máximo que deja ≥ X % de margen" por cuota (`margen_a_precio`).

## Jugar el descuento: dos formas (hay que elegir)
- **A (recomendada): en la pantalla del ERP** (misma lógica que "Jugar mi precio"): subís el Excel, ves la tabla, movés el % o el precio por fila / por lote, y al final **descargás el MISMO Excel** con la hoja nueva ya con los valores elegidos y la columna "VALOR A COPIAR". No se duplica ninguna fórmula.
- **B: fórmulas vivas dentro de la hoja nueva** (cambiás el % en Excel y se recalcula). Obliga a reescribir en fórmulas de Excel comisión, IVA, IIBB, cheque, costo fijo por tramo, envío y cuotas: duplica el motor y puede desfasarse. Si la querés igual, se prueba contra el motor recalculando con LibreOffice.

## Valor a copiar
Hay que fijar con un archivo real qué significa SELLER_PERCENTAGE (¿% del ORIGINAL_PRICE que absorbe el vendedor?) y cómo recalcula ML FINAL_PRICE / SELLER_AMOUNT al subir, los decimales que admite y los mínimos/máximos por campaña. El valor a copiar se calcula con el % redondeado como lo acepta ML y el margen se muestra sobre el precio que realmente queda.

## Sub-etapas (cada una para revisar)
- **C0 — Archivo:** leer la hoja Promociones por encabezado, agregar una hoja de prueba "ERP" con unas columnas fijas, verificar bit a bit que el resto del archivo no cambia, abrirlo en LibreOffice, y vos lo probás subiéndolo a ML. Necesita un Excel real de una campaña (aunque sea con pocos ítems).
- **C1 — Cruce y margen:** SKU → PM / precio / costo / IVA / cuenta; margen al precio de oferta y por cuota con el motor (incluye la regla de aporte de ML); lista de faltantes; hoja nueva con esos valores. Tests de paridad contra el motor.
- **C2 — Pantalla:** subir el Excel, tabla con filtros, jugar el descuento por fila / lote (atajos: "dejar en precio PM", "máximo descuento con margen ≥ X %", por cuota).
- **C3 — Exportar:** el mismo Excel con la hoja nueva con lo elegido y "VALOR A COPIAR" (% o monto); verificación de integridad y descarga.
- **C4 (opcional):** envío real por publicación vía API, fórmulas vivas (opción B), guardar la campaña para retomarla.

## Preguntas abiertas
1. Regla del **aporte de ML**: ¿el cliente paga FINAL_PRICE y ML le acredita al vendedor MELI_AMOUNT? ¿La comisión se calcula sobre FINAL_PRICE o sobre otro precio? Un ejemplo con números de una venta real lo resuelve.
2. Un **Excel real** de una campaña (para fijar columnas, estilos y qué acepta ML).
3. Qué significa y cómo se recalcula **SELLER_PERCENTAGE** (y cuándo ML pide monto en vez de %).
4. ¿Opción **A** o **B** para jugar el descuento?
5. ¿Cuenta por **elección al subir** o por **detección con los ITEM_ID**?
