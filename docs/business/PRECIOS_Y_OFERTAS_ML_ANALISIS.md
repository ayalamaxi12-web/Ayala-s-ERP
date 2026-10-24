# «Precios y ofertas ML»: ¿puede Ofertas ML absorber a Verificar ML?

Estado: **solo análisis (documentación)**. No cambia código, datos ni endpoints. **Verificar ML no se retira hasta el OK de Maxx**, que espera a Natalia (martes) y la revisión de los flujos de n8n.
Fuentes: `docs/index.html` (`calcExp`, `getRulePct`, `buildMLRow`, `renderML`, `fixAllML`, `ofmPrecioEsperadoPM`, `ofmRender`, `ofmSimularActivar`, `ayalaCoreConfirmarAplicar`) y `backend/main.py` / `backend/ml_ofertas.py` (`/ayala-core/item/{id}/aplicar-precio`, `fijar_precio_base`, `_registrar_historial_oferta`). Lo que no se puede ver desde el repo está marcado **a confirmar**.

## 0. Resumen
1. **No usan la misma fórmula.** Verificar ML: PM × regla (tabla de Reglas de Precio) + $8.500 de envío si el resultado llega a $33.000. Ofertas ML: PM × (1 + % real que cobra ML por la cuota); el envío solo entra si ya se conoce el costo real de esa publicación. El «combo» no existe en ninguna de las dos (en Verificar ML está fijo en 1).
2. **Verificar ML hace tres cosas que Ofertas ML no hace:** revisa **todas** las publicaciones de la planilla (no solo las que tienen oferta), usa la **regla** de cada publicación, y **escribe el precio de lista** (de a una o «Corregir todos»). Escribe sin confirmación, sin margen, sin operador y sin registro.
3. **El botón «Poner precio» es posible** reutilizando `/ayala-core/item/{id}/aplicar-precio`, que ya verifica el resultado con un GET y deja registro. Faltan 3 ajustes chicos en el backend (margen, bajo umbral y hora en el registro) y una decisión de negocio: **qué fórmula define el precio** (sección 1).
4. **Reglas de Precio solo la lee Verificar ML.** Si Verificar ML se retira, esa tabla queda sin uso, salvo que su cálculo pase al módulo nuevo. Hoy además se guarda **por navegador** (no es compartida).
5. **Antes de retirar:** pasar a Ofertas ML los 4 usos que hoy solo cubre Verificar ML (sección 4) y revisar n8n.

## 1. ¿El «PM esperado» de Ofertas ML usa la misma fórmula que Verificar ML?
**No.** Las dos parten del mismo dato (`S.pmData[sku].ml`, el precio ML del PM, cargado desde las planillas PM de Configuración) pero lo transforman distinto.

| | **Verificar ML** (`calcExp`) | **Ofertas ML** (`ofmPrecioEsperadoPM`) |
|---|---|---|
| Fórmula | `PM × combo × regla`; si el resultado es **≥ $33.000** suma **$8.500** | `PM × (1 + % de ML por cuota/100)`; **sin** combo, **sin** regla |
| Multiplicador | Tabla **Reglas de Precio** (21 reglas, p. ej. «Premium 3 cuotas» 1,15, «6 cuotas» 1,20, «Kit −1%» 0,99): es un **margen de seguridad propio**, más alto a propósito que lo que cobra ML | `CUOTAS_PCT_ML` = **lo que ML cobra de verdad**: 3 c. 8,9 %, 6 c. 13,4 %, 9 c. 17,8 %, 12 c. 21,6 % (debe coincidir con `CUOTAS_PCT_DEFAULT` de `backend/ml_ofertas.py`) |
| Combo / pack | `comboQty` existe pero **siempre vale 1** (las dos cargas de la planilla lo fijan en 1): el kit/pack se expresa solo por el nombre de la regla (p. ej. «Kit / Pack −1%») | No lo considera |
| Envío | Plano: **+$8.500** si el esperado ≥ `S.shippingThreshold` ($33.000), **estimado, mismo para todas** | **Real y solo si se conoce**: suma el costo real de envío únicamente cuando la publicación tiene envío gratis **y** ya se abrió «Gestionar» (esa consulta es cara y el escaneo en bloque no la trae); si no, el envío queda **afuera** |
| De dónde sale la «regla» o las cuotas | De la planilla **«Ecom publicaciones ML»** (columna «Regla de Precio», una por MLA) | De la **oferta** que devuelve ML (`cuotas_ofrecidas`); una oferta sin cuotas se compara contra el PM tal cual |
| Qué compara contra lo esperado | El precio **vigente**: `promo_price` si hay, si no `price` | El **precio de oferta** (`precio_oferta`, lo que paga el cliente), nunca el tachado |
| Tolerancia | Dos bandas: `S.tolGreen` (OK, por defecto **0,5 %**) y `S.tolYellow` (tolerancia, por defecto **2 %**) | Una sola: difiere si `|dif| > S.tolGreen` y, si no hay valor, **1,5** |
| Universo | Todas las publicaciones de la planilla (también las sin oferta) | Solo publicaciones con oferta activa en ML (las dos cuentas) |

**Ejemplos con el mismo PM** (calculados con las fórmulas del código):
| Caso | Verificar ML | Ofertas ML | Diferencia |
|---|---|---|---|
| PM $10.000, «Premium 6 cuotas» (×1,20) | $12.000 | $11.340 (6 c. = 13,4 %) | −5,5 % |
| PM $30.000, «Premium 3 cuotas» (×1,15) | $34.500 → ≥ $33.000 → **$43.000** | $32.670 (sin envío conocido) | −24 % |
| PM $25.000, «ML Unitario» (×1,00) | $25.000 | $25.000 | 0 |
| PM $20.000, «Kit / Pack −1%» | $19.800 | $20.000 (ignora el kit) | +1 % |

**Por qué importa:** si Ofertas ML absorbe a Verificar ML hay que **elegir una sola fórmula**. Hoy no hay una «correcta»: la tabla de reglas es un margen de seguridad que Maxx carga a propósito; la de Ofertas ML es el costo real de ML. Son decisiones de negocio distintas (precio a publicar vs. costo de vender), no un bug. Para el botón «Poner precio» se propone usar el **precio calculado con la tabla de reglas** (es el que hoy se publica) y mostrar al lado el margen real (ver sección 3). **A confirmar con Natalia.**

## 2. Qué hace Verificar ML que Ofertas ML no, y qué haría falta para «Poner precio»
**Solo Verificar ML:**
1. **Revisa todo el catálogo cargado** (planilla «Ecom publicaciones ML», hasta 3.000 filas), no solo lo que tiene oferta. Detecta publicaciones con el precio de lista desalineado del PM aunque nunca hayan tenido una promoción.
2. **Aplica la regla de cada publicación** (cuotas, kit, mayorista, «Oferta Tradicional», «Fijar Precio 1/2»…). Ofertas ML no sabe qué regla tiene cada MLA.
3. **Escribe el precio de lista:** el ✓ por fila (con un precio manual o el esperado) y **«Corregir todos en ML»** (todas las filas «Difiere»/«Tolerancia», una tras otra). Usa `PUT /ml-proxy/{mla}` con `{price}` y el token del navegador: **sin confirmación, sin mostrar margen, sin operador, sin registro y sin verificar con un GET aparte**.
4. **Conexión manual de tokens ML** (campos «Access Token» principal y secundario) y la carga de publicaciones desde la planilla. El token también se obtiene solo del backend al abrir el ERP (`autoConnectML` → `/ml/token`), así que lo manual es un respaldo.
5. **Exporta CSV** del cruce (SKU, MLA, regla, PM, esperado, precio ML, oferta, diferencia, estado) y filtra por regla.

**Solo Ofertas ML:** margen real con costo de Táctica; activar/sacar ofertas y campañas con operador y registro; simulador de descuento; las dos cuentas.

**Qué se necesitaría para un botón «Poner precio» en Ofertas ML**
| Falta | Detalle |
|---|---|
| a) **El precio a poner** | Decidir la fórmula (sección 1) y traer la **regla por MLA** desde «Ecom publicaciones ML» (hoy Ofertas ML no la lee). Sin la regla, solo podría proponer «PM» o «PM + cuotas reales». |
| b) **Qué precio se escribe** | `aplicar-precio` sin tachado fija el **precio de lista** (`fijar_precio_base`: `PUT /items/{id}` con solo `price` + GET de verificación). Una fila de Ofertas ML es una **oferta activa**: cambiar el precio de lista con una oferta andando puede ser rechazado o alterar el tachado/descuento. **A confirmar en vivo con una publicación de prueba**, no se puede ver desde el repo. La primera versión debería cubrir solo publicaciones **sin oferta activa** (o pedir «Sacar» antes). |
| c) **Margen y umbral** | Ya existen: `ofmMargenAt` / `margenParaFila` y `OFM.umbral` (hoy 10 %). Hay que calcularlos **con el precio nuevo**. |
| d) **Registro completo** | El endpoint hoy guarda margen vacío y «Bajo Umbral = No» fijos y solo la **fecha** (sin hora). Ver sección 3. |
| e) **Operador** | `ofm-operador` es un selector (se elige el nombre; no hay login). Es el «quién» disponible hoy. |
| f) **Token y clave** | No requiere nada nuevo: las escrituras ya usan las credenciales del backend y la clave `X-ERP-Key` que agrega el wrapper de `fetch`. |

## 3. Diseño propuesto: «Poner precio» con `/ayala-core/item/{id}/aplicar-precio`  *(sin implementar)*
**Dónde:** en cada tarjeta de Ofertas ML (junto a «Gestionar» y «Ver en ML») y una vista de revisión por lote que tilda varias y confirma **una sola vez**, pero escribe **de a una** (mismo criterio que el Motor de Precios: «nunca un lote silencioso»).

**Flujo (una publicación):**
1. «Poner precio» abre un panel con: **precio actual** (de ML), **precio nuevo** (calculado y editable) y **margen resultante** (con el costo de Táctica y el TC vigente), más la regla usada y la fuente del cálculo.
2. **Si el margen queda bajo el umbral** (`OFM.umbral`): aviso destacado (ícono + texto + borde, no solo color) y el botón cambia a «Confirmar igual (bajo umbral)». Mismo texto que hoy usa «Activar» («Confirmá solo si es intencional»).
3. **Si no hay costo/IVA de Táctica:** se muestra «margen sin dato» y se pide confirmación explícita (no se bloquea: hoy Verificar ML escribe sin margen).
4. **Si hay oferta activa** en esa publicación: aviso «el precio de lista cambia con una oferta en curso; ML puede rechazarlo o cambiar el tachado» y, en la primera versión, el botón queda desactivado hasta sacar la oferta (punto b de la sección 2).
5. **Operador obligatorio** (como `ofmRequireOperador`): sin operador no se envía.
6. Se llama a `POST /ayala-core/item/{id}/aplicar-precio` con `{cuenta, sku, precio, precio_anterior, operador, margen_pct, bajo_umbral}` (sin `precio_tachado`).
7. Se muestra el resultado real: ✅ con el precio verificado por el GET del backend, o ❌ con el motivo de ML (p. ej. `has_bids` explicado por `_explicar_has_bids`). Si falla, **no se reintenta solo**.

**Cambios en el backend (chicos, aditivos):**
- `aplicar-precio` debe **leer `margen_pct` y `bajo_umbral`** del cuerpo y pasarlos al registro (hoy escribe `""` y `"No"` fijos; las rutas `/activar` y `/activar-campana` ya lo hacen así).
- Agregar **hora** al registro (hoy `Fecha` es `date.today()`, sin hora). Cambia la tabla `Historial Ofertas ML`: sumar una columna «Hora» **al final** (el Sheet existente necesita el encabezado nuevo a mano; el código no migra pestañas ya creadas).
- Opcional: aceptar `origen` (p. ej. «Precios y ofertas ML») para distinguirlo de las escrituras del Motor de Precios, que hoy usan «Ayala Core -- aplicar precio».

**Registro «quién y cuándo»:** pestaña `Historial Ofertas ML` del Sheet «ML Competencia» (`SPREADSHEET_ID` del backend, el mismo `COMP_SHEET_ID` del frontend; constante `HIST_OFERTAS_SHEET_NAME`): fecha, hora, cuenta, MLA, SKU, acción, precio anterior, precio nuevo, margen resultante, bajo umbral, **operador** (nombre elegido en el selector). Limitación honesta: es un **nombre declarado**, no una identidad autenticada (no hay usuarios; la única protección es la clave compartida `X-ERP-Key`).

**Guardas:** de a una por vez; sin escritura si falta backend o clave; resultado por fila; nada se escribe en ML desde «Cargar» ni desde mirar; el botón no aparece en las filas de la cuenta sin credenciales.

**Pruebas que acompañarían a la implementación:** unitarias del cálculo de margen/umbral con el precio nuevo y del texto del aviso; test de contrato de `aplicar-precio` (el registro lleva margen, bajo umbral y hora); y una **prueba en vivo con una publicación propia de prueba** antes de habilitarlo (verificar lista con y sin oferta activa).

## 4. ¿Quién más lee Reglas de Precio y qué se rompe si se retira Verificar ML?
**Quién lee la tabla de reglas (`RULES`):**
- `getRulePct` ← `calcExp` ← `buildMLRow` ← **Verificar ML** (la tabla, el filtro por regla, el CSV y «Corregir todos»). **Es el único consumidor funcional.**
- `renderRules` (la página «Reglas de Precio» que la edita) y `populateRuleFilter` (el selector de Verificar ML).
- **Persistencia:** `saveStor`/`loadStor` guardan las reglas en `localStorage` (`global_erp_v1`). Son **por navegador**: si dos personas cambian multiplicadores, no se ven entre sí. **Hallazgo:** hoy cada PM podría estar calculando con una tabla distinta (a confirmar con Natalia).
- **Backend:** ningún endpoint ni test lee `RULES`. El comentario de `ml_ofertas.py` (~l. 954) aclara que **no** usa la tabla de reglas sino los % reales de ML.
- **Verificar Ecom / Táctica / Rentabilidad:** no usan `RULES`. Sí comparten `S.shippingThreshold`/`S.shippingCost` (los $33.000 y $8.500), que se editan en Configuración.
- **Fuera del repo (a confirmar):** si los flujos de n8n o alguna planilla leen «Ecom publicaciones ML» o llaman a `/ml-proxy` (`PUT`) o `/ecom/set-price-rule`. Es justo lo que Maxx quiere revisar antes de retirar nada.

**Qué se rompe o se pierde si se retira Verificar ML (sin reemplazo):**
| Pierde | Impacto | Cómo cubrirlo |
|---|---|---|
| Revisión del **precio de lista de todo el catálogo** contra el PM | Se pierde la única detección de desalineaciones sin oferta | Que «Precios y ofertas ML» cargue la planilla y revise todas las publicaciones (sección 2.a) |
| Tabla **Reglas de Precio** (página + filtro) | Queda sin uso; las reglas por MLA dejan de calcularse | Migrar la fórmula al módulo nuevo (decisión de la sección 1) y retirar la página después |
| **«Corregir todos en ML»** y el ✓ por fila | Se pierde la corrección masiva en lista | El botón «Poner precio» por lote (de a una) y mejor: con confirmación y registro |
| **Conexión manual de tokens ML** | Se pierde el respaldo manual; el token automático (`/ml/token`) sigue | Confirmar que el automático alcanza (a confirmar con Natalia) |
| **CSV de cruce** | Se pierde el export | Agregarlo al módulo nuevo |
| Helpers `mlFetch` / `mlPut` | Los usa también la «Ofertas ML vieja» (sin menú) | Se pueden borrar juntos, cuando se jubile la vieja |
| `S.pubData` / `loadMLSheets` | Solo Verificar ML | Pasan al módulo nuevo si se unifica |
| «Competidores ML → Refrescar historial» | Usa `S.mlToken` | **No se rompe** mientras el token automático se cargue al abrir el ERP |

**Orden sugerido (sin tocar nada hasta el OK):** (1) decidir la fórmula con Natalia; (2) revisar n8n; (3) implementar «Poner precio» y la revisión del catálogo **dentro** de Ofertas ML mientras Verificar ML sigue vivo; (4) comparar resultados unos días en paralelo; (5) recién ahí retirar Verificar ML y Reglas de Precio (con el mismo proceso de jubilación que SKUs & Referencias: marcador de vuelta atrás, link viejo que redirige, sin borrar datos).

## 5. Preguntas abiertas para Maxx / Natalia
1. ¿El precio a publicar sigue siendo **PM × regla** (con margen de seguridad) o pasa a **PM + costo real de ML**? Define la fórmula del módulo nuevo.
2. ¿Los PMs editan la tabla de **Reglas de Precio** en su navegador? Si sí, hoy hay tablas distintas por persona.
3. ¿El **token automático** (`/ml/token`) cubre todo, o alguien usa el manual?
4. ¿«Poner precio» debe poder tocar publicaciones **con oferta activa**, o solo las que no la tienen?
5. ¿Qué lee n8n de «Ecom publicaciones ML» o de los endpoints de escritura? (revisión pendiente de los flujos exportados).
