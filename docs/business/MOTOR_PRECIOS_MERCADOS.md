# Motor de Precios: mercados (Bloque 2, PR 4)

El Motor calcula con la fórmula de siempre (`ayala_core.calcular_precio_condicion`, reverse-markup). Para cada mercado cambian **los números**, no la forma.

## Mercados y condiciones de pago
| Mercado | Condiciones | Comisión | Cuotas |
|---|---|---|---|
| Mercado Libre | Contado, Reducida, 3, 6, 9, 12 | 15,32 % (los parámetros de siempre, no se leen de la pestaña) | los de siempre |
| Frávega | Simple, 3, 6, 9, 12 | 15,5 % base (a confirmar) | 3: 6,8 · 6: 10,6 · 9: 13,7 · 12: 16,6 (se suman a la base; a confirmar) |
| OnCity | ídem Frávega | **copiado de Frávega, a confirmar** (filas propias) | ídem |
| Megatone | ídem Frávega | **copiado de Frávega, a confirmar** (filas propias) | ídem |
| Web (Mercado Pago) | Simple, 3, 6, 9, 12, 18, 24 | 6 % por cobro | 0 · 3,40 · 7,90 · 12,60 · 15,20 · 22,10 · 27,60, **× (1 + recargo 20 %, editable y a confirmar)** = 4,08 · 9,48 · 15,12 · 18,24 · 26,52 · 33,12 |

«Reducida» existe solo en Mercado Libre. «Simple» es el Contado de los otros mercados (solo la comisión base). La pantalla muestra la **comisión total desglosada** (base + cuotas [+ recargo]) y la marca «a confirmar».

## Pestaña «Mercados» del Sheet del ERP
Columnas: `mercado`, `concepto`, `cuotas`, `porcentaje`, `incluye IVA` (SI / NO / a confirmar), `vigencia desde`, `vigencia hasta`, `fuente`, `nota`. Conceptos: `comision_base`, `cuotas` (columna `cuotas` = 3, 6, … o `simple`), `recargo_cuotas`, `reducida`, y las filas de `todos` (`costo_orden`, `impuesto_cheque`, `iibb`).
- **Se lee con el patrón de foto**: «Tarifas: hace X · Actualizar» (`GET /mercados/tarifas`, `POST /mercados/tarifas/actualizar`). La foto se guarda en la base (`ml_foto`, módulo `mercados_tarifas`); si la lectura falla se conserva la anterior y se avisa. Sin foto, se usan los valores iniciales del código y la pantalla lo dice.
- **Crear las pestañas**: botón «Crear pestañas Mercados y Envios» (o `POST /mercados/init`), con confirmación. Crea «Mercados» con los valores iniciales y «Envios» **vacía, solo con encabezados** (`mercado, peso desde, peso hasta, largo, ancho, alto, costo, vigencia`). **No pisa nada si ya existen.** Es lo único que escribe este PR, y solo en el Sheet del ERP.
- **Avisos** (un solo lugar, debajo del selector): falta una fila («falta dato: tarifa de 12 cuotas de OnCity»: esa condición no se calcula), vigencia vencida o todavía no vigente, «a confirmar», datos copiados. Si falta un dato, el cálculo dice «falta dato: …» y no inventa la tarifa.

## Descuentos comunes (panel compartido, activable por mercado)
Costo por orden de Ecom **$149,12** (monto en pesos, entra como costo fijo de la orden), impuesto al cheque **1,2 %** (sobre el precio con IVA) e IIBB **5 %** (sobre el precio sin IVA): los mismos valores para todos los mercados (filas `todos` de la pestaña), editables en pantalla y con un interruptor por mercado. El envío se carga a mano; vacío = automático «con la misma regla que ML», marcado «estimado como ML» en los otros mercados.

La fórmula ganó **un solo término opcional**, `costo_orden` (default 0): con 0, el precio es exactamente el de antes (test de paridad). 

## Decisiones tomadas y puntos que necesitan tu OK
1. **Resuelto (Maxx):** la comisión de ML en el Motor **queda en 15,32 %**, anotada en la pestaña «Mercados»; Frávega, OnCity y Megatone usan 15,5 %.
2. **Resuelto (Maxx):** el costo por orden ($149,12) está **apagado en ML y activo en los otros cuatro**, como está. Cuando se decida cambiarlo será un solo cambio (`ACTIVOS_POR_DEFECTO` en `backend/mercados.py`). Para decidir con datos, al abrir «Descuentos comunes» en ML se muestra, junto al interruptor, **cuánto sube el precio de contado** al activarlo, con el SKU más barato y el más caro de los SKU piloto (dos cálculos por lote, no guarda nada).
3. La comisión se trata, en todos los mercados, con la misma estructura de ML (la comisión se descuenta sobre 1,21 por el IVA del servicio). La columna «incluye IVA» de las tarifas **queda informativa y marcada «a confirmar»**: no altera la cuenta hasta que se confirme.
4. Renta objetivo de 18 y 24 cuotas (solo Web): arrancan en el valor de 12 cuotas (24 %) y son editables.
5. Lo que **no pude hacer**: las capturas de las webs de OnCity y Megatone (`referencia/oncity_web.png`, `referencia/megatone_web.png`) no llegaron al repositorio, y `full-logo.png` tampoco (es de otro PR). Los logos de Frávega (SVG y PNG), OnCity (color y blanco) y Megatone están en `docs/assets/logos/`.
6. Las tarjetas de resultado con la identidad completa (logo, color y tipografía) llegan en el PR siguiente (vista «Todos»); acá la identidad aparece en los botones del selector.

## Vista «Todos» (Bloque 2, PR 5)
Con «Todos» elegido, «Calcular» pide un lote por mercado (5 pedidos en paralelo, mismos parámetros y los interruptores de cada mercado) y muestra **una tarjeta por mercado** con todos los precios finales por condición de pago, una columna por SKU y, si hay pack, el precio de la publicación y el **por unidad**. Cada tarjeta tiene un botón «Ver en …» que pasa a ese mercado. Falta un dato → la celda dice «falta dato: …». Los avisos de todos los mercados aparecen juntos en el panel de configuración.

**Identidad (solo dentro de las tarjetas y del selector; el resto del módulo sigue con el estilo Global):**
| Mercado | Encabezado | Logo | Color en la tabla | Tipografía |
|---|---|---|---|---|
| Mercado Libre | amarillo `--mk-ml` con texto azul `--mk-ml-tinta` | isotipo oficial + el texto «Mercado Libre» | encabezado de tabla amarillo suave | **Nunito Sans** (la más cercana disponible en Google Fonts a la que usa ML, Proxima Nova) |
| Frávega | blanco con línea violeta | `fravega.svg` (el nombre va como logo) | cuotas «sin interés» en verde `--mk-fravega-verde`; gris para el encabezado; botón violeta | **Roboto** 400/500/700 (deducción visual de su web, a confirmar) |
| OnCity | azul `--mk-oncity-azul` | `oncity-blanco.png` | chip claro con texto azul; botón azul | **Outfit** (aproximación visual; alternativa Urbanist) |
| Megatone | gris | `megatone.png` | precios en rojo del logo; botón verde `--mk-megatone-verde-texto` con texto blanco | **Rubik** (aproximación visual; alternativa Montserrat) |
| Web | celeste de marca `--celeste-marca` con texto en tinta | `global-blanco.png` + «Web (Mercado Pago)» | encabezado celeste claro | **Montserrat** (la del ERP) |

Las tipografías de los otros cuatro mercados **se cargan solo al elegir «Todos»** (un `<link>` a Google Fonts agregado en ese momento); el resto del ERP no paga ese costo. Los colores nunca son la única señal (logo y nombre siempre) y todos los textos cumplen 4,5:1 (verificado con datos simulados).
Detalle técnico: las tarjetas no usan `<header>`/`<footer>` porque esas etiquetas heredan los estilos de la barra de la app.

## Ajustes de presentación (25/10)
- **Avisos de configuración**: una sola línea resumen («N a confirmar», y «N avisos de configuración» si falta un dato o venció una vigencia), con el detalle plegado por defecto y cada concepto una sola vez. Ya decididos y sin «a confirmar»: comisión base 15,5 % y cuotas de Frávega, OnCity y Megatone; comisión de ML 15,32 %; costo por orden $149,12; Web con base 6 % más recargo de 20 % en las cuotas (`mercados.DECIDIDOS`). Sigue «a confirmar» solo las cuotas de Mercado Pago de la Web (un aviso).
- **«Copiado de Frávega»** (OnCity y Megatone) es una nota gris chica, no un aviso. **Tarifas sin leer del Sheet** es información («usando los valores iniciales del código»), no un aviso.
- La tarjeta de Mercado Libre en «Todos» muestra su comisión real (15,32 %); antes decía «—» porque ML sin cambios no devolvía parámetros.
- **Vista «Todos»**: dos tarjetas por fila en escritorio (una en 1024 y 390), ancho máximo de 48 rem, tabla del ancho de su contenido (la columna de precios pegada a la de condiciones) y, con muchos SKU, scroll horizontal con la columna de condiciones fija. Corrige que el contenedor se mostraba como bloque (una tarjeta debajo de otra a todo el ancho).
- **Dónde escribe «Crear pestañas Mercados y Envios»**: en el Sheet que indica la variable `MERCADOS_SHEET_ID` (ver más abajo); nunca se ejecutó contra un Sheet real hasta que se confirme el destino.

## Sheet de configuración (variable `MERCADOS_SHEET_ID`)
Las pestañas «Mercados» y «Envios» viven en el Sheet que indica la variable de entorno **`MERCADOS_SHEET_ID`** (el ID de la URL: lo que está entre `/d/` y `/edit`). Va en el **servicio del backend** (Ayala-s-ERP, el que corre `uvicorn`); la tarea diaria (`scripts/ecom_diario.py`) no usa mercados. La cuenta de servicio de Google tiene que ser **Editora** del Sheet. Sin la variable no se lee ni se escribe ningún Sheet: las tarifas salen de los valores iniciales del código y la pantalla oculta «Actualizar» y «Crear pestañas». La confirmación de «Crear pestañas» muestra el nombre del Sheet. Ya no se usa el Sheet fijo `SPREADSHEET_ID` para esto.


## Decisiones de Maxi sobre Mercado Libre (27/10)
- **Comisión 15,5 %** para Mercado Libre y para todos los mercados (antes ML usaba 15,32 %).
- **Costo fijo por unidad de ML** forma parte de la renta: el precio se resuelve con el costo fijo del tramo en que cae (≤ $14.999: $1.330 · $15.000–23.999: $2.740 · $24.000–32.999: $3.320 · desde $33.000: sin costo fijo). Tabla de Flex/acuerdo/retiro; Full/correo/colecta dependen de tamaño y peso y **no** están modelados. En el borde de un tramo el precio nunca queda por debajo del escalón.
- **Costo por orden de Ecom ($149,12)** se descuenta también en ML (todo lo que se vende por Ecom lo lleva).
- No se tocó la tabla de cuotas (8,90 / 13,40 / 17,80 / 21,60, verificada en el simulador de ML el 2/9): la ayuda de ML pegada dice 8,50 / 12,90 / 17,30 / 20,80 y queda **pendiente de confirmar**. Tampoco los tramos de Ofertas ML (1255/2500/3030), que difieren de la ayuda.
- Con estas reglas los precios de ML **cambian a propósito**; los demás mercados no.
