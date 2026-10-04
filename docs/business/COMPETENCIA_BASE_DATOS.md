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

## Doble escritura (transitoria)
Los monitores, `/competidores/refresh` y `/ml/tracker/run` siguen escribiendo a los históricos viejos (el front
todavía los lee) y además a `Historial_Precios`. Se cortan los viejos en la Etapa 3, cuando la pantalla lea el nuevo.
