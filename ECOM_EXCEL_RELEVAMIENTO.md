# ECOM_EXCEL_RELEVAMIENTO.md

Relevamiento del proceso manual de ECOM que hoy alimenta la Rentabilidad,
para el adaptador `backend/rentabilidad/ingesta_ecom.py`. Reglas dadas por
Maxx (2026-07-31) y verificadas contra dos archivos reales que compartió
para este relevamiento — **no versionados en el repo** (los subió a `docs/`
temporalmente, se eliminan después de validar, son archivos de trabajo con
datos reales de venta).

## Origen

Reporte de ECOM exportado a Excel manualmente por rango de fechas (Fecha de
Creación, rango personalizado — típicamente 23→22 de cada mes). En el
futuro se reemplaza por API o por un adaptador Chrome, **sin cambiar el
proceso funcional ni tocar el motor** — por eso el adaptador solo entrega
`LineaEcomInput`, igual que hace `ingesta_tactica.py` para SQL Server.

## Estructura real del archivo crudo (verificado)

Hoja única (`Worksheet`). Fila 1 = encabezado informativo (`Periodo` +
rango de fechas). Fila 2 = vacía. **Fila 3 = encabezados reales.** Datos
desde la fila 4. El export además rellena la hoja con filas completamente
vacías después del último dato real (en el archivo de prueba: 997 filas
"de datos" nominales, de las cuales solo 229 tenían `Número Orden` — el
resto son padding y se ignoran por eso, no por ninguna regla de negocio).

Columnas reales confirmadas (nombres exactos del export crudo):
`Número Orden`, `Sku's Vendidos`, `Fecha Creación Venta`, `Estado Venta`,
`Fecha Pago`, `Estado Pago`, `Costo Sin Iva (total de productos)`,
`IVA A Favor`, `Canal De Venta`, `Usuario Integración`, `Medio De Cobro`,
`Entrega / Envio`, `Comisión Venta`, `Comisión Cobro`, `Costo Envío`,
`Impuestos (retenciones)`, **`Precio Neto`** (= columna Q "Precio SIN IVA"
del diccionario de datos — el export crudo la nombra distinto; el
adaptador prueba ambos títulos), `Total Impuestos`, `Precio Final`,
`Dif IVA`, `Cash`, `Utilidad Venta`, `Utilidad Costo`.

**No hay columna de TC en el export crudo.** Ver más abajo.

## Regla de exclusión — Estado de Pago (corrige RENTABILIDAD_FUNCIONAL.md a v2.1)

Solo `Cobrado`/`Cobro Parcial` participan (no se filtran entre sí). Todo lo
demás se excluye completamente — confirmado con datos reales: el archivo
crudo trae 2 líneas con `Estado Pago = "En Mediación"` (con espacio inicial
real en varios casos: `" Cobro Parcial"`, por eso el adaptador hace
`.strip()`). No se documentaron ejemplos reales de `Reembolsado`/`Sin
cobro` en este archivo puntual, pero la regla es la misma lista blanca:
**cualquier valor fuera de `{Cobrado, Cobro Parcial}` se excluye**, para no
arriesgar incluir por default un estado nuevo no visto todavía. Detalle
completo y corrección del funcional en `RENTABILIDAD_FUNCIONAL.md` v2.1
§7.7/§10 (ya actualizado).

## Validación de costo

En el archivo real (229 filas) **ninguna** tenía costo 0 o vacío — no hay
ejemplo real del caso "SKU madre" para verificar contra datos, pero la
regla es simple e implementada igual: `Costo Sin Iva <= 0` → incidencia
`COSTO_NO_RESUELTO`, la línea no se calcula, no se inventa una resolución
(no se intenta resolver la variante desde `Sku's Vendidos`).

## Postventa

Confirmado en la planilla procesada de Maxx: la única línea con
`Canal De Venta = "Posventa"` ya tenía `Precio SIN IVA = 0` y
`Precio Final = 0`, con `Rentabilidad = -(Costo Total)` exacto (costo
74.26 USD × TC 1500 = -111.390). El adaptador fuerza este override
explícitamente para `Posventa` sin importar el dato de origen, para no
depender de que ECOM siempre lo traiga ya en cero.

## TC — corrige la hipótesis original

El Excel de ECOM **no trae una cotización por línea** (a diferencia de
Táctica, que sí tiene `IDCotizacionMoneda` por factura). Verificado en la
planilla procesada real: **el mismo valor de TC (1500) se repite en las
1432 líneas reales del período completo**. Conclusión: Maxx aplica un
único TC (BNA) al cerrar/procesar el período completo, no uno por
línea/fecha. Por eso `EcomExcelAdapter.procesar(path, tc)` recibe el TC
como parámetro — no lo lee de ninguna columna ni sale a buscar históricos
por día.

## Validación de fórmula (line-by-line, contra datos reales)

Se recalculó Neto/Costo Total/Rentabilidad para 5 líneas reales de la
planilla procesada de Maxx usando exactamente la fórmula ya implementada
en `RentabilidadEcomCalculator` (imp. cheque 1,2% de `Precio Final`, IIBB
5% de `Precio SIN IVA`, comisión y envío deducidos íntegros, costo
convertido a pesos por TC) — **coincidencia exacta, centavo a centavo, en
las 5 líneas** (ej. orden 1405031: Neto/CostoTotal/Rentabilidad calculados
474146.6862 / 195405 / 278741.6862, idéntico al de la planilla). **El motor
no requiere ningún cambio.**

## Corrida real del adaptador (archivo crudo completo, 1 día)

`EcomExcelAdapter().procesar(archivo_crudo, tc=1500)`: 229 filas reales →
227 calculables + 2 excluidas por `Estado Pago="En Mediación"` + 0
incidencias de costo. Rentabilidad total del día (suma de las 227):
$1.550.308,63 — orden de magnitud coherente con las rentabilidades
individuales observadas.

## Fuera de alcance (confirmado por Maxx)

PM, categorías, subcategorías, responsables, listas de comparación de
márgenes y reportes personales no forman parte de este adaptador — el
adaptador solo entrega líneas listas para `RentabilidadEcomCalculator`.
Esa lógica ya vive en los providers de `adapters.py` (Sheets), sin
relación con este módulo.

## Pendiente

- Los dos archivos de prueba no están en el repo (se eliminan después de
  este relevamiento a pedido de Maxx) — si hace falta re-validar en el
  futuro, pedirle un archivo nuevo.
- No se validó el caso real de "SKU madre sin costo" (no había ningún
  ejemplo en el archivo compartido) — la lógica de incidencia está lista
  pero sin un caso real para confirmar el mensaje/formato esperado por el
  operador.
- Persistencia hacia `venta_ecom` (asignar `periodo`, chequeo de
  `SkuExcluido`) es una etapa separada, no construida — mismo alcance
  acotado que `ingesta_tactica.py`.
- API de ECOM: Maxx está gestionando credenciales; cuando las tenga se
  evalúa si conviene reemplazar el Excel — el adaptador ya está diseñado
  para eso (el motor no depende del formato de origen).
