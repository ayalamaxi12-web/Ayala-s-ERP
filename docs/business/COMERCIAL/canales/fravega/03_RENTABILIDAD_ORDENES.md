# 03 — RENTABILIDAD POR ORDEN · FRÁVEGA
## Para Claude Code · Agosto 2026

> Se apoya en `01_MAPA_API.md` (relevamiento del 13/08/2026) y en el análisis del archivo real de
> liquidación del período 16/07 al 31/07/2026.
>
> **Leer `../../00_LEEME` §5 antes de empezar.** Este módulo es **lectura y cálculo**: no escribe
> nada en el canal. Está del lado habilitado de la puerta.

---

## 1. El alcance, y lo que NO es

**Lo único que hay que resolver:** para cada orden de Frávega que ya está en ECOM, traer de
Frávega los dos datos que ECOM no baja bien y aplicarlos a la rentabilidad.

| Dato | De dónde |
|---|---|
| **Comisión total** (base + comercial + financiera) | Frávega |
| **Fee logístico** | Frávega |

Todo el resto del dato de la orden —ítems, SKU, cantidades, precio de venta, costo del
producto— **sale de ECOM y queda como está.** El precio de venta que baja ECOM ya es correcto.

**Fuera de alcance por ahora:** conciliar lo pagado contra lo facturado, cuadrar las dos razones
sociales de Frávega, gestión de penalidades, ajustes contables. Son válidos pero no es esto.

---

## 2. Por qué el dato de ECOM está mal

**ECOM aplica una comisión lineal.** Frávega no cobra una comisión lineal: cobra una base fija
más un recargo por financiación que depende del plan de cuotas activo en la publicación al
momento de la venta.

Por eso el desvío no es aleatorio ni parejo: **aparece solo en las órdenes de publicaciones con
cuotas.** En el período analizado, 8 líneas de 219.

Y el fee logístico de ECOM tampoco coincide, porque es una tabla escalonada de Frávega y no un
cálculo derivable.

---

## 3. La estructura real de la comisión — verificada sobre datos

La comisión se descompone en **tres componentes**, cada uno con su tasa y su monto:

| Componente | Tasas observadas | Quién la factura |
|---|---|---|
| **Comisión Base** | 0,15 (constante) | Frávega Tech S.A. |
| **Comisión Comercial** | 0,00 en el período analizado | — |
| **Comisión Financiera** | 0,00 · **0,068** · **0,106** | Frávega S.A.C.I. e I. |

Combinaciones observadas de **Total Comisiones**: `0,150` · `0,218` · `0,256`.

O sea: 15% cuando no hay cuotas, 21,8% con un plan, 25,6% con otro.

**La fórmula verifica exacto:**

```
Valor total Comisiones = Valor del sku × Total Comisiones
```

Se cumple en las 188 líneas de tipo Facturación. Las 31 de tipo Devolución no coinciden porque
llevan signo invertido.

### 3.1 La financiera no se puede inferir del SKU

Depende del **plan de cuotas activo en la publicación cuando se vendió**, no del producto. El
mismo SKU puede tener financiera en una orden y no en otra.

**Consecuencia: la tasa financiera se toma de la liquidación, no se calcula.** No hay forma de
derivarla desde el catálogo.

---

## 4. El fee logístico es una tabla escalonada, no un cálculo

Valores observados: `457,20` · `1.016` · `2.755` · `3.490,05` · `5.509` · `6.779`.

**El mismo SKU cae en escalones distintos según la orden.** Ejemplo real: un soporte de TV pagó
1.016 en 84 líneas y 2.755 en 8.

**Consecuencia importante: NO hay que calcular kilo aforado.** Frávega informa el fee por línea.
Peso y dimensiones dejan de ser un insumo del cálculo — siguen sirviendo para auditar si alguna
vez se quiere verificar que la escala aplicada es la correcta, pero el módulo no los necesita.

Operamos **con colecta**, así que la tabla de Fulfillment no aplica.

---

## 5. La fuente del dato: el archivo de liquidación

**Se descarga del Seller Center** (`seller-center.fravega.com/settlements/last`). No tiene API.

Hay dos vistas y las dos sirven:

| Vista | Qué es |
|---|---|
| **Liquidación actual** | Período cerrado. Se descarga como archivo Excel |
| **Próxima liquidación** | Período en curso. Botón "Descargar todas las órdenes" |

**Los montos de "Próxima liquidación" NO cambian al cerrar el período.** Confirmado.

**Consecuencia de diseño: no hay estados provisorio y definitivo.** Un solo valor por orden. El
dato está disponible antes de que cierre la quincena, así que la rentabilidad no tiene que
esperar.

### 5.1 Estructura del archivo

Cuatro pestañas: **Totales**, **Detalle de Operaciones**, **Penalidades**, **Ajustes**.

La que importa es **Detalle de Operaciones**, con 20 columnas:

| Columna | Uso en este módulo |
|---|---|
| `Orden` | **Clave de cruce.** Formato `v91950430frvg-01` |
| `Id seq` | Identificador secuencial |
| `Tipo de operacion` | `Facturación` o `Devolución`. **Define el signo** |
| `Fecha de operacion` | |
| `Fecha de compra` | |
| **`Fee logistico`** | **Dato a aplicar** |
| `Envío` | Lo que pagó el comprador. **No es costo.** En este período, 0 |
| **`Sku`** | Permite imputar a nivel producto, no solo orden |
| `Nombre del Sku` | |
| `Valor del sku` | Base de cálculo de la comisión |
| `Comisión Base` | Tasa |
| `Valor Comisión Base` | Monto |
| `Comisión Comercial` | Tasa |
| `Valor Comisión Comercial` | Monto |
| `Comisión Financiera` | Tasa |
| `Valor Comisión Financiera` | Monto |
| `Total Comisiones` | Tasa total |
| **`Valor total Comisiones`** | **Dato a aplicar** |
| `Valor total Descuento Comercial` | Menor. En el período, total $2.560 |
| `Nro de recibo` | Vacío en el período analizado |

**El archivo trae más columnas que la vista en pantalla.** Hay que usar el archivo, no scrapear
la tabla.

### 5.2 Granularidad

Una orden puede tener **más de una línea** — hasta 2 en el período analizado. 219 líneas para 200
órdenes únicas.

**Para aplicar a la rentabilidad hay que agrupar por orden**, sumando `Valor total Comisiones` y
`Fee logistico` con el signo que corresponda según `Tipo de operacion`.

Y como el archivo trae `Sku`, **si en el futuro se quiere rentabilidad por producto y no solo por
orden, el dato ya está.** No hace falta cambiar la ingesta.

---

## 6. El cruce ECOM ↔ Frávega

### 6.1 Los identificadores

De la liquidación: `Orden` con formato **`v91950430frvg-01`**.

De la API de VTEX (`GET /api/oms/pvt/orders/{orderId}`):

| Campo | Qué es |
|---|---|
| `orderId` | ID interno de VTEX |
| `sequence` | Número de secuencia |
| `marketplaceOrderId` | ID del pedido del marketplace |
| `sellerOrderId` | ID que asigna el vendedor o su integrador |

El formato de la liquidación coincide con el patrón de `orderId` de VTEX que aparece en el
Seller Center.

### 6.2 La tarea que bloquea todo

**Encontrar en ECOM el campo que contiene el número de orden de Frávega.**

Code tiene acceso por SQL. Tomar una orden de Frávega en ECOM y buscar un campo que contenga un
valor con el patrón `v########frvg-##`. Puede llamarse referencia externa, número de canal, orden
externa, id de marketplace.

**Si el campo no existe, hay que resolver la trazabilidad antes de calcular nada.** Y no se puede
cruzar por monto y fecha: dos órdenes del mismo producto el mismo día son indistinguibles, y un
falso match asigna la comisión equivocada sin que nada lo señale. Un módulo de rentabilidad que
imputa costos a la orden equivocada es peor que la planilla manual.

---

## 7. Qué hace el módulo

```
1. Ingerir el archivo de liquidación (pestaña Detalle de Operaciones)
2. Agrupar por Orden:
      comision_total = Σ Valor total Comisiones   (negativo si Devolución)
      fee_logistico  = Σ Fee logistico            (negativo si Devolución)
3. Cruzar contra la orden de ECOM por el identificador de Frávega
4. En la cascada de rentabilidad, REEMPLAZAR:
      comisión que trae ECOM  →  comision_total de Frávega
      costo de envío de ECOM  →  fee_logistico de Frávega
5. Todo el resto del dato de ECOM queda intacto
```

### 7.1 Guardar el desglose, no solo el total

Aunque a la cascada entre el total, **guardar los tres componentes por separado** —base,
comercial, financiera— con su tasa y su monto.

Motivo: la financiera es el costo de vender en cuotas. Si queda fundida en un total, no se puede
responder cuánto cuesta la financiación ni si conviene. Guardarla es gratis; recuperarla después
no.

### 7.2 Marcar las órdenes sin dato de Frávega

Una orden de ECOM que no aparece en ninguna liquidación es un caso a mostrar, no a completar con
el dato de ECOM en silencio. Puede ser que el período todavía no la incluya, o que el cruce
falló.

**Un margen calculado con la comisión lineal de ECOM tiene que estar marcado como tal.** Si se
mezcla con los que tienen el dato real, se pierde la distinción y el promedio miente.

---

## 8. Dos cosas que van al criterio de Rentabilidad, no acá

**Impuestos.** Las tasas y montos de la liquidación están **sin impuestos**. Después se facturan
con IVA 21% más percepciones. Hay que decidir si la rentabilidad se calcula toda neta o toda con
impuestos, y ser consistente. Mezclar los dos criterios desplaza el margen varios puntos sin que
se note.

Esta decisión la define `RENTABILIDAD_FUNCIONAL.md`, que es intocable desde Comercial. Si el
criterio no está ahí, se reporta como pendiente de Rentabilidad.

**Devoluciones.** El detalle trae líneas de tipo `Devolución` que netean la facturación. Hay que
definir si la rentabilidad de una orden devuelta es cero, negativa por los costos no
reintegrados, o si la orden se excluye. No es una decisión de este módulo.

---

## 9. Orden de construcción

| # | Qué | Bloquea |
|---|---|---|
| 1 | **Encontrar el campo del identificador de orden de Frávega en ECOM.** SQL | Todo |
| 2 | Ingesta del archivo de liquidación, pestaña Detalle de Operaciones | — |
| 3 | Agrupación por orden con el signo de `Tipo de operacion` | 2 |
| 4 | Cruce y reemplazo de comisión y fee en la cascada | 1, 3 |
| 5 | Persistir el desglose de los tres componentes de comisión | 3 |
| 6 | Marcar las órdenes sin dato de Frávega | 4 |

El punto 1 es descubrimiento, no desarrollo, y no se puede saltear.

---

## 10. Lo verificado y lo que queda abierto

### Verificado sobre el archivo real del período 16/07 al 31/07/2026

- `Valor total Comisiones = Valor del sku × Total Comisiones` en las 188 líneas de Facturación
- Tres componentes de comisión con tasas 0,15 / 0,068 / 0,106
- Fee logístico como tabla escalonada, informado por línea
- El total de comisiones del detalle reconstruye el de la pestaña Totales: $422.645,30
- El fee del detalle reconstruye el de Totales: $232.754,75
- Los montos de Próxima Liquidación no cambian al cerrar

### Abierto, y no bloquea este módulo

- El monto a facturar por Frávega Tech ($407.140,91) no coincide con la suma de comisiones base
  del detalle ($506.776,48). La diferencia de $99.635 puede ser notas de crédito de períodos
  anteriores — la nota (5) del archivo lo insinúa. **Afecta la conciliación contra facturas, no
  la rentabilidad por orden**
- La pestaña `Ajustes` vino vacía. No se sabe qué trae cuando tiene contenido
- Comisión Comercial vino en 0 en todo el período. No se sabe cuándo se activa
- La columna `Envío` vino en 0 en todo el período
