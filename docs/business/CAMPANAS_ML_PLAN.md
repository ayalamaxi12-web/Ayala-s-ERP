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

## Tipos de campaña (2026-10-14)
- **Con reparto** (Día de la Madre, "Con aporte de Mercado Libre"): SELLER_PERCENTAGE + MELI_PERCENTAGE; se edita SELLER_PERCENTAGE; se aplica la regla del aporte de ML.
- **Simple** (Sumate, Wellness Week, Semana del Mueble, Acelera Full, Lo mejor de todos los días): solo DISCOUNT_PERCENTAGE, que es lo que se edita. Criterio conservador de Maxx: el descuento es TODO del vendedor (sin aporte de ML), así nunca se sobreestima el margen. El aporte real por tipo se verá más adelante.
- `leer_promociones` detecta el tipo por la presencia de SELLER_PERCENTAGE y normaliza ambas al mismo formato de fila (en las simples SELLER_PERCENTAGE = DISCOUNT_PERCENTAGE, SELLER_AMOUNT = lista − final, MELI_* vacío). Solo corta sin ITEM_ID / ORIGINAL_PRICE / la columna del descuento; cualquier otra columna ausente es un aviso. Editable = celda celeste de la columna del descuento; si ninguna fila la trae, se asume editable lo que no está participando (con aviso). Todo el análisis y la hoja a agregar tienen la misma estructura para los dos tipos.
- Probado con variantes sintéticas y con 6 Excels reales (Día de la Madre, Con aporte de ML, Sumate al Día de la Madre, Semana del Mueble, Acelerá Full, Lo mejor de todos los días): los 6 se leen sin cortar, tipo y columna editable correctos, la hoja nueva se agrega con integridad OK. Falta Wellness Week (no llegó).
- **Corrección con los datos reales:** la regla "entero 5–80" de ML es sobre el descuento TOTAL (DISCOUNT_PERCENTAGE), no sobre el del vendedor: en "Con aporte de ML" 189 de 191 filas traen SELLER_PERCENTAGE con decimales (ej. 4,5 + 0,5 = 5). La pantalla ahora juega el TOTAL (entero 5–80); ML mantiene su aporte (el monto si ML lo informó, si no el %) y el vendedor pone el resto, que es el valor a copiar en SELLER_PERCENTAGE (puede tener decimales). En las simples total = DISCOUNT_PERCENTAGE.
- Editable: celda celeste FFCADDF8; "Lo mejor de todos los días" pinta con otro celeste (FFECF3FC) y ninguna con el de siempre: ahí se asume editable lo que no es gris (FFF3F3F3) ni está participando, con aviso.

## Aporte de ML: confirmado (2026-10-14)
Prueba real de Maxx: al cambiar el descuento del vendedor en una publicación donde ML también aporta, lo que ML asume NO cambia. La suposición (ML mantiene su aporte) queda confirmada; ya no es un criterio conservador sino el comportamiento real.
- En los Excels, el aporte de ML es un **monto en $** (en "Con aporte de ML" el % viene redondeado y no cierra con el monto: ej. $202,35 sobre lista $41.699 = 0,4853%, el Excel muestra 0,5%); en las 9 filas de Día de la Madre es un % limpio de la lista (3,5% / 3,75%). Como el precio de lista no cambia al jugar el descuento, monto fijo y % de lista fijo son lo mismo: el código mantiene el monto en $ cuando ML lo informa (`meli_monto`) y recién si no, el %. El máximo descuento que cumple un margen (`pct_max_para_margen`) también usa ese monto, no el % redondeado.

## Usabilidad de la pantalla (2026-10-14)
Problemas reportados al probar con datos reales: lento al cambiar el %, a veces no tomaba el valor, el orden no funcionaba, el lote no cambiaba las filas.
- **Causa**: cada edición llamaba a `/campanas-ml/simular`, que reconstruía el catálogo de Ecom y GRAL CATEGORIAS en cada pedido; con pedidos solapados la respuesta vieja pisaba la edición nueva (valor que "no toma"); el lote esperaba esa respuesta sin mostrar nada; y los encabezados no tenían orden (solo el selector).
- **Arreglo**: el margen al jugar el descuento se calcula en el navegador (`cpMargenLocal`, espejo de `precio_a_margen` con aporte de ML; el backend manda los parámetros del motor `motor_ml` y el costo/IVA de cada SKU `calc`). Sin llamadas al editar: instantáneo, sin carreras. Lote (poner %, máx. descuento que cumple el margen, volver al Excel) también local. Enter aplica y baja al siguiente. Orden por columna con clic en el encabezado (▲/▼; vacíos siempre al final) y por el selector. Cambiar el TC recalcula todo.
- El backend cachea 5 min el contexto de costos (`_campanas_datos`), por si se vuelve a subir un Excel. `/campanas-ml/simular` queda disponible pero la pantalla ya no lo usa.
- Paridad: `test_front_campanas.py` compara `cpMargenLocal` contra `margen_oferta` del motor en >200 casos (tramos, umbral de envío por lista, aporte de ML, cuotas) a ≤ 0,011 pp, y `cpPctMax` contra `pct_max_para_margen`.

## El backend manda sobre el navegador (2026-10-14)
Pedido de Maxx: el simulador no puede mostrar un margen distinto del real (como pasó con las cuotas); si hay diferencia, el valor final/exportado sale del backend.
- Medición: 20.000 casos al azar (lista, descuento, aporte de ML, costo, IVA, cuota, envío) navegador vs `margen_oferta` del motor: diferencia máxima 0,005 pp de margen y $0,005 de rentabilidad (el redondeo a 4 decimales del motor). No es idéntico al décimo de centavo; por eso el backend manda.
- Cada edición muestra un valor ≈ (vista previa local) y `cpConfirmar` pide enseguida (600 ms, en segundo plano) el cálculo al backend (`/campanas-ml/simular`, mismo TC): el resultado del backend REEMPLAZA al local, la fila deja de marcar ≈ y se registra la diferencia máxima. Si la fila se editó de nuevo mientras tanto, no se pisa y se confirma en la pasada siguiente. Si el backend difiere (>0,011 pp) se muestra el del backend y se avisa en rojo; si no responde, queda ≈ con aviso.
- Para C3 (export): los valores que se exporten SALEN del backend (se confirman todas las filas modificadas antes de exportar), nunca del cálculo local.

## Dos ventas reales de SEW-MINI ($26.599) — 2026-10-14
- **FULL**: comisión 15% ($3.989,85), costo fijo $3.400, envío $0, impuestos $240 → recibe $18.968.
- **FLEX**: comisión 15%, costo fijo $3.320, envío +$8.990 (lo paga el comprador y ML se lo acredita al vendedor), impuestos $321 → recibe $27.957.
- **Envío < $33.000**: es $0 (Full) o un ingreso (Flex); nunca un costo. Auditoría: el motor (`_estructura` ML: envío solo si la LISTA ≥ umbral), Campañas (`calc.envio` = 0 por defecto y el mismo umbral), Ofertas ML (`ENVIO_TRAMOS_DEFAULT`: 0 por debajo de 33.000) y Competidores (`compMargenAt`: envío solo desde 33.000) no descuentan envío por debajo de $33.000. Un test fija el criterio aunque alguien pase un envío.
- **Comisión por categoría**: 15,5% toners (Insumo de Impresión), 15% SEW-MINI. `EntradaMotor.comision_pct` (None = la general 15,5%); Campañas toma la de la categoría del SKU desde `pricing_comision_categoria` (10 categorías cargadas en el seed: Audio y Video 16%, Insumo de Impresión/Periféricos/Conectores 15,5%, Gráfica y Estampado/Comercial y Oficinas 15%, Equip. Automotor 14,5%, Construcción y Hogar 14,4%, Electrodomésticos/Seguridad 14%) y cae a la general con un aviso si la categoría no está. Origen mostrado por fila ("com 15%"). Pendiente: confirmar esos valores y leer la comisión REAL de cada publicación desde ML.
- **Impuestos de ML en el Recibís = 0,904%** del monto (240/26.599; 321/(26.599+8.990)): explica la diferencia constante del Excel de campañas. No entra al margen (IIBB y cheque propios ya lo cubren): solo al "Recibís" que se compara con ML (`IMPUESTOS_ML_PCT`).
- **Costo fijo**: la tabla trae 3.320 para este tramo; en Full se cobró 3.400 (+$80), en Flex 3.320. En el primer tramo, el Excel de campañas sugería +$60. Hipótesis: Full cobra un adicional por tramo; falta una venta real < $16.000 para confirmarlo. Sin cambios en la tabla.
- **Bonificación Flex (+$8.990)**: es plata a favor; pendiente verla como dato (descuentos y bonificaciones), no entra al margen.
