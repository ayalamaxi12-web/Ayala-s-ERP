# Clave del backend (`X-ERP-Key`) — cómo funciona y cómo activarla

**Qué exige clave** (`backend/erp_auth.py`): todo POST/PUT/PATCH/DELETE, `GET /ml/token` y `GET /ml-proxy`.
**Qué sigue abierto:** `/`, `/health`, `/tc/bna`, el resto de los GET, y `GET /rentabilidad/reporte/*`
(n8n, con su propio `X-Reporte-Token` / `RENT_REPORTE_TOKEN`). El cron de Ecom corre en proceso, sin HTTP.

**Modo permisivo:** sin `ERP_API_KEY` en Railway no se bloquea nada; el log de Railway muestra líneas
`[auth] PERMISIVO ... METHOD /ruta origin=...` con los requests protegidos que llegaron (una vez por ruta
y por arranque). **Activar = definir `ERP_API_KEY`; desactivar = borrarla** (hay que redeployar/reiniciar
para que Railway la aplique).

**CORS:** solo `https://ayalamaxi12-web.github.io` (variable opcional `CORS_ORIGINS`, separada por comas).

**Front:** Configuración → "Clave del backend" (se guarda en `localStorage`, `erp_backend_key`) →
Guardar → Testear (`🔑 clave OK` / `⚠ la clave falta o es incorrecta` / `clave aún no exigida`).
La API key de Sheets se carga en Configuración (no está más en el HTML).

## Orden para el día de activación
1. Mergear y desplegar (backend en Railway; front se publica solo en GitHub Pages). Verificar `/health`.
2. Con la clave aún SIN definir, que cada usuario: recargue con Ctrl+F5, pegue la **API key de Sheets nueva** y la
   **Clave del backend** en Configuración, Guardar y Testear (debe decir `clave aún no exigida`).
3. Revisar el log de Railway: no deben aparecer rutas protegidas inesperadas (nada de n8n/cron).
4. Cuando todos lo hicieron: definir `ERP_API_KEY` en Railway (mismo valor que repartiste) y esperar el redeploy.
5. Cada usuario: Testear → debe decir `🔑 clave OK`. Probar una escritura inofensiva y verificar n8n.
6. Rollback: borrar `ERP_API_KEY` en Railway → vuelve a permisivo.
