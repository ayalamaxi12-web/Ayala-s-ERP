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


## Decisiones del usuario (2026-10-13)
- Opción A: se juega el descuento en la pantalla del ERP; se descarga el mismo Excel con la hoja nueva + columna "VALOR A COPIAR". Sin fórmulas vivas.
- Cuenta (IT/MT): se detecta con los ITEM_ID, corregible a mano.
- Aporte de ML: el margen se calcula sobre el precio que resulta del descuento del vendedor (SELLER_PERCENTAGE); ML acredita su parte (MELI_PERCENTAGE). La comisión de ML se calcularía sobre el precio final que paga el cliente (por confirmar con un dato real).
- SELLER_PERCENTAGE = % que pone el vendedor; MELI_PERCENTAGE = lo que pone ML; juntos = DISCOUNT_PERCENTAGE. ML pide enteros entre 5% y 80%; puede pedir % o monto (SELLER_AMOUNT): soportar ambos.

## Hallazgos del Excel real (Día de la Madre, 1885 filas)
- Hojas: `Ayuda`, `hidden` (veryHidden, trae el id de campaña que ML valida) y `Promociones`. Es una exportación de Google Sheets.
- `Promociones`: fila 1 OCULTA con los nombres técnicos (TITLE, ITEM_ID, SKU, …, FLEX_ID); filas 2–5 son encabezados/ayudas; datos desde la fila 6; columnas U–AJ ocultas; paneles congelados en C6; una validación de datos en ACTION ("Aplicar propuesta,No aplicar").
- Editables = celdas con relleno celeste FFCADDF8 en G/H: 1877 filas; las 8 "Participando" tienen relleno gris (no editables).
- SELLER_AMOUNT/SELLER_PERCENTAGE vienen como TEXTO ('524.95', '5') en las filas nuevas y como número en las 9 ya participando; MELI_* vienen '-' salvo en 9 filas (aporte ML 3,5%/3,75%/3,154%).
- 213 filas sin SKU. NEW_RECEIVES ("Recibís") viene como texto con formato `$ 6,947.91`: sirve como dato real para validar la comisión.
- Sin protección de hoja/libro, sin sharedStrings que tocar: el agregado a nivel ZIP deja idénticas las demás entradas.

## C0 — implementado
`backend/campanas_ml_xlsx.py` (`leer_promociones`, `agregar_hoja`, `verificar_integridad`), endpoints `POST /campanas-ml/leer` y `/campanas-ml/probar-hoja`, snippet `backend/scripts/c0_probar_hoja.js`, tests `backend/test_campanas_ml_xlsx.py`. Pendiente: que el usuario suba a ML el archivo con la hoja de prueba.

## C0 validado
ML aceptó el Excel con la hoja extra (prueba de 1 fila, 2026-10-13). El formato de agregado a nivel ZIP queda validado.

## C1 — implementado
- `rentabilidad/campanas_ml.py`: `precios_oferta` (montos de ML mandan sobre el %, que viene redondeado), `margen_oferta`, `pct_max_para_margen` (mayor % entero 5–80 que cumple un margen objetivo; recorre todos los enteros porque el margen no es monótono por el costo fijo/envío), `analizar`.
- Motor: `EntradaMotor.precio_cliente` (opcional, None = igual que antes). Con aporte de ML: venta, cheque e IIBB sobre el precio del vendedor (cliente + crédito de ML); comisión, cuotas, costo fijo y envío sobre el precio que paga el cliente. `margen_a_precio` lo rechaza. Paridad con el front intacta (60/60).
- `POST /campanas-ml/analizar` (xlsx, `tc`, `margen_objetivo` en %): por fila, PM, precio PM, costo, margen contado/3/6/9/12, margen sin aporte de ML, `descuento_que_cuadra_pct`, avisos. Snippet `backend/scripts/c1_analizar.js`.
- Pendiente de confirmar con datos reales: base de la comisión de ML en ofertas cofinanciadas; envío real por ítem (hoy 0 con aviso desde $33.000); 213 filas sin SKU en el Excel de Día de la Madre.

## Validación contra el "Recibís" de ML (2026-10-14, 5 filas del Excel de Día de la Madre, sin aporte de ML, contado)
| lista | final | Recibís ML | motor actual (15,5% · tabla) | diferencia |
|---|---|---|---|---|
| 10.499 | 9.974,05 | 6.947,91 | 7.098,07 | +150,16 |
| 19.459 | 18.486,05 | 12.713,59 | 12.880,71 | +167,12 |
| 10.499 | 8.159 | 5.430,60 | 5.564,35 | +133,75 |
| 34.403 | 32.682,85 | 13.055,99 | 27.617,01 (sin envío) | +14.561 |
| 22.499 | 15.117 | 9.897,21 | 10.033,86 | +136,65 |
- **CORRECCIÓN (2026-10-14, con una venta real de ML, toner TN1060COMP, $21.202,80: cargo por vender 15,5% = 3.286,43 + costo fijo 2.740, impuestos 245,62):** la comisión ES 15,5% y el costo fijo de 2.740 coincide con la tabla. La hipótesis de "16,404%" era un error: salía de atribuir al cargo de venta una diferencia que está en otro lado.
- Descomposición del "Recibís" del Excel: `final − 15,5% − costo fijo − 0,904% del final` (filas 2 y 5, exacto al centavo) y, en el primer tramo (filas 1 y 3), además **$60** fijos. Ese 0,904% se parece a los "Impuestos" que ML muestra aparte de la venta (en la venta real fueron 1,158% del precio): son retenciones, no comisión. El motor ya contempla IIBB y cheque por su cuenta, así que no se agrega.
- Los $60 del primer tramo (se vería como costo fijo 1.390 en vez de 1.330) NO están verificados: hace falta una venta real de un producto de ese tramo (< $16.000) con el desglose de ML. No se tocó la tabla.
- El **tramo del costo fijo y el umbral de envío se definen por el precio de LISTA**, no por el rebajado (fila 5: final 15.117 < 16.000 pero ML cobra 2.740; fila 4: final 32.682,85 < 33.000 pero lista 34.403 ≥ 33.000 → sin costo fijo y con envío; envío implícito ≈ $14.266 tras el 0,904%). Implementado: `EntradaMotor.precio_lista`.
- El caso con aporte de ML sigue sin dato real.

## C2 — implementado (pantalla "Campañas ML")
- Sidebar → 🎪 Campañas ML (`page-campanas-ml`, funciones `cp*` en `docs/index.html`). Subís el Excel; el backend (`POST /campanas-ml/analizar`) lo lee, cruza con PM + costo de Ecom, detecta la cuenta y devuelve el margen por cuota.
- **Cuenta IT/MT**: `campanas_ml_cuentas.detectar` pide `seller_id` a ML por lotes de 20 (`/items?ids=`, público) y lo mapea con `ml_auth.SELLERS`. La cuenta de la campaña = la de la mayoría; se corrige con el selector. Filas de otra cuenta quedan marcadas ⚠. De paso completa el SKU de las filas sin SKU en el Excel (213 en Día de la Madre) con el `seller_custom_field`/`SELLER_SKU` de la publicación (marcado "·ML").
- **Jugar el descuento**: el % vendedor de cada fila editable es un campo (entero 5–80, rojo si no cumple; "Excel: x%" si lo cambiaste). Al cambiarlo se recalcula en el backend (`POST /campanas-ml/simular`, mismo motor: sin paridad que mantener); ML mantiene su %. Lote sobre las filas editables filtradas: poner un % a todas, "máx. descuento que cumple el margen objetivo" (para la cuota de referencia) y volver al % del Excel.
- **Avisos fijos** (pendientes confirmados con Maxx 2026-10-14): (1) primer tramo de costo fijo: se usa $1.330; el Recibís del Excel sugiere ~$60 más (¿$1.390?) a confirmar con una venta real < $16.000; (2) el envío real desde $33.000 de lista no se trae todavía: esos márgenes no lo descuentan.
- Pendiente C3: exportar el mismo Excel con la hoja nueva + columna VALOR A COPIAR (% entero o monto).
