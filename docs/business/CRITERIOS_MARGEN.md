# CRITERIOS DE MARGEN — Fuente única

> **Regla madre:** todos los módulos del ERP calculan el margen igual. Un solo criterio, un
> solo número por concepto. Si un módulo difiere de este documento, está mal y se corrige
> contra este documento (no al revés).
>
> El cálculo vive en el ERP (código / config en DB), no en planillas externas. La planilla de
> Matías es donde él trabaja sus precios y debe amoldarse a estos mismos criterios, pero NO es
> la fuente del cálculo del motor.

---

## 1. Base del margen %
- Margen % = **rentabilidad / precio SIN IVA × 100**.
- Siempre sobre **neto (sin IVA)**.
- Nunca sobre el precio con IVA, nunca sobre "neto de cargos".

## 2. Comisión ML e impuestos
- **Comisión ML: 15,5% único** por ahora.
  - *Futuro (no ahora):* comisión real por categoría de ML, matcheando cada SKU con el Excel
    de publicaciones de ML, que trae la categoría real por publicación.
- **IIBB: 5%, sobre el precio SIN IVA.**
- **Imp. cheque: 1,2%, sobre el precio CON IVA.**
- Los dos impuestos van **SEPARADOS, cada uno sobre su base distinta.**
  - Prohibido unificarlos en un solo porcentaje sobre un solo lado. Ese es el error del
    **6,5%** de Ayala Core (sumaba IIBB + imp. cheque y los descontaba juntos de un solo lado).

## 3. Cargos reales vs. estimados (comisión, envío, cuotas)
- **Rentabilidad real (lo ya vendido):** usar el cargo REAL que trae Ecom (comisión, envío,
  cuotas tal como vienen; son números puestos, no fórmula).
  - **ML y WooCommerce:** dato confiable (Woo trae bien el descuento de MP).
  - **Frávega / OnCity / Megatone:** Ecom NO siempre los trae exactos (ni comisión ni envío).
    Es el único camino hoy, pero es aproximado.
  - *Futuro (en carpeta):* conectar las APIs de los marketplaces para traer el cargo real de
    cada uno y reemplazar el dato impreciso de Ecom.
- **Motor (proyección):** estima comisión = **precio CON IVA × 15,5%** (para que matchee con
  cómo ML la cobra realmente).

## 4. Impuesto al cheque
- Entra **SIEMPRE, en todos los módulos**, incluido el motor y Ayala Core.
- 1,2% sobre el precio con IVA.
- *Corregir Ayala Core:* hoy no lo resta por separado (está dentro del 6,5% mal unificado).

## 5. Cuotas
- Costo de cuotas: viene de Ecom en lo real y está bien (Ecom a veces trae el %).
  Marketplaces pendientes de conectar al 100%.
- **NO existe plan de 18 cuotas.** Eliminarlo de los cálculos (sacarlo de Competidores).

## 6. Envío
- **Real para lo vendido** (viene de Ecom, número puesto).
- **Motor estima** con lo configurado hoy: **umbral envío gratis $33.000 / costo envío
  $8.500**, hasta que haya pesos y dimensiones cargados.
- *Futuro:* envío real por publicación cuando se carguen pesos/dimensiones del depósito.

## 7. Costo y Tipo de Cambio (una sola fuente cada uno)
- **Costo del producto:**
  - La verdad es **Táctica** (correcto en ~98% de los SKU).
  - Táctica es frágil: vive en el servidor de la oficina; si se cae VPN/Tailscale, corta todo.
  - **Ecom es el respaldo estable y 98% confiable** (coincide con Táctica).
  - **Una sola fuente de costo para todos los módulos.** Competidores deja de usar la planilla
    PM por su lado.
- **Tipo de cambio:**
  - **BNA dólar billete venta del día, siempre.**
  - **Fallback: el último TC guardado.** Nunca 1, nunca un valor fijo que quede viejo.

## 8. Oferta Tradicional y piso de margen
- **Oferta Tradicional:** no es un descuento real, es para posicionar / ganar visibilidad en
  ML. El objetivo es que el precio final quede **igual al precio del PM**, arrancando por
  **25%** como referencia; se ajusta el % si ML no lo permite por credibilidad. La regla es
  "el % que deje el precio final en el del PM", no 25% fijo.
- **Piso de margen:** el ideal es no vender a pérdida, pero **NO es una regla dura.**
  - Se vende a pérdida **conscientemente** y con frecuencia por razones válidas: mercadería
    vieja, falta de costos, sacarse stock de encima, pruebas.
  - El sistema **muestra / alerta** el margen real pero **NO bloquea**. La decisión es humana,
    la toma quien lo permite o decide.
- *Futuro (no ahora, no mezclar):* distinguir en los reportes de n8n las ofertas especiales /
  campañas de ML (con aporte de ML, o por pedido del PM para rotar mercadería) para que NO
  salten como error en los mails de Maca/Nati — esas ventas por debajo son a propósito.

## 9. Qué motor manda
- **Motor oficial de cálculo: `rentabilidad/motor_precios.py`.** Los criterios de este
  documento viven ahí (código / config en DB). El cálculo vive en el ERP, no en planillas.
- **Ayala Core queda apartado A PROPÓSITO** (por diseño, no por error de duplicación): tiene
  el motor definido con Matías, que calcula por **costo de envío real** y a su manera para que
  puedan vender tanto los distribuidores como nosotros en ML. Unificarlo es el **paso
  siguiente**, no ahora.
- **Corrección inmediata a Ayala Core:** separar IIBB (5% s/ sin IVA) e imp. cheque (1,2% s/
  con IVA). Sacar el 6,5% unificado. (Solo los impuestos — no fusionar con el motor oficial
  todavía.)
- **Plan:** corregir impuestos en ambos → comprobar que motor oficial y Ayala Core den los
  MISMOS números → recién después reformular / unificar.

---

## ⚠️ Notas críticas de sincronización
- El motor de cálculo vive en el **ERP (código)**. Corregir el código es suficiente para que
  el ERP calcule bien; no depende de ninguna planilla externa.
- La **planilla de Matías** (Google Sheet) es donde Matías trabaja sus precios y debe
  **amoldarse a estos mismos criterios**. La ajusta Matías a mano (no Code, que solo toca
  código). Es un paso aparte, en paralelo, para que todos trabajen con el mismo criterio.
- El árbitro de "cómo tiene que dar" es el **ERP de Maxx**, que divide los impuestos como
  define este documento.

---

## Los 7 lugares que hoy calculan distinto (a unificar contra este documento)
1. Dashboard — margen % sobre con IVA → pasar a sin IVA.
2. Rentabilidad — sobre neto (ok, es la referencia).
3. Ofertas ML — sobre neto.
4. Competidores — sobre neto menos cargos → pasar a sin IVA; dejar de usar planilla PM para
   costo; sacar plan de 18 cuotas.
5. Motor Ayala Core — corregir impuestos (sacar 6,5%, separar), sumar imp. cheque; queda
   apartado por lo demás.
6. Motor oficial `rentabilidad/motor_precios.py` — fuente única de criterios.
7. Fórmulas JS del frontend — que lean del motor, no constantes copiadas.

*(Confirmar la lista exacta con la auditoría — §3/§5.5 de AUDITORIA_ERP.md.)*
