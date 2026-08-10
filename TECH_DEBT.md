# Deuda técnica

## Observabilidad de jobs en background (refresh_job / tracker_job / vendedor_job)

Diagnosticado: 2026-07-10, durante validación de F0-IDENTITY (commit `bac5b2b`).

Los logs de progreso de los background jobs (`job_status[job_id]["log"].append(...)`) nunca llegan
a ninguno de los dos canales de observación actuales:

- **Railway**: no hay `print()`/`logging` acompañando los `.append()` — el log vive solo en un
  dict en memoria (`job_status`, `backend/main.py:22`). Railway únicamente captura stdout/stderr,
  así que estas líneas nunca aparecen ahí, sin importar el job.
- **UI** (`docs/index.html`, `compRefreshHistorial`, ~línea 2907): mientras el job corre, el
  polling pinta solo `data.log[data.log.length-1]` (se pisa por líneas posteriores); al terminar,
  el bloque `status==='done'` reemplaza todo `status.innerHTML` con un string hardcodeado
  (`✅ ${rows_added} filas · ${prices_fetched} precios`) que no lee `data.log` en absoluto.

**Impacto concreto**: las líneas `📊 Identidad ML — item_id usados / product_id excluidos / sin
identificador / sin link` agregadas en `refresh_job` (`backend/main.py:897-903`) son correctas y
completas dentro de `job_status[job_id]["log"]`, pero invisibles en ambos canales. Verificable
pegando `{backend}/competidores/refresh/status/{job_id}` en el navegador mientras el job corre o
justo al terminar — el array completo está ahí.

Mismo patrón estructural (no específico de F0-IDENTITY) en `tracker_job` y `vendedor_job`.

**Estado**: no resuelto intencionalmente. F1-Observability queda pausado a pedido de negocio
(2026-07-10) hasta después de definir prioridades de roadmap CGCC / Inteligencia Competitiva.
