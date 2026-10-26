# Full ML: guía paso a paso para armar el envío

Para quien arma el envío a Full desde su PC. Pantalla: **Full ML → Simulador de reposición**. Todo lo que hace la pantalla es **de lectura**: no escribe en Mercado Libre ni en ninguna planilla. Lo único que sale de acá es un archivo (Excel/CSV) que se sube a mano a ML.

## 1. Antes de empezar
1. Abrí Full ML. Se muestra la **última lectura guardada** (arriba dice cuándo se hizo). Si es vieja, apretá **Actualizar**; tarda unos minutos porque lee de a poco para no pasarse del límite de ML. Si algún lote falla, se avisa «datos incompletos» y esa fila queda marcada.
2. Elegí la pestaña de la cuenta (**Group** o **Arg**). Cada una se arma por separado.

## 2. Parámetros (arriba, se recalculan al instante)
| Parámetro | Qué hace |
|---|---|
| **Fecha estimada de llegada** | Cuándo creés que entra el envío. El simulador resta lo que se va a vender hasta ese día. Si la cambiás, cambia «Stock a llegada» y la cantidad sugerida. |
| **Días de ventas** | Cuántos días hacia atrás mira para medir la venta diaria (por defecto 30). |
| **Semanas objetivo** | Para cuántas semanas querés dejar stock en Full después de llegar. Más semanas = se sugiere más. |
| **Usar ventas de mi depósito como referencia** | Solo para publicaciones **sin historial en Full** (nuevas). Usa lo que vendieron desde tu depósito como estimación de lo que venderían en Full. |
| **Enviar el % de esas ventas** | Qué fracción de esa venta de depósito mandar (por defecto 30 %). |

Tres cosas que conviene saber:
- La **venta diaria se calcula sobre los días en que hubo stock en Full**, no sobre los 30 días. Si quebró 21 días, no te diluye la venta con días en que no había nada para vender. Ejemplo: 110 unidades en 9 días con stock = 12,2 por día.
- Si la publicación **quebró stock** y vendió bastante, se marca **venta censurada** (la venta real probablemente era mayor): tomala como piso, no como techo.
- Las cantidades se muestran **en unidades de la publicación**: un combo ×3 vendido una vez cuenta como 1 venta, no 3.

## 3. Revisar vs. enviar (son dos cosas distintas)
- **Para revisar** (filtros: Todos · Con historial en Full · Nuevos sin historial · Quebraron stock · Con envío sugerido · Datos incompletos): **solo cambian lo que ves**. No marcan nada. Los filtros **no son excluyentes**: una fila puede estar en varios (por ejemplo «Quebraron» es un subconjunto de «Con historial»), y «Todos» muestra todas aunque no entren en ningún grupo.
- **Para enviar** (casilla de cada fila y botones *Tildar las visibles con sugerido* / *Tildar todas las visibles* / *Destildar las visibles*): **marcan** qué filas van al archivo. Las marcas valen aunque cambies de filtro.

Flujo recomendado: filtrá («Con envío sugerido»), revisá las filas dudosas, apretá *Tildar las visibles con sugerido*, cambiá filtro, corregí a mano lo que haga falta.

## 4. Leer cada fila
**Cantidad a enviar (paq.)** es la editable (empieza igual al sugerido). Las demás ayudan a decidir: *Ventas Full 30d*, *Ventas mi depósito 30d*, *Demanda usada*, *Ventas/día*, *Stock objetivo*, *Stock a llegada*, *Sugerido*, *Envíos pendientes*, *Stock Ecom*, *Stock Táctica* y **Por qué** (la explicación en palabras de por qué esa cantidad). Si el stock disponible de Ecom + Táctica no alcanza para todas las publicaciones del mismo SKU, se prioriza la que más vende.

## 5. Envíos que ya están en camino
ML no informa por API los envíos ya despachados que todavía no entraron. Para que no se los pida de nuevo: **Cargar PDF de envío pendiente** (se pueden elegir **varios** PDF a la vez y se **suman**). Se descuentan de lo que hay que enviar.

## 6. Exportar
- **Exportar para subir a ML**: solo filas **marcadas con cantidad > 0 y con código de ML**. Por eso el contador puede decir «622 seleccionadas» pero exportar menos: las que no están habilitadas en Full (sin código) se salen y se avisa «hay que habilitarla en Mercado Libre».
- **Exportar CSV**: para revisar o guardar en otro formato.

## 7. Qué pasa si…
- *Pasan los días sin actualizar:* la foto vieja se ve igual, con su fecha; las alertas viejas pasan a «ya no aparece».
- *Aparece «datos incompletos»:* ML cortó una lectura; esas filas usan el dato anterior o se marcan. Volvé a **Actualizar** más tarde.
- *Una fila dice «sin vincular»:* la publicación no tiene SKU de Ecom; se asume factor 1. Arreglala en la planilla de referencias.
