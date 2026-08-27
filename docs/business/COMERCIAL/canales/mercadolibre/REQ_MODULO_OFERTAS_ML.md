# Requerimiento — Módulo de Ofertas ML (Ayala ERP)

> Documento para Claude Code. Textifica qué queremos construir. **No empezar a codear hasta completar la Fase 0 (auditoría) y reportar hallazgos.**

---

## 0. Contexto y regla de oro

Estamos sumando un **módulo de Ofertas** al ERP, apoyado en la sección de API de ML ya habilitada. El módulo gestiona **dos tipos de oferta**:

1. **Promociones nativas de ML** — campañas y descuentos por publicación que ofrece la plataforma.
2. **Descuentos propios** — precios rebajados que cargamos nosotros.

Corre sobre **las dos cuentas desde el arranque**: IT (`115764017`) y MT (`34801784`).

**Regla de oro:** no reinventar el cálculo de rentabilidad. Ya existe. Este módulo se **apoya** en el motor de rentabilidad existente, no lo duplica. Antes de construir nada, auditá lo que ya hay (Fase 0).

---

## 1. FASE 0 — Auditoría previa (hacer PRIMERO, no codear todavía)

Antes de escribir una línea, reconocé y reportá lo que ya existe. Hay **dos piezas** de rentabilidad a auditar:

### 1.1 Motor de rentabilidad sobre los Excel
- Es el que ya trabajamos: reglas de exclusión, IVA, CF1/CF2, prefijos de pérdida, etc. Documentado en `docs/business/RENTABILIDAD_FUNCIONAL.md`.
- Hoy tiene cargados **todos los descuentos** que asumimos al bajar renta **más** lo que descuenta la plataforma.
- **Verificá:** que el cálculo esté **completo y correcto** — que estén todos los descuentos que asumimos + todo lo que ML efectivamente cobra, sin que falte ninguno.

### 1.2 Panel de descuentos editable (dentro de "Competidores ML")
- Es una barra de parámetros **editable** que ya construimos, ubicada en el módulo **Competidores ML** del dashboard. Su calculadora (`compMargenAt()` en `docs/index.html`) es la que se reutiliza para Ofertas.
- **Aclaración importante de alcance:** este panel nació atado al **scraping de páginas de competencia**. Esa fuente de datos se reemplaza más adelante por otra tarea (3 links de competidor por SKU) — **eso NO es parte de este requerimiento**. Para Ofertas solo interesa reutilizar la **calculadora de descuentos**, independiente de la fuente de precios de competencia. No toques ni dependas del scraping.

### 1.2.b Valores reales de descuentos ML — actualizados 26/08/2026 (relevados en cuenta real + tarifas oficiales)

Estos son los valores CONFIRMADOS que debe usar la calculadora. Reemplazan cualquier valor viejo del panel:

**Comisión por venta (cargo por vender) — EDITABLE POR CATEGORÍA.** Varía por categoría (rango general 11,62%–17,75%). Tóners confirmado en 15,5%. Las 15 categorías principales (77% de las publicaciones) llevan su comisión propia; el resto usa un valor general editable por defecto. La comisión debe ser **editable por categoría**, cada una con su porcentaje.

**Costo fijo por unidad vendida** — solo en productos de menos de $33.000, por tramos de precio (logística Flex / acuerdo / retiro):
- Hasta $15.999 → $1.255
- $16.000 a $23.999 → $2.500
- $24.000 a $33.000 → $3.030
- $33.000 o más → $0
- (Nota: con Full/correo/colecta el costo fijo se calcula por precio+medidas+peso; dejar la regla Flex como base y contemplar Full como caso aparte si se necesita.)

**Cuotas sin interés (% que se SUMA al cargo por vender):**
- 3 cuotas → 8,40%
- 6 cuotas → **12,30%** (RESUELVE la divergencia del REQ anterior: el valor real es 12,30%, confirmado en simulador + tabla oficial)
- 9 cuotas → 15,70%
- 12 cuotas → 19,20%
- **18 cuotas NO existe en ML Argentina hoy** — el máximo es 12. Eliminar el plan de 18 del panel.

**Costo de envío** — umbral de envío gratis: $33.000 (en productos de $33.000+ el vendedor absorbe el envío). Con descuento por reputación (la cuenta es MercadoLíder Platinum). Tabla oficial ya con descuento (0,5–1 kg): <$33.000 → $9.800 · $33.000–$49.999 → $7.000 · +$50.000 → $7.470.

**TC:** BNA automático (endpoint `/tc/bna` ya existente).

### 1.2.c Impuestos — TRATAMIENTO ESPECÍFICO DE ECOM (no confundir con las retenciones de ML)

Regla de negocio propia, distinta de lo que informa ML:
- El margen NO suma los impuestos como un descuento más. De los impuestos, se toman **solo dos** y se descuentan explícitamente:
  - **Imp. Cheque = 1,2%**
  - **IIBB = 5%**
- **El margen final se calcula sobre el precio de venta SIN IVA.** Es decir: primero se quita el IVA del precio, y sobre esa base neta se aplica todo lo demás.
- (Las retenciones que muestra ML, ~0,9%, son percepciones/anticipos de crédito fiscal que se recuperan — NO son costo puro y NO van en esta fórmula.)

### 1.3 Qué tenés que reportar al terminar la Fase 0
Un informe corto con:
1. **Qué encontraste** — ubicación en el repo de ambas piezas (archivos, funciones), y qué hace cada una.
2. **Validación** — ¿el cálculo de rentabilidad está completo y correcto? ¿Coinciden los descuentos del motor (1.1) con los parámetros del panel editable (1.2), o hay divergencias? Marcá cualquier descuento que falte o esté duplicado.
3. **Aptitud para ofertas** — ¿sirve tal cual para calcular el **margen de una oferta** (dado un precio con descuento, cuánto margen real queda)? ¿O hay que modificar/conectar algo? Sé concreto: qué función se reutiliza, qué le falta.
4. **Recomendación** — reutilizar tal cual / extender / refactorizar. Con el motivo.

**No avances a la Fase 1 hasta que revisemos juntos este informe.**

---

## 2. FASE 1 — Lectura y visibilidad (primer objetivo del módulo)

### 2.0 Fórmula canónica de margen de una oferta (usar EXACTAMENTE esto)

Dado un **precio de oferta** (el precio con descuento que va a tener la publicación):

```
base_sin_iva   = precio_oferta / (1 + iva_pct)          # IVA se quita primero; margen se mide sobre base sin IVA
comision       = precio_oferta × comision_categoria_pct  # editable por categoría
costo_fijo     = tramo_por_precio(precio_oferta)         # 1255 / 2500 / 3030 / 0 (solo <33k, regla Flex)
cuotas         = precio_oferta × cuotas_pct              # 0 si no ofrece cuotas; 8,4 / 12,3 / 15,7 / 19,2%
envio          = regla_envio(precio_oferta)              # 0 si <33k; si aplica, tabla con descuento reputación
imp_cheque     = precio_oferta × 1,2%                    # sobre el precio CON IVA (bruto)
iibb           = base_sin_iva × 5%                       # corregido 2026-08-27: sobre el precio SIN IVA (neto), no sobre precio_oferta
costo_producto = costo_sin_iva_desde_TACTICA × TC        # costo/IVA SIEMPRE desde Táctica (fuente oficial), NO del PM Sheet

margen_$   = base_sin_iva − comision − costo_fijo − cuotas − envio − imp_cheque − iibb − costo_producto
margen_%   = margen_$ / base_sin_iva
```

Reglas firmes:
- **El margen se calcula sobre el precio de venta SIN IVA** (base_sin_iva), no sobre el precio final.
- **Impuestos: solo Imp. Cheque (1,2%) e IIBB (5%)** entran como descuento. Nada más de impuestos.
- **Costo e IVA del producto salen de Táctica** (fuente oficial), nunca del PM Sheet, para que el margen no dependa de que alguien mantenga la planilla al día.
- Cada parámetro (comisión por categoría, cuotas, envío, costo fijo, imp. cheque, IIBB, TC) es **editable con on/off**.
- **RECÁLCULO INSTANTÁNEO:** cuando el usuario modifica a mano cualquier descuento o porcentaje, TODOS los márgenes de la vista se recalculan al instante, sin recargar ni apretar un botón. Es requisito, no opcional.

### 2.1 Alcance de la lectura

Objetivo principal y punto de partida: **ver todas las ofertas/promos activas en un solo lugar**, cruzando las dos cuentas.

- Traer desde la API de ML las promociones/campañas activas y las publicaciones en oferta de **IT y MT** (ofertas propias, campañas mías, y campañas de ML en las que participo).
- Sumar los **descuentos propios** que cargamos por fuera de ML.
- Vista unificada por publicación / SKU: precio normal, precio con oferta, % de descuento, tipo de oferta (promo ML vs propia vs campaña ML), cuenta (IT/MT), vigencia.
- **Margen real de cada oferta** con la fórmula canónica de arriba.

Entregable de fase: un dashboard de ofertas de solo lectura, con el margen real visible por oferta y recálculo instantáneo al tocar cualquier parámetro.

---

## 3. FASE 2 — Detección y alertas

- **Detectar SKUs que deberían estar en oferta y no están** (ej. alta rotación, con stock, sin promo activa) y viceversa.
- **Alertar ofertas que pierden plata** — margen real por debajo de un umbral configurable (usando el motor de Fase 0).
- Priorización por impacto (facturación del SKU × margen en riesgo).

---

## 4. FASE 3 — Escritura (crear/editar ofertas desde el ERP) · GATEADA

> **Importante — gate de escritura.** El objetivo final es **leer + escribir**: crear y editar ofertas desde el ERP. Pero la escritura a canales está **bloqueada por el gate de `docs/canales/mercadolibre/00_LEEME.md` §5** hasta que Rentabilidad cierre. Como esta fase además depende del motor de rentabilidad validado, el orden natural es:
> - Fases 1 y 2 (lectura, cálculo, alertas): **desbloqueadas ahora**.
> - Fase 3 (escritura a ML): **detrás del gate**, se construye recién cuando Rentabilidad esté cerrado y el gate lo permita.

Alcance cuando se habilite (gestión completa de ofertas desde el ERP):
- **Dejar de participar** en una oferta/campaña, y **volver a participar**.
- **Modificar el precio** de una oferta.
- Crear / dar de baja ofertas (promo ML y descuento propio) sobre ambas cuentas.
- Antes de confirmar cualquier cambio, mostrar el **margen real resultante** (fórmula canónica §2.0) y **advertir o bloquear** si el margen cae bajo el umbral configurable. El usuario ve, en el momento, qué margen le va a quedar con la modificación antes de aplicarla.
- Registro de cambios (quién, cuándo, precio anterior → nuevo, margen anterior → nuevo).

---

## 5. Cómo trabajar este documento

- La auditoría de **Fase 0 ya se hizo** (informe recibido). Hallazgos clave incorporados: reutilizar `compMargenAt()` (extender, no reescribir), portarla de `docs/index.html` al backend, y tomar costo/IVA desde Táctica.
- Verificá en developers/API/MCP y en los MD de `canales/mercadolibre/` todo lo necesario para traer las ofertas activas (propias, campañas mías y campañas de ML) de ambas cuentas.
- Construí Fases 1 y 2 (lectura, cálculo con la fórmula canónica §2.0, alertas). No toques la escritura (Fase 3) hasta que el gate de §5 del LEEME lo permita.
- Respetá la arquitectura y los contratos de datos canónicos ya definidos en el ERP.

## 6. Apéndice — Comisión por categoría (tabla a completar)

La comisión es **editable por categoría**. Las 15 categorías principales (77% de las 6.188 publicaciones) llevan su comisión propia; el resto usa un valor general editable. Valores confirmados y pendientes:

| # | Categoría | Publicaciones | Comisión |
|---|-----------|--------------:|----------|
| 1 | Tóners | 1.191 | 15,5% |
| 2 | Cartuchos de tinta | 1.032 | 15,5% |
| 3 | Rollos y planchas de vinilo | 689 | 14,3% |
| 4 | Tintas para impresoras | 390 | 15,5% |
| 5 | Papeles de librería y oficina | 319 | 15,0% |
| 6 | Filamentos para impresora 3D | 278 | 15,5% |
| 7 | Fundas para notebooks y netbooks | 201 | 15,5% |
| 8 | Auriculares | 114 | 15,5% |
| 9 | Estampadoras | 104 | 14,5% |
| 10 | Sistemas de tinta continuos | 91 | 15,5% |
| 11 | Cintas para impresora | 90 | 15,5% |
| 12 | Calculadoras | 76 | 15,0% |
| 13 | Gorros y sombreros | 72 | 15,5% |
| 14 | Tapas para encuadernación | 66 | 15,0% |
| 15 | Anilladoras | 66 | 15,0% |
| — | Resto (110 categorías) | 1.409 | valor general editable (sugerido 15,5%) |

Todas relevadas el 26/08/2026 en cuenta real + tarifas oficiales de ML. Comisión única por categoría (no hay clásica vs premium base; lo "premium" es el adicional por cuotas). Siguen siendo **editables por categoría** por si ML actualiza alguna.
