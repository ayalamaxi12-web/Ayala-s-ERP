# Base de datos de competencia (Etapa 1)

Parte de `MODULO_COMPETENCIA_SPEC.md`. Código: `backend/competencia_db.py`, migración en
`backend/scripts/migrar_competencia.py`, tests en `backend/test_competencia_db.py`.

## Esquema (mismo Spreadsheet, `SPREADSHEET_ID`)
- **`Referencias_Mercado`** (Tipo=`Competencia`): único registro de links. SKU resuelto una sola vez al migrar
  (SKU de la fila `V-*` → `General` por link → vacío; nunca por título). Se agrega al final la columna
  `Cantidad` (unidades por publicación). La **categoría no se toca**: la define Maca a mano en el Excel.
- **`Historial_Precios`**: único histórico, una fila por lectura:
  `Referencia_ID, SKU, Entidad, Fecha, Hora, Precio, Precio_Tachado, Descuento, Cuotas, Estado, Metodo, Fuente, Link`.
  En vivo es idempotente por `(Referencia_ID, Fecha)`.
- **`Migracion_Huerfanos`**: lecturas que no se pudieron atar a una referencia o fecha (nada se descarta).
- Un solo lector: `main.leer_precio_publicacion`. Catálogo (`/p/`) sin `wid` = estado `Sin lectura` (no se guarda
  fila; se resuelve en la Etapa 2).

## Migración
`python scripts/migrar_competencia.py` = dry-run (solo lectura + informe). `--ejecutar --plan-hash <hash>` escribe
solo si el hash coincide con el informe aprobado. No borra ni edita nada existente; es idempotente; al terminar
re-lee el Sheet y verifica que todo cierre exacto (origen = nuevas + fusionadas + ya existían + huérfanas).

## Endpoint de migración (Railway)
`POST /competencia/migracion/run` con header `X-ERP-Key` (falla cerrado: sin `ERP_API_KEY` en el servidor devuelve 503,
aunque el middleware esté en modo permisivo). Body `{}` = dry-run; `{"ejecutar": true, "plan_hash": "<hash aprobado>"}`
= migración real, solo si el hash calculado en ese momento coincide. Corre en un hilo; un solo job a la vez (409).
Seguimiento: `GET /competencia/migracion/status/{job_id}` (también con clave). Al terminar re-lee el Sheet y verifica
que las filas de `Historial_Precios`, `Referencias_Mercado`, `Entidades` y `Migracion_Huerfanos` sean las esperadas.
Las lecturas SIN precio no se migran (se cuentan aparte en el informe); antes de escribir se respalda
`Historial Competidores` en la pestaña `Respaldo_Hist_Competidores_<fecha>`.

## Doble escritura (transitoria)
Los monitores, `/competidores/refresh` y `/ml/tracker/run` siguen escribiendo a los históricos viejos (el front
todavía los lee) y además a `Historial_Precios`. Se cortan los viejos en la Etapa 3, cuando la pantalla lea el nuevo.

## Etapa 2: scraper automático (carpeta `scraper/`)
Lee la **planilla de Maca** (`PLANILLA_MACA_ID` en `scraper/config.py`; pestañas `A-CATEGORIAS` y `B-SKU-COMPETENCIA`, encabezados en la
fila 3) en lugar de la pestaña `Vendedores`. Sincroniza `Entidades` y `Referencias_Mercado` (columna nueva `Rol_Competidor`), scrapea
perfiles de tienda y publicaciones puntuales con Selenium (perfil de Chrome persistente) y escribe en `Historial_Precios` con las mismas
reglas de la Etapa 1. Eventos en `Eventos_Competencia`; tiendas con publicaciones que no son referencias, en `Discovery_Sugerencias`.
Instalación, modo prueba y tarea de las 17:30: `scraper/README_WINDOWS.md`.

Pendiente: alertas de **stock bajo** (< 5) — lógica lista pero desactivada hasta que la columna de stock de B-SKU tenga el dato real.

Cambios masivos reversibles (`backend/competencia_referencias.py`): `POST /competencia/referencias/desactivar-entidad` (dry-run por defecto;
la real exige `esperado` = cantidad del dry-run y registra cada valor anterior en `Cambios_Referencias`) y
`POST /competencia/referencias/revertir-lote`. Misma clave `X-ERP-Key` estricta que la migración.
