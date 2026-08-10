# COMERCIAL_IMPLEMENTACION.md

## Diseño Técnico — Dominio Comercial · ERP Ayala

**Versión 0.1 — SOLO PLANTILLA. Ninguna sección desarrollada.**
**Documento subordinado a:** `business/COMERCIAL/01_COMERCIAL_FUNCIONAL.md`

---

## 0. Relación entre los documentos

Mismo criterio que rige entre `RENTABILIDAD_FUNCIONAL.md` y `RENTABILIDAD_IMPLEMENTACION.md`.

| | `01_COMERCIAL_FUNCIONAL.md` | Este documento |
|---|---|---|
| Contiene | Reglas de negocio, estados, validaciones, casos de aceptación | Modelo de datos, servicios, adaptadores, colas, persistencia |
| Autoridad | **Normativo.** Ninguna regla se cambia sin decisión funcional | Orientativo. Se puede reorganizar libremente |
| Ante conflicto | **Gana el funcional, siempre** | Cede |

**Regla:** si este documento impide reproducir una regla del funcional, **este documento está mal**. Se cambia este, no el otro.

**Y una segunda subordinación:** el dominio Comercial consume el margen que calcula Rentabilidad. Este documento **no puede** redefinir la cascada, agregar componentes ni cambiar una base imponible. Si Comercial necesita algo que la cascada no da, se reporta como pendiente de Rentabilidad.

**Este documento no se desarrolla hasta que Rentabilidad esté terminada** y su suite de regresión pase al centavo.

---

## Índice

### 1. Modelo de datos
1.1 Entidades del dominio y sus tablas · 1.2 Maestros, derivados y observados · 1.3 Campos de control transversales · 1.4 Tablas paramétricas · 1.5 Precisión numérica y monedas

### 2. Arquitectura de canales
2.1 Patrón de adaptador por canal · 2.2 Interfaz común derivada del contrato de canal · 2.3 Traducción a los contratos canónicos · 2.4 Registro de capacidades por canal · 2.5 Cómo se agrega un canal sin tocar el dominio

### 3. Motor de reglas de precio
3.1 Resolución de la regla aplicable · 3.2 Cálculo del Precio Objetivo · 3.3 Cálculo inverso del Precio de Exhibición · 3.4 Redondeos · 3.5 Integración con la cascada de Rentabilidad

### 4. Guardrails y overrides
4.1 Validador de guardrails · 4.2 Ciclo de vida de un override · 4.3 Vencimiento y retorno automático a la regla · 4.4 Reacción ante cambio de costo

### 5. Publicador saliente
5.1 Cola idempotente · 5.2 Prioridad entre tipos de cambio · 5.3 Reintentos con backoff · 5.4 Límites de tasa y ventanas · 5.5 Registro de llamadas

### 6. Receptor de eventos
6.1 Endpoint de webhooks · 6.2 Normalización a evento canónico · 6.3 Recuperación de notificaciones perdidas · 6.4 Fallback a polling

### 7. Reconciliador
7.1 Comparación entre Estado Deseado y Estado Observado · 7.2 Clasificación de divergencias · 7.3 Programación y cadencia · 7.4 Generación de excepciones

### 8. Máquina de estados del ciclo de campaña
8.1 Estados y transiciones · 8.2 Persistencia y reanudación desde el punto de corte · 8.3 Guardia de tiempo máximo fuera de campaña · 8.4 Simulación previa · 8.5 Reporte de resultado

### 9. Inventario y sincronización de stock
9.1 Cálculo de disponibilidad · 9.2 Asignación por canal · 9.3 Propagación a todas las publicaciones del mismo SKU · 9.4 Conciliación con el depósito del canal

### 10. Órdenes
10.1 Ingreso y normalización · 10.2 Mapeo a SKU y excepción bloqueante · 10.3 Reserva de stock · 10.4 Cálculo de rentabilidad preliminar

### 11. Inteligencia competitiva
11.1 Adquisición de datos · 11.2 Motor de detectores · 11.3 Almacenamiento histórico sin pisar datos · 11.4 Componentes que requieren navegador y por qué no corren en el servidor

### 12. Centro de excepciones
12.1 Modelo de excepción · 12.2 Severidad y bloqueo · 12.3 Bandeja y resolución

### 13. Agregaciones y dashboard
13.1 Vistas de agregación · 13.2 Trazabilidad de todo total · 13.3 Desglose por canal, línea y responsable

### 14. Modo sombra
14.1 Cómo se garantiza que nada se escriba · 14.2 Qué se registra igual

### 15. Suite de regresión
15.1 Casos de aceptación como test automatizado · 15.2 Criterios de tolerancia · 15.3 Puertas entre fases

### 16. Orden de implementación
Secuencia y dependencias entre componentes.

### 17. Prohibiciones técnicas
Lista explícita, cada una derivada de una regla del funcional o de un error real documentado.

---

## Nota sobre el patrón de adaptador

La decisión de arquitectura central de este documento es el **adaptador por canal**: el dominio habla un solo idioma —los contratos canónicos de `02_CONTRATO_DE_CANAL.md` §4— y cada canal tiene un traductor.

La prueba de que el patrón está bien implementado es simple: **agregar un canal nuevo no debe requerir modificar ni una línea del dominio.** Si hay que tocar el motor de precios, el reconciliador o el publicador para sumar Frávega, el adaptador está mal diseñado.
