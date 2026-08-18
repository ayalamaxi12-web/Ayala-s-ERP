# TACTICA_SQL_RELEVAMIENTO.md

Relevamiento del SQL Server de Táctica para reemplazar la exportación manual de
Excel del reporte **Facturación → Análisis de productos**, que hoy es la
fuente de `venta_tactica` en el motor de Rentabilidad
(`backend/rentabilidad/models.py`).

**Conexión** (solo lectura): `10.10.10.99`, base `FG`, usuario `tactica`.
Motor: `pymssql` (FreeTDS embebido, sin driver ODBC de sistema). SQL Server
2019, base de datos ~281 tablas — el ERP de origen es una instalación de
"Sylloge/Strategikon" genérica (nombres de tabla en español, `RecID` binario
empaquetado como clave primaria en casi todas las tablas).

**Estado: relevamiento estructural completo y validado contra datos reales.
La regla de régimen de comprobante (Cuenta 1 / Cuenta 2 / Pérdida
Definitiva) es la regla oficial de negocio dada por Maxx — ver §5. Queda
pendiente solo la verificación estructural de qué columna SQL exacta marca
"Electrónica" (bloqueada por caída de VPN, no por falta de regla).

---

## 1. Tablas relevantes

| Tabla | Rol |
|---|---|
| `facturas` | Encabezado de comprobante. Un registro por factura/NC/ND. |
| `facturasitems` | Líneas de comprobante (SKU + cantidad + importes). **Una fila = una línea de VentaTactica.** |
| `talonarios` | Numeración por sucursal/tipo. `NroSucursal` = prefijo del "Nº Factura" (confirmado, ver §3). `Tipo` = enum interno del tipo de comprobante (ver §5, gap abierto). |
| `fiscal` | Maestro de clientes/proveedores (razón social, CUIT). Es el "Cliente" de la factura vía `facturas.IDFiscal`. |
| `productos` | Maestro de SKU (fabricante, tipo de producto, descripción) — redundante con lo que ya trae `facturasitems` por línea. |
| `usuarios` | Usuario/vendedor, vía `facturasitems.IDUsuarioVendedor`. |
| `monedacotizaciones` | Cotización de moneda **snapshot por línea**, vía `facturasitems.IDCotizacionMoneda`. `CotMoneda2` = cotización de Dólares (moneda Nº2) para esa cotización puntual. |
| `moneda` | Decodifica `NroMoneda`: 1=Pesos, 2=Dolares, 3=Euro, 4=CNY. |

Tablas descartadas tras inspección (no aportan al reporte de Análisis de
Productos): `grupocomprobantes` (vacía), `detalleslistas` (vacía, no hay
tabla de valores para decodificar `talonarios.Tipo`), `ventaslineas` /
`ventasresumen*` (pertenecen a presupuestos/cotizaciones, no a facturación),
`reportes` (son metadatos de reportes del cliente de escritorio de Táctica,
no contienen la definición SQL de "Análisis de productos" — es un reporte
nativo del ERP, no una consulta guardada).

---

## 2. Join confirmado (probado contra ~15 líneas reales del 2026-07-31)

```sql
SELECT
    t.NroSucursal, f.Numero, f.FechaEmision,
    fis.RazonSocial AS Cliente,
    t.Tipo AS TalonarioTipo,          -- gap abierto, ver §5
    fi.Codigo, fi.Fabricante, fi.TipoProducto, fi.Cantidad,
    fi.ImportePrecioVenta1 AS PrecioVentaPesos,
    u.Usuario AS Vendedor,
    mc.CotMoneda2 AS TC
FROM facturas f
JOIN talonarios t      ON t.RecID = f.IDTalonario
JOIN facturasitems fi  ON fi.IDFactura = f.RecID
LEFT JOIN fiscal fis   ON fis.RecID = f.IDFiscal
LEFT JOIN usuarios u   ON u.RecID = fi.IDUsuarioVendedor
LEFT JOIN monedacotizaciones mc ON mc.RecID = fi.IDCotizacionMoneda
WHERE f.FechaEmision BETWEEN @desde AND @hasta
```

Resultados de muestra (reales, 2026-07-31):

| NroSucursal | Numero | Cliente | TalonarioTipo | Codigo | Cantidad | PrecioVentaPesos | Vendedor | TC |
|---|---|---|---|---|---|---|---|---|
| 3 | 127128 | Sign Solutions SA | 38 | MESH-LINER-12X12-320X50MT | 40 | 216402.40 | Brian Avila | 1520.0 |
| 5001 | 19036022 | DOS Alsina Walter Leonardo | 23 | PV-TV-SMART-43IFHD | 3 | 274888.60 | Hernan Schmidt | 1510.0 |
| 3 | 9788 | Vega Pablo Nicolas | 40 | INKCARTHP667XLC | 1 | 21983.00 | Estefania Zeballos | 1510.0 |

`TC` (1510–1520) es consistente con la cotización real del dólar al
31/07/2026 — confirma que `monedacotizaciones.CotMoneda2` vía
`IDCotizacionMoneda` es el TC correcto e inmutable por línea (§5.5 del
funcional: tomado al momento de la carga, no se recalcula).

---

## 3. Mapeo columna VentaTactica → origen SQL

| Columna (letra) | Campo `VentaTactica` | Origen SQL | Confianza |
|---|---|---|---|
| A · Fecha | `fecha` | `facturas.FechaEmision` | Alta |
| B · Empresa | `empresa` | `fiscal.RazonSocial` (vía `facturas.IDFiscal`) | Alta — verificado, incluye personas físicas igual que el Excel actual |
| C · Codigo | `codigo` | `facturasitems.Codigo` | Alta |
| D · Descripción | `descripcion` | `facturasitems.Descripcion` | Alta |
| E · Fabricante | `fabricante` | `facturasitems.Fabricante` | Alta |
| F · Tipo de Producto | `tipo_producto` | `facturasitems.TipoProducto` | Alta |
| G · Familia | — (no está en `VentaTactica`, pendiente si se necesita) | `productos.SubFamilia` (join extra por `IDProducto`) | Media — no probado |
| H · Vendedor | `vendedor` | `usuarios.Usuario` (vía `facturasitems.IDUsuarioVendedor`) | Alta — verificado |
| I · Tipo de Factura | `tipo_factura` | **Ninguna columna decodificada — GAP, ver §5** | — |
| J · Nº Factura | `nro_factura` | `LPAD(talonarios.NroSucursal,5,'0') + '-' + LPAD(facturas.Numero,8,'0')` | Alta — el prefijo `NroSucursal` calza exacto con los prefijos de pérdida definitiva ya sembrados en `seed.py` (`00007`, `05007` ⇔ `NroSucursal` 7 y 5007, confirmado por conteo real) |
| N · Cantidad | `cantidad` | `facturasitems.Cantidad` | Alta |
| P · Precio de Venta | `precio_venta` | `facturasitems.ImportePrecio1` (slot de pesos, ya totalizado por línea — no requiere multiplicar por `cantidad`) | **Corregida 2026-08-14, dos vueltas.** 1ª vuelta (incompleta): se creyó que `ImportePrecioVenta1` era unitario y que `× Cantidad` daba el total, validado contra la factura `00003-00127258` (`HP664XLKCOMP-PRM`) — coincidía por casualidad, porque ahí `ImportePrecioVenta1 == ImporteUnitario1`. 2ª vuelta (la vigente): Maxx detectó otra factura real, `00003-00127272` (cliente Polgraf SH, SKU `WFSLV-15%-152X30`, cantidad 8), donde el importe correcto confirmado es $1.336.800,00 — `ImportePrecioVenta1 × Cantidad` da $1.417.248 (mal), mientras que `ImporteUnitario1 × Cantidad` = `ImportePrecio1` = $1.336.800,00 (correcto). Confirmado además sobre 100 líneas reales con `ImportePrecioVenta1 <> ImporteUnitario1`: en el 100% de los casos `ImportePrecio1 == ImporteUnitario1 × Cantidad`, nunca `ImportePrecioVenta1 × Cantidad`. `ImportePrecioVenta1` es otro campo (parece un precio de referencia/sugerido, no el efectivamente facturado) y ya no se usa. **Signo de Nota de Crédito resuelto el mismo día** (ver §5): `facturas.Tipo=1` invierte el signo de `cantidad`/`precio_venta`; `facturas.Tipo=2` (Nota de Débito) se excluye por completo. |
| V · TC | `tc` | `monedacotizaciones.CotMoneda2` (vía `facturasitems.IDCotizacionMoneda`) | Alta — verificado contra cotización real del día |

Todo lo demás en `VentaTactica` (`costo_lista`, `iva`, `margen_real`, etc.)
es **CALCULADO** por el motor, no viene de esta ingesta (lo resuelven
`CostoVigenteProvider`/`IvaProvider` y `RentabilidadTacticaCalculator`, ya
implementados).

---

## 4. `nro_factura` y prefijos de pérdida definitiva — confirmado

Conteo real de facturas por `(NroSucursal, talonarios.Tipo)`:

```
NroSucursal=7:    Tipo 7 (n=1), Tipo 8 (n=18), Tipo 10 (n=4)
NroSucursal=5007: Tipo 23 (n=1)
```

Ambos sucursales (7 y 5007) coinciden exactamente con
`PREFIJOS_PERDIDA_DEFINITIVA = ["00007", "05007"]` ya sembrado en
`backend/rentabilidad/seed.py` — **sin tocar ese seed**, esto confirma que
`nro_factura` se arma con `NroSucursal` como prefijo. Además, en `NroSucursal=7`
aparecen líneas con `Codigo='PROMOS-PM21'`, que coincide exactamente con el
patrón `PROMOS-*` de `SkuAuxiliar` también ya sembrado — otra confirmación
cruzada independiente.

---

## 5. Régimen de comprobante — REGLA OFICIAL (Maxx, 2026-07-31)

**Esto reemplaza cualquier hipótesis estadística previa sobre
`talonarios.Tipo`.** No es una inferencia derivada de la base — es la regla
de negocio tal cual la confirmó Maxx, y tiene prioridad absoluta sobre
cualquier patrón que "parezca" corresponderse en los datos.

### Pérdida definitiva

Comprobantes con prefijo de talonario **`00007`** o **`05007`** (ya sembrado
en `seed.py` como `PREFIJOS_PERDIDA_DEFINITIVA`, confirmado por conteo real
en §4). No recuperan absolutamente nada: ni costo, ni impuestos, ni IVA, ni
costo financiero. Prioridad absoluta sobre cualquier otra regla — se chequea
primero, siempre (ya implementado así en `resolver_regimen`, sin cambios).

### Cuenta 1 — Factura A, Factura B y Factura E Electrónica (y sus Notas de Crédito)

Mismo comportamiento exacto para las tres letras fiscales, siempre que sea
**Electrónica**:

- Descuenta IVA, Impuesto al cheque (1,2%), Ingresos Brutos (5%), costo del
  producto y Costo Financiero 1.
- La Nota de Crédito revierte exactamente lo mismo (misma fórmula,
  cantidades/importes ya vienen en negativo desde el origen — no hay lógica
  de reversa separada, es la fórmula de Cuenta 1 aplicada tal cual).

  **Corregido 2026-08-14 (mismo día, tercera vuelta):** el supuesto ("vienen
  en negativo desde el origen") era falso — se confirmó por SQL que
  `facturasitems` no tiene ninguna fila con `Cantidad < 0` en toda la tabla,
  ni casi ninguna con `ImportePrecio1 < 0` (2 filas, ambas de centavos por
  redondeo). El campo real que marca Nota de Crédito es **`facturas.Tipo`**
  (no `talonarios.Tipo`, que es otro campo, un enum interno de 26 valores
  sin decodificar) — es el mismo campo que alimenta el filtro "Tipo de
  Factura" del buscador de Táctica (desplegable de 3 opciones, confirmado
  por Maxx mirando la pantalla real: Factura, Nota de Crédito, Nota de
  Débito, en ese orden): `Tipo=0` Factura, `Tipo=1` Nota de Crédito,
  `Tipo=2` Nota de Débito. Verificado contra 5 facturas reales que Maxx
  confirmó como Nota de Crédito (distintas sucursales/letras/regímenes:
  `05001-19036035` CVE, `00003-00009815` CEA, `00003-00001128` CEB,
  `00004-00000069` CEE, `00007-00000001` CVA) — las 5 tienen `Tipo=1` sin
  excepción. Regla de negocio (Maxx): Nota de Débito se excluye por
  completo (`f.Tipo <> 2` en el `WHERE` de `_QUERY`), Nota de Crédito sí
  participa pero con `cantidad`/`precio_venta` invertidos en signo
  (`_fila_desde_row`), ya que el costo también se invierte río abajo al
  multiplicarse por `cantidad`.

Corresponde a `Regimen.CUENTA_1` — ya implementado en
`RentabilidadTacticaCalculator` sin cambios.

### Cuenta 2 — Factura E NO Electrónica (y su Nota de Crédito)

Tratamiento completamente distinto:

- Solo descuenta costo del producto y Costo Financiero 2.
- No descuenta IVA, Impuesto al cheque ni Ingresos Brutos.
- La Nota de Crédito revierte únicamente costo y Costo Financiero 2.

Corresponde a `Regimen.CUENTA_2` — ya implementado sin cambios.

**Identificación práctica de Cuenta 1 vs Cuenta 2** (criterios dados por
Maxx, en orden de confiabilidad a verificar contra la base):

1. La factura **no dice "Electrónica"** → Cuenta 2.
2. En la Razón Social / Empresa aparece el indicador **"2"** → Cuenta 2.
3. Normalmente pertenecen a talonarios de la **serie 0500x** → Cuenta 2.

**Verificado contra los 3 casos ya confirmados por Maxx**: la columna que
implementa el criterio 1 es `facturas.CAE` (Código de Autorización
Electrónica de AFIP), no `TipoEW` (que resultó ser prácticamente siempre 0
en toda la base — descartado como discriminante).

| Caso confirmado | Régimen | `CAE` observado |
|---|---|---|
| Sucursal 3, Tipo 38 (Factura A) | Cuenta 1 | 14 dígitos reales (ej. `86316189981185`) |
| Sucursal 3, Tipo 40 (NC A) | Cuenta 1 | 14 dígitos reales |
| Sucursal 5001, Tipo 23 (NC, sin electrónica) | Cuenta 2 | **`0`** en las 5 facturas revisadas |

**Regla de identificación implementada**: `facturas.CAE = 0` → Cuenta 2;
`facturas.CAE != 0` → Cuenta 1. Es un campo fiscal (AFIP no autoriza un CAE
real para comprobantes no electrónicos), no una inferencia estadística —
consistente con el criterio 1 que dio Maxx.

**Nota sobre las fórmulas ya implementadas**: dado que Cuenta 1 y Cuenta 2
solo dependen de "es electrónica o no" (nunca de la letra fiscal A/B/E, que
el propio Maxx confirma que es indistinguible en el cálculo), el adaptador
de ingesta **no necesita decodificar la letra fiscal exacta** para que el
motor calcule correctamente — solo necesita el booleano electrónica/no
electrónica más el prefijo de talonario. El string `tipo_factura` que se
persista en `VentaTactica.tipo_factura` (columna I, para paridad visual con
el Excel) puede construirse como un valor representativo ya sembrado en
`RegimenComprobante` (`"FEA"` para Cuenta 1, `"FAE"` para Cuenta 2, ajustando
a `"CEA"`/`"CVE"` si la línea es una Nota de Crédito vía signo de
`Cantidad`) — no hace falta sembrar nuevas filas en `regimen_comprobante`.

### PROMOS — descartado, no implementar

Maxx confirma: **toda la lógica histórica de PROMOP21/PROMOP10.5 y
similares queda descartada.** No implementar ninguna regla especial para
esos comprobantes — si aparecen registros históricos (como
`PROMOS-PM21`, visto en la muestra de sucursal 7 en §4), se conservan solo
por compatibilidad, no forman parte del proceso actual. Esto es consistente
con lo que ya documenta `calculators.py` (§7.6): sin rama especial para
`PROMOS-*`, se les aplica la fórmula general — y como esos SKU aparecen
bajo prefijo `00007` (pérdida definitiva), ya caen fuera del cálculo por esa
vía, sin necesitar lógica propia.

### Exclusiones — SKU auxiliares

Envíos, Fixture y conceptos auxiliares se excluyen igual que hoy en el
Excel — no forman parte de la rentabilidad del producto. Esto ya está
modelado en `SkuExcluido`/`MotivoExclusion` (§1.3 del diseño técnico); el
adaptador de ingesta debe marcar estas líneas como `excluido=True` con el
motivo correspondiente en vez de omitirlas (§1.2: "exclusión lógica, nunca
borrado físico").

---

## 7. Costo vigente e IVA — confirmado contra la base real (2026-08-14)

Hasta acá `CostoVigenteProvider`/`IvaProvider` leían de la hoja `Global`/
`Importacion Tactica` (una bajada manual del propio sistema). Con acceso SQL
confirmado, Maxx pidió leer directo de la base — el Sheet nunca fue la
fuente real, era una copia. `RENTABILIDAD_FUNCIONAL.md` §5.4/§5.6
actualizados en consecuencia.

**Costo vigente** — `productos` → `productosprecios`:

```
productos.Codigo (= SKU)
  → productos.RecID
  → productosprecios.IDProducto
  → productosprecios.Costo   (USD, NroMonedaCosto=2)
```

`productosprecios` tiene una fila por `NroLista` (distintas listas de
precio) — confirmado con un producto real que `Costo` es **idéntico en
las 6 listas** (2.72 en las 6), así que no hace falta elegir cuál: se
toma la de menor `NroLista` vía `OUTER APPLY ... ORDER BY NroLista` para
no depender de que exista una lista puntual. La cascada de dos columnas
S/R de la hoja `Global` no tiene equivalente acá — no hace falta, hay un
solo valor.

**IVA** — `productos` → `tasasiva`:

```
productos.Codigo (= SKU)
  → productos.IDTasaIVAVentas
  → tasasiva.RecID
  → tasasiva.Descripcion   ("IVA Debito 21%" / "IVA Debito 10.5%" / ...)
```

`tasasiva` completa (RecID reales omitidos, son binarios): Débito y
Crédito, cada uno en 21% / 10.5% / 0% / 27%; Crédito además tiene 5% y
2.5%. Solo "IVA Debito 21%"/"IVA Debito 10.5%" son válidos para el motor
(§5.4) — el resto cae en "no reconocido", igual que ya hacía el código
contra la hoja.

Query combinada (implementada en `adapters.py`,
`_QUERY_CATALOGO_COSTO_IVA`):

```sql
SELECT
    p.Codigo AS sku,
    costo_lista.Costo AS costo,
    ti.Descripcion AS iva_descripcion
FROM productos p
OUTER APPLY (
    SELECT TOP 1 pp.Costo
    FROM productosprecios pp
    WHERE pp.IDProducto = p.RecID
    ORDER BY pp.NroLista
) costo_lista
LEFT JOIN tasasiva ti ON ti.RecID = p.IDTasaIVAVentas
WHERE p.Codigo IS NOT NULL AND p.Codigo <> ''
```

Validado en vivo (2026-08-14): 277 líneas reales del 12/08/2026, 0
`config_faltante`, márgenes calculados correctamente sin ninguna
dependencia de Sheets.

**Tablas relacionadas, vistas pero no usadas todavía** (relevamiento del
mismo día, quedan documentadas por si hacen falta a futuro):
`productosimpuestos` (relación producto↔impuesto, tipo genérico, no se
usó porque `productos.IDTasaIVAVentas` ya resuelve directo), `productosstock`
/`vw_productosstock_readable` (stock, `Peso`/`Ancho`/`Largo`/`Profundidad`
por producto — vino todo `NULL` para los SKUs probados, no sirvió para la
investigación de sobre-volumen de Mercado Libre Full de esa sesión),
`productosproveedores` (precio de compra por proveedor, no el costo
vigente que usa el motor), `productosstockmovimientos` (historial de
movimientos de stock con `ImporteCosto1..6` por movimiento — podría ser
la fuente de un costo histórico real si algún día hace falta reconstruir
el costo vigente de un período pasado, no investigado en profundidad).

## 8. Estado

1. ~~Verificar columna SQL de "Electrónica"~~ — resuelto en §5 (`facturas.CAE`).
2. ~~Escribir el adaptador SQL de solo lectura~~ — **hecho**:
   `backend/rentabilidad/ingesta_tactica.py` (`TacticaSqlAdapter`), con tests
   de fixture en `tests/test_ingesta_tactica.py` (sin red) y validado además
   en vivo contra el servidor real: 60 líneas del 31/07/2026, 59 `FEA` + 1
   `FAE` — y esa única `FAE` es exactamente la factura `05001-19036022` que
   ya habíamos confirmado manualmente como Cuenta 2 en §5. Coincide perfecto.
3. ~~Costo vigente e IVA desde Sheets~~ — resuelto en §7: ahora leen SQL
   directo (`productosprecios.Costo`, `tasasiva.Descripcion`), sin
   dependencia de `Global`/`Importacion Tactica`.
4. Pendiente, no bloqueante: variables de entorno
   `RENT_TACTICA_SQL_SERVER/USER/PASSWORD/DATABASE` en Railway para
   producción (por ahora solo probadas localmente, `backend/.env`); columna
   `Familia` si se termina necesitando (no es un campo de `VentaTactica`
   hoy); la etapa de ingesta/persistencia real hacia la tabla
   `venta_tactica` (asignar `periodo`, chequear `SkuExcluido`) — el
   adaptador de este documento solo resuelve la lectura, no persiste.
