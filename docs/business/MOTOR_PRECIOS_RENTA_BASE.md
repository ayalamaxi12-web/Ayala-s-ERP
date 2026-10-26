# Motor de Precios: sobre qué se calcula la renta

## 1. Cómo funciona hoy (y desde cuándo)
El % de renta se aplica **sobre el precio de venta CON IVA**. No es un cambio reciente: es la fórmula del motor original.

- `AYALA_CORE.md` (A.3, «La fórmula exacta»): confirmada leyendo `Motor!B32:G32` de la planilla real el **2026-09-02**. El denominador es `1/(1+iva) − comisión/1,21 − IIBB/(1+iva) − financiero − renta_objetivo_pct …`: `renta_objetivo_pct` se resta **sin dividir por el IVA**, o sea es X % del precio con IVA. El motor reproduce el ejemplo congelado de A.3.1 al peso exacto.
- `backend/ayala_core.py`, `calcular_precio_condicion`: desde el primer commit del módulo (septiembre de 2026) resta `renta_pct / 100` tal cual. Después se agregaron el cheque (1,2 % sobre el precio con IVA, `CRITERIOS_MARGEN.md` §2) y el costo por orden (Bloque 2), y la renta no se tocó.
- Por eso la **rentabilidad real** (`CRITERIOS_MARGEN.md` §1: renta ÷ precio SIN IVA) y el % de renta objetivo del Motor **no están en la misma base**: 10 % del precio con IVA es 10 × IVA ≈ 11,05 % del precio sin IVA (con IVA 1,105). Verificado con el SKU de USD 13,5, IVA 1,105, TC 1550 (Frávega, costo por orden 149,12): con renta 10 % el precio de contado es 34.011 y la renta 3.401 = 10,00 % del precio con IVA y 11,05 % del sin IVA.

## 2. La cuenta paso a paso («Ver cuenta»)
Renta = Precio ÷ IVA − costo − comisión ÷ 1,21 − financiero − envío ÷ 1,21 − IIBB (5 % del precio sin IVA) − cheque (1,2 % del precio con IVA) − costo por orden.

Cada condición tiene un botón «Ver cuenta» que abre la cuenta en líneas, con el IVA de cada una: precio (con IVA), precio sin IVA, costo (sin IVA), comisión (% sobre el precio con IVA; en la cuenta se resta ÷ 1,21), financiero (% sobre el precio con IVA, se resta tal cual), envío (÷ 1,21), IIBB (sobre el precio sin IVA), cheque (sobre el precio con IVA), costo por orden (monto fijo) y renta, con su equivalente en las dos bases. Los encabezados de Comisión y Envío de la tabla dicen «(con IVA; en la cuenta se resta sin IVA)». La cuenta es solo para mostrar: sale del mismo precio que ya da el motor (`mercados.cuenta_paso_a_paso`, que cierra con `mercados.desglose` y con el precio que devuelve la fórmula).

## 3. «Renta sobre»: precio con IVA / precio sin IVA
Interruptor junto a los % de renta. **Por defecto «Precio con IVA», que es exactamente la cuenta de siempre** (el pedido ni lleva el parámetro). Con «Precio sin IVA» el término de renta del denominador pasa a `renta_pct/100 ÷ iva_factor` y la renta queda en X % del precio sin IVA; el precio baja respecto del de «con IVA» con el mismo número cargado. Al lado de la renta en pesos se ve el equivalente en la otra base. Se aplica a toda la pantalla del Motor (tabla, vista «Todos», «Detectar publicaciones» y «Comparar un solo MLA»).
Backend: parámetro `renta_base` (`con_iva`|`sin_iva`, 422 si es otro) en `/ayala-core/motor-lote`, `/ayala-core/sku/{sku}/motor` y `/ayala-core/publicaciones/run`; la respuesta trae `renta_base` y `cuentas` por condición.

## 4. Aviso de porcentajes raros
Si el % de renta de una condición visible se aparta más de 10 puntos de la mediana de las demás (o está fuera de 0–100) se marca el campo (`aria-invalid`) y aparece un aviso («Revisá la renta: 6 cuotas (32,279 %) se aparta mucho de las demás (mediana 10 %)»). Es solo un aviso: no bloquea ni cambia ningún precio. Con los valores de fábrica (32/32/30/28/26/24) no aparece.

## Paridad
Con «con IVA» todo da idéntico a `main`: 40 combinaciones (5 mercados × pack 1 y 3 × Full sí/no × envío estimado/manual) × 9 SKU piloto, precios, precios por unidad y desglose, 0 diferencias; y 96 combinaciones de la fórmula de Mercado Libre contra `main`.
