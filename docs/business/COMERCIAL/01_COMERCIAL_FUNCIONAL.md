# 01 — COMERCIAL FUNCIONAL

## Especificación Funcional — Dominio Comercial · ERP Ayala

**Versión 0.1 — ÍNDICE. Ninguna sección desarrollada.**
**Estado: estructura aprobada, contenido pendiente.**

> **Cómo se completa este documento.** Sección por sección, en el orden del índice. Cada sección se desarrolla solo cuando hay evidencia real del negocio detrás — planillas, capturas del panel, documentación del canal, o una decisión funcional explícita. **Ninguna sección se completa por criterio propio ni por buenas prácticas.**
>
> Mientras una sección esté vacía, dice `PENDIENTE` y qué evidencia necesita. Un hueco declarado es mejor que un supuesto silencioso.
>
> **Regla de oro heredada:** primero se replica, después se mejora.

---

## Índice

### Parte I — Marco

**1. Propósito y regla de oro**
1.1 Qué define este documento · 1.2 Qué no define · 1.3 Criterio único de aceptación

**2. Alcance**
2.1 Qué entra en el dominio Comercial · 2.2 Qué queda en Rentabilidad · 2.3 Qué queda fuera del ERP · 2.4 Canales en alcance y canales diferidos

**3. Glosario**
Términos exactos a usar en todo el dominio. Toda ambigüedad de vocabulario se resuelve acá.

**4. Modelo conceptual**
4.1 Entidades del dominio · 4.2 Relaciones · 4.3 Qué es maestro, qué es derivado y qué es observado · 4.4 Estado Deseado contra Estado Observado

**5. Principios del dominio**
Reglas que atraviesan todas las secciones y no se repiten en cada una.

---

### Parte II — Producto y publicación

**6. Ciclo de vida de una publicación**
6.1 Alta · 6.2 Estados y transiciones · 6.3 Matriz de canal: qué publicaciones debe tener cada SKU · 6.4 Pausado, reactivación y cierre · 6.5 Publicaciones huérfanas y fantasma

**7. Contenido de la publicación**
7.1 Título, descripción y atributos · 7.2 Imágenes · 7.3 Variaciones · 7.4 Categoría y ficha técnica · 7.5 Calidad de la publicación

**8. Identificación y mapeo**
8.1 SKU propio como clave · 8.2 Mapeo entre SKU y publicación por canal · 8.3 Qué hacer cuando una publicación no mapea a ningún SKU

---

### Parte III — Precio

**9. Precio base y reglas de precio**
9.1 Precio base por mercado · 9.2 Tipos de regla de precio · 9.3 Asignación de regla por publicación · 9.4 Redondeos y terminaciones comerciales

**10. Precio Objetivo y Precio de Exhibición**
10.1 Derivación del Precio Objetivo · 10.2 Cálculo inverso del Precio de Exhibición · 10.3 Ratio máximo de inflación

**11. Guardrails**
11.1 Piso de margen global y por línea · 11.2 Variación máxima por cambio · 11.3 Precio mínimo absoluto · 11.4 Comportamiento ante violación

**12. Overrides**
12.1 Alta de un precio manual · 12.2 Motivo y vencimiento obligatorios · 12.3 Aviso previo y retorno automático a la regla · 12.4 Monitoreo ante cambio de costo · 12.5 Indicador de salud: porcentaje fuera de regla · 12.6 Panel de excepciones vigentes

**13. Propagación de un cambio de costo**
13.1 Recálculo de precios sugeridos · 13.2 Publicaciones con regla contra publicaciones con override · 13.3 Decisión humana antes de publicar

---

### Parte IV — Competencia

**14. Catálogo y Buy Box**
14.1 Publicaciones de catálogo contra tradicionales · 14.2 Estado competitivo · 14.3 Precio para ganar · 14.4 Palancas no económicas · 14.5 Piso de margen aplicado a la competencia

**15. Inteligencia competitiva**
15.1 Vendedores monitoreados · 15.2 Monitoreo de cambios de competidores · 15.3 Detección de publicidad por keyword · 15.4 Detección de eventos de plataforma · 15.5 Actores desconocidos y su clasificación

**16. Posicionamiento y exposición**
16.1 Tipo de publicación y su efecto · 16.2 Señales de pérdida de exposición · 16.3 Reputación y su impacto comercial

---

### Parte V — Stock

**17. Disponibilidad y asignación**
17.1 Stock físico contra stock a exponer · 17.2 Reglas de asignación por canal · 17.3 Reserva y liberación

**18. Stock en depósito del canal**
18.1 Stock en Fulfillment · 18.2 Conciliación contra depósito propio · 18.3 Stock no disponible y sus causas · 18.4 Multiplicadores de packs

**19. Sincronización de stock**
19.1 Prioridad sobre otros cambios · 19.2 Propagación a todas las publicaciones del mismo SKU · 19.3 Prevención de sobreventa

---

### Parte VI — Campañas y promociones

**20. Campañas del canal**
20.1 Tipos de campaña · 20.2 Elegibilidad y descuento exigido · 20.3 Costo para el vendedor · 20.4 Campañas co-fondeadas

**21. Ciclo de recomposición de precios en campaña**
21.1 Secuencia completa · 21.2 Máquina de estados persistente · 21.3 Simulación previa obligatoria · 21.4 Guardia de tiempo máximo fuera de campaña · 21.5 Ventana de ejecución · 21.6 Reporte de resultado

**22. Promociones propias**
22.1 Descuentos individuales · 22.2 Cupones · 22.3 Cuotas sin interés y su costo financiero

**23. Eventos de plataforma**
23.1 Detección y calendario · 23.2 Anticipación requerida · 23.3 Preparación de catálogo

---

### Parte VII — Ventas

**24. Órdenes**
24.1 Ingreso de una venta · 24.2 Normalización a orden canónica · 24.3 Mapeo a SKU · 24.4 Packs y órdenes multi-producto · 24.5 Estados de venta y de pago

**25. Rentabilidad de la venta**
25.1 Rentabilidad preliminar con comisión real · 25.2 Diferencia contra la rentabilidad proyectada · 25.3 Impacto de promociones sobre el precio efectivo

**26. Envíos**
26.1 Modalidades · 26.2 Costo por peso y dimensiones · 26.3 Etiquetas y seguimiento

**27. Devoluciones y cancelaciones**
27.1 Retorno físico e inspección · 27.2 Reingreso a stock o baja por merma · 27.3 Reversión de la rentabilidad · 27.4 Provisión por devoluciones

---

### Parte VIII — Posventa

**28. Preguntas y mensajería**
28.1 Preguntas previas a la compra · 28.2 Mensajería posventa · 28.3 Pendientes de respuesta y priorización

**29. Reclamos y mediaciones**
29.1 Tipos de reclamo · 29.2 Gestión y evidencia · 29.3 Impacto en reputación

---

### Parte IX — Dinero

**30. Facturación del canal**
30.1 Quién emite · 30.2 Descarga y archivo · 30.3 Datos fiscales del comprador · 30.4 Excepciones manuales

**31. Liquidaciones y conciliación**
31.1 Períodos de liquidación · 31.2 Comisión estimada contra comisión cobrada · 31.3 Retenciones y percepciones · 31.4 Desvío de estimación por componente · 31.5 Retroalimentación a los parámetros del motor

---

### Parte X — Sincronización

**32. Eventos y notificaciones**
32.1 Notificaciones del canal contra polling · 32.2 Clasificación y priorización · 32.3 Notificaciones perdidas · 32.4 Comunicados institucionales del canal

**33. Publicación al canal**
33.1 Cola, idempotencia y reintentos · 33.2 Prioridad entre tipos de cambio · 33.3 Límites de tasa y ventanas de sincronización · 33.4 Registro de cada llamada

**34. Reconciliación**
34.1 Comparación entre Estado Deseado y Estado Observado · 34.2 Clasificación de divergencias · 34.3 Cadencia · 34.4 Generación de excepciones

**35. Centro de excepciones**
35.1 Tipos de excepción · 35.2 Severidad y bloqueo · 35.3 Bandeja de trabajo · 35.4 Resolución y trazabilidad

---

### Parte XI — Visualización

**36. Dashboard comercial**
36.1 Indicadores del dominio · 36.2 Vistas por canal, línea y responsable · 36.3 Alertas accionables · 36.4 Qué **no** va en el dashboard

**37. Reportes**
37.1 Reportes como agregaciones puras · 37.2 Trazabilidad de todo total a las líneas que lo componen

---

### Parte XII — Cierre

**38. Casos de uso**
Recorridos completos de punta a punta, cada uno con actor, precondición, secuencia y resultado esperado.

**39. Validaciones y controles**
Tabla de controles con severidad, comportamiento y regla violada. Ningún control corrige un dato en silencio.

**40. Casos de aceptación**
Datos reales del negocio. Criterio de aceptación del dominio.

**41. Observaciones**
Inconsistencias detectadas y documentadas, no corregidas.

**42. Pendientes**
Únicamente donde no existe evidencia suficiente. Con quién resuelve cada uno.

**43. Anti-patrones**
Lista explícita de lo que está prohibido, cada uno con el error real que lo originó.

---

## Notas sobre la organización de este índice

Tres decisiones que conviene entender antes de completarlo:

**El dashboard va al final, no al principio.** Es una vista sobre todo lo demás: no se puede especificar qué mostrar antes de definir qué existe. Ponerlo primero es la forma más rápida de terminar con un tablero que muestra lo que era fácil de calcular en lugar de lo que hace falta decidir.

**Todo este documento es agnóstico de canal.** No aparece el nombre de ninguna plataforma. Si una sección solo tiene sentido para un canal, va en `canales/{canal}/`, no acá. Esa disciplina es lo que permite que el módulo crezca a cuatro canales sin reescribirse.

**El precio se separa de la competencia a propósito.** La Parte III define cómo se forma un precio; la Parte IV, cómo reacciona a la competencia. Mezclarlas produce el error que ya existe en las planillas vigentes: fijar el precio contra el competidor sin piso de margen.
