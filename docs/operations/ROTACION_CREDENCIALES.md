# Rotación de credenciales (incidente de seguridad de Railway)

Estado: **solo documento**. No se cambió código, variables ni valores. En todo este archivo figuran **solo nombres** de variables; ningún valor.
Base del análisis: `main` al 24/10/2026 (código del backend, del scraper y de los scripts, más todo el historial de git: 205 commits, todas las ramas).

## 0. Resumen para decidir rápido
1. **Tratá como comprometidas TODAS las variables del servicio del backend y del servicio Cron en Railway** (secciones 1 y 2), más cualquier variable que Railway agregue sola (`DATABASE_URL`, `PG*`, `RAILWAY_*`) y que no figura acá. Compará el panel de Variables de Railway contra la tabla de la sección 2: **lo que esté en el panel y no en esta lista, avisame** (no lo encontré en el código).
2. **Hallazgo en el historial de git: 1 secreto commiteado.** Una **API key de Google (formato `AIza…`)** estuvo hardcodeada en `docs/index.html` (un solo valor distinto en todo el historial). Está desde el primer commit del repo (`31a4880`, 15/09/2026) hasta el commit `21d13e6` (04/10/2026, «sacar la API key de Sheets hardcodeada»), que la quitó del código pero **no del historial**. Sigue en la punta de **5 ramas remotas viejas** (sección 4). Hay que revocarla/regenerarla aunque ya no esté en `main`. Si el repositorio es público (GitHub Pages lo pide en el plan gratuito; no puedo verlo desde acá), esa clave estuvo expuesta a cualquiera.
3. No encontré en el historial: JSON de cuentas de servicio, claves privadas PEM, tokens de ML, contraseñas, URLs de base con usuario y contraseña, claves de Tailscale ni tokens de GitHub/Slack/Anthropic.
4. **Dos puntos del código filtran más de lo debido** (sección 5): el token `RENT_REPORTE_TOKEN` puede viajar en la URL (`?token=`), y el refresh token de ML que entrega cada renovación se guarda solo en memoria (afecta cómo rotar ML).
5. **Orden sugerido y qué se rompe en cada paso: sección 6.**

## 1. Servicios y lugares donde viven credenciales
| Lugar | Qué corre | Credenciales que usa |
|---|---|---|
| Railway, servicio **backend** (`uvicorn`, `backend/Dockerfile` + `entrypoint.sh`) | API del ERP, jobs, túnel Tailscale | Casi todas las variables de la sección 2 |
| Railway, servicio **Cron** (`backend/railway.cron.json`, 09:00 UTC) | `scripts/ecom_diario.py`: cierre diario de Ecom | `RENT_DATABASE_URL`, `RENT_ECOM_*`, `GOOGLE_CREDENTIALS_JSON`, `RENT_SHEET_*`, `RENT_TACTICA_SQL_*` (solo si `TS_EN_JOB=1`), `TS_AUTHKEY` (idem) |
| Railway, **Postgres** (addon) | Base del motor de Rentabilidad, fotos, snapshots | su propia contraseña (`PG*` / `DATABASE_URL`) |
| **PC de Maca/Maxx (Windows)**: scraper (`scraper/`) | Scraper de competencia con Selenium | archivo `credentials.json` (cuenta de servicio de Google), carpeta `perfil_chrome/` (sesión de Mercado Libre iniciada en Chrome), variables `ERP_BACKEND_URL` y `ERP_API_KEY` (`setx`) |
| **PC de Maxx**: `scripts/ts_pc_relay.py` | Puente TCP hacia la SQL de Táctica por Tailscale | no usa secretos (solo `TS_RELAY_LISTEN`, `TS_RELAY_TARGET`) |
| **n8n** (fuera de este repo) | Avisos y reportes diarios por mail | guarda en sus credenciales, entre otras cosas, `ERP_API_KEY` y `RENT_REPORTE_TOKEN`; **no puedo verlas desde el repo: rotarlas allá también** |
| **Navegadores** de cada usuario (GitHub Pages) | `docs/index.html` | `localStorage`: `erp_backend_key` (= `ERP_API_KEY`), `global_erp_v1` (tokens de ML, API key de Sheets, cookie y email de Ecom, ids de planillas PM) |
| Cuentas externas | Google Cloud, Mercado Libre, Ecom (app.ecomexperts.com), Táctica (SQL Server), Tailscale | donde se rota cada una |

## 2. Inventario de variables (solo nombres)
Leyenda de «Servicio»: GG = Google, ML = Mercado Libre, TAC = Táctica SQL, TS = Tailscale, PG = Postgres, N8N = n8n, ECO = Ecom, ERP = propia del ERP, — = no es secreta.

| Variable | Para qué sirve | Servicio | Dónde se usa | ¿Secreta? | Cómo se rota |
|---|---|---|---|---|---|
| `GOOGLE_CREDENTIALS_JSON` | JSON de la cuenta de servicio de Google para leer y escribir Sheets/Drive (PM, categorías, competencia, historial, stock Táctica) | GG | `backend/main.py`, `rentabilidad/gsheets.py`, `scripts/ecom_diario.py`, `scripts/migrar_competencia.py` | **Sí, crítica** | Google Cloud Console → IAM → Cuentas de servicio → Claves: **crear una clave nueva**, cargarla en Railway (backend **y** Cron) y en `scraper/credentials.json`, y **recién después borrar la clave vieja**. Si se sospecha de la cuenta entera, crear otra cuenta y compartirle las planillas |
| `ML_APP_ID` | ID de la aplicación de Mercado Libre | ML | `backend/ml_auth.py` | No (identificador) | No rota; es el ID de la app |
| `ML_CLIENT_SECRET` | Secreto de la app de ML para renovar tokens | ML | `backend/ml_auth.py` | **Sí, crítica** | Panel de desarrolladores de ML → la app → regenerar el secreto. ML no documenta si eso invalida los tokens ya emitidos: probarlo |
| `ML_REFRESH_TOKEN` (cuenta IT/Group) y `ML_REFRESH_TOKEN_2` (cuenta MT/Arg) | Renuevan el access token de cada cuenta vendedora | ML | `backend/ml_auth.py` | **Sí, crítica** | Reautorizar cada cuenta con el flujo OAuth del ERP (`/ml/exchange`) para obtener un par nuevo; revocar el acceso de la app desde cada cuenta de ML invalida los viejos |
| `ML_TOKEN` y `ML_TOKEN_2` | Access token inicial (vence en horas; el backend lo renueva solo) | ML | `backend/ml_auth.py`, `main.py` | **Sí** | Se reemplazan al reautorizar; vencen solos |
| `RENT_ECOM_EMAIL`, `RENT_ECOM_PASSWORD` | Usuario y contraseña de Ecom para ingesta, catálogo de costos y cierre diario | ECO | `rentabilidad/ingesta_ecom_api.py`, `scripts/ecom_diario.py` | **Sí, crítica** (la contraseña) | Cambiar la contraseña de ese usuario en Ecom y actualizar las dos variables (backend y Cron). Conviene un usuario dedicado al ERP |
| `RENT_DATABASE_URL` | Cadena de conexión a Postgres (incluye usuario y contraseña) | PG | `rentabilidad/config.py`, `migrations/env.py`, `main.py`, `scripts/ecom_diario.py` | **Sí, crítica** | En el servicio Postgres de Railway, regenerar/cambiar la contraseña del usuario; si la variable es una referencia al servicio Postgres se actualiza sola, si es un texto pegado hay que pegarla de nuevo (no se puede saber desde el repo cuál es el caso) |
| `RENT_TACTICA_SQL_SERVER`, `RENT_TACTICA_SQL_DATABASE`, `RENT_TACTICA_SQL_USER`, `RENT_TACTICA_SQL_PASSWORD` | Conexión a la SQL Server de Táctica (costo e IVA por producto, ingesta) | TAC | `rentabilidad/adapters.py`, `ingesta_tactica.py` | **Sí** (usuario y contraseña); servidor y base son sensibles pero no rotan | Cambiar la contraseña de ese usuario SQL en el servidor de Táctica (administrador de la oficina) y actualizar la variable. Idealmente un usuario de solo lectura |
| `TS_AUTHKEY` | Clave para que el contenedor se una a la red Tailscale | TS | `backend/entrypoint.sh` | **Sí, crítica** | Tailscale → Settings → Keys: **revocar** la clave y generar otra (marcar efímera); cargarla. Además revisar en Machines que no haya dispositivos desconocidos y revisar las ACL |
| `TS_HOSTNAME`, `TS_UP_TIMEOUT`, `TS_EN_JOB` | Nombre del nodo, espera y modo job del túnel | TS | `backend/entrypoint.sh` | No | — |
| `ERP_API_KEY` | Clave compartida (`X-ERP-Key`) que protege escrituras, `/ml/token`, `/ml-proxy`, competencia y proyección | ERP | `backend/erp_auth.py`, `proyeccion_snapshot.py`, `scraper/`, `scripts/subir_proyeccion.py` | **Sí, crítica** | Generar un valor aleatorio largo nuevo, cargarlo en Railway y repartirlo a: cada navegador (Configuración → «Clave del backend»), la PC del scraper (`setx ERP_API_KEY`), n8n y quien corra `subir_proyeccion.py`. **No borrar la variable durante la rotación: sin ella el backend queda en modo permisivo y no bloquea nada** |
| `RENT_REPORTE_TOKEN` | Token de los reportes para n8n (`X-Reporte-Token` o `?token=`) | N8N / ERP | `backend/rentabilidad/api.py` | **Sí** | Valor nuevo en Railway y en las credenciales de n8n. **Sin la variable, esos reportes quedan abiertos** (código de `_verificar_token_reporte`): no borrarla |
| `CORS_ORIGINS` | Orígenes permitidos (por defecto, el GitHub Pages del ERP) | — | `backend/main.py` | No | — |
| `BACKEND_URL`, `ERP_BACKEND_URL` | URL del backend para scripts y scraper | — | `scripts/subir_proyeccion.py`, `scraper/config.py` | No | — |
| `SCRAPER_CREDENTIALS`, `SCRAPER_PERFIL_CHROME` | Rutas del `credentials.json` y del perfil de Chrome del scraper | — (rutas) | `scraper/config.py` | No (pero **lo que apuntan sí es secreto**, ver abajo) | — |
| `RENT_SHEET_GLOBAL_ID`, `RENT_SHEET_CATEGORIAS_ID`, `RENT_SHEET_BASE_GENERAL_ID`, `RENT_SHEET_MARGEN_VERONICA_ID`, `RENT_SHEET_MARGEN_MATIAS_ID`, `RENT_SHEET_MARGEN_CRISTIAN_ID`, `RENT_SHEET_MASTER_COMPRAS_ML_ID`, `RENT_SHEET_VINCULACION_ID` | IDs de planillas de Google | GG | `rentabilidad/config.py` | No son secretos (el acceso lo da la cuenta de servicio) | No rotan; si una planilla se filtró, revisar con quién está compartida |
| `TS_RELAY_LISTEN`, `TS_RELAY_TARGET`, `TS_BRIDGE_LISTEN`, `TS_BRIDGE_TARGET`, `TS_BRIDGE_SOCKS` | Direcciones de los puentes TCP hacia Táctica | — | `scripts/ts_pc_relay.py`, `ts_sql_bridge.py` | No | — |
| `PORT`, `PGCONNECT_TIMEOUT`, `PGOPTIONS` | Puerto y timeouts | — | `entrypoint.sh`, `ecom_diario.py`, `ayala_core.py` | No | — |
| `GEMINI_API_KEY`, `GOOGLE_API_KEY` | Solo herramientas de generación de logos/imágenes en `.claude/skills/design/` (no son del ERP en producción) | GG (AI Studio) | `.claude/skills/design/scripts/` | Sí, **si alguna vez se cargaron** | Google AI Studio → regenerar. Si nunca estuvieron en Railway, no aplica |

**Secretos que no son variables de Railway** (también hay que rotarlos):
- `scraper/credentials.json` (cuenta de servicio de Google de la PC del scraper). Se rota junto con `GOOGLE_CREDENTIALS_JSON`.
- `scraper/perfil_chrome/` (sesión de Mercado Libre iniciada en esa PC): equivale a una contraseña. Cerrar todas las sesiones de esa cuenta de ML, cambiar su contraseña y volver a iniciar sesión en el scraper.
- **API key de Google para Sheets** (la carga cada usuario en Configuración y la guarda su navegador, `global_erp_v1` → `sheetsKey`; además la del historial de git): Google Cloud Console → APIs y servicios → Credenciales → **regenerar y restringirla** a la API de Sheets y al origen `https://ayalamaxi12-web.github.io`; repartir la nueva y pedir que cada usuario la pegue en Configuración.
- `erp_backend_key`, `mlToken`, `mlToken2`, `ecomCookie`, `ecomEmail` en el `localStorage` de cada navegador: se renuevan solos al rotar lo de arriba; para sacarlos de un navegador, cerrar sesión o borrar los datos del sitio.
- Credenciales dentro de **n8n** (Google/mail y las dos de arriba).
- `backend/credentials.json` (uso local de desarrollo, documentado en `CLAUDE.md`): **no está en el `.gitignore` de la raíz** (solo el del scraper la ignora). Hoy no está commiteado (verificado en todo el historial), pero un `git add .` accidental la subiría.

## 3. Lo que NO es secreto (para no perder tiempo rotando)
IDs de vendedor de ML y de planillas de Google, la dirección interna de la SQL de Táctica (`10.10.10.99`), URLs de ML y Ecom, nombres de pestañas, las direcciones de mail con las que se comparte el historial de conciliación (datos personales, no credenciales).

## 4. Búsqueda de secretos en el repo y en el historial
Método: `git grep` sobre **los 205 commits de todas las ramas** con patrones de: API keys de Google (`AIza…`), claves privadas PEM, JSON de cuenta de servicio (`"type": "service_account"`, `"private_key"`), tokens de ML (`APP_USR-`, `TG-`), claves de Tailscale (`tskey-`), tokens de GitHub, Anthropic/OpenAI, Slack, JWT, URLs con usuario y contraseña (`postgres://usuario:clave@…`), claves en la query (`?key=`, `?token=`), asignaciones de `password/secret/api_key/token/client_secret` a un texto largo; más una búsqueda de archivos agregados alguna vez con nombres de credenciales (`.env`, `credentials*`, `*.pem`, `*.key`, perfiles de Chrome, `.sqlite`).

| Hallazgo | Dónde | Detalle | Qué hacer |
|---|---|---|---|
| **API key de Google (`AIza…`)** | `docs/index.html`, 56 commits, **1 valor distinto** | Desde el commit `31a4880` (15/09/2026, primer commit) hasta que `21d13e6` (04/10/2026) la quitó. En todo el historial aparece **un solo valor**. No pego el valor | **Revocarla/regenerarla** (ver «API key de Google para Sheets» arriba) y restringirla. Reescribir historia no alcanza si el repo fue público o clonado |
| Ramas remotas que todavía la contienen en su punta | `origin/claude/apps-script-folder-detection-iaqyu9`, `origin/claude/clever-mendel-dsb1ta`, `origin/claude/funny-heisenberg-vcd1hw`, `origin/claude/loving-newton-wg28xw`, `origin/claude/magical-cori-40o1nx` | Ramas viejas anteriores a la limpieza | Borrarlas en GitHub si ya no se usan (decidilo vos; no borré nada) |
| Falsos positivos descartados | `.claude/skills/design-system/scripts/generate-slide.py:649` | Es la ruta de un archivo `design-tokens.css`, no un secreto | — |
| Sin hallazgos | resto | Ningún JSON de cuenta de servicio, PEM, token de ML, contraseña, URL de base con clave o clave de Tailscale en ningún commit | — |

Limitación: la búsqueda cubre este repositorio. No cubre capturas de pantalla (`docs/capturas_pr/`: son imágenes de pantallas con datos de prueba, no se leyeron píxel a píxel), ni lo que pudo pegarse en issues/PR de GitHub, ni los logs de Railway o de n8n.

## 5. Logs y mensajes de error: revisión (sin cambios hechos)
| Dónde | Qué pasa | Riesgo | Propuesta (para un PR de código, cuando lo pidas) |
|---|---|---|---|
| `backend/rentabilidad/api.py` (`_verificar_token_reporte`) y los endpoints `/rentabilidad/reporte/*` | Aceptan `RENT_REPORTE_TOKEN` por **`?token=` en la URL**, además del header. La comparación no es de tiempo constante | **Alto**: la URL con el token queda en los logs de acceso de Railway, en el historial de ejecuciones de n8n y en cualquier proxy | Aceptar solo el header `X-Reporte-Token`; comparar con `hmac.compare_digest`; rotar el token igual (la URL vieja pudo quedar registrada) |
| `backend/ml_auth.py:42` y `:63` | Imprime `res.text` de la respuesta de ML cuando falla la renovación del token | Bajo: es el cuerpo de error de ML (no incluye el secreto que enviamos), pero queda en los logs | Imprimir solo el código de estado y el campo `error` |
| `backend/main.py:61` | El handler global devuelve al navegador `Error interno: {exc}` y `:60` lo imprime con `repr` | Medio-bajo: un error de Postgres o de Táctica puede incluir host, puerto y usuario; los de `requests` incluyen la URL completa pedida | Devolver un mensaje genérico con un id de error y dejar el detalle solo en el log del servidor |
| `backend/main.py:265, 278, 312, 355, 375` (proxy de ML y similares) | `detail=str(e)` devuelve al cliente el texto de la excepción | Bajo-medio: mismas razones | Mensaje genérico + detalle solo en log |
| `backend/main.py:2330, 2580` | `No se pudo leer el Sheet de competencia: {e}` / `No se pudo consultar Mercado Libre: {e}` | Bajo | Idem |
| `backend/rentabilidad/ingesta_ecom_api.py` (`EcomApiError`) | Incluye el error de `requests` (URL base de Ecom, sin credenciales; el cuerpo del login no se imprime) | Bajo | — |
| `backend/main.py` (`/ecom/login`) | Recibe email y contraseña de Ecom en el cuerpo y **devuelve la cookie `CAKEPHP`** al navegador, que la guarda en `localStorage` | Medio: la cookie vale mientras dura la sesión (el código dice que vence cada día) | Dejarlo; al rotar la contraseña de Ecom se invalidan las sesiones |
| `backend/erp_auth.py:82` (modo permisivo) | Imprime método, ruta y origen de requests sin clave | Sin riesgo: no imprime la clave | — |
| `backend/scripts/migrar_competencia.py` | Arma URLs con `?key=<API key de Sheets>` | Bajo (script manual): si falla, el error de `urllib` puede mostrar la URL con la clave | Pasar la clave por header |
| Mis cambios recientes (`ml_foto.py`, `ml_full_foto.py`) | Los mensajes de error guardados y mostrados **ya salen sin URL** (`mensaje_para_usuario`) | — | — |

No encontré en el código ningún `print`/log que escriba el valor de `ERP_API_KEY`, `GOOGLE_CREDENTIALS_JSON`, `ML_*`, `RENT_ECOM_PASSWORD`, `RENT_DATABASE_URL`, `RENT_TACTICA_SQL_PASSWORD` ni `TS_AUTHKEY`. Los logs de Railway y de n8n **no se pueden ver desde el repo**: revisalos a mano buscando la URL de los reportes con `?token=`.

## 6. Orden de rotación sugerido y qué se rompe en cada paso
Criterio: primero lo que permite **escribir plata** (precios en Mercado Libre y Ecom) y lo que protege el acceso al backend; después los datos; al final lo que se rota sin impacto. Avisar a los usuarios antes de empezar: durante la rotación habrá pantallas con error.

| # | Qué rotar | Qué se rompe mientras tanto (y hasta cuándo) | Cómo verificar que quedó |
|---|---|---|---|
| 0 | **Preparación**: anotar quién usa el ERP; **no borrar** `ERP_API_KEY` ni `RENT_REPORTE_TOKEN` (sin ellas el backend queda abierto); revisar usuarios activos de Railway/GitHub/Google | Nada | — |
| 1 | **`ERP_API_KEY`** (valor nuevo en Railway; repartirlo a navegadores, PC del scraper, n8n, `subir_proyeccion`) | Cada navegador, el scraper y n8n reciben **401** en todo lo protegido (escrituras, `/ml/token`, `/ml-proxy`, competencia, proyección) hasta cargar la clave nueva. Lectura abierta sigue andando | Configuración → «Clave del backend» → Testear dice «clave OK» |
| 2 | **Mercado Libre**: regenerar `ML_CLIENT_SECRET`, reautorizar **las dos cuentas** (IT y MT) y cargar `ML_REFRESH_TOKEN`, `ML_REFRESH_TOKEN_2`, `ML_TOKEN`, `ML_TOKEN_2`; revocar el acceso viejo desde cada cuenta | Verificar ML, Full ML, Ofertas ML, Campañas, Análisis de Competencia (precios propios), Ayala Core y el simulador **no pueden leer ni escribir en ML** hasta cargar los tokens nuevos. **Cuidado**: el backend guarda el refresh token que ML entrega en cada renovación solo en memoria (`ml_auth.py`), no lo persiste en Railway; tras un reinicio vuelve a usar el de la variable. Cargar ambos pares **juntos** y no reiniciar mientras tanto | Full ML → Actualizar; Ofertas ML → cargar |
| 3 | **Ecom**: cambiar la contraseña del usuario y actualizar `RENT_ECOM_PASSWORD` (y `RENT_ECOM_EMAIL` si cambia) en backend **y** Cron | Verificar Ecom, costos del catálogo (la foto guardada sigue disponible), Ayala Core y el cierre diario de las 09:00 UTC fallan hasta actualizar. Los navegadores deben volver a iniciar sesión en Ecom (cookie vencida) | «Costos Ecom → Refrescar costos» funciona |
| 4 | **Postgres** (`RENT_DATABASE_URL`) | Backend y Cron **sin base**: Precios & Márgenes, cierres, fotos guardadas (Full ML), costos de Ecom, proyección 2027 y motor de precios dan error hasta redeployar con la conexión nueva. Corre en el arranque la migración de esquema | `/health`; abrir Precios & Márgenes |
| 5 | **Google**: nueva clave de la cuenta de servicio en `GOOGLE_CREDENTIALS_JSON` (backend y Cron) y en `scraper/credentials.json`; después borrar la clave vieja. **Regenerar y restringir la API key de Sheets** y repartir la nueva | Con la clave nueva cargada antes de borrar la vieja **no hay corte**. Al borrar la vieja sin haber cargado la nueva: sin Sheets en el backend (PM, categorías, competencia, historial, stock Táctica) y en el scraper. La API key vieja de Sheets deja de funcionar en el navegador: las pantallas que leen Sheets (Ventas, Histórico, Cobranzas, Brasil, planillas PM) muestran «Falta la API Key de Sheets» hasta que cada usuario pegue la nueva | Actualizar desde Sheets (Precios & Márgenes); Ventas carga datos |
| 6 | **Táctica SQL**: contraseña nueva del usuario SQL → `RENT_TACTICA_SQL_PASSWORD` | Costo e IVA de Táctica no responden: el IVA sale de Ecom (hay aviso en pantalla) y las funciones que leen Táctica por SQL fallan hasta actualizar | Verificar Táctica; Precios & Márgenes sin el aviso de IVA |
| 7 | **Tailscale**: revocar `TS_AUTHKEY` y cargar una nueva; borrar dispositivos desconocidos | El backend ya levantado **mantiene el túnel**; un redeploy sin la clave nueva se queda sin túnel a Táctica (queda el aviso, el resto anda) | Tras redeployar, el log dice «Túnel Tailscale arriba» |
| 8 | **`RENT_REPORTE_TOKEN`** (valor nuevo en Railway **y** en n8n) | Los mails diarios de n8n (Ecom, motor de precios) fallan con 401 hasta actualizar n8n | Ejecutar manualmente el flujo de n8n |
| 9 | **n8n y PC del scraper**: credenciales internas de n8n; en la PC, cambiar la contraseña de la cuenta de ML y cerrar sus sesiones, borrar y recrear `perfil_chrome/`, actualizar `ERP_API_KEY` | El scraper no corre hasta volver a iniciar sesión en ML | Corrida de prueba del scraper |
| 10 | **Limpieza**: borrar las 5 ramas remotas viejas (opcional), revisar quién tiene acceso a Railway/GitHub/Google Cloud/Tailscale, agregar `credentials.json` al `.gitignore` raíz | — | — |

Tiempo total estimado: la parte que más coordinación pide es la 1 (repartir la clave a todos) y la 5 (cada usuario pega la API key nueva de Sheets); conviene hacerlas fuera de horario de uso.

## 7. Qué necesito de vos
- La lista de **variables que aparecen en el panel de Railway** (solo nombres), para cruzar con la sección 2.
- Si el repositorio de GitHub es **público o privado**.
- Cuándo querés que haga los PR de código de la sección 5 (token solo por header, mensajes de error sin detalle, `.gitignore`). **No cambio nada hasta que me avises.**
