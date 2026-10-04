# MÓDULO DE COMPETENCIA / ANÁLISIS — Especificación

> Spec de diseño del módulo unificado de análisis de competencia. Es el norte; se construye
> **por etapas**, no de una. Prerrequisito: los CRITERIOS_MARGEN tienen que estar aplicados
> primero (este módulo calcula con esos criterios para que los números cierren con el resto
> del ERP).

---

## Objetivo
Unificar en un solo módulo todo lo que hoy está disperso sobre competencia, para **decidir
rápido** sobre una categoría, un PM o un SKU — mirando histórico y precio reciente, con
filtros. La filosofía de siempre: el que procesa la información más rápido gana; el sistema
informa, el humano decide.

---

## Decisión de arquitectura: el precio "en vivo"
- ML devuelve **403 por API** en publicaciones ajenas. El precio de competidores NO se puede
  traer por la API desde Railway.
- El scraping (navegador) **no corre en Railway**. Vive en la PC de Maxx (como `ml_vendedor`).
- **Decisión tomada (versión "ahora"):**
  - El scraper corre **solo, programado** en la PC (Tareas de Windows), con **login guardado**
    (no lo pide cada vez). Actualiza el histórico a diario sin intervención.
  - El "en vivo" = el **último precio scrapeado** (máx. 1 día de atraso, suficiente para el
    90% de los casos).
  - **Descartado:** scrapear desde el celu / n8n (consume datos, frágil, inviable).
- **Futuro (no ahora):** botón "precio ahora mismo" por link, que dispare el scrapeo de ESE
  link en el momento. Requiere un agente corriendo en la PC. Se evalúa si el atraso de 1 día
  no alcanza para algún caso puntual.

---

## Qué unificar (hoy está fragmentado — hallazgos de la auditoría)
- **3 históricos que no se leen entre sí** → **un solo histórico**, en formato largo (una fila
  por lectura: link/SKU, fecha, precio).
- **2 modelos de link de competidor desconectados** (el viejo V-* + General + ML Competencia;
  el nuevo Referencias_Mercado) → **un solo registro de links**, con el SKU resuelto una vez
  (Referencias_Mercado como base).
- **4 lectores de precio distintos** → **un solo lector de precio por link.**
- La pantalla con **modo histórico** y **modo reciente**, con los **mismos filtros**.

---

## Secciones del módulo

### 1. Competencia ("el rey" — el más barato)
- Vistas: **por SKU** y **por categoría** (las dos ya existen hoy).
- Filtros: **vendedor/es** (cuadritos: todos / uno / varios), **categoría**, **buscador por
  SKU**.
- Por cada competidor: histórico de precios + último precio + indicador **subió / bajó**.
- **La categoría de cada competidor la define Maca a mano** en el Excel que trae los datos. El
  sistema NO debe auto-clasificar: respeta lo que viene del Excel (es tarea humana).

### 2. Distribuidores
- Misma lógica, pero son clientes que compran y deben **respetar los precios arreglados**.
- Filtro clave: **por PM asignado a cada distribuidor**.
  - Ej.: Verónica → American Computers; Matías → Tiendafonopel.
- También vistos **por SKU y por categoría**.
- Hoy son pocos; pensado para escalar a muchos distribuidores con muchos SKU de varios PM.
- Uso: en reuniones con distribuidores, mostrar que están mapeados y ver **quién respeta y
  quién no**.

### 3. El competidor particular (seguimiento directo)
- Un competidor puntual que Maxx sigue de cerca (le vendió y arreglaron precios).
- Vive en Análisis, pero **se asoma al lado del Motor Ayala**: al tocar/modificar un precio,
  ver si ese competidor lo cambió.

---

## Criterio transversal
Todo junto, pero **arrastrable / filtrable rápido**: ver todo, o una categoría, o un PM
(distribuidores), o un competidor (cuadritos), o un SKU (buscador) — en histórico o en
reciente. Información acotada en un solo lugar, para decidir rápido.

---

## Cálculo
Todo lo que muestre margen usa los **CRITERIOS_MARGEN** (sin IVA como base, 15,5% comisión,
IIBB 5% s/ sin IVA, imp. cheque 1,2% s/ con IVA separados, TC BNA, costo única fuente). Para
que los números del módulo coincidan con el resto del ERP.

---

## Mejora al scraper (va con esto)
- `ml_vendedor` → correr **programado** en la PC (Tareas de Windows), no a mano.
- **Login guardado** (sesión persistida) para que no lo pida cada corrida.
- Nota: la versión del scraper que está en el repo (`/ml/vendedor/run`) es más pobre y NO
  corre en Railway (falta selenium + Chrome). La buena es la local (`ml_vendedor.py`), que
  hoy NO está versionada en el repo. Definir si se versiona.

---

## Plan de ataque por etapas (una por vez, no todo junto)
1. **Unificar la base de datos de competencia:** un solo registro de links
   (Referencias_Mercado) + un solo histórico en formato largo + un solo lector de precio.
2. **Automatizar el scraper** en la PC (programado + login guardado).
3. **La pantalla unificada** con filtros (vendedor/es, categoría, SKU) y modo histórico /
   reciente — sección Competencia.
4. **Sección Distribuidores** (filtro por PM asignado).
5. **El competidor particular asomándose al Motor Ayala.**
6. **(Futuro)** botón "precio ahora mismo" por link.

---

## Antes de construir — Code debe:
- Mapear qué piezas de competencia existen hoy y cuáles se reusan vs. se tiran (ya está en
  AUDITORIA_ERP.md §3).
- Confirmar si se reforma lo existente (recomendado) o se crea de cero.
- NO empezar hasta que CRITERIOS_MARGEN esté aplicado y los números cierren.
