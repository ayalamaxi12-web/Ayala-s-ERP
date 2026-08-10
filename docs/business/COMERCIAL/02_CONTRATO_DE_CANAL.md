# 02 — CONTRATO DE CANAL

## Qué debe cumplir todo canal del dominio Comercial

**Versión 0.1 — SOLO ESTRUCTURA. Ninguna sección desarrollada.**

> **Por qué existe este documento.** Sin un contrato común, cada canal se documenta e implementa desde cero y el módulo Comercial se convierte en cuatro módulos pegados con cinta. Con contrato, agregar un canal es completar una ficha y escribir un adaptador; el dominio no se toca.
>
> Este documento define **capacidades**, no endpoints. Los endpoints de cada canal viven en `canales/{canal}/01_MAPA_API.md`.

---

## Índice

**1. Propósito del contrato**
1.1 Qué es un canal · 1.2 Qué NO es un canal · 1.3 Relación con el dominio

**2. Capacidades obligatorias**
Sin estas, un canal no puede integrarse al dominio.
2.1 Leer publicaciones propias · 2.2 Identificar cada publicación de forma unívoca · 2.3 Resolver el SKU propio · 2.4 Escribir precio · 2.5 Escribir stock · 2.6 Leer órdenes

**3. Capacidades opcionales**
Su ausencia es una limitación documentada, no un impedimento.
3.1 Notificaciones o webhooks · 3.2 Campañas y promociones · 3.3 Catálogo competitivo · 3.4 Depósito del canal · 3.5 Mensajería y posventa · 3.6 Liquidaciones · 3.7 Publicidad · 3.8 Métricas de visitas

**4. Contratos de datos canónicos**
La forma normalizada en que el dominio recibe la información, sea cual sea el canal.
4.1 Publicación canónica · 4.2 Orden canónica · 4.3 Movimiento de stock canónico · 4.4 Evento canónico · 4.5 Componente de costo de canal

**5. Traducción canal a canónico**
5.1 Responsabilidad del adaptador · 5.2 Qué se normaliza y qué se conserva crudo · 5.3 Qué hacer con los campos que no tienen equivalente

**6. Requisitos técnicos transversales**
6.1 Autenticación y renovación de credenciales · 6.2 Límites de tasa · 6.3 Idempotencia de la escritura · 6.4 Registro de cada llamada · 6.5 Modo sombra

**7. Ficha de canal**
Plantilla que todo canal nuevo debe completar antes de implementarse.
7.1 Datos de identificación · 7.2 Capacidades soportadas y no soportadas · 7.3 Componentes de costo que cobra el canal · 7.4 Límites conocidos · 7.5 Qué requiere navegador porque la API no lo cubre

**8. Limitaciones declaradas por canal**
Tabla comparativa. Una limitación documentada no habilita una excepción a las reglas del dominio.

**9. Cómo se incorpora un canal nuevo**
Secuencia de pasos, de la ficha al adaptador en producción.

---

## Nota sobre la asimetría entre canales

No todos los canales exponen lo mismo, y el dominio no debe nivelar por abajo.

La regla es: **el dominio define la regla completa; el canal declara qué parte puede cumplir.** Si un canal no soporta campañas, eso se documenta como limitación de ese canal — no desaparece la sección de campañas del funcional, y no se inventa una campaña simulada del lado del ERP.
