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
    ├── 00_LEEME_CANALES.md      ← cómo se documenta un canal nuevo
    ├── mercadolibre/            ← documentado
    ├── woocommerce/             ← vacío, pendiente
    ├── fravega/                 ← vacío, pendiente
    └── oncity/                  ← vacío, pendiente
```

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
| 7 | `../../architecture/COMERCIAL_IMPLEMENTACION.md` | Diseño técnico |

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

**Después de que Rentabilidad esté terminada y su suite de regresión pase al centavo.** No antes.

El motivo no es procedimental. Comercial escribe precios en canales reales; si el margen que respalda esos precios no está validado, el sistema automatiza pérdidas a escala. La Fase 2 de Rentabilidad —el motor corriendo en modo sombra con el Reporte de Divergencia— es la puerta.

Mientras Rentabilidad no cierre, en esta carpeta se **documenta**, no se implementa.

---

## 6. Principios del dominio

Heredados de `01_TRASPASO_ERP.md` y no negociables acá:

**El canal es un espejo, no una fuente.** Ante divergencia entre lo que el ERP calculó y lo que el canal muestra, se genera una **excepción**. Nunca se corrige el dato del ERP para que coincida con el canal.

**Modo sombra obligatorio.** Todo el dominio debe poder calcular y proponer sin escribir nada en ningún canal.

**Ningún precio se publica sin pasar guardrails.** Salvo excepción aprobada y con vencimiento. No existe el override indefinido.

**Toda escritura al canal pasa por cola, es idempotente y tiene reintentos.** Prioridad: stock > precio > contenido.

**Un dato tiene un solo dueño.** Maestro, derivado u observado. Los derivados no se editan jamás.

**Ante duda no resuelta: marcar como pendiente, no inventar.**

---

## 7. Estado de la documentación

| Documento | Estado |
|---|---|
| `00_LEEME.md` | Completo |
| `01_COMERCIAL_FUNCIONAL.md` | **Solo índice.** A desarrollar sección por sección |
| `02_CONTRATO_DE_CANAL.md` | **Solo estructura** |
| `canales/mercadolibre/01_MAPA_API.md` | Completo a nivel de área. Detalle de endpoints se consulta con MCP |
| `canales/mercadolibre/02_MCP.md` | Completo |
| `canales/woocommerce/`, `fravega/`, `oncity/` | Vacías |
| `../../architecture/COMERCIAL_IMPLEMENTACION.md` | **Solo plantilla** |

---

## 8. Qué NO va en esta carpeta

- Reglas de cálculo de margen o de la cascada de rentabilidad → van en `RENTABILIDAD_FUNCIONAL.md`
- Documentación de Táctica o Ecom → son sistemas transitorios, ver `01_TRASPASO_ERP.md`
- Código, nombres de clase, esquemas de tabla → van en `architecture/COMERCIAL_IMPLEMENTACION.md`
- Un módulo separado de Inteligencia Competitiva → está **dentro** de Comercial como capacidad, no aparte
