# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Ayala's ERP — an internal operations tool for Global Electronics covering sales dashboards, price
verification across sales channels (MercadoLibre, Ecom, Web/WooCommerce, Fravega), competitor
price tracking, and MercadoLibre offer management. There is no build system, package manager, or
test suite — the whole app is two files:

- `docs/index.html` — the entire frontend. A single static HTML file (~4500 lines: CSS, then one
  `<script>` block) with no framework, no bundler, no npm. It calls the Google Sheets API directly
  from the browser and calls the Python backend for anything requiring a secret (ML tokens, Ecom
  session cookies, Fravega API keys) or server-side scraping.
- `backend/main.py` — a FastAPI app that proxies/authenticates to MercadoLibre, Ecom
  (app.ecomexperts.com), Fravega, and does scraping/spreadsheet jobs. One file, no sub-modules.

## Running it

Backend (from `backend/`):
```
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```
Requires a `credentials.json` Google service account file in `backend/` (or a `GOOGLE_CREDENTIALS_JSON`
env var containing the same JSON) for Sheets/Drive access, plus `ML_TOKEN`, `ML_REFRESH_TOKEN`,
`ML_APP_ID`, `ML_CLIENT_SECRET`, `ML_TOKEN_2`, `ML_REFRESH_TOKEN_2` for MercadoLibre.

Frontend: `docs/index.html` is opened directly / served as a static file (it's a GitHub Pages site
at the repo's `docs/` folder). It has no dependency install step. On first load it needs a backend
URL entered in the "Configuración" page (saved to `localStorage` as `erp_backend_url`) and a Google
Sheets API key (`localStorage` `sheetsKey`) to pull data.

Deploy: the backend deploys to Railway via `backend/Dockerfile` + `backend/railway.json`
(`uvicorn main:app --host 0.0.0.0 --port ${PORT}`). The frontend deploys as GitHub Pages from
`docs/`. There are no CI checks, linters, or tests in this repo — verify changes by exercising the
page/endpoints manually.

## Architecture

### Backend (`backend/main.py`)

A single FastAPI app, organized into clearly delimited sections (look for the `# ══...` banner
comments) rather than routers/modules:

- **ML token** (`/ml/token`) — refreshes and caches MercadoLibre OAuth tokens for two seller
  accounts ("IT" and "MT"), each with its own token/refresh-token/expiry cache (`_token_cache`,
  `_token_cache_2`).
- **ML proxy** (`/ml-proxy*`) — generic passthrough to `api.mercadolibre.com` so the frontend never
  holds API secrets directly; accepts a caller-supplied token via the `x-vk-token` header, falling
  back to the server's own token. Includes a paginated "fetch all active listing ids for a seller"
  endpoint that has to page through MercadoLibre's `items/search` in three sort orders to work
  around its result-window limits.
- **ML auth** (`/ml/exchange`) — OAuth code exchange, redirect URI is hardcoded to the GitHub Pages
  URL.
- **ML tracker** (`/ml/tracker/run` + status polling) — background job that reads competitor
  MercadoLibre links from the "ML Competencia" tab of a fixed Google Sheet (`SPREADSHEET_ID`),
  scrapes each item/product via the ML API, and writes price/discount/installments back into the
  sheet.
- **ML vendedor** (`/ml/vendedor/run` + status polling) — background job using Selenium
  (headless Chrome via `webdriver-manager`) to scrape a competitor's full MercadoLibre storefront
  (title/price/discount/installments per listing), paginating through search results, and writes
  each vendor's catalog into its own `V - <nombre>` sheet tab.
- **Job status** — all background jobs (`tracker_job`, `vendedor_job`, `refresh_job`) share one
  `job_status` in-memory dict keyed by job id; there's no persistence, so job history is lost on
  restart. `/jobs` and `/jobs/{id}/log` expose it generically.
- **Ecom proxy** (`/ecom/*`) — logs into app.ecomexperts.com (`ecom_login`, extracts the `CAKEPHP`
  session cookie) and updates per-channel prices there. Price updates are the trickiest part: Ecom
  has no clean price-update API, so `ecom_update_price` fetches an HTML fragment
  (`prices_index`), scrapes hidden form field names/values out of it with regex
  (`ecom_parse_variants`) to recover each price-list row's ids, then re-POSTs the changed field as
  a form-encoded save. `name_map` normalizes loose price-list names ("web", "ml", "lista 1"...)
  to Ecom's exact list names.
- **Competidores refresh** (`/competidores/refresh`) — background job that reads every `V - *`
  vendor sheet tab (populated by the vendedor scraper), re-fetches current MercadoLibre prices for
  every MLA found, and appends a dated snapshot to a `Historial Competidores` tab, capped at
  `MAX_HISTORY_DATES` (10) distinct dates (oldest date's rows get pruned).
- **Tipo de cambio** (`/tc/bna`) — scrapes the Banco Nación page for the USD sell rate, regex-parsed
  out of the rendered HTML table, cached for 1 hour.

Google Sheets access always goes through `get_gs()`, which prefers `GOOGLE_CREDENTIALS_JSON` (env,
for Railway) over a local `credentials.json` file (for local dev).

### Frontend (`docs/index.html`)

Single-page app, no routing library: `goPage(pageName, el)` toggles `.page` divs
(`id="page-<name>"`) and sidebar items, and lazily loads each page's data the first time it's
visited (flags like `dashLoaded`/`histLoaded`/`cobrLoaded`/`brLoaded` prevent reloading). All
mutable app state lives in one global `S` object (tokens, connected-sheet configs, loaded rows,
pagination/sort state, tolerance thresholds) plus a handful of page-specific globals
(`allSalesData`, `COMP`, `intelHistory`, `ofertasData`, etc.). Persistence is `localStorage` only —
`saveStor()`/`loadStor()` round-trip most of `S`, and several features (Fravega creds, backend URL,
per-feature caches) use their own dedicated `localStorage` keys.

Data sources, none of which require the backend for *reading*:
- **Google Sheets, read via the public Sheets REST API** (`https://sheets.googleapis.com/v4/...`)
  called directly from the browser with an API key (`S.sheetsKey` or the fallback `API_KEY`
  constant). Each feature area has its own hardcoded spreadsheet id/tab/gid constants near the top
  of the script (`CATS_ID`, `TACTICA_ID`, `DASH_SHEET_ID`, `COMP_SHEET_ID`, `OFERTAS_ID`,
  `FRAVE_PUB_ID`, `WEB_WOO_ID`, `WEB_ECOM_ID`, etc.) — there is no config UI for most of these,
  they're baked into the code, so changing which sheet a feature reads means editing the constant.
  The "PM" sheets (`pm1..pm4`, one per price-manager person) are the exception: those ids/tabs are
  user-configurable in the Configuración page and stored in `S.sheets`.
- **CSV upload** for Ecom/Fravega exports, parsed client-side (`parseCSV`/`splitLine`, handles
  both `,` and `;` delimiters and quoted fields) via drag-and-drop or file input (`setupDZ`).
- **The FastAPI backend** for anything needing a secret or server execution: ML token exchange/
  proxying, Ecom login + price writes, Fravega API calls, competitor scraping jobs, BNA exchange
  rate. `getBackendUrl()` reads the URL the user configured; nearly every backend call fails
  silently into a toast if it's unset or unreachable.

Cross-cutting concepts used across most "verify X" pages (Ecom, ML, Táctica, Web, Fravega):
- **PM (price manager) data** — the source-of-truth prices per SKU, loaded from the pm1-4 sheets
  into `S.pmData[sku]`. Each "Verificar X" page compares what's live on that channel against the
  matching PM price and flags mismatches beyond `S.tolGreen`/`S.tolYellow` tolerance percentages.
- **RULES** — a fixed list of MercadoLibre "pricing rule" names → multiplier (e.g. installment
  markups, kit/pack discounts). `getRulePct()` + `calcExp()` derive the *expected* ML price from a
  PM base price, a rule, and a combo quantity, adding `S.shippingCost` once price crosses
  `S.shippingThreshold`.
- **Categories** — a separate sheet (`CATS_ID`, tab `GRAL CATEGORIAS`) mapping SKU → categoria/
  subcategoria/PM owner, loaded into `S.catData` and looked up via `catRec()`/`getCat()` (SKUs are
  normalized and a `pv-` prefix is stripped as a fallback lookup).
- **SKU normalization** (`normSku`) strips whitespace/zero-width characters and lowercases — used
  as the join key between PM data, category data, and each channel's rows, so most bugs in "why
  didn't this SKU match" trace back to normalization or a missing `normSku()` call somewhere in the
  chain.

Sidebar pages, grouped by what they do:
- **Ventas & Rentabilidad / Histórico / Cobranzas / Brasil** — sales dashboards built from the
  `DASH_SHEET_ID` sheet (multiple monthly tabs listed in `DASH_SHEETS`), with client-side filtering
  (date range, canal, categoria, PM, SKU) and Chart.js visualizations.
- **Verificar Ecom / Táctica / ML** — the price-reconciliation pages described above (Ecom's
  comparison table has Web and Fravega price-list columns built in — those are not separate pages);
  each has its own `render*()` function, its own sort/pagination state on `S`, and (for Ecom/ML)
  inline "fix" actions that write the corrected price back to the channel via the backend.
- **Rentabilidad Táctica** — margin/profitability calculator for the "Táctica" sales channel.
- **Ofertas ML** — bulk-manages MercadoLibre seller campaign offers/promotions across both seller
  accounts (IT/MT).
- **Competidores ML / Intel. Competitiva** — competitor price tracking UI on top of the
  `/ml/vendedor` and `/competidores/refresh` backend jobs and their sheet output.
- **Configuración / Reglas de Precio / ML Tools** — connects the backend URL, ML/Ecom accounts, PM
  sheets, and Sheets API key; edits the `RULES` multiplier table.

## Working in this codebase

- Both main files are effectively monolithic and minified-by-convention (long single-line
  functions, no whitespace formatting) rather than reformatted/refactored piecemeal — match the
  existing density when editing nearby code rather than reformatting whole functions.
- The frontend has no module system: every function and `const` in the `<script>` block is a
  global, and features are attached to `S` and looked up by page name string (`page-<name>` id,
  `data-page` attribute, and the `if(page==='...')` dispatch in `goPage`) — adding a new page means
  touching the sidebar HTML, a `page-<name>` div, and a branch in `goPage`.
- Secrets (ML tokens, Ecom cookie, Fravega keys, Sheets API key) live in the browser's
  `localStorage` and/or are passed through the backend per-request; there is no server-side user
  auth or session model.
