# 02 — MCP · MERCADO LIBRE

## Qué es

Mercado Libre expone un **servidor MCP oficial de documentación**. Permite consultar la documentación de la API desde Claude Code, en vivo, sin navegar el portal a mano.

**Es un MCP de documentación, no operativo.** No consulta datos reales de la cuenta, no ejecuta operaciones, no devuelve publicaciones ni órdenes. Solo lee documentación.

Herramientas que expone:

| Herramienta | Para qué |
|---|---|
| `search_documentation` | Buscar por tema en toda la documentación |
| `get_documentation_page` | Traer una página completa por su ruta |

---

## Configuración

```json
{
  "mcpServers": {
    "mercadolibre": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://mcp.mercadolibre.com/mcp"]
    }
  }
}
```

Al conectar se abre el flujo OAuth en el navegador.

> **Usar una cuenta de desarrollo, no la cuenta vendedora de producción.** Aunque el MCP solo lea documentación, no hay razón para autenticar con la cuenta que factura.

---

## Cómo usarlo — el mandato

**Ninguna integración se implementa de memoria.** El conocimiento de entrenamiento sobre la API de Mercado Libre puede estar desactualizado o directamente equivocado. La documentación en vivo no.

Flujo obligatorio antes de escribir código que toque la API:

1. **Ubicar el área** en `01_MAPA_API.md`. El mapa dice dónde mirar.
2. **Consultar el MCP** para traer los parámetros, la estructura de respuesta, los límites y los códigos de error reales.
3. **Citar la ruta de documentación** en el commit o en el comentario del módulo.
4. Si la documentación no responde la duda, **verificar contra usuario de prueba** y guardar la respuesta real como **contrato verificado con fecha**.

**Nunca asumir el comportamiento de un endpoint.**

---

## División de trabajo entre el mapa y el MCP

Esta separación es deliberada y conviene entenderla:

| | `01_MAPA_API.md` | MCP |
|---|---|---|
| Responde | ¿Qué endpoint resuelve esta necesidad de negocio? | ¿Cómo se llama exactamente y qué devuelve? |
| Estabilidad | Alta — las áreas y las necesidades no cambian | Siempre al día |
| Origen | Relevamiento manual con fecha | Documentación oficial en vivo |
| Ante conflicto | Cede | **Manda** |

El mapa existe porque el MCP no sabe nada del negocio: no puede decir que `price_to_win` es la pieza central de la inteligencia competitiva de esta empresa, ni que el `inventory_id` es lo que resuelve la conciliación de stock con FULL. El MCP existe porque el mapa no puede mantenerse al día solo.

**Si el MCP dice que un endpoint del mapa no existe o cambió, gana el MCP.** Y conviene anotarlo para corregir el mapa.

---

## Qué consultar primero, por fase

Antes de arrancar cada fase, traer con el MCP la documentación de estas páginas:

| Fase | Páginas a consultar |
|---|---|
| 3 | `items-y-busquedas` · `producto-sincroniza-modifica-publicaciones` · `productos-recibe-notificaciones` · `rate-limit-error-429` |
| 4 | `api-de-precios` · `comision-por-vender` · `tipos-de-publicacion-y-actualizaciones-de-articulos` · `costos-de-envios` |
| 5 | `central-de-promociones` · `deals` · `descuento-individual` · `referencias-de-precios` · `promotions-pricing` |
| 6 | `user-products` · `stock-multi-origen` · `stock-multiwarehouse` · `envios-fulfillment` |
| 7 | `gestiona-ventas` · `gestion-packs` · `pagos` |
| 8 | `envios` · `facturacion` · `descargar-facturas-mla` |

---

## Preguntas concretas que hay que resolver con el MCP

Están abiertas y afectan decisiones de diseño. No inventar la respuesta.

| # | Pregunta | Bloquea |
|---|---|---|
| 1 | ¿Dónde vive el SKU propio de forma canónica: `seller_custom_field`, el atributo `SELLER_SKU`, o ambos? ¿Cómo detectar con confiabilidad que un ítem **no** tiene SKU? | Mapeo de órdenes y publicaciones |
| 2 | ¿Se puede modificar el precio de una publicación **dentro** de una campaña activa, o hay que salir primero? | Diseño del ciclo de campaña, Fase 5 |
| 3 | ¿Cuáles son los rate limits documentados, por app y por usuario? ¿Qué headers informan el límite restante? | Diseño de la cola |
| 4 | ¿Existe un parámetro para pedir solo ciertos campos en la respuesta y reducir payload? Sintaxis exacta | Eficiencia de todas las llamadas |
| 5 | ¿Cuál es el formato exacto del payload del callback de webhooks, cómo se suscribe y cuál es la política de reintentos? | Reemplazar polling, Fase 3 |
| 6 | ¿Cuáles son los endpoints **vigentes** de Product Ads, ahora que los legados `/advertising/product_ads/...` fueron dados de baja el 26/02/2026? | Módulo de publicidad |
| 7 | ¿Existe sandbox o entorno de pruebas? ¿Cómo se usa? | Poder probar sin tocar producción |
| 8 | ¿El filtro `reputation_health_gauge` ya aplica a MLA, o sigue limitado a México, Chile y Brasil? | Detección de ítems en riesgo |
| 9 | ¿Qué endpoints aceptan operaciones en lote y con qué tope de IDs? | Diseño de sincronización masiva |
| 10 | ¿Qué datos de una publicación **no** se pueden obtener por API y solo se ven en la web? | **Define qué hay que seguir scrapeando. Es una decisión de arquitectura** |

La pregunta 10 es la más importante de la lista: marca la frontera entre lo que resuelve la API y lo que necesita navegador.
