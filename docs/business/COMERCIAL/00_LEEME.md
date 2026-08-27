# 00 — LEEME

## Dominio COMERCIAL — Ayala ERP

Esta carpeta contiene la documentación funcional del dominio **Comercial**: la gestión de publicaciones, precios, ventas, campañas y sincronización en todos los canales de venta.

---

## 1. Qué contiene esta carpeta

```
business/COMERCIAL/
├── 00_LEEME.md                  ← este archivo
├── 01_COMERCIAL_FUNCIONAL.md    ← especificación funcional del dominio
├── 02_CONTRATO_DE_CANAL.md      ← qué debe cumplir todo canal, sea cual sea
└── canales/
    └── mercadolibre/
        ├── 01_MAPA_API.md       ← qué endpoint resuelve qué necesidad
        ├── 02_MCP.md            ← cómo consultar la documentación oficial
        ├── 03_MODULO_FULL.md    ← Full y conciliación de stock
        └── mcp.json             ← configuración del MCP, lista para pegar
```

Las carpetas de WooCommerce, Frávega y OnCity se crean cuando se documente cada canal, no antes.

**Mercado Libre es un canal, no el módulo.** Está primero porque es el de mayor volumen y el único con documentación completa, no porque sea el dominio. Todo lo que valga para cualquier canal va en `01` o `02`; lo que sea específico de una plataforma va en su carpeta dentro de `canales/`.

Esa separación es la razón de que la carpeta esté armada así: agregar un canal nuevo debe ser **crear una carpeta**, nunca reorganizar la documentación existente.

---

## 2. Orden de lectura

| # | Documento | Qué responde |
|---|---|---|
| 1 | `00_LEEME.md` | Cómo está organizado esto |
| 2 | `../../business/RENTABILIDAD_FUNCIONAL.md` | Cómo se calcula el margen. **Comercial depende de esto** |
| 3 | `01_COMERCIAL_FUNCIONAL.md` | Reglas del dominio, agnósticas de canal |
| 4 | `02_CONTRATO_DE_CANAL.md` | Qué capacidades debe exponer un canal |
| 5 | `canales/{canal}/01_MAPA_API.md` | Qué endpoint de ese canal resuelve qué necesidad |
| 6 | `canales/{canal}/02_MCP.md` | Cómo consultar la documentación oficial de ese canal |
| 7 | `canales/{canal}/03_*.md` en adelante | Módulos específicos de ese canal |
| 8 | `../../architecture/COMERCIAL_IMPLEMENTACION.md` | Diseño técnico |

**Rentabilidad se lee antes que Comercial, no después.** Comercial fija precios, y un precio sin margen calculado es una decisión a ciegas. La cascada de rentabilidad es un insumo del dominio comercial, no un módulo paralelo.

---

## 3. Autoridad entre documentos

```
RENTABILIDAD_FUNCIONAL.md
        ↓  (Comercial consume el margen, no lo redefine)
01_COMERCIAL_FUNCIONAL.md
        ↓
02_CONTRATO_DE_CANAL.md
        ↓
canales/{canal}/01_MAPA_API.md
        ↓
COMERCIAL_IMPLEMENTACION.md
```

Reglas de precedencia:

**`RENTABILIDAD_FUNCIONAL.md` es intocable desde acá.** Comercial no puede redefinir cómo se calcula un margen, ni agregar componentes a la cascada, ni cambiar una base imponible. Si Comercial necesita algo que la cascada no da, se reporta como pendiente de Rentabilidad; no se resuelve en Comercial.

**El funcional manda sobre la implementación.** Si `COMERCIAL_IMPLEMENTACION.md` impide reproducir una regla del funcional, está mal el técnico. Se cambia el técnico.

**Lo agnóstico manda sobre lo específico de canal.** Si un canal no puede cumplir una regla del dominio, eso es una **limitación documentada del canal**, no una excepción a la regla. La regla queda.

**La documentación oficial del canal manda sobre el mapa.** Ver punto 4.

---

## 4. El MCP oficial es obligatorio

**Ninguna integración se implementa de memoria.**

El conocimiento de entrenamiento sobre las APIs de los canales puede estar desactualizado o directamente equivocado. La documentación en vivo no.

Flujo obligatorio antes de escribir código que toque un canal:

1. Ubicar el área en `canales/{canal}/01_MAPA_API.md`. El mapa dice **dónde** mirar.
2. Consultar el MCP oficial para traer parámetros, estructura de respuesta, límites y códigos de error **reales**.
3. Citar la ruta de documentación en el commit o en el comentario del módulo.
4. Si la documentación no responde la duda, verificar contra usuario de prueba y guardar la respuesta real como **contrato verificado con fecha**.

**Está prohibido programar un endpoint de memoria.** Un parámetro inventado no falla en desarrollo: falla en producción, sobre precios y stock reales.

**Si el MCP contradice al mapa, gana el MCP** — y hay que corregir el mapa.

---

## 5. Cuándo empieza la implementación

**La puerta es sobre ESCRITURA, no sobre lectura.** La distinción es la que decide qué se puede
construir hoy.

### Escritura al canal — bloqueada

Publicar precios, activar promociones, modificar publicaciones, mover stock. **Nada de esto se
implementa hasta que Rentabilidad esté terminada y su suite de regresión pase al centavo.**

El motivo no es procedimental. Comercial escribe precios en canales reales; si el margen que
respalda esos precios no está validado, el sistema automatiza pérdidas a escala. La Fase 2 de
Rentabilidad —el motor corriendo en modo sombra con el Reporte de Divergencia— es la puerta.

### Excepción — escritura habilitada para el módulo de Ofertas ML (2026-08-27)

El criterio original de este punto —motor de rentabilidad en vivo corriendo en modo sombra, con
su suite de regresión pasando al centavo— **quedó obsoleto, no cumplido.** Ese motor en vivo no
terminó de validarse (`RENTABILIDAD_FUNCIONAL.md.md` sigue con V-01/V-02/V-03 abiertas, y
`RENTABILIDAD_IMPLEMENTACION.md.md` §7 sigue listando T-9 y E-4 como pendientes de esa
verificación) y **dejó de ser el camino de cálculo que se usa.** No se lo marca acá como completo
porque no lo está — simplemente dejó de ser la puerta. Esos dos documentos no se tocan por esto.

El cierre real de Rentabilidad pasó por otro camino: la captura de los períodos ya calculados en
el Sheet al cerrar cada mes ("fotos" de las pestañas), ingestada a la rentabilidad histórica vía
`backend/rentabilidad/importar_historico.py`. Ese es el dashboard que está terminado y en uso hoy
("Ventas & Rentabilidad") — no el motor en vivo, que quedó en el ERP como herramienta de consulta
manual aparte, sin ser el criterio de esta puerta.

La base de ese cálculo son las fórmulas y los descuentos que definió la dirección, y no todos
tienen el mismo respaldo. **Los descuentos de plataforma** (comisión, envío, cuotas) sí están
verificados contra la API real de Mercado Libre. **Los impuestos de la regla ECOM** (Imp. Cheque
1,2% sobre precio con IVA, IIBB 5% sobre precio sin IVA — corregido 2026-08-27, no es la misma
base para los dos) no salen de ninguna API — son un criterio que definió la dirección, no un dato
verificado contra una fuente externa. Además, **nada de esto está
contrastado contra libros contables** — queda fuera de alcance, no hay acceso a esa fuente desde
acá. La fuente de verdad, para lo que no viene de la API, es el criterio autorizado por la
dirección, no una auditoría contable independiente. Que quede explícito para que nadie lo lea
como una verificación que no es.

Con esa base, **la escritura queda habilitada para el módulo de Ofertas ML** (activar, pausar y
dar de baja una oferta/descuento propio desde el ERP, ver
`canales/mercadolibre/REQ_MODULO_OFERTAS_ML.md` Fase 3) — **y solo para ese módulo.** No habilita
escritura en ningún otro punto de Comercial ni de ningún otro canal; cualquier otra escritura
(Full, Táctica, Ecom, WooCommerce, etc.) sigue bloqueada por esta misma sección y requiere su
propia evaluación — no hereda esta.

### Lectura, conciliación y diagnóstico — habilitadas

Traer stock, ventas, visitas y estado de publicaciones. Comparar contra los sistemas propios.
Detectar diferencias y mostrarlas. **Nada de esto toca un precio ni escribe al canal, así que
el riesgo que la puerta previene no aplica.**

`canales/mercadolibre/03_MODULO_FULL.md` está enteramente de este lado y puede construirse ya.

### Por qué importa que esté escrito

Sin esta distinción, la regla se lee como una prohibición total y pasa una de dos cosas: o se
frena trabajo que no tiene riesgo, o alguien la interpreta por su cuenta y arranca igual.
**Interpretar una regla de negocio en lugar de preguntar es el modo de falla más peligroso.**

### Sobre leer Táctica y ECOM

El §8 excluye la **documentación** de Táctica y ECOM de esta carpeta, porque son sistemas
transitorios. Eso no prohíbe leerlos: la conciliación necesita el stock del depósito Full de
ECOM y el factor de descuento de las vinculaciones. **Leer está habilitado. Escribir en ellos,
no.**

---

## 6. Principios del dominio

Heredados de `01_TRASPASO_ERP.md` y no negociables acá:

**El canal es un espejo, no una fuente.** Ante divergencia entre lo que el ERP calculó y lo que el canal muestra, se genera una **excepción**. Nunca se corrige el dato del ERP para que coincida con el canal.

**Modo sombra obligatorio.** Todo el dominio debe poder calcular y proponer sin escribir nada en ningún canal.

**Ningún precio se publica sin pasar guardrails.** Salvo excepción aprobada y con vencimiento. No existe el override indefinido.

**Toda escritura al canal pasa por cola, es idempotente y tiene reintentos.** Prioridad: stock > precio > contenido.

**Un dato tiene un solo dueño.** Maestro, derivado u observado. Los derivados no se editan jamás.

**Ante duda no resuelta: marcar como pendiente, no inventar.**

**Un número que no se puede medir no se estima en silencio.** Si un dato viene de una fuente
que puede estar sesgada —por ejemplo, ventas de un producto que estuvo sin stock— el sistema
tiene que **marcar el dato como no confiable**, no promediarlo y seguir. Ver
`canales/mercadolibre/03_MODULO_FULL.md` §2.

---

## 7. Estado de la documentación

| Documento | Estado |
|---|---|
| `00_LEEME.md` | Completo |
| `01_COMERCIAL_FUNCIONAL.md` | **Solo índice.** A desarrollar sección por sección |
| `02_CONTRATO_DE_CANAL.md` | **Solo estructura** |
| `canales/mercadolibre/01_MAPA_API.md` | Completo a nivel de área. Detalle de endpoints se consulta con MCP |
| `canales/mercadolibre/02_MCP.md` | Completo |
| `canales/mercadolibre/03_MODULO_FULL.md` | Completo. **Listo para implementar** — es lectura, ver §5 |
| `canales/mercadolibre/00_FICHA.md` | **No existe.** El `02_CONTRATO_DE_CANAL` §7 la pide |
| WooCommerce, Frávega, OnCity | Sin documentar. Las carpetas se crean al documentarlas |
| `../../architecture/COMERCIAL_IMPLEMENTACION.md` | **Solo plantilla** |

---

## 8. Qué NO va en esta carpeta

- Reglas de cálculo de margen o de la cascada de rentabilidad → van en `RENTABILIDAD_FUNCIONAL.md`
- Documentación de Táctica o Ecom → son sistemas transitorios, ver `01_TRASPASO_ERP.md`. **Esto es sobre dónde vive la documentación, no una prohibición de leerlos** — ver §5
- Código, nombres de clase, esquemas de tabla → van en `architecture/COMERCIAL_IMPLEMENTACION.md`
- Un módulo separado de Inteligencia Competitiva → está **dentro** de Comercial como capacidad, no aparte
