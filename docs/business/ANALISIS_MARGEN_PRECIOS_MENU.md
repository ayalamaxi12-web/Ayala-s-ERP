# Análisis y diseño: margen de los módulos ML, «Poner precio», Verificar ML, sección Mercado Libre, menú por usuario y uso por módulo

Estado: **solo análisis y diseño. No se implementó nada y no se retira nada.** Este documento **reemplaza** lo dicho sobre la fórmula y el botón «Poner precio» en `PRECIOS_Y_OFERTAS_ML_ANALISIS.md` (#48): ahora el operador elige el precio y no se multiplica nada (sección 9), y las Reglas de Precio no se migran ni se usan como fórmula (sección 10).
Base: `main` con #46 mergeado. Lo que no se puede ver desde el repo (flujos de n8n, planillas, datos reales) está marcado **a confirmar**.

## 0. Resumen
1. **Margen (8):** los módulos ML ya coinciden con la rentabilidad por orden en IIBB (5 % sobre neto), cheque (1,2 % sobre bruto), base del margen (precio sin IVA) y en que no incluyen costos de estructura. **Difieren en 6 cosas**; las dos importantes son el **costo por operación de Ecom ($149,12 por orden, que los módulos ML no descuentan)** y el **envío (Ofertas ML usa $7.000/$7.470, Análisis $8.500, la rentabilidad el real)**.
2. **Poner precio (9):** diseño con operador que elige el precio, margen visible, aviso bajo el umbral, confirmación, operador obligatorio y registro completo; reutiliza `/ayala-core/item/{id}/aplicar-precio` con 3 ajustes chicos de backend.
3. **Verificar ML (10):** nada del repo lo consume salvo su pantalla; lo que n8n lea no se ve. Las Reglas de Precio se exportan a una hoja de referencia **antes** de retirarlas (cada PM tiene su tabla en su navegador).
4. **Estructura ML (11), menú por usuario (12), uso por módulo (13):** propuestas listas para decidir.
5. **Verificaciones (14):** (a) el encabezado del Motor de Precios **sigue diciendo «no escribe nada a ML»** (aunque tiene botón que escribe); (b) **Mix crea referencias sin la columna `Activo` y Análisis las descarta como «inactivas»**; el scraper no pisa lo cargado; (c) nada enlaza la «Ofertas ML vieja».

## 8. Alineación del margen de los módulos ML con la rentabilidad por orden
**Referencia:** rentabilidad por orden ECOM del *Nuevo Reporte de Facturación* (`RENTABILIDAD_FUNCIONAL.md.md` §7.1): `Z = Q − M − O − S − T − OP`, `AB = Z − AA`, rentabilidad % = `AB / Q`.
`Q` = venta sin IVA · `M` = comisión de venta real · `O` = costo de envío real · `S` = impuesto al cheque (1,2 % sobre el bruto `U`) · `T` = IIBB (5 % sobre `Q`) · `OP` = costo por operación de Ecom · `AA` = costo (USD × TC de la orden).
**Sin costos de estructura** (sueldos, gastos generales): ni el reporte ni los módulos ML los incluyen; los cubre el cierre de administración. Se mantiene así.

**Módulos comparados:** Ofertas ML (`ofmMargenAt`, panel de parámetros), Análisis de Competencia / Competidores / Jugar (`compMargenAt`, panel de parámetros, que desde la etapa A vive en Análisis) y, por contexto, Campañas ML (usa el motor oficial `motor_precios` vía `cpMargenLocal`).

| Concepto | Rentabilidad por orden | Ofertas ML | Análisis de Competencia | ¿Coincide? |
|---|---|---|---|---|
| Base del margen | `AB / Q` (sin IVA) | sobre sin IVA | sobre sin IVA | **Sí** |
| IIBB | 5 % sobre `Q` (sin IVA) | 5 % sobre sin IVA | 5 % sobre sin IVA | **Sí** |
| Impuesto al cheque | 1,2 % sobre `U` (con IVA) | 1,2 % sobre el precio con IVA | 1,2 % sobre el precio con IVA | **Sí** |
| Costos de estructura | No | No | No | **Sí** |
| **Costo por operación Ecom (`OP`)** | **$149,12 por orden** (parámetro `costo_operacion_ecom`, se descuenta íntegro) | **No lo descuenta** | **No lo descuenta** | **No** |
| **Comisión** | `M` = la **real** de la orden (incluye costo fijo y cuotas tal como las cobra ML) | 15,5 % del precio con IVA **+** costo fijo por tramo **+** cuotas, estimados | 15,5 % + costo fijo por tramo + cuotas (Jugar), estimados | **Parcial**: la estimación es la del motor (`CRITERIOS_MARGEN` §3), pero es estimación; si la real difiere, el margen difiere |
| **Envío** | `O` real por orden | **Tramos por precio: $0 hasta $33.000, $7.000 hasta $50.000, $7.470 desde ahí** (`OFM.envioTramos`) | **$8.500 si el precio llega a $33.000** (`cfg-envio`, `umbral`) | **No**, y los dos módulos ML **difieren entre sí**; `CRITERIOS_MARGEN` §6 dice $8.500 / $33.000 |
| **IVA del precio** | `Q` viene calculado de la orden; el reporte **prohíbe recalcularlo** dividiendo (§7.2: en el régimen 10,5 % `U/Q = 1,10`, no 1,105) | factor que trae el backend desde Táctica | factor del SKU desde el catálogo de Ecom (`ivaSku`) | **Parcial**: en SKU de 10,5 % o con varios SKU por orden puede haber ~0,45 % de desvío del neto |
| **Costo del producto** | `G × TC`; **costo vigente** (§5.6) | costo y IVA **de Táctica** (el encabezado de la pantalla lo dice) | costo del **catálogo de Ecom** (`COSTOS_ECOM`) | **No**: `CRITERIOS_MARGEN` §7 fija **Ecom como fuente primaria** y Táctica solo para cruzar; Ofertas ML sigue en Táctica |
| **Tipo de cambio** | TC de la orden (fotografía histórica) | BNA del día (o manual) | BNA del día (o manual) | **Esperado**: es proyección, no venta |
| Cuotas | dentro de `M` | resta `precio × % del plan` (tabla de cuotas del motor) | ídem | **A confirmar** si `M` ya incluye el costo de cuotas (`CRITERIOS_MARGEN` §3 dice «tal como vienen de Ecom») |

**Qué habría que alinear (propuesta, sin implementar):**
1. **Agregar `OP`** ($149,12 por orden, hoy parámetro de la base) al margen de Ofertas ML y de Análisis. Es **por orden, no por unidad**: con 1 unidad por publicación se descuenta una vez; en combos o packs se descuenta una vez por orden. El motor oficial `motor_precios` tampoco lo trae (solo la rentabilidad real), así que conviene sumarlo **en el motor** y que los dos módulos lo lean de ahí.
2. **Una sola regla de envío** en los dos módulos, la de `CRITERIOS_MARGEN` §6 ($8.500 desde $33.000) o la tabla por tramos de Ofertas ML, pero **una**. Decisión de Maxx: hoy hay tres valores ($7.000, $7.470, $8.500).
3. **Una sola fuente de costo** (Ecom, según `CRITERIOS_MARGEN` §7) también en Ofertas ML.
4. **Parámetros desde una sola fuente**: hoy cada módulo tiene su propia copia en el navegador (`OFM` y `cfg-*`). La propuesta de `CRITERIOS_MARGEN` §9 («fórmulas JS del frontend que lean del motor, no constantes copiadas») sigue pendiente.
5. Dejar el **IVA** como está y documentar el desvío de los SKU de 10,5 %.
**Orden sugerido:** (a) decidir envío y costo (Maxx), (b) sumar `OP` y unificar en el motor, (c) un PR que haga leer a los dos módulos del mismo origen, con la **paridad de márgenes** en 0 casos fuera de tolerancia contra el motor, (d) recién ahí «Poner precio».
**No cambia ninguna fórmula de precio** de Verificar Ecom/Táctica ni las reglas del PM.

## 9. «Poner precio» en Ofertas ML («Precios y ofertas ML»)
**Reglas de Maxx:** el operador elige el precio, se muestra el margen, avisa si queda bajo el umbral, **no multiplica nada**. Reutiliza `POST /ayala-core/item/{id}/aplicar-precio` con confirmación, **operador obligatorio** y **registro completo** (margen, bajo umbral real, precio anterior y nuevo, fecha y hora).

**Panel (por publicación, junto a «Gestionar»):**
1. **Precio actual** en ML (de solo lectura).
2. **Precio nuevo**: campo numérico vacío; **no hay precio sugerido ni multiplicadores**. Opcional y solo informativo: «PM: $X» como referencia (no se aplica solo).
3. **Margen resultante** en vivo, con el desglose (comisión, costo fijo, cuotas, envío, cheque, IIBB, costo) usando los parámetros **ya alineados** (sección 8). Sin costo: «margen sin dato».
4. **Aviso bajo el umbral** (`OFM.umbral`): ícono + texto + borde, y el botón pasa a «Confirmar igual (bajo umbral)».
5. **Confirmación** (diálogo accesible): cuenta, MLA, SKU, precio actual → nuevo, margen, umbral y **operador**; solo se habilita con operador elegido.
6. Resultado real: ✅ con el precio **verificado por el GET del backend**, o ❌ con el motivo de ML (`_explicar_has_bids`). Nunca se reintenta solo. De a una publicación; un lote tilda varias pero escribe de a una, con resultado por fila.

**Backend (aditivo):** `aplicar-precio` hoy guarda `Margen % Resultante = ""` y `Bajo Umbral = "No"` **fijos** y solo la **fecha**. Cambios: (a) leer `margen_pct` y `bajo_umbral` del cuerpo (las rutas `/activar` y `/activar-campana` ya lo hacen); (b) agregar la columna **Hora** al final de `Historial Ofertas ML` (el Sheet existente necesita el encabezado nuevo a mano; el código no migra pestañas); (c) `origen = «Precios y ofertas ML»`.
**«Bajo umbral real»:** lo calcula el navegador con los parámetros alineados y lo registra; para que no sea un dato declarado sin control, una etapa posterior puede **recalcularlo en el backend** con el motor y guardar ambos (si difieren, alerta).
**Registro:** fecha, hora, cuenta, MLA, SKU, acción, precio anterior, precio nuevo, margen, bajo umbral, operador. **Limitación:** el operador es un nombre elegido en un selector, no una identidad autenticada (ver sección 12).
**Publicaciones con oferta activa:** cambiar el precio de lista con una oferta en curso puede ser rechazado o alterar el tachado; **a confirmar en vivo** con una publicación de prueba. Versión 1: solo sin oferta activa (o pedir «Sacar» antes).
**Pruebas:** cálculo de margen/umbral con el precio elegido, texto del aviso, contrato de `aplicar-precio` (el registro lleva margen, bajo umbral y hora) y prueba en vivo con una publicación propia.

## 10. Verificar ML: dependencias y retiro
**Quién lo usa o lo consume (verificado en el repo):**
- Frontend: `renderML`, `fetchMLPrices`, `fixAllML` (ahora apagada, #51), `exportML`, la página «Reglas de Precio» y el filtro por regla. Los helpers `mlFetch` y `mlPut` los comparte con la «Ofertas ML vieja» (sin menú).
- Backend: **ningún endpoint ni test lo consume**. Lo único que escribe es `PUT /ml-proxy/{mla}`, que sigue protegido con `X-ERP-Key`.
- **n8n (lo que se ve en el repo):** n8n consume `GET /campanas/calendario` (aviso diario de campañas), `GET /rentabilidad/reporte/*` y los reportes del motor de precios (`reportes_pricing.py`, con `X-Reporte-Token`) y el export de ventas Ecom a un Sheet de historial. **Ninguno es de Verificar ML.** Lo que n8n pueda leer de «Ecom publicaciones ML» o llamar a `/ml-proxy` o `/ecom/set-price-rule` **no se ve desde el repo: a confirmar con los flujos exportados** (pendiente de Maxx; por eso no se retira ningún endpoint).
- **Qué se rompe si se retira junto con las Reglas de Precio:** se pierde la revisión del precio de lista de todo el catálogo (única herramienta que lo hace), la corrección masiva en lista, la conexión manual de tokens ML (el token automático `/ml/token` sigue), el CSV de cruce y la tabla de reglas. Detalle en `PRECIOS_Y_OFERTAS_ML_ANALISIS.md` §4.

**Reglas de Precio: no se migran ni se usan como fórmula.** Propuesta de **exportarlas a una hoja de referencia antes de retirarlas**:
1. Botón «Exportar reglas» en la página de Reglas: baja un **CSV** (sin backend) con `regla`, `multiplicador actual en este navegador`, `multiplicador por defecto del código`, `fecha` y `quién exporta`.
2. **Cada persona que use la tabla la exporta** (las reglas se guardan **por navegador**; las tablas pueden diferir entre PMs). Hallazgo a confirmar con Natalia.
3. Maxx consolida los CSV en una pestaña **«Reglas de Precio (referencia)»** del Sheet (solo lectura, con la fecha de archivo). Si se prefiere automático: un `POST /reglas/exportar` (con `X-ERP-Key`) que escriba la pestaña con `get_gs()`; **es un endpoint nuevo, no se hace sin OK**.
4. Recién con las exportaciones guardadas y el OK de Maxx: congelar la página (cartel «solo lectura»), después retirarla. Nada se borra de las planillas.
**Verificar ML queda «a decidir»** (espera a Natalia, el martes, y a los flujos de n8n).

## 11. Estructura final propuesta de la sección Mercado Libre
| Módulo | Qué es | Estado |
|---|---|---|
| **Ofertas ML** (nombre propuesto: **«Precios y ofertas ML»**) | Ofertas y campañas propias y de ML + «Poner precio» (sección 9) | Tabla compacta en #50; «Poner precio» después de alinear el margen |
| **Campañas ML** | Simulador del Excel de la Central de Promociones | Sin cambios de función |
| **Análisis de Competencia** | Competencia por SKU/categoría/eventos, Jugar mi precio, **parámetros de margen** (etapa A) y, después, ventas/título/días por publicación (etapa B) | Vigente |
| **Full ML** | Conciliación y reposición | Vigente |
| **Verificar ML** | Revisión del precio de lista contra el PM | **A decidir** (escritura apagada; sin retirar) |
| Competidores ML | Hoy: «✏ Ecom», refrescar historial, ventas/títulos de pestañas `V-*` | **Sale de la sección cuando se complete la etapa D** (no antes de que «Jugar mi precio» envíe) |
| ML Tools | Jobs del tracker/vendedor | Ya está en **Sistema** (barra celeste de Global) |
| Reglas de Precio | Tabla de multiplicadores | En **Sistema**; se exporta y se retira junto con Verificar ML, con el OK de Maxx |
Menú resultante de la sección: **Precios y ofertas ML · Campañas ML · Análisis de Competencia · Full ML** (y Verificar ML mientras no se decida). No se une ni se jubila nada hoy.

## 12. Menú por usuario
**¿Hay permisos por usuario? No.** El ERP no tiene usuarios ni sesiones (`CLAUDE.md`): la única protección es la **clave compartida `X-ERP-Key`** (`erp_auth.py`) para los endpoints que escriben o exponen credenciales. Lo más parecido a un «usuario» son los selectores de **operador** (Natalia, Maxi A., Maxi I., Macarena) en Ofertas ML y en el Motor de Precios: un nombre elegido a mano.
**Propuesta (sin borrar nada, en dos pasos):**
- **Paso 1 — menú por perfil (visual):** selector «¿Quién sos?» en la barra superior, guardado en el navegador (`erp_operador`, el mismo que usan Ofertas ML y el Motor). Una pestaña **«Menú por usuario»** del Sheet (`Usuario · Módulo · Visible`) que edita Maxx; el menú oculta (no elimina) los módulos con «No». **Maxx ve todos** (perfil «Dirección» con todo en «Sí»; si el Sheet no responde, se muestran todos). Los módulos ocultos siguen existiendo y accesibles por código.
- **Paso 2 — permisos reales (si hace falta):** una clave por persona (`ERP_API_KEY` por usuario, con los módulos que puede escribir) y que `erp_auth` valide usuario + ruta. Es una decisión de seguridad aparte; el paso 1 **no es seguridad**, solo orden.
**Opción por defecto:** paso 1. **Limitación honesta:** cualquiera puede cambiar «¿Quién sos?» o abrir un módulo oculto; sirve para que cada operador vea solo lo suyo, no para impedir accesos.

## 13. Uso por módulo (contador liviano, 2 a 3 semanas)
- **Qué se cuenta:** visitas por **módulo, día y operador** (la entrada a la página en `goPage`). Sin contenido de pantalla, sin precios, sin datos de ventas.
- **Cómo:** el navegador acumula en memoria y manda **un solo resumen** cada 5 minutos o al cerrar (`fetch` con `keepalive`, con la clave que ya agrega el wrapper); `POST /uso/modulos` con `{fecha, operador, conteos:{modulo:visitas}}`.
- **Dónde:** pestaña **«Uso ERP»** del Sheet (`Fecha · Módulo · Operador · Visitas · Última vez`); el backend **suma** sobre la fila del día (una lectura y una escritura por resumen: muy por debajo de la cuota de Sheets). Alternativa: una tabla en la base del backend (más robusta, pero el pedido fue una pestaña).
- **Cuándo:** 2 a 3 semanas y se apaga con una bandera; después se borra la pestaña. Informe: tabla dinámica por módulo/semana/operador.
- **Límites:** cuenta entradas, no tiempo de uso; si el operador no está elegido, queda «sin operador». Es un endpoint nuevo (necesita OK).

## 14. Verificaciones (solo informar)
**(a) Motor de Precios — encabezado.** **No está corregido.** `docs/index.html` (página `page-ayala-core`) sigue diciendo «*Etapa 1 (solo lectura) -- … No escribe nada a ML todavía.*», pero la página **sí escribe**: «Confirmar y aplicar» llama a `/ayala-core/item/{id}/aplicar-precio` (ya registrado en el mapa de módulos). Conviene corregir el texto en un PR de presentación.
**(b) Mix — adónde escribe y si el scraper lo pisa.**
- Escribe con `POST /intel-comercial/mix/cargar` en el Sheet de competencia: agrega filas a **`Referencias_Mercado`** (`Origen = Mix`, `Tipo = Competencia`) y, si el vendedor es nuevo, a **`Entidades`**; lee el precio de cada publicación con el navegador del backend (Selenium) y lo muestra, pero **no escribe historial**.
- **Hallazgo:** Mix **no completa la columna `Activo`** (el scraper/migración sí pone `Si`) y `competencia_analisis` **descarta como «inactivas» las referencias con `Activo` vacío**: lo cargado por Mix **no aparece en Análisis hasta que alguien marque `Activo = Sí`** en la planilla (**a confirmar con la planilla real**: puede que tenga un valor por defecto). Tampoco completa `Cantidad` (Análisis asume 1).
- **¿Lo pisa el scraper?** **No:** `competencia_db` declara «nada se borra ni se edita de lo existente»; si una referencia ya existe y el SKU difiere lo registra como conflicto, no lo escribe. **Riesgo:** Mix deduplica por `(SKU, publicación)` y la migración por `clave_ref(link, entidad, item)`: **pueden crearse duplicados** (mismo link cargado por Mix y por la migración).
**(c) «Ofertas ML vieja» sin menú.** **Nada la enlaza:** no hay `data-page="ofertas-ml"` ni `goPage('ofertas-ml')` en el HTML; solo se llega desde la consola. La página y sus funciones (`ofertasLoad`, `ofertasUpdateMasivo`, que **escribiría** precios y tachados) siguen en el código, y `ofertas-ml` está además en las listas de tema (`MODULO_MK`, `PAGINAS_ESTILO_NUEVO`). Seguro por ahora; el retiro del código muerto queda para la jubilación.

## 15. Preguntas para Maxx
1. **Envío:** ¿una sola regla de $8.500 desde $33.000, o la tabla $0 / $7.000 / $7.470? (sección 8)
2. **Costo:** ¿Ofertas ML pasa al costo del catálogo de Ecom, como dice `CRITERIOS_MARGEN`? (sección 8)
3. **`OP`:** ¿se suma el costo por operación de Ecom ($149,12) al margen proyectado? (sección 8)
4. **Menú:** ¿paso 1 (perfil visual) ahora y paso 2 (claves por persona) más adelante? (sección 12)
5. **Mix:** ¿hay que marcar `Activo` a mano hoy, o la planilla lo hace sola? (sección 14b)
