# 00 — LEEME PRIMERO

## Kit de construcción — Ayala ERP

Esta carpeta contiene todo lo necesario para construir el ERP sin improvisar arquitectura ni inventar reglas de negocio. Leer este archivo completo **antes** de escribir código.

---

## 1. Qué es este proyecto

Un ERP propio para un distribuidor de electrónica en Argentina que vende por dos cuentas de Mercado Libre Argentina, tienda propia WooCommerce, Frávega y OnCity.

**Objetivo declarado:** dejar de entrar al sitio de Mercado Libre para trabajar.

**El corazón del sistema es el motor de precios y rentabilidad.** Todo lo demás se construye alrededor.

---

## 2. Orden de lectura

| # | Archivo | Qué contiene | Autoridad |
|---|---|---|---|
| 1 | `00_LEEME_PRIMERO.md` | Este archivo | Orientación |
| 2 | `01_TRASPASO_ERP.md` | Contexto de negocio, sistemas actuales, impuestos, cascada, fronteras, anti-patrones | **Normativo** |
| 3 | `02_RENTABILIDAD_FUNCIONAL.md` | Especificación funcional del módulo de Rentabilidad | **Normativo** |
| 4 | `03_RENTABILIDAD_IMPLEMENTACION.md` | Diseño técnico del módulo de Rentabilidad | Subordinado a 02 |
| 5 | `04_MAPA_API_MERCADOLIBRE.md` | Mapa de la API: qué endpoint resuelve qué necesidad | Referencia |
| 6 | `05_MCP_MERCADOLIBRE.md` | Cómo consultar la documentación oficial de ML | Obligatorio |
| 7 | `Motor_Pricing_Componentes.xlsx` | Tabla de componentes de la cascada, cargable como configuración inicial | **Normativo** |

**Jerarquía ante conflicto:** `02_RENTABILIDAD_FUNCIONAL.md` > `01_TRASPASO_ERP.md` > todo lo demás. Si dos archivos se contradicen, gana el de mayor autoridad y hay que reportar la contradicción, no resolverla por criterio propio.

---

## 3. Reglas de oro

**Primero se replica, después se mejora.** El sistema vigente son planillas de Google Sheets con errores conocidos y documentados. El ERP tiene que reproducir los números correctos, no los números actuales — y la diferencia entre ambos está especificada. Ninguna regla se "mejora" sin decisión funcional explícita.

**Lógica configurable, no código.** Toda regla de negocio —impuestos, comisiones, márgenes, redondeos, reglas de precio— es un registro editable en base de datos. Agregar un impuesto nuevo nunca debe requerir un despliegue.

**Un dato tiene un solo dueño.** Todo dato es maestro, derivado u observado. Los derivados no se editan jamás.

**El canal es un espejo, no una fuente.** Ante divergencia entre lo que calcula el ERP y lo que muestra Mercado Libre, se genera una **excepción**. Nunca se corrige el dato del ERP para que coincida con el canal.

**Toda excepción vence.** No existe el override indefinido.

**El sistema debe poder correr en modo sombra:** calcular todo sin escribir nada en ningún canal.

**Ante duda no resuelta: marcar como pendiente, no inventar.** Un hueco declarado es infinitamente mejor que un supuesto silencioso.

---

## 4. Mandato de documentación — no negociable

**Ninguna integración con Mercado Libre se implementa de memoria.**

Antes de escribir código que toque la API:

1. Consultar el MCP oficial de documentación (ver `05_MCP_MERCADOLIBRE.md`).
2. Citar la ruta de documentación en el commit o en el comentario del módulo.
3. Si la documentación no responde la duda, verificar contra usuario de prueba y guardar la respuesta real como **contrato verificado con fecha**.

**Nunca asumir comportamiento de un endpoint.** El conocimiento de entrenamiento sobre la API de ML puede estar desactualizado; la documentación en vivo no.

---

## 5. Stack

| Capa | Tecnología |
|---|---|
| Backend | Python + FastAPI |
| Frontend | JavaScript |
| Persistencia | A definir. Hoy el sistema vigente usa Google Sheets; el ERP debe usar base de datos propia |
| Despliegue | Railway (backend), GitHub Pages (frontend) |

**Restricción conocida:** Selenium y Chrome no corren en el tier gratuito de Railway. Todo scraping que dependa de navegador se ejecuta localmente y sube resultados, no se hostea.

---

## 6. Contexto que hay que tener presente

**Los Product Managers comisionan sobre el margen.** El margen no es un indicador de gestión: es base de cálculo de remuneración. Eso obliga a reproducibilidad histórica —poder reconstruir el cálculo de un mes cerrado con los costos, tipo de cambio y alícuotas que regían entonces— y a un momento de congelamiento mensual.

**Táctica y Ecom son transitorios.** Son los sistemas de gestión de hoy, no la arquitectura objetivo. **No construir integraciones bidireccionales con ninguno de los dos**: solo importadores, tratados como deuda técnica con fecha de vencimiento.

**Hay una capa intermedia de nueve planillas de Google Sheets** entre los sistemas fuente y los usuarios. Esa capa es el enemigo, no un componente a integrar. El objetivo de la primera fase es matarla, empezando por el maestro de costos y el tipo de cambio.

**Permisos y multiusuario están diferidos por decisión.** Pero el concepto de **actor** y la **auditoría** no: cada evento registra quién lo hizo, aunque hoy ese quién sea siempre el mismo. Retro-encajar autoría cuando ya hay dos años de historial es imposible, y sobre ese historial se calculan comisiones.

**Brasil está fuera de alcance.** El modelo de datos debe quedar preparado para multi-país, pero no se implementa.

---

## 7. Orden de construcción

| Fase | Contenido | Riesgo |
|---|---|---|
| 0 | Plataforma: eventos, auditoría con actor, colas idempotentes | Bajo |
| 1 | Maestros: costos propios con vigencias, tipo de cambio con histórico, alícuotas por SKU | Bajo |
| 2 | Motor de cascada configurable + **Reporte de Divergencia** | Bajo |
| 3 | Lectura del canal: importar publicaciones, mapear SKU, reconciliar | Bajo |
| 4 | Escritura de precios + guardrails + overrides | Alto |
| 5 | Motor de ofertas y ciclo de campaña | Alto |
| 6 | Stock e inventario | Alto |
| 7+ | Órdenes · envíos y facturación · postventa · conciliación financiera · inteligencia | Medio |

**La Fase 2 es la puerta.** El motor corre en modo sombra y produce el Reporte de Divergencia: por SKU, el margen que muestra la planilla, el margen real recalculado, el desvío en puntos, un flag de "cruza a negativo" y qué componente lo explica.

Ese reporte es a la vez el entregable de negocio y la prueba de que el motor calcula bien. **No se avanza a la Fase 3 sin que la suite de regresión de `02_RENTABILIDAD_FUNCIONAL.md` pase al centavo.**

---

## 8. Pendientes que bloquean partes específicas

No bloquean el arranque. Sí bloquean los módulos indicados.

| Pendiente | Bloquea | Quién resuelve |
|---|---|---|
| Tres verificaciones contra el libro de rentabilidad (§16 de `02`) | Congelar la especificación de Rentabilidad | Relevamiento |
| Régimen del comprobante MLA | Cálculo de esas líneas | Funcional |
| Alícuotas reales de IIBB, porción computable del impuesto al cheque, orden del impuesto interno | Valores de la cascada, **no su estructura** | Contador |
| Quién es dueño del stock físico | Fase 6 | Interno |
| Qué es "Importacion Gaona" | Modelo de inventario | Interno |
| Restricciones de ML para modificar precio dentro de campaña | Fase 5 | Verificar vía MCP |

---

## 9. Qué NO construir

- Integraciones bidireccionales con Táctica o Ecom
- Brasil
- Pantallas de administración de usuarios, roles o matrices de acceso
- Lógica basada en colores o formato de celda
- Reglas propias en los reportes: los reportes son agregaciones puras
- Cualquier corrección de las observaciones documentadas
- Un módulo separado de Inteligencia Competitiva: está absorbido dentro del CGCC como su capa de detección
