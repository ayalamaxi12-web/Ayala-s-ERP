# Integración Mercado Libre ↔ ERP — Mapa de oportunidades

Documento de trabajo para mapear TODAS las conexiones posibles entre la API de Mercado Libre y el ERP de Global Electronics. Insumo para la revisión que hará Code sobre la documentación `.md` de ML.

---

## 1. Objetivo (a dónde queremos llegar)

Hoy la dirección opera saltando entre las plataformas de ML y el sistema de gestión: mira un dato en ML (ventas del día, comisión cobrada, ranking de una categoría, stock de Full, una promo), lo interpreta "a ojo", y toma una decisión cruzándolo mentalmente con lo que sabe del sistema (stock, margen, costo, precio del PM).

**La meta es eliminar ese salto.** Que la API de ML traiga el dato exacto (no interpretado a ojo, no un título cortado que hay que adivinar) y que el ERP lo cruce automáticamente con el dato interno correspondiente, de modo que la decisión se tome en un solo lugar, con ambos lados del dato a la vista.

No se trata de listar la API de ML en abstracto: se trata de, por cada dato que hoy se mira saltando de plataforma a sistema, encontrar el endpoint que lo trae exacto y el dato interno con el que se cruza.

---

## 2. Módulos ML ya construidos (NO reconstruir)

| Módulo | Estado | Qué trae de ML |
|--------|--------|----------------|
| **OAuth 2 cuentas** (IT 115764017 / MT 34801784) | ✅ Funcionando, con refresh automático | Base de autenticación de todo lo demás |
| **Precios en vivo / Ofertas ML** | ✅ Hecho | Precio actual por lote (`GET /items/{MLA}/prices`), promociones con monto/vigencia; cruza con PM y costo de envío |
| **Scraper vendedor/competencia** (`ml_vendedor.py`) | ⚠️ A medias | Publicaciones de competidores, 2 pasadas, corre local (Selenium, 1×día por anti-bot) |
| **CGCC** (Centro de Gobierno del Canal Comercial) | ⚠️ Fase 0 hecha | Normaliza datos del scraper, detecta actores desconocidos, mapea PVP. Faltan los 4 detectores |
| **Conciliación Full** | ✅ Hecho | Aptas por publicación de ambas cuentas, cruza con depósito ecom |

---

## 3. Inventario operativo — qué se mira hoy saltando ML↔sistema

Cada fila es un momento en que hoy se abre ML en lugar del sistema. La tarea de Code es unir cada una con el/los endpoint(s) exacto(s) de la doc de ML.

### 3.1 Ventas en Vivo ("cómo viene el día")
- **En ML:** ranking de publicaciones más vendidas del día.
- **Cruzar con sistema:** stock actual, días de stock, precio, margen real (viene de Rentabilidad), ventas 7/30/90/180 días por canal.
- **Decisión:** ¿lo empujo (hay stock + margen), lo freno (sin stock o margen negativo), o lo dejo?
- **Tipo:** lectura + cruce.

### 3.2 Métricas / Análisis de Mercado (trabajo de Maca)
- **En ML:** lo más vendido por categoría, desglosado por publicación — **ML oculta cuál es** (muestra un pedazo de título, hay que adivinar).
- **Cruzar con sistema:** SKU real propio, para comparar contra el competidor exacto.
- **Valor clave:** con el dato exacto por API se deja de adivinar. Engancha con la Base de Competencia de Maca.
- **Tipo:** lectura + cruce.
- **PENDIENTE DE MAPEO:** confirmar si "más vendido por categoría" sale por API (tendencias) o es solo del panel visual.

### 3.3 Facturación (cruce de comisiones)
- **En ML:** lo que efectivamente cobraron por comisión de venta (comisión venta, comisión cobro, costo envío, retenciones) a nivel orden.
- **Cruzar con sistema:** comisión teórica que calculó el módulo de Rentabilidad.
- **Decisión:** detectar cuando ML cobra de más o distinto a lo pactado, sin revisar factura por factura.
- **Clave de unión:** N° de orden / MLA.
- **Tipo:** lectura + cruce. **El más limpio de implementar** — el dato ya aparece en el export de órdenes.

### 3.4 Full
- **En ML:** aptas para vender por publicación (ambas cuentas).
- **Cruzar con sistema:** stock del depósito Full en ecom.
- **Estado:** ✅ ya implementado como conciliación. Falta pasarlo de Excel a proceso automático.
- **Tipo:** lectura + cruce.

### 3.5 Promociones (participar / despartir desde el ERP)
- **En ML:** campañas disponibles, vigencias, precios de promo.
- **Cruzar con sistema:** precio del PM, margen, costo → simular margen ANTES de aceptar.
- **Decisión:** entrar/salir de promos jugando con el margen; recibir alertas de fechas y de cambios de precio.
- **Tipo:** lectura + **ACCIÓN** (único módulo que escribe a ML).
- **Actualizado 2026-08-29:** modificar SÍ se puede por API pública para campaña propia (`SELLER_CAMPAIGN`) y descuento propio (`PRICE_DISCOUNT`) — implementado en `ml_ofertas.py` (`fijar_precio_base`/`meter_en_campana`/`activar_oferta_propia`/`sacar_de_promocion`), confirmado contra developers.mercadolibre.com.ar. Sigue sin confirmar: participar en una campaña *de ML* (`P-MLA...`, ej. Descuentazos) por API pública — no probado todavía. El cálculo de margen y las alertas son de nuestro lado, no dependen de ML.

---

## 4. Límites conocidos de la API de ML (paredes ya confirmadas)

| Límite | Detalle | Alternativa |
|--------|---------|-------------|
| Nº de cuotas por publicación | La API no lo expone; solo "con/sin cuotas" | Inferir por umbral de precio, o dato de ecom |
| Modificar oferta individual | No por API pública (requiere sesión web) | Acción manual, o solo listar/participar/salir |
| Visitas y conversión de competidores | Sin endpoint | Velocidad = delta de "vendidos" entre corridas |
| Publicación oculta en análisis de mercado | ML muestra título parcial | Confirmar si API de tendencias lo da completo |

---

## 5. Prioridad de datos (orden del director)

Lo principal, en orden: **ventas, facturación, métricas, promociones, Full.**

---

## 6. Tabla resumen para la revisión

| Módulo ML | Trae de ML | Cruza del sistema | Tipo | Traba |
|-----------|-----------|-------------------|------|-------|
| Ventas en Vivo | Ranking publis del día | Stock, días stock, precio, margen, ventas multi-período | Lectura+cruce | — |
| Métricas/Mercado | Más vendido por categoría (publi oculta) | SKU propio real | Lectura+cruce | Publi sin identificar |
| Facturación | Comisiones reales | Comisión teórica (Rentabilidad) | Lectura+cruce | — |
| Full | Aptas por publicación | Stock depósito ecom | Lectura+cruce | Ya hecho |
| Promociones | Campañas, vigencias | Precio PM, margen, costo | Lectura+acción | Ya hecho (campaña propia + descuento propio); falta confirmar campañas de ML (`P-MLA...`) |
