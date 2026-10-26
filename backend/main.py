"""
Ayala's ERP - Backend API
"""
from pydantic import BaseModel
from fastapi import FastAPI, BackgroundTasks, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import requests, re, time, os, gspread
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from starlette.concurrency import run_in_threadpool
from google.oauth2.service_account import Credentials
import json

import ml_full
import ml_reposicion
import ml_ofertas
import ayala_core
import competencia_db
from erp_auth import ClaveERPMiddleware
from ml_auth import APP_ID, CLIENT_SECRET, ML_TOKEN, get_ml_token, get_ml_token_2, ml_headers
from rentabilidad.adapters import CostoVigenteProvider, IvaProvider
from rentabilidad import costos_ecom
from rentabilidad.api import migrar_y_sembrar, router as rentabilidad_router
from rentabilidad.config import ConfiguracionFaltante
from proyeccion_snapshot import router as proyeccion_router
from ml_full_foto import router as ml_full_foto_router
from proyeccion_transito import router as transito_router

app = FastAPI(title="Ayala's ERP API", version="1.0.0")
# Orden: el último en agregarse es el más externo. CORS va por fuera de la clave
# para que el 401 también lleve headers CORS y el navegador pueda leerlo.
app.add_middleware(ClaveERPMiddleware)
# CORS cerrado al front en GitHub Pages. CORS_ORIGINS (separados por coma)
# reemplaza la lista, p. ej. para sumar http://localhost:5500 en desarrollo.
# Ojo: CORS solo frena a otros sitios web, no a curl -- la protección real es
# la clave X-ERP-Key (erp_auth.py).
_CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "https://ayalamaxi12-web.github.io").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Proyeccion-Version"])
app.include_router(rentabilidad_router)
app.include_router(proyeccion_router)
app.include_router(ml_full_foto_router)
app.include_router(transito_router)


# Starlette no agrega los headers de CORSMiddleware a una excepción que se
# escapa sin manejar (ServerErrorMiddleware, que sí devuelve el 500, corre
# POR FUERA de CORSMiddleware) — el navegador nunca llega a leer ese 500 y
# lo reporta como "Failed to fetch", sin mostrar el error real. Encontrado
# en vivo (2026-08-11) probando /rentabilidad/tactica/periodo sin
# RENT_TACTICA_SQL_* configurado. Estos handlers devuelven una Response
# normal, que sí pasa por el middleware con los headers correctos.
@app.exception_handler(ConfiguracionFaltante)
async def _configuracion_faltante_handler(request: Request, exc: ConfiguracionFaltante):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(Exception)
async def _error_no_manejado_handler(request: Request, exc: Exception):
    print(f"Error no manejado en {request.url.path}: {exc!r}")
    return JSONResponse(status_code=500, content={"detail": f"Error interno: {exc}"})


@app.on_event("startup")
def _rentabilidad_startup():
    # Crea el esquema (Alembic) y siembra las tablas paramétricas. No debe
    # tumbar el resto del ERP si la base de Rentabilidad no está disponible
    # todavía (ej. RENT_DATABASE_URL sin configurar en un deploy nuevo).
    try:
        migrar_y_sembrar()
    except Exception as e:
        print(f"Rentabilidad: no se pudo migrar/sembrar en el arranque: {e}")
    # El catálogo de costos de Ecom se guarda en la base (una foto por refresco). Acá solo se carga a memoria
    # (milisegundos) y, si no hay una foto de las últimas 24 h, se baja una nueva en este hilo aparte (~80 s).
    import threading
    threading.Thread(target=costos_ecom.precalentar, daemon=True).start()

SPREADSHEET_ID = '15b9kMzQFHdBOE5_7vWgriiiulHI6Yc9upJBUBBiXepY'
# "VENTAS POR CANALES MATIAS" -- Excel real de Matías donde vive el control
# de precios de las planchas de sublimación (Ayala Core), pestaña "ERP
# AYALA". Ver ayala_core_precios_excel más abajo.
EXCEL_MATIAS_ID = '1aCQx9iQoLDoT0G-P0vRfRJ-MV9rH7hBeRxXyacWtdXk'
EXCEL_MATIAS_TAB = 'ERP AYALA'

job_status = {}

def get_gs():
    creds_json = os.getenv('GOOGLE_CREDENTIALS_JSON')
    if creds_json:
        creds = Credentials.from_service_account_info(json.loads(creds_json),
            scopes=['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive'])
    else:
        creds = Credentials.from_service_account_file('credentials.json',
            scopes=['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive'])
    return gspread.authorize(creds)

def extract_ids(url):
    ids = {'item_id': None, 'product_id': None}
    for pat, key in [
        (r'item_id:(ML[A-Z]+\d+)', 'item_id'),
        (r'[?&#]wid=(ML[A-Z]+\d+)', 'item_id'),
        (r'/(MLA\d{8,})', 'item_id'),
        (r'searchVariation=(ML[A-Z]+\d+)', 'product_id'),
        (r'/p/(ML[A-Z]+\d+)', 'product_id'),
        (r'/up/(ML[A-Z]+\d+)', 'product_id'),
    ]:
        m = re.search(pat, url, re.I)
        if m and not ids[key]:
            ids[key] = m.group(1)
    return ids

# ══════════════════════════════════════════════════════
# IDENTIDAD ML — capa F0 (Data Quality)
# Aislada: todavía no la usa ningún endpoint/job. No reemplaza a
# extract_mla/extract_ids en producción hasta que se apruebe ese paso.
# ══════════════════════════════════════════════════════

_ML_PATH_ITEM_RE = re.compile(r'/(ML[A-Z]+-?\d{8,})')
_ML_PATH_PRODUCT_P_RE = re.compile(r'/p/(ML[A-Z]+-?\d+)', re.I)
_ML_PATH_PRODUCT_UP_RE = re.compile(r'/up/(ML[A-Z]+-?\d+)', re.I)
_ML_PARAM_ITEM_ID_RE = re.compile(r'item_id:(ML[A-Z]+-?\d+)', re.I)
_ML_PARAM_WID_RE = re.compile(r'[?&#]wid=(ML[A-Z]+-?\d+)', re.I)
_ML_PARAM_SEARCHVAR_RE = re.compile(r'searchVariation=(ML[A-Z]+-?\d+)', re.I)

def _split_url_zones(link):
    """Separa la URL en (path, resto) donde resto = todo desde el primer '?' o '#' en adelante."""
    s = str(link) if link is not None else ''
    for sep in ('?', '#'):
        idx = s.find(sep)
        if idx != -1:
            return s[:idx], s[idx:]
    return s, ''

def _normalize_ml_id(raw_id):
    """Colapsa variantes con/sin separador ('MLA-123' y 'MLA123') a una forma canónica."""
    return re.sub(r'[^A-Z0-9]', '', raw_id.upper())

def resolve_ml_identity(link):
    """
    Contrato de identidad ML aprobado para F0 (Data Quality — Competitors).
    Devuelve dict {estado, tipo, identificador, link_origen}.
    estado: 'Sin Link' | 'Sin Identificador' | 'Identificador Válido'
    tipo:   'item_id' | 'product_id' | None
    No lanza excepciones ante entradas vacías, None o sin formato de URL.
    """
    origen = link
    s = str(link).strip() if link is not None else ''
    if not s:
        return {'estado': 'Sin Link', 'tipo': None, 'identificador': None, 'link_origen': origen}

    path, _resto = _split_url_zones(s)

    # item_id tiene prioridad: primero el permalink de path (zona más confiable),
    # luego los marcadores nombrados (item_id:/wid=, ya auto-anclados por su propio
    # literal, por eso se buscan sobre el string completo y no solo sobre "resto")
    for pat, zona in ((_ML_PATH_ITEM_RE, path), (_ML_PARAM_ITEM_ID_RE, s), (_ML_PARAM_WID_RE, s)):
        m = pat.search(zona)
        if m:
            return {'estado': 'Identificador Válido', 'tipo': 'item_id',
                    'identificador': _normalize_ml_id(m.group(1)), 'link_origen': origen}

    # product_id: solo si no se encontró item_id
    for pat, zona in ((_ML_PATH_PRODUCT_P_RE, path), (_ML_PATH_PRODUCT_UP_RE, path), (_ML_PARAM_SEARCHVAR_RE, s)):
        m = pat.search(zona)
        if m:
            return {'estado': 'Identificador Válido', 'tipo': 'product_id',
                    'identificador': _normalize_ml_id(m.group(1)), 'link_origen': origen}

    return {'estado': 'Sin Identificador', 'tipo': None, 'identificador': None, 'link_origen': origen}

def fetch_item(item_id):
    r = requests.get(f'https://api.mercadolibre.com/items/{item_id}', headers=ml_headers(), timeout=10)
    return r.json() if r.status_code == 200 else None

def fetch_product(product_id):
    if product_id.upper().startswith('MLAU'): return None
    r = requests.get(f'https://api.mercadolibre.com/products/{product_id}', headers=ml_headers(), timeout=10)
    if r.status_code != 200: return None
    data = r.json()
    if not data.get('buy_box_winner'):
        r2 = requests.get(f'https://api.mercadolibre.com/products/{product_id}/items?limit=1', headers=ml_headers(), timeout=10)
        if r2.status_code == 200:
            results = r2.json().get('results', [])
            if results:
                first = results[0]
                if isinstance(first, dict) and first.get('price', 0) > 0:
                    first['title'] = first.get('title') or data.get('name', '')
                    return first
                elif isinstance(first, str):
                    item = fetch_item(first)
                    if item:
                        item['title'] = item.get('title') or data.get('name', '')
                        return item
    return data

def fetch_seller(seller_id):
    if not seller_id: return ''
    r = requests.get(f'https://api.mercadolibre.com/users/{seller_id}', headers=ml_headers(), timeout=10)
    return r.json().get('nickname', '') if r.status_code == 200 else ''

def parse_item(data, tipo='item'):
    if not data: return None
    if tipo == 'product':
        w = data.get('buy_box_winner') or {}
        title = data.get('name') or data.get('title', '')
        price = w.get('price', 0) or data.get('price', 0)
        orig = w.get('original_price') or data.get('original_price')
        seller = w.get('seller_id') or data.get('seller_id')
        inst = w.get('installments') or data.get('installments')
        nick = ''
    else:
        title = data.get('title', '')
        price = data.get('price', 0)
        orig = data.get('original_price')
        seller = data.get('seller_id')
        nick = (data.get('seller') or {}).get('nickname', '')
        inst = data.get('installments')
    discount = f"{round((1-price/orig)*100)}%" if orig and orig > price else ''
    cuotas = 'Sin cuotas'
    if inst and inst.get('quantity', 1) > 1:
        m = f"${round(inst['amount']):,}".replace(',', '.')
        s = ' sin interés' if inst.get('rate', 1) == 0 else ''
        cuotas = f"{inst['quantity']}x {m}{s}"
    return {'title': title, 'price': price, 'orig_price': orig,
            'discount': discount, 'cuotas': cuotas, 'seller_id': seller, 'seller_nick': nick}

@app.get("/")
def root():
    return {"app": "Ayala's ERP", "version": "1.0.0", "status": "online"}

@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now().isoformat()}

@app.post("/auth/check")
def auth_check():
    """Para que el front verifique su clave sin efectos: es POST, así que el
    middleware exige X-ERP-Key (401 si es mala). `clave_activa` dice si el
    backend ya la está exigiendo (ERP_API_KEY definida) o sigue permisivo."""
    return {"ok": True, "clave_activa": bool(os.environ.get("ERP_API_KEY", "").strip())}

# ══════════════════════════════════════════════════════
# ML TOKEN
# ══════════════════════════════════════════════════════

@app.get("/ml/token")
async def ml_get_token(account: str = "IT"):
    """Get fresh ML token for IT or MT account"""
    if account == "MT":
        return {"token": get_ml_token_2(), "account": "MT", "seller_id": "34801784"}
    return {"token": get_ml_token(), "account": "IT", "seller_id": "115764017"}

# ══════════════════════════════════════════════════════
# ML PROXY
# ══════════════════════════════════════════════════════

@app.get("/ml-proxy")
async def ml_proxy_get(request: Request, path: str):
    token = request.headers.get("x-vk-token", "")
    headers = {"Authorization": f"Bearer {token}"} if token else ml_headers()
    try:
        r = requests.get(f"https://api.mercadolibre.com/{path.lstrip('/')}", headers=headers, timeout=20)
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/ml-proxy/{mla}")
async def ml_proxy_put(mla: str, request: Request):
    token = request.headers.get("x-vk-token", "")
    auth = f"Bearer {token}" if token else ml_headers()["Authorization"]
    body = await request.json()
    try:
        r = requests.put(f"https://api.mercadolibre.com/items/{mla}",
            headers={"Authorization": auth, "Content-Type": "application/json"},
            json=body, timeout=20)
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ml-proxy")
async def ml_proxy_post(request: Request):
    """Generic ML proxy for PUT/POST/DELETE operations"""
    body = await request.json()
    token = request.headers.get("x-vk-token", "")
    if not token:
        token = get_ml_token()
    method = body.get("method", "PUT").upper()
    path = body.get("path", "")
    payload = body.get("body", {})
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    url = f"https://api.mercadolibre.com/{path}"
    try:
        if method == "PUT":
            r = requests.put(url, headers=headers, json=payload, timeout=15)
        elif method == "POST":
            r = requests.post(url, headers=headers, json=payload, timeout=15)
        elif method == "DELETE":
            r = requests.delete(url, headers=headers, timeout=15)
        else:
            raise HTTPException(status_code=400, detail=f"Method {method} not supported")
        try:
            return r.json()
        except:
            return {"status": r.status_code, "body": r.text[:500]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/ml-proxy/all-ids/{seller_id}")
async def ml_proxy_all_ids(seller_id: str, request: Request, token: str = ""):
    if not token:
        token = request.headers.get("x-vk-token", "")
    headers = {"Authorization": f"Bearer {token}"} if token else ml_headers()
    ids = []; total = 0; seen = set()
    def fetch_range(sort_order="desc"):
        for offset in range(0, 1000, 100):
            url = f"https://api.mercadolibre.com/users/{seller_id}/items/search?status=active&limit=100&offset={offset}&sort=start_time_{sort_order}"
            r = requests.get(url, headers=headers, timeout=20)
            d = r.json()
            nonlocal total
            if "paging" in d: total = d["paging"].get("total", total)
            results = d.get("results", [])
            if not results: break
            for rid in results:
                if rid not in seen: seen.add(rid); ids.append(rid)
            if len(results) < 100: break
    try:
        fetch_range("desc"); fetch_range("asc")
        for offset in range(0, 1000, 100):
            if len(ids) >= total: break
            url = f"https://api.mercadolibre.com/users/{seller_id}/items/search?status=active&limit=100&offset={offset}&sort=price_desc"
            r = requests.get(url, headers=headers, timeout=20)
            d = r.json(); results = d.get("results", [])
            if not results: break
            for rid in results:
                if rid not in seen: seen.add(rid); ids.append(rid)
            if len(results) < 100: break
        return {"ids": ids, "total": total, "fetched": len(ids)}
    except Exception as e:
        return {"ids": ids, "total": total, "fetched": len(ids), "error": str(e)}

@app.get("/ml-proxy/visits")
async def ml_proxy_visits(ids: str, request: Request):
    token = request.headers.get("x-vk-token", "")
    headers = {"Authorization": f"Bearer {token}"} if token else ml_headers()
    try:
        r = requests.get(f"https://api.mercadolibre.com/items/visits?ids={ids}", headers=headers, timeout=15)
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ══════════════════════════════════════════════════════
# ML AUTH
# ══════════════════════════════════════════════════════

@app.post("/ml/exchange")
async def ml_exchange(request: Request):
    body = await request.json()
    code = body.get("code", "")
    if not code:
        raise HTTPException(status_code=400, detail="code requerido")
    try:
        r = requests.post("https://api.mercadolibre.com/oauth/token", data={
            "grant_type": "authorization_code", "client_id": APP_ID,
            "client_secret": CLIENT_SECRET, "code": code,
            "redirect_uri": "https://ayalamaxi12-web.github.io/Ayala-s-ERP/",
        }, timeout=15)
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ══════════════════════════════════════════════════════
# ML TRACKER
# ══════════════════════════════════════════════════════

@app.post("/ml/tracker/run")
async def run_tracker(background_tasks: BackgroundTasks):
    job_id = f"tracker_{int(time.time())}"
    job_status[job_id] = {"status": "running", "started": datetime.now().isoformat(), "log": []}
    background_tasks.add_task(tracker_job, job_id)
    return {"job_id": job_id, "status": "started"}

def tracker_job(job_id):
    log = job_status[job_id]["log"]
    try:
        ss = get_gs().open_by_key(SPREADSHEET_ID)
        try:
            sheet = ss.worksheet('ML Competencia')
        except:
            sheet = ss.add_worksheet('ML Competencia', 500, 10)
            sheet.append_row(['Link ML','Título','Vendedor','Precio Real ($)','Precio Tachado ($)','Descuento %','Cuotas','Último Update'])
        all_values = sheet.get_all_values()
        filas_datos = all_values[1:]
        ok = errors = 0; batch = []; lecturas_hist = []
        for i, row in enumerate(filas_datos):
            job_status[job_id]["progress"] = {"current": i, "total": len(filas_datos), "label": "Consultando links"}
            url = row[0].strip() if row else ''
            if not url: continue
            row_num = i + 2
            try:
                ids = extract_ids(url)
                data = None
                if ids['item_id']: data = fetch_item(ids['item_id'])
                if not data and ids['product_id']: data = fetch_product(ids['product_id'])
                tipo = 'item' if ids['item_id'] and data else 'product'
                parsed = parse_item(data, tipo)
                if not parsed:
                    batch.append({'range': f'B{row_num}', 'values': [['❌ Sin datos']]}); errors += 1; continue
                nick = parsed['seller_nick'] or (fetch_seller(parsed['seller_id']) if parsed['seller_id'] else '')
                now = datetime.now().strftime('%d/%m/%Y %H:%M')
                batch.append({'range': f'B{row_num}:H{row_num}', 'values': [[
                    parsed['title'], nick, parsed['price'],
                    parsed['orig_price'] or '', parsed['discount'] or 'Sin descuento',
                    parsed['cuotas'], now]]})
                lecturas_hist.append({'link': url, 'entidad': nick, 'precio': parsed['price'],
                                      'tachado': parsed['orig_price'] or '', 'descuento': parsed['discount'] or '',
                                      'cuotas': parsed['cuotas'], 'estado': 'OK', 'metodo': 'API'})
                ok += 1; time.sleep(0.5)
            except Exception as e:
                log.append(f"❌ Fila {row_num}: {e}"); errors += 1
        if batch: sheet.batch_update(batch)
        competencia_db.registrar_lecturas_seguro(ss, lecturas_hist, 'ML Competencia (tracker)', log)
        job_status[job_id] = {"status": "done", "ok": ok, "errors": errors, "log": log, "finished": datetime.now().isoformat()}
    except Exception as e:
        job_status[job_id] = {"status": "error", "message": str(e), "log": log}

@app.get("/ml/tracker/status/{job_id}")
def tracker_status(job_id: str):
    return job_status.get(job_id, {"status": "not_found"})

# ══════════════════════════════════════════════════════
# ML FULL — conciliación de stock (docs/business/COMERCIAL/canales/
# mercadolibre/03_MODULO_FULL.md). Solo lectura, ninguna escritura al
# canal ni a Ecom. Job propio en ml_full.py (no comparte job_status con
# el resto para no acoplar ese módulo a main.py).
# ══════════════════════════════════════════════════════

@app.post("/ml-full/conciliar/run")
async def ml_full_conciliar_run(background_tasks: BackgroundTasks):
    job_id = f"mlfull_{int(time.time())}"
    background_tasks.add_task(ml_full.iniciar_job, job_id)
    return {"job_id": job_id, "status": "started"}

@app.get("/ml-full/conciliar/status/{job_id}")
async def ml_full_conciliar_status(job_id: str):
    return ml_full.estado_job(job_id) or {"status": "not_found"}

# ══════════════════════════════════════════════════════
# ML FULL — simulador de reposición (mismo doc, §5 y §10 puntos 5/12).
# Sigue siendo de solo lectura: calcula y muestra cuánto convendría
# enviar, no crea el envío real en Mercado Libre. Job propio en
# ml_reposicion.py, no compartido con ml_full.py ni con main.py.
# ══════════════════════════════════════════════════════

@app.post("/ml-full/reposicion/run")
async def ml_full_reposicion_run(
    background_tasks: BackgroundTasks, fecha_llegada: date, dias_ventas: int = 30, semanas_objetivo: float = 3,
):
    job_id = f"mlrepo_{int(time.time())}"
    background_tasks.add_task(
        ml_reposicion.iniciar_job, job_id, None, None, dias_ventas, semanas_objetivo, fecha_llegada,
    )
    return {"job_id": job_id, "status": "started"}

@app.get("/ml-full/reposicion/status/{job_id}")
async def ml_full_reposicion_status(job_id: str):
    return ml_reposicion.estado_job(job_id) or {"status": "not_found"}

def _reposicion_pdf_sync(contenido: bytes) -> dict:
    return {"pendientes_por_inventory": ml_reposicion.parsear_pdf_envio_pendiente(contenido)}

@app.post("/ml-full/reposicion/pdf-envio-pendiente")
async def ml_full_reposicion_pdf(archivo: UploadFile = File(...)):
    """Sube el PDF "Instrucciones de preparación" de un envío Full en
    preparación (lo descarga Maxx a mano del panel de Full de ML -- ver
    docstring de `parsear_pdf_envio_pendiente`, no hay API pública para
    esto). Devuelve `{inventory_id: unidades}` para que el frontend
    complete "Envíos pendientes (paq.)" -- no escribe nada, solo lectura."""
    contenido = await archivo.read()
    return await run_in_threadpool(_reposicion_pdf_sync, contenido)

# ══════════════════════════════════════════════════════
# CAMPAÑAS ML (Excel de la Central de Promociones)
# ══════════════════════════════════════════════════════
import campanas_ml_xlsx

def _campanas_leer_sync(contenido: bytes) -> dict:
    try:
        r = campanas_ml_xlsx.leer_promociones(contenido)
    except campanas_ml_xlsx.ExcelInvalido as e:
        raise HTTPException(status_code=422, detail=str(e))
    f = r["filas"]
    return {"campana": r["campana"], "hojas": r["hojas"], "filas": len(f), "tipo": r["tipo"],
            "col_editable": r["col_editable"], "avisos": r["avisos"],
            "editables": sum(1 for x in f if x["editable"]),
            "con_aporte_ml": sum(1 for x in f if x.get("MELI_PERCENTAGE")),
            "sin_sku": sum(1 for x in f if not x.get("SKU")), "muestra": f[:3]}

@app.post("/campanas-ml/leer")
async def campanas_ml_leer(archivo: UploadFile = File(...)):
    """Lee el Excel de una campaña (solo lectura, no guarda nada)."""
    return await run_in_threadpool(_campanas_leer_sync, await archivo.read())

def _campanas_probar_hoja_sync(contenido: bytes) -> tuple[bytes, dict]:
    try:
        r = campanas_ml_xlsx.leer_promociones(contenido)
        filas = [[x["ITEM_ID"], x.get("SKU"), x.get("ORIGINAL_PRICE"), x.get("SELLER_PERCENTAGE"),
                  (x.get("SELLER_PERCENTAGE"), "copiar"), "prueba C0"] for x in r["filas"]]
        nuevo, info = campanas_ml_xlsx.agregar_hoja(
            contenido, "ERP Prueba", ["ITEM_ID", "SKU", "PRECIO ORIGINAL", "% ACTUAL", "VALOR A COPIAR", "NOTA"], filas)
    except campanas_ml_xlsx.ExcelInvalido as e:
        raise HTTPException(status_code=422, detail=str(e))
    return nuevo, {**info, **campanas_ml_xlsx.verificar_integridad(contenido, nuevo, info["hoja"])}

@app.post("/campanas-ml/probar-hoja")
async def campanas_ml_probar_hoja(archivo: UploadFile = File(...)):
    """C0: devuelve el MISMO xlsx con una hoja de prueba agregada, para verificar
    que ML lo acepta al subirlo. El informe de integridad va en `X-Integridad`."""
    from fastapi.responses import Response
    nuevo, rep = await run_in_threadpool(_campanas_probar_hoja_sync, await archivo.read())
    return Response(nuevo, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"X-Integridad": json.dumps({"ok": rep["ok"], "problemas": rep["problemas"]}),
                             "Access-Control-Expose-Headers": "X-Integridad",
                             "Content-Disposition": 'attachment; filename="campana_con_hoja_prueba.xlsx"'})

def _campanas_contexto(db_fn):
    from rentabilidad import motor_precios
    from rentabilidad.api import _datos_sku_fn, _resolver_tc
    from rentabilidad.cierre_ecom_diario import ayer_en_argentina
    from datetime import timedelta
    return motor_precios, _datos_sku_fn, _resolver_tc, ayer_en_argentina() + timedelta(days=1)

_CAMP_CTX = {"t": 0.0, "datos": None, "avisos": []}

def _campanas_datos(datos_sku_fn, avisos: list, ttl: int = 300):
    """Costo/IVA/PM por SKU de Ecom + GRAL CATEGORIAS: armarlo (catálogo y Sheet) es lo caro de cada pedido, así que se
    reutiliza 5 minutos. Los avisos de la carga se repiten en cada respuesta."""
    if _CAMP_CTX["datos"] is not None and time.time() - _CAMP_CTX["t"] < ttl:
        avisos.extend(_CAMP_CTX["avisos"])
        return _CAMP_CTX["datos"]
    av: list = []
    datos = datos_sku_fn(av)
    _CAMP_CTX.update(t=time.time(), datos=datos, avisos=av)
    avisos.extend(av)
    return datos

def _campanas_objetivo(margen_objetivo: str | None):
    try:
        return Decimal(margen_objetivo) / 100 if margen_objetivo else None
    except Exception:
        raise HTTPException(status_code=422, detail=f"margen_objetivo no numérico: {margen_objetivo!r}")

def _campanas_analizar_sync(contenido: bytes, tc: str | None, margen_objetivo: str | None, plan_objetivo: str = "contado",
                            cuenta: str | None = None) -> dict:
    from ml_auth import SELLERS
    from rentabilidad import campanas_ml
    from rentabilidad.db import sesion
    import campanas_ml_comision
    import campanas_ml_cuentas
    motor_precios, datos_sku_fn, resolver_tc, fecha = _campanas_contexto(None)
    try:
        leido = campanas_ml_xlsx.leer_promociones(contenido)
    except campanas_ml_xlsx.ExcelInvalido as e:
        raise HTTPException(status_code=422, detail=str(e))
    objetivo, avisos = _campanas_objetivo(margen_objetivo), []
    if cuenta and cuenta not in SELLERS:
        raise HTTPException(status_code=422, detail=f"Cuenta desconocida: {cuenta!r} (opciones: {list(SELLERS)})")
    filas = leido["filas"]
    ids = [f["ITEM_ID"] for f in filas]
    try:
        det, av = campanas_ml_cuentas.detectar(ids)
        avisos += av
    except Exception as e:  # sin token / ML caído: se sigue sin cuenta
        det = {}
        avisos.append(f"No se pudo detectar la cuenta ni completar SKUs desde ML ({type(e).__name__}: {e}).")
    # Comisión REAL de cada publicación (Cargo por vender), por par categoría/tipo de ML; si falla, tabla por categoría.
    comisiones_ml: dict = {}
    try:
        comisiones_ml, av = campanas_ml_comision.comisiones(
            {f["ITEM_ID"]: {"category_id": (det.get(f["ITEM_ID"]) or {}).get("category_id"),
                            "listing_type_id": (det.get(f["ITEM_ID"]) or {}).get("listing_type_id"),
                            "precio": f.get("ORIGINAL_PRICE")} for f in filas})
        avisos += av
    except Exception as e:  # noqa: BLE001
        avisos.append(f"No se pudo leer la comisión real de ML ({type(e).__name__}: {e}): se usa la tabla por categoría.")
    completados = 0
    for f in filas:
        d = det.get(f["ITEM_ID"]) or {}
        c = comisiones_ml.get(f["ITEM_ID"])
        if c:
            f["comision_real"], f["comision_origen"] = c["pct"], "ml"
        f["cuenta"] = cuenta or d.get("cuenta")      # la cuenta elegida a mano manda sobre la detectada
        if not f.get("SKU") and d.get("sku_ml"):
            f["SKU"], f["sku_origen"], completados = d["sku_ml"], "ml", completados + 1
    if completados:
        avisos.append(f"{completados} filas sin SKU en el Excel se completaron con el SKU de la publicación en ML.")
    if cuenta:
        otras = [f["ITEM_ID"] for f in filas if (det.get(f["ITEM_ID"]) or {}).get("cuenta") not in (None, cuenta)]
        if otras:
            avisos.append(f"Elegiste la cuenta {cuenta}, pero {len(otras)} publicaciones son de la otra cuenta (ej. {otras[0]}): revisalas.")
    tc_valor = resolver_tc(tc)
    datos = _campanas_datos(datos_sku_fn, avisos)
    with sesion() as db:
        r = campanas_ml.analizar(db, filas, fecha, tc_valor, datos, motor_precios.cargar_parametros(db, fecha),
                                 margen_objetivo=objetivo, plan_objetivo=plan_objetivo)
    resumen = campanas_ml_cuentas.resumen_cuentas(det, ids)
    if cuenta:
        resumen = {**resumen, "sugerida": cuenta, "elegida": True}
    return {**r, "campana": leido["campana"], "tipo": leido["tipo"], "col_editable": leido["col_editable"],
            "avisos": leido["avisos"] + avisos, "cuentas": resumen,
            "comisiones_ml": sorted({(c["categoria"], c["tipo"], float(c["pct"]) * 100) for c in comisiones_ml.values()})}

@app.post("/campanas-ml/analizar")
async def campanas_ml_analizar(archivo: UploadFile = File(...), tc: str | None = None, margen_objetivo: str | None = None,
                               plan_objetivo: str = "contado", cuenta: str | None = None):
    """C1/C2: cruza cada fila del Excel con el PM y el costo de Ecom, detecta la cuenta (IT/MT) por ITEM_ID
    y devuelve el margen a precio de oferta (contado/3/6/9/12) con la regla del aporte de ML. Solo lectura.
    `margen_objetivo` (en %, ej. 20) agrega el mayor % entero de descuento que lo cumple para `plan_objetivo`."""
    return await run_in_threadpool(_campanas_analizar_sync, await archivo.read(), tc, margen_objetivo, plan_objetivo, cuenta)

class _SimularIn(BaseModel):
    filas: list[dict]
    tc: str | None = None
    margen_objetivo: str | None = None
    plan_objetivo: str = "contado"

def _campanas_simular_sync(body: "_SimularIn") -> dict:
    """Recalcula filas con el descuento TOTAL que se está jugando (`descuento_pct`, entero 5–80). ML mantiene su aporte
    (`meli_pct` / `meli_monto`) y el vendedor pone el resto. Cada fila: item_id, sku, precio_original, descuento_pct,
    meli_pct, meli_monto, editable, titulo."""
    from rentabilidad import campanas_ml
    from rentabilidad.db import sesion
    motor_precios, datos_sku_fn, resolver_tc, fecha = _campanas_contexto(None)
    if len(body.filas) > 3000:
        raise HTTPException(status_code=422, detail="Demasiadas filas en un pedido (máx. 3000).")
    def fila(f):
        # Lo que se juega es el descuento TOTAL (entero); ML mantiene su aporte y el vendedor pone el resto.
        orig = f["precio_original"]
        meli = f.get("meli_pct") or 0
        if f.get("meli_monto"):
            meli = f["meli_monto"] / orig * 100
        total = f.get("descuento_pct")
        seller = f.get("seller_pct") if total is None else total - meli
        return {"fila": f.get("fila"), "ITEM_ID": f.get("item_id"), "SKU": f.get("sku"), "TITLE": f.get("titulo"),
                "ORIGINAL_PRICE": orig, "SELLER_PERCENTAGE": seller, "MELI_PERCENTAGE": meli or None,
                "DISCOUNT_PERCENTAGE": total, "editable": f.get("editable", True), "cuenta": f.get("cuenta"),
                "comision_real": f.get("comision"), "comision_origen": f.get("comision_origen")}
    filas = [fila(f) for f in body.filas if f.get("item_id") and f.get("precio_original")]
    avisos = []
    tc_valor, objetivo = resolver_tc(body.tc), _campanas_objetivo(body.margen_objetivo)
    datos = _campanas_datos(datos_sku_fn, avisos)
    with sesion() as db:
        r = campanas_ml.analizar(db, filas, fecha, tc_valor, datos, motor_precios.cargar_parametros(db, fecha),
                                 margen_objetivo=objetivo, plan_objetivo=body.plan_objetivo)
    return {**r, "avisos": avisos}

@app.post("/campanas-ml/simular")
async def campanas_ml_simular(body: _SimularIn):
    return await run_in_threadpool(_campanas_simular_sync, body)

def _campanas_exportar_sync(contenido: bytes, payload: str) -> tuple[bytes, dict]:
    """C3: el MISMO Excel de ML con la hoja "ERP Análisis" agregada (todas las filas, VALOR A COPIAR). Todo lo que se escribe sale del
    análisis del backend con los descuentos que mandó la pantalla; `Promociones` no se toca."""
    import campanas_ml_export
    from rentabilidad import campanas_ml
    from rentabilidad.db import sesion
    try:
        p = json.loads(payload)
        enviadas = {int(f["fila"]): f for f in p["filas"]}
    except Exception:
        raise HTTPException(status_code=422, detail="El detalle de filas a exportar no es válido.")
    try:
        leido = campanas_ml_xlsx.leer_promociones(contenido)
    except campanas_ml_xlsx.ExcelInvalido as e:
        raise HTTPException(status_code=422, detail=str(e))
    motor_precios, datos_sku_fn, resolver_tc, fecha = _campanas_contexto(None)
    originales = {f["fila"]: f for f in leido["filas"]}
    filas, avisos = [], []
    for f in leido["filas"]:
        e = enviadas.get(f["fila"])
        if e is not None and e.get("item_id") != f["ITEM_ID"]:
            raise HTTPException(status_code=422, detail=f"La fila {f['fila']} no coincide con el Excel (¿es otro archivo?).")
        orig = f["ORIGINAL_PRICE"]
        meli = (e or {}).get("meli_monto") or f.get("MELI_AMOUNT") or 0
        total = (e or {}).get("descuento_pct")
        fila = dict(f)
        if e is not None and total is not None and orig:
            fila.update(SELLER_PERCENTAGE=total - meli / orig * 100, SELLER_AMOUNT=None, MELI_AMOUNT=meli or None,
                        MELI_PERCENTAGE=meli / orig * 100 if meli else None, DISCOUNT_PERCENTAGE=total)
        if e is not None:
            fila.update(cuenta=e.get("cuenta"), comision_real=e.get("comision"), comision_origen=e.get("comision_origen"))
            if not fila.get("SKU") and e.get("sku"):
                fila["SKU"] = e["sku"]
        filas.append(fila)
    tc_valor = resolver_tc(p.get("tc"))
    datos = _campanas_datos(datos_sku_fn, avisos)
    with sesion() as db:
        analisis = campanas_ml.analizar(db, filas, fecha, tc_valor, datos, motor_precios.cargar_parametros(db, fecha))
    enc, cuerpo = campanas_ml_export.construir(analisis, leido["tipo"], originales)
    try:
        nuevo, info = campanas_ml_xlsx.agregar_hoja(contenido, campanas_ml_export.NOMBRE_HOJA, enc, cuerpo)
    except campanas_ml_xlsx.ExcelInvalido as e:
        raise HTTPException(status_code=422, detail=str(e))
    return nuevo, {**info, **campanas_ml_xlsx.verificar_integridad(contenido, nuevo, info["hoja"]), "filas": len(cuerpo), "tipo": leido["tipo"]}

@app.post("/campanas-ml/exportar")
async def campanas_ml_exportar(archivo: UploadFile = File(...), payload: str = Form(...)):
    """C3: devuelve el mismo Excel con la hoja "ERP Análisis" (columna VALOR A COPIAR). `payload` = JSON {tc, filas:[{fila,
    item_id, descuento_pct, meli_monto, comision, comision_origen, cuenta, sku}]} con el descuento total que se jugó en cada fila."""
    from fastapi.responses import Response
    nuevo, rep = await run_in_threadpool(_campanas_exportar_sync, await archivo.read(), payload)
    if not rep["ok"]:
        raise HTTPException(status_code=500, detail=f"El Excel generado no pasó la verificación de integridad: {rep['problemas']}")
    return Response(nuevo, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"X-Integridad": json.dumps({"ok": rep["ok"], "problemas": rep["problemas"], "filas": rep["filas"], "hoja": rep["hoja"]}),
                             "Access-Control-Expose-Headers": "X-Integridad",
                             "Content-Disposition": 'attachment; filename="campana_con_ERP_Analisis.xlsx"'})

# ══════════════════════════════════════════════════════
# CALENDARIO DE CAMPAÑAS (aviso diario, lo llama n8n)
# ══════════════════════════════════════════════════════

def _campanas_calendario_sync(hoy: str | None, dias_aviso: int, con_elegibles: bool, incluir_finalizadas: bool) -> dict:
    import campanas_calendario
    from datetime import timedelta
    from rentabilidad.cierre_ecom_diario import ayer_en_argentina
    try:
        dia = date.fromisoformat(hoy) if hoy else ayer_en_argentina() + timedelta(days=1)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"hoy debe ser AAAA-MM-DD: {hoy!r}")
    if not 0 <= dias_aviso <= 60:
        raise HTTPException(status_code=422, detail="dias_aviso debe estar entre 0 y 60.")
    return campanas_calendario.calendario(ml_ofertas.MLOfertasClient(), dia, dias_aviso, con_elegibles, incluir_finalizadas=incluir_finalizadas)

@app.get("/campanas/calendario")
async def campanas_calendario_endpoint(hoy: str | None = None, dias_aviso: int = 5, con_elegibles: bool = True,
                                       incluir_finalizadas: bool = False):
    """Aviso diario de campañas de ML (n8n). Protegido con X-ERP-Key. Consulta IT y MT, separa eventos especiales de cupones/operativas,
    calcula los días que faltan (al límite de adhesión si lo tiene, si no al inicio), en cuántos ítems es elegible cada cuenta y marca las
    que están a EXACTAMENTE `dias_aviso` días (5) en `a_5_dias`. La misma campaña en IT y MT sale una sola vez con las dos cuentas.
    `hoy` (AAAA-MM-DD) permite probar con otra fecha; `con_elegibles=false` evita las ~2 llamadas por campaña."""
    return await run_in_threadpool(_campanas_calendario_sync, hoy, dias_aviso, con_elegibles, incluir_finalizadas)

# ══════════════════════════════════════════════════════
# ML VENDEDOR (scraper)
# ══════════════════════════════════════════════════════

@app.post("/ml/vendedor/run")
async def run_vendedor(background_tasks: BackgroundTasks):
    job_id = f"vendedor_{int(time.time())}"
    job_status[job_id] = {"status": "running", "started": datetime.now().isoformat(), "log": []}
    background_tasks.add_task(vendedor_job, job_id)
    return {"job_id": job_id, "status": "started"}

def vendedor_job(job_id):
    log = job_status[job_id]["log"]
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        ss = get_gs().open_by_key(SPREADSHEET_ID)
        try:
            cfg = ss.worksheet('Vendedores')
        except:
            job_status[job_id] = {"status": "error", "message": "No existe pestaña Vendedores", "log": log}; return
        rows = cfg.get_all_values()
        vendedores = [{'nombre': r[0].strip(), 'url': r[1].strip(), 'row': i+2}
                      for i, r in enumerate(rows[1:]) if len(r) > 1 and r[0].strip() and r[1].strip()]
        if not vendedores:
            job_status[job_id] = {"status": "done", "log": ["Sin vendedores"]}; return
        options = Options()
        options.add_argument('--headless=new'); options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        options.add_argument('--window-size=1920,1080')
        try:
            from selenium.webdriver.chrome.service import Service
            from webdriver_manager.chrome import ChromeDriverManager
            driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        except:
            driver = webdriver.Chrome(options=options)
        def parse_price(t):
            if not t: return 0
            n = re.sub(r'[^\d]', '', t); return int(n) if n else 0
        def scroll(drv):
            last = drv.execute_script("return document.body.scrollHeight")
            for _ in range(15):
                drv.execute_script("window.scrollTo(0, document.body.scrollHeight);"); time.sleep(1.2)
                new = drv.execute_script("return document.body.scrollHeight")
                if new == last: break
                last = new
        def scrape(drv):
            items = []
            cards = drv.find_elements(By.CSS_SELECTOR, '.poly-card') or drv.find_elements(By.CSS_SELECTOR, '.ui-search-result__wrapper')
            for card in cards:
                try:
                    title = ''
                    for sel in ['.poly-component__title', '.ui-search-item__title']:
                        try:
                            title = card.find_element(By.CSS_SELECTOR, sel).text.strip()
                            if title: break
                        except: pass
                    link = ''
                    try:
                        h = card.find_element(By.CSS_SELECTOR, 'a').get_attribute('href')
                        link = h.split('?')[0] if h else ''
                    except: pass
                    orig = 0
                    try: orig = parse_price(card.find_element(By.CSS_SELECTOR, 's.andes-money-amount--previous .andes-money-amount__fraction').text)
                    except: pass
                    price = 0
                    try: price = parse_price(card.find_element(By.CSS_SELECTOR, '.poly-price__current .andes-money-amount__fraction').text)
                    except: pass
                    if not price:
                        try:
                            for f in reversed(card.find_elements(By.CSS_SELECTOR, '.andes-money-amount__fraction')):
                                v = parse_price(f.text)
                                if v > 0: price = v; break
                        except: pass
                    disc = ''
                    try: disc = card.find_element(By.CSS_SELECTOR, '.andes-money-amount__discount').text.strip()
                    except: pass
                    cuotas = 'Sin cuotas'
                    try: cuotas = card.find_element(By.CSS_SELECTOR, '.poly-component__installments').text.strip()
                    except: pass
                    if title and price:
                        items.append({'title': title, 'price': price, 'orig_price': orig or '',
                                      'discount': disc, 'cuotas': cuotas, 'link': link})
                except: continue
            return items
        def click_next(drv):
            for sel in ['.andes-pagination__button--next a', 'a[title="Siguiente"]']:
                try:
                    el = drv.find_element(By.CSS_SELECTOR, sel)
                    if 'disabled' in el.find_element(By.XPATH, '..').get_attribute('class'): return False
                    el.click(); time.sleep(2); return True
                except: pass
            return False
        try:
            for idx_v, v in enumerate(vendedores):
                job_status[job_id]["progress"] = {"current": idx_v, "total": len(vendedores), "label": f"Escaneando {v['nombre']}"}
                log.append(f"Procesando: {v['nombre']}")
                all_items = []; page = 1; seen = set()
                driver.get(v['url']); time.sleep(2.5)
                while True:
                    cur = driver.current_url
                    if cur in seen: break
                    seen.add(cur)
                    try: WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, '.poly-card, .ui-search-result')))
                    except: break
                    scroll(driver); items = scrape(driver)
                    if not items: break
                    all_items.extend(items)
                    log.append(f"  Pág {page}: {len(items)} items | Total: {len(all_items)}")
                    if not click_next(driver): break
                    page += 1; time.sleep(1)
                seen_t = set()
                unique = [item for item in all_items if item['title'] not in seen_t and not seen_t.add(item['title'])]
                sn = f'V - {v["nombre"]}'[:50]
                existing_sheets = [s.title for s in ss.worksheets()]
                if sn in existing_sheets:
                    log.append(f"⏭ {v['nombre']}: pestaña ya existe, saltando scraping")
                    cfg.update(values=[[datetime.now().strftime('%d/%m/%Y %H:%M')]], range_name=f'C{v["row"]}')
                    time.sleep(0.3); continue
                try:
                    ws = ss.worksheet(sn); ws.clear()
                except:
                    ws = ss.add_worksheet(title=sn, rows=5000, cols=10)
                ws.update(values=[['Titulo','Precio ($)','Precio Tachado ($)','Descuento','Cuotas','Ventas','Link','SKU','Cantidad']], range_name='A1:I1')
                rows_d = [[i['title'],i['price'],i['orig_price'],i['discount'],i['cuotas'],'',i['link'],'',''] for i in unique]
                for ci in range(0, len(rows_d), 500):
                    chunk = rows_d[ci:ci+500]; s = ci+2
                    ws.update(values=chunk, range_name=f'A{s}:I{s+len(chunk)-1}'); time.sleep(0.3)
                cfg.update(values=[[datetime.now().strftime('%d/%m/%Y %H:%M')]], range_name=f'C{v["row"]}')
                log.append(f"✅ {v['nombre']}: {len(unique)} productos (nueva pestaña)"); time.sleep(1)
        finally:
            driver.quit()
        job_status[job_id] = {"status": "done", "log": log, "finished": datetime.now().isoformat()}
    except Exception as e:
        job_status[job_id] = {"status": "error", "message": str(e), "log": log}

@app.get("/ml/vendedor/status/{job_id}")
def vendedor_status(job_id: str):
    return job_status.get(job_id, {"status": "not_found"})

@app.get("/jobs")
def list_jobs():
    return {k: {**v, "log": v.get("log", [])[-5:]} for k, v in job_status.items()}

@app.get("/jobs/{job_id}/log")
def job_log(job_id: str):
    job = job_status.get(job_id, {})
    return {"log": job.get("log", []), "status": job.get("status")}

# ══════════════════════════════════════════════════════
# ECOM PROXY
# ══════════════════════════════════════════════════════
import httpx
from urllib.parse import urlencode, quote

ECOM_BASE = "app.ecomexperts.com"
ECOM_API_BASE = "api.ecomexperts.com"

async def ecom_request(method, hostname, path, headers, body=None):
    url = f"https://{hostname}{path}"
    if "Cookie" in headers:
        headers["Cookie"] = headers["Cookie"].strip()
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        resp = await client.request(method, url, headers=headers, content=body)
        try:
            return {"statusCode": resp.status_code, "headers": dict(resp.headers), "body": resp.json()}
        except:
            return {"statusCode": resp.status_code, "headers": dict(resp.headers), "body": resp.text}

async def ecom_login(email, password):
    payload = json.dumps({"User": {"email_address": email, "password": password}}).encode()
    res = await ecom_request("POST", ECOM_API_BASE, "/users/users/doLogin.json",
        {"Content-Type": "application/json", "Accept": "application/json"}, payload)
    set_cookie = res["headers"].get("set-cookie", "")
    if res["statusCode"] == 200 and set_cookie:
        parts = [c.split(";")[0] for c in set_cookie.split(",") if "CAKEPHP=" in c and "deleted" not in c]
        cookie = parts[-1] if parts else set_cookie.split(";")[0]
        return {"success": True, "cookie": cookie}
    return {"success": False, "statusCode": res["statusCode"]}

async def ecom_find_listing(cookie, mla):
    path = f"/api/mt_listings?search_term={quote(mla)}&tab=tabmercadolibre&filter_m_status=active&filter_status=active&page=1"
    res = await ecom_request("GET", ECOM_BASE, path,
        {"Cookie": cookie, "Accept": "application/json", "X-Requested-With": "XMLHttpRequest"})
    data = res["body"].get("data", []) if isinstance(res["body"], dict) else []
    match = next((i for i in data if (i.get("MlItem", {}) or {}).get("id") == mla), None)
    if match:
        return {"found": True, "listingId": match.get("MtListing", {}).get("id"),
                "mla": mla, "priceRuleId": match.get("MtListing", {}).get("mt_listing_price_rule_id"),
                "catalogListing": (match.get("MlItem") or {}).get("catalog_listing")}
    return {"found": False, "error": f"MLA no encontrado: {mla}"}

async def ecom_fetch_price_html(cookie, sku_madre):
    path = f"/gestion/mt_products/MtProducts/prices_index?tab=tabactive&search_term={quote(sku_madre)}&filter_payment=1&order=nuevos&active_search_fields[]="
    res = await ecom_request("GET", ECOM_BASE, path,
        {"Cookie": cookie, "Accept": "application/json", "X-Requested-With": "XMLHttpRequest"})
    if isinstance(res["body"], dict):
        return res["body"].get("html", "")
    return ""

def ecom_parse_variants(html):
    variants = []; variant_order = []; seen = set()
    for m in re.finditer(r'name="data\[MtProductVariant\]\[(\d+)\]\[MtProductPrice\]\[', html):
        if m.group(1) not in seen:
            seen.add(m.group(1)); variant_order.append(m.group(1))
    table_match = re.search(r'class="[^"]*mt-editable-table[^"]*">(.*?)</table>', html, re.DOTALL)
    price_names = []
    if table_match:
        table_html = table_match.group(1)
        price_names = [re.sub(r'<[^>]+>', '', m.group(1)).strip()
                       for m in re.finditer(r'<th[^>]*>(.*?)</th>', table_html, re.DOTALL)]
    else:
        price_names = [re.sub(r'<[^>]+>', '', m.group(1)).strip()
                       for m in re.finditer(r'<th[^>]*>(.*?)</th>', html, re.DOTALL)]
    price_map = {}
    for m in re.finditer(
        r'name="data\[MtProductVariant\]\[(\d+)\]\[MtProductPrice\]\[(\d+)\]\[price\]"[^>]*value="([\d.]*)"', html):
        vId, pId, price_str = m.group(1), m.group(2), m.group(3)
        price_val = float(price_str) if price_str else 0.0
        if vId not in price_map: price_map[vId] = []
        price_map[vId].append({"priceId": pId, "currentPrice": price_val})
    vp_map = {}
    for m in re.finditer(
        r'name="data\[MtProductVariant\]\[(\d+)\]\[MtProductPrice\]\[(\d+)\]\[variant_price_id\]"\s+value="(\d*)"', html):
        vp_map[f"{m.group(1)}_{m.group(2)}"] = m.group(3)
    for i, vId in enumerate(variant_order):
        prices = []
        for pi, p in enumerate(price_map.get(vId, [])):
            prices.append({"name": price_names[pi] if pi < len(price_names) else f"Lista {pi+1}",
                           "priceId": p["priceId"], "currentPrice": p["currentPrice"],
                           "variantPriceId": vp_map.get(f"{vId}_{p['priceId']}", "")})
        variants.append({"variantId": vId, "position": i+1, "prices": prices})
    return variants

async def ecom_update_price(cookie, sku, sku_madre, variant_position, price, price_name):
    name_map = {
        'mercado libre': 'Mercado Libre', 'ml': 'Mercado Libre',
        'precio web': 'Precio Web', 'web': 'Precio Web',
        'precio web 2': 'Precio Web 2', 'web2': 'Precio Web 2',
        'fravega': 'Fravega', 'frave': 'Fravega',
        'lista 1 tactica con iva': 'Lista 1 Tactica Con IVA', 'lista 1': 'Lista 1 Tactica Con IVA',
        'lista 2 tactica con iva': 'Lista 2 Tactica Con IVA', 'lista 2': 'Lista 2 Tactica Con IVA',
    }
    name = name_map.get((price_name or '').lower().strip(), price_name or 'Mercado Libre')
    search_sku = sku_madre if sku_madre and sku_madre != sku else sku
    html = await ecom_fetch_price_html(cookie, search_sku)
    if not html:
        return {"success": False, "error": "Sin respuesta HTML de Ecom"}
    variants = ecom_parse_variants(html)
    if not variants:
        return {"success": False, "error": f"SKU no encontrado: {search_sku}"}
    target = variants
    if len(variants) > 1 and sku_madre and sku_madre != sku:
        pos = variant_position if isinstance(variant_position, int) else -1
        if 0 <= pos < len(variants):
            target = [variants[pos]]
        else:
            return {"success": False, "error": f"Se requiere variantPosition. Variantes: {len(variants)}"}
    results = []
    for variant in target:
        entry = next((p for p in variant["prices"]
                      if name.lower() in p["name"].lower() or p["name"].lower() in name.lower()), None)
        if not entry: continue
        params = {
            f"data[MtProductVariant][{variant['variantId']}][MtProductPrice][{entry['priceId']}][price]": str(price),
            f"data[MtProductVariant][{variant['variantId']}][MtProductPrice][{entry['priceId']}][variant_price_id]": entry["variantPriceId"],
            f"data[MtProductVariant][{variant['variantId']}][MtProductPrice][{entry['priceId']}][old_price]": str(entry["currentPrice"]),
        }
        body = urlencode(params).encode()
        res = await ecom_request("POST", ECOM_BASE, "/gestion/mt_products/MtProductPrices/save_prices",
            {"Content-Type": "application/x-www-form-urlencoded", "Cookie": cookie,
             "Accept": "application/json", "X-Requested-With": "XMLHttpRequest",
             "Referer": f"https://{ECOM_BASE}/gestion/mt_products/MtProducts/prices_index"}, body)
        ok = (res["body"].get("success") if isinstance(res["body"], dict) else False) or res["statusCode"] == 200
        results.append({"variantId": variant["variantId"], "ok": ok})
    return {"success": all(r["ok"] for r in results) if results else False,
            "sku": sku, "price": price, "results": results}

async def ecom_apply_price_rule(cookie, listing_id):
    res = await ecom_request("POST", ECOM_BASE,
        f"/mt_listings/MtListings/apply_price_rule_on_listing/{listing_id}.json",
        {"Cookie": cookie, "Accept": "application/json", "X-Requested-With": "XMLHttpRequest", "Content-Length": "0"})
    return res["body"]

async def ecom_set_price_rule(cookie, listing_id, price_rule_id):
    payload = json.dumps({"listing_price_rule_id": str(price_rule_id), "apply": True}).encode()
    res = await ecom_request("PUT", ECOM_BASE, f"/api/listings/setPriceRule/{listing_id}",
        {"Content-Type": "application/json", "Cookie": cookie,
         "Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}, payload)
    return {"success": res["statusCode"] == 200, "response": res["body"]}

@app.post("/ecom/login")
async def ecom_login_endpoint(request: Request):
    body = await request.json()
    return await ecom_login(body.get("email"), body.get("password"))

@app.post("/ecom/update-price")
async def ecom_update_price_endpoint(request: Request):
    body = await request.json()
    result = await ecom_update_price(
        body.get("cookie"), body.get("sku"), body.get("skuMadre"),
        body.get("variantPosition"), body.get("price"), body.get("priceName", "Mercado Libre"))
    print(f"UPDATE PRICE: sku={body.get('sku')} price={body.get('price')} result={result}")
    return result

@app.post("/ecom/find-listing")
async def ecom_find_listing_endpoint(request: Request):
    body = await request.json()
    return await ecom_find_listing(body.get("cookie"), body.get("mla"))

@app.post("/ecom/apply-price-rule")
async def ecom_apply_price_rule_endpoint(request: Request):
    body = await request.json()
    return await ecom_apply_price_rule(body.get("cookie"), body.get("listingId"))

@app.post("/ecom/set-price-rule")
async def ecom_set_price_rule_endpoint(request: Request):
    body = await request.json()
    return await ecom_set_price_rule(body.get("cookie"), body.get("listingId"), body.get("priceRuleId"))

@app.post("/ecom/debug-html")
async def ecom_debug_html(request: Request):
    body = await request.json()
    try:
        html = await ecom_fetch_price_html(body.get("cookie", "").strip(), body.get("sku", ""))
        variants = ecom_parse_variants(html)
        return {"html_length": len(html), "html_snippet": html[:8000],
                "variants_found": len(variants), "variants": variants[:3]}
    except Exception as e:
        return {"error": str(e)}

# ══════════════════════════════════════════════════════
# COMPETIDORES — Refresh histórico
# ══════════════════════════════════════════════════════

HIST_SHEET_NAME = "Historial Competidores"
MAX_HISTORY_DATES = 10

@app.post("/competidores/refresh")
async def refresh_competidores(request: Request):
    body = await request.json()
    ml_token = body.get("token", ML_TOKEN)
    job_id = f"refresh_{int(time.time())}"
    job_status[job_id] = {"status": "running", "log": [], "started": datetime.now().isoformat()}
    import threading
    threading.Thread(target=refresh_job, args=(job_id, ml_token), daemon=True).start()
    return {"job_id": job_id, "status": "started"}

def extract_mla(link):
    m = re.search(r'(MLA\d+)', str(link), re.I)
    return m.group(1).upper() if m else None

def refresh_job(job_id, ml_token):
    log = job_status[job_id]["log"]
    try:
        ss = get_gs().open_by_key(SPREADSHEET_ID)
        today = datetime.now().strftime('%d/%m/%Y')
        all_sheets = ss.worksheets()
        vendor_sheets = [ws for ws in all_sheets if ws.title.startswith('V - ')]
        log.append(f"📋 {len(vendor_sheets)} pestañas de competidores encontradas")
        if not vendor_sheets:
            job_status[job_id] = {"status": "error", "message": "No hay pestañas V - Vendedor", "log": log}; return
        all_items = []
        id_stats = {'sin_link': 0, 'sin_identificador': 0, 'product_id_excluido': 0, 'item_id_usado': 0}
        id_examples = {'sin_identificador': [], 'product_id_excluido': []}
        for idx_ws, ws in enumerate(vendor_sheets):
            job_status[job_id]["progress"] = {"current": idx_ws, "total": len(vendor_sheets), "label": "Leyendo competidores"}
            vendedor = ws.title[3:]
            try:
                rows = ws.get_all_values()
                if len(rows) < 2: continue
                hdrs = rows[0]
                link_idx = next((i for i,h in enumerate(hdrs) if 'link' in h.lower()), 6)
                title_idx = next((i for i,h in enumerate(hdrs) if 'titulo' in h.lower() or 'title' in h.lower()), 0)
                sku_idx = next((i for i,h in enumerate(hdrs) if h.lower() == 'sku'), 7)
                qty_idx = next((i for i,h in enumerate(hdrs) if 'cantidad' in h.lower()), 8)
                for row in rows[1:]:
                    if len(row) <= link_idx:
                        id_stats['sin_link'] += 1
                        continue
                    identidad = resolve_ml_identity(row[link_idx])
                    if identidad['estado'] == 'Sin Link':
                        id_stats['sin_link'] += 1
                        continue
                    if identidad['estado'] == 'Sin Identificador':
                        id_stats['sin_identificador'] += 1
                        if len(id_examples['sin_identificador']) < 5:
                            id_examples['sin_identificador'].append(f"{vendedor}: {row[link_idx]}")
                        continue
                    if identidad['tipo'] == 'product_id':
                        id_stats['product_id_excluido'] += 1
                        if len(id_examples['product_id_excluido']) < 5:
                            id_examples['product_id_excluido'].append(f"{vendedor}: {row[link_idx]} -> {identidad['identificador']}")
                        continue
                    id_stats['item_id_usado'] += 1
                    all_items.append({'vendedor': vendedor,
                        'titulo': row[title_idx] if len(row) > title_idx else '',
                        'link': row[link_idx],
                        'sku': row[sku_idx] if len(row) > sku_idx else '',
                        'cantidad': row[qty_idx] if len(row) > qty_idx else '',
                        'mla': identidad['identificador'],
                        'estado': identidad['estado']})
            except Exception as e:
                log.append(f"⚠ Error leyendo {ws.title}: {e}")
        log.append(f"🔗 {len(all_items)} links encontrados con MLA")
        log.append(f"📊 Identidad ML — item_id usados: {id_stats['item_id_usado']} · "
                    f"product_id excluidos: {id_stats['product_id_excluido']} · "
                    f"sin identificador: {id_stats['sin_identificador']} · "
                    f"sin link: {id_stats['sin_link']}")
        for _cat, _ejemplos in id_examples.items():
            if _ejemplos:
                log.append(f"   ↳ ejemplos {_cat}: " + " | ".join(_ejemplos))
        headers = {'Authorization': f'Bearer {ml_token}', 'User-Agent': 'Mozilla/5.0'}
        mla_prices = {}
        mlas = list(set(item['mla'] for item in all_items))
        for i in range(0, len(mlas), 20):
            job_status[job_id]["progress"] = {"current": i, "total": len(mlas), "label": "Consultando precios ML"}
            batch = mlas[i:i+20]
            try:
                r = requests.get(f"https://api.mercadolibre.com/items?ids={','.join(batch)}&attributes=id,price,original_price,title,installments",
                    headers=headers, timeout=15)
                if r.status_code == 200:
                    for item in r.json():
                        if item.get('code') == 200 and item.get('body'):
                            b = item['body']
                            orig = b.get('original_price') or b.get('price', 0)
                            price = b.get('price', 0)
                            disc = f"{round((1-price/orig)*100)}% OFF" if orig and orig > price else ''
                            inst = b.get('installments') or {}
                            cuotas = 'Sin cuotas'
                            if inst.get('quantity', 1) > 1:
                                m_str = f"${round(inst['amount']):,}".replace(',', '.')
                                s_str = ' sin interés' if inst.get('rate', 1) == 0 else ''
                                cuotas = f"{inst['quantity']}x {m_str}{s_str}"
                            mla_prices[b['id']] = {'precio': price, 'tachado': orig if orig and orig > price else '',
                                                    'descuento': disc, 'cuotas': cuotas}
                log.append(f"✅ Lote {i//20+1}: {len(batch)} MLAs consultados")
                time.sleep(0.3)
            except Exception as e:
                log.append(f"❌ Error lote {i//20+1}: {e}")
        log.append(f"💰 Precios obtenidos: {len(mla_prices)}/{len(mlas)} MLAs")
        try:
            hist_ws = ss.worksheet(HIST_SHEET_NAME)
        except:
            hist_ws = ss.add_worksheet(title=HIST_SHEET_NAME, rows=50000, cols=12)
            log.append("📋 Pestaña Historial Competidores creada")

        HIST_HEADERS = ['Vendedor','Titulo','Precio ($)','Precio Tachado ($)','Descuento','Cuotas',
                        'Link','SKU','Cantidad','Fecha Refresh','Item ID','Estado Identidad']
        existing = hist_ws.get_all_values()
        if not existing or existing[0] != HIST_HEADERS:
            hist_ws.update(values=[HIST_HEADERS], range_name='A1:L1')
            existing = hist_ws.get_all_values()
            log.append("🔧 Header de Historial Competidores actualizado a 12 columnas (Item ID, Estado Identidad)")

        if len(existing) > 1:
            fecha_idx = 9
            existing_dates = list(dict.fromkeys(row[fecha_idx] for row in existing[1:] if len(row) > fecha_idx and row[fecha_idx]))
            if today in existing_dates:
                existing_dates.remove(today)
                keep_rows = [existing[0]] + [r for r in existing[1:] if len(r) > fecha_idx and r[fecha_idx] != today]
                hist_ws.clear()
                if keep_rows: hist_ws.update(values=keep_rows, range_name=f'A1:L{len(keep_rows)}')
                existing_dates_clean = existing_dates
            else:
                existing_dates_clean = existing_dates
            while len(existing_dates_clean) >= MAX_HISTORY_DATES:
                oldest = existing_dates_clean[0]; existing_dates_clean.pop(0)
                all_vals = hist_ws.get_all_values()
                keep = [all_vals[0]] + [r for r in all_vals[1:] if len(r) > fecha_idx and r[fecha_idx] != oldest]
                hist_ws.clear(); hist_ws.update(values=keep, range_name=f'A1:L{len(keep)}')
                log.append(f"🗑 Fecha más vieja eliminada: {oldest}"); time.sleep(0.5)
        new_rows = []
        for item in all_items:
            p = mla_prices.get(item['mla'], {})
            new_rows.append([item['vendedor'], item['titulo'], p.get('precio',''), p.get('tachado',''),
                             p.get('descuento',''), p.get('cuotas',''), item['link'],
                             item['sku'], item['cantidad'], today, item['mla'], item['estado']])
        for i in range(0, len(new_rows), 500):
            hist_ws.append_rows(new_rows[i:i+500], value_input_option='RAW'); time.sleep(0.3)
        log.append(f"✅ {len(new_rows)} filas agregadas al historial con fecha {today}")
        competencia_db.registrar_lecturas_seguro(ss, [
            {'link': item['link'], 'entidad': item['vendedor'], 'precio': mla_prices[item['mla']]['precio'],
             'tachado': mla_prices[item['mla']]['tachado'], 'descuento': mla_prices[item['mla']]['descuento'],
             'cuotas': mla_prices[item['mla']]['cuotas'], 'estado': 'OK', 'metodo': 'API'}
            for item in all_items if item['mla'] in mla_prices], 'Refresh competidores', log)
        job_status[job_id] = {"status": "done", "log": log, "rows_added": len(new_rows),
                               "prices_fetched": len(mla_prices), "finished": datetime.now().isoformat()}
    except Exception as e:
        import traceback
        job_status[job_id] = {"status": "error", "message": str(e), "log": log + [traceback.format_exc()]}

@app.get("/competidores/refresh/status/{job_id}")
def refresh_status(job_id: str):
    return job_status.get(job_id, {"status": "not_found"})


# ══════════════════════════════════════════════════════
# TIPO DE CAMBIO — BNA scraper
# ══════════════════════════════════════════════════════

def obtener_tc_bna() -> dict:
    """TC venta del dólar billete del BNA -- delega en el ÚNICO scraper
    (`rentabilidad/tc_bna.py`, 2026-10): BNA del día; si no responde, el
    último TC guardado (`source: "ultimo_guardado"`). Si no hay ninguno,
    `tc: 0` + error: quien llama NO debe seguir con 1 ni con un valor fijo."""
    from rentabilidad import tc_bna
    try:
        info = tc_bna.obtener_tc_bna_info()
    except tc_bna.TcBnaError as e:
        return {"tc": 0, "error": str(e), "source": "error"}
    out = {"tc": float(info["tc"]), "source": info["source"]}
    if info.get("fecha"):
        out["fecha"] = info["fecha"].astimezone().strftime('%d/%m/%Y %H:%M')
    if info["source"] == "ultimo_guardado":
        out["aviso"] = "El BNA no respondió: se usa el último TC guardado."
    return out


def tc_info_rapido() -> dict:
    """TC para pantallas que no deben esperar a la red (Motor de Precios): memoria o último guardado, y se refresca solo en un hilo aparte."""
    from rentabilidad import tc_bna
    try:
        info = tc_bna.obtener_tc_bna_info_rapido()
    except tc_bna.TcBnaError:
        raise HTTPException(status_code=503, detail="No hay TC del BNA ni un TC guardado: no se puede calcular el margen.")
    if not info.get("tc") or info["tc"] <= 0:
        raise HTTPException(status_code=503, detail="No hay TC del BNA ni un TC guardado: no se puede calcular el margen.")
    return info


def tc_rapido_requerido() -> Decimal:
    return Decimal(str(tc_info_rapido()["tc"]))


def tc_bna_requerido() -> Decimal:
    """TC para cálculos de margen: nunca 1, nunca 0 -- sin TC corta con 503."""
    tc = obtener_tc_bna().get("tc") or 0
    if tc <= 0:
        raise HTTPException(status_code=503, detail="No hay TC del BNA ni un TC guardado: no se puede calcular el margen.")
    return Decimal(str(tc))


@app.get("/tc/bna")
async def get_tc_bna():
    return obtener_tc_bna()


# ══════════════════════════════════════════════════════
# DISTRIBUCION — inicialización de pestañas
# ══════════════════════════════════════════════════════

DISTRIB_SHEETS = {
    'Distribuidores': ['Distribuidor','Provincia','Localidad','Estado','Seller_ID','Responsable','Tolerancia_PVP','Fecha_Alta','Fecha_Ultima_Revision','Observaciones','Link_ML'],
    'Distribuidor_SKU': ['Distribuidor','SKU','Descripcion','Activo','PVP_Override','PVP_Oficial'],
    'Distribucion_Auditoria': ['Distribuidor','SKU','Fecha','Precio_Detectado','Cumple','Diferencia_%'],
}

@app.post("/distribucion/init")
def init_distribucion():
    try:
        ss = get_gs().open_by_key(SPREADSHEET_ID)
        existing = {ws.title for ws in ss.worksheets()}
        result = {}
        for name, headers in DISTRIB_SHEETS.items():
            if name in existing:
                result[name] = 'ya existía'
                continue
            sheet = ss.add_worksheet(title=name, rows=1000, cols=len(headers))
            sheet.append_row(headers)
            result[name] = 'creada'
        return {"status": "ok", "sheets": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════
# DISTRIBUCION — monitor de precio en vivo (MVP, sin comparación PVP)
# ══════════════════════════════════════════════════════

MONITOR_HEADERS = ['Distribuidor','SKU','Link','Precio_Detectado','Fecha_Hora','Estado','Metodo','Detalle_Error','Seller_ID','Official_Store_ID']

def _monitor_extract_ids(link):
    """
    A diferencia de resolve_ml_identity (que devuelve un único tipo con prioridad
    item_id > product_id), acá necesitamos product_id y wid AL MISMO TIEMPO: un link
    de catálogo trae ambos, y el wid identifica la oferta puntual dentro del catálogo.
    Reutiliza los mismos regex/helpers de la capa de identidad ML (F0).
    """
    s = str(link) if link is not None else ''
    path, _resto = _split_url_zones(s)
    product_id = None
    for pat in (_ML_PATH_PRODUCT_P_RE, _ML_PATH_PRODUCT_UP_RE):
        m = pat.search(path)
        if m:
            product_id = _normalize_ml_id(m.group(1)); break
    wid = None
    m = _ML_PARAM_WID_RE.search(s)
    if m:
        wid = _normalize_ml_id(m.group(1))
    item_id = None
    if not product_id:
        m = _ML_PATH_ITEM_RE.search(path) or _ML_PARAM_ITEM_ID_RE.search(s)
        if m:
            item_id = _normalize_ml_id(m.group(1))
        elif wid:
            item_id = wid  # sin product_id de catálogo, el wid es el item individual a mirar
    return {'product_id': product_id, 'wid': wid, 'item_id': item_id}

def _monitor_leer_catalogo(product_id, wid):
    """Publicación de catálogo (/p/, /up/): la oferta puntual del distribuidor se identifica
    por wid dentro de /products/{id}/items — endpoint público, no gateado por ownership."""
    if not wid:
        return {'precio': None, 'estado': 'Error', 'metodo': 'API', 'seller_id': None, 'official_store_id': None,
                'detalle_error': 'Link de catálogo sin wid= — no se puede identificar la oferta puntual del distribuidor'}
    try:
        offers = []; offset = 0
        while True:
            r = requests.get(f"https://api.mercadolibre.com/products/{product_id}/items",
                headers=ml_headers(), params={'limit': 100, 'offset': offset}, timeout=15)
            if r.status_code != 200:
                try:
                    msg = r.json().get('message', r.text[:120])
                except Exception:
                    msg = r.text[:120]
                return {'precio': None, 'estado': 'Error', 'metodo': 'API', 'seller_id': None, 'official_store_id': None,
                        'detalle_error': f'API {r.status_code} en /products/{product_id}/items: {msg}'}
            data = r.json()
            results = data.get('results', [])
            offers.extend(results)
            total = data.get('paging', {}).get('total', len(offers))
            offset += len(results)
            if not results or offset >= total:
                break
        match = next((o for o in offers if o.get('item_id') == wid), None)
        if not match:
            return {'precio': None, 'estado': 'Error', 'metodo': 'API', 'seller_id': None, 'official_store_id': None,
                    'detalle_error': f'wid {wid} no encontrado entre las {len(offers)} ofertas de {product_id} (¿vendedor no coincide o publicación eliminada?)'}
        return {'precio': match.get('price'), 'estado': 'OK', 'metodo': 'API',
                'seller_id': match.get('seller_id'), 'official_store_id': match.get('official_store_id'),
                'detalle_error': ''}
    except Exception as e:
        return {'precio': None, 'estado': 'Error', 'metodo': 'API', 'seller_id': None, 'official_store_id': None,
                'detalle_error': f'API error: {e}'}

def _monitor_try_api_item(item_id):
    """Intento rápido por API para item individual (no catálogo).
    Devuelve (precio, seller_id, official_store_id, detalle) o (None, None, None, detalle)."""
    try:
        r = requests.get(f"https://api.mercadolibre.com/items/{item_id}", headers=ml_headers(), timeout=10)
        if r.status_code == 200:
            data = r.json()
            price = data.get('price')
            if price:
                return price, data.get('seller_id'), data.get('official_store_id'), ''
            return None, None, None, 'API 200 pero sin precio en la respuesta'
        try:
            msg = r.json().get('message', r.text[:120])
        except Exception:
            msg = r.text[:120]
        return None, None, None, f'API {r.status_code}: {msg}'
    except Exception as e:
        return None, None, None, f'API error: {e}'

def _monitor_try_selenium(driver, link):
    """Visita la publicación puntual (sin scroll/paginación) y lee el precio del DOM."""
    from selenium.webdriver.common.by import By
    try:
        driver.get(link); time.sleep(2.5)
        page_text = driver.find_element(By.TAG_NAME, 'body').text.lower()
        if 'pausada' in page_text or 'pausado' in page_text:
            return None, "Selenium: la publicación aparece pausada"
        if 'ya no está disponible' in page_text or 'no encontramos la página' in page_text or 'esta publicación ya no' in page_text:
            return None, "Selenium: la publicación ya no está disponible"
        price = 0
        for sel in ['.ui-pdp-price__second-line .andes-money-amount__fraction',
                    '.ux-price__second-line .andes-money-amount__fraction',
                    '.andes-money-amount__fraction']:
            try:
                txt = driver.find_element(By.CSS_SELECTOR, sel).text
                v = int(re.sub(r'[^\d]', '', txt) or 0)
                if v: price = v; break
            except Exception:
                continue
        if price:
            return price, ''
        return None, 'Selenium: no se encontró precio en la página'
    except Exception as e:
        return None, f'Selenium error: {e}'

def _monitor_launch_driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    options = Options()
    options.add_argument('--headless=new'); options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
    options.add_argument('--window-size=1920,1080')
    try:
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager
        return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    except Exception:
        return webdriver.Chrome(options=options)

def leer_precio_publicacion(link, driver_holder):
    ids = _monitor_extract_ids(link)

    if ids['product_id']:
        return _monitor_leer_catalogo(ids['product_id'], ids['wid'])

    if ids['item_id']:
        price, seller_id, official_store_id, api_detail = _monitor_try_api_item(ids['item_id'])
        if price:
            return {'precio': price, 'estado': 'OK', 'metodo': 'API',
                    'seller_id': seller_id, 'official_store_id': official_store_id, 'detalle_error': ''}
        if driver_holder['driver'] is None:
            driver_holder['driver'] = _monitor_launch_driver()
        price2, sel_detail = _monitor_try_selenium(driver_holder['driver'], link)
        if price2:
            return {'precio': price2, 'estado': 'OK', 'metodo': 'Selenium',
                    'seller_id': None, 'official_store_id': None, 'detalle_error': ''}
        return {'precio': None, 'estado': 'Error', 'metodo': 'Selenium',
                'seller_id': None, 'official_store_id': None, 'detalle_error': f"{api_detail} | {sel_detail}"}

    return {'precio': None, 'estado': 'Error', 'metodo': '', 'seller_id': None, 'official_store_id': None,
            'detalle_error': 'Link no reconocido (sin product_id ni item_id)'}

def _registrar_lecturas_monitor(ss, results, fuente):
    """Doble escritura a Historial_Precios (Etapa 1 competencia). Los históricos viejos siguen escribiéndose
    porque el front todavía los lee; esto nunca rompe el monitor. Catálogo sin wid = 'Sin lectura', no se guarda."""
    lecturas = []
    for r in results:
        estado, guardar = competencia_db.normalizar_resultado(
            {'precio': r.get('precio_detectado'), 'detalle_error': r.get('detalle_error', '')}, r['link'])
        if guardar:
            lecturas.append({'link': r['link'], 'entidad': r.get('entidad_nombre') or r.get('distribuidor', ''),
                             'precio': r.get('precio_detectado'), 'estado': estado, 'metodo': r.get('metodo', '')})
    return competencia_db.registrar_lecturas_seguro(ss, lecturas, fuente)

@app.post("/distribucion/monitor/run")
def run_monitor():
    try:
        ss = get_gs().open_by_key(SPREADSHEET_ID)
        try:
            sku_ws = ss.worksheet('Distribuidor_SKU')
        except Exception:
            raise HTTPException(status_code=400, detail="No existe la pestaña Distribuidor_SKU")

        headers = sku_ws.row_values(1)
        if 'Link_Publicacion' not in headers:
            col = len(headers) + 1
            if col > sku_ws.col_count:
                sku_ws.add_cols(col - sku_ws.col_count)
            sku_ws.update_cell(1, col, 'Link_Publicacion')
            headers.append('Link_Publicacion')

        idx = {h: i for i, h in enumerate(headers)}
        rows = sku_ws.get_all_values()[1:]
        targets = []
        for r in rows:
            link = r[idx['Link_Publicacion']].strip() if len(r) > idx['Link_Publicacion'] else ''
            if not link:
                continue
            targets.append({
                'distribuidor': r[idx['Distribuidor']] if len(r) > idx.get('Distribuidor', -1) else '',
                'sku': r[idx['SKU']] if len(r) > idx.get('SKU', -1) else '',
                'link': link,
            })

        try:
            mon_ws = ss.worksheet('Monitor_Lecturas')
        except Exception:
            mon_ws = ss.add_worksheet(title='Monitor_Lecturas', rows=2000, cols=len(MONITOR_HEADERS))
            mon_ws.append_row(MONITOR_HEADERS)

        driver_holder = {'driver': None}
        results = []
        try:
            for t in targets:
                res = leer_precio_publicacion(t['link'], driver_holder)
                fecha_hora = datetime.now().strftime('%d/%m/%Y %H:%M')
                results.append({
                    'distribuidor': t['distribuidor'], 'sku': t['sku'], 'link': t['link'],
                    'precio_detectado': res['precio'], 'fecha_hora': fecha_hora,
                    'estado': res['estado'], 'metodo': res['metodo'], 'detalle_error': res['detalle_error'],
                    'seller_id': res.get('seller_id'), 'official_store_id': res.get('official_store_id'),
                })
                mon_ws.append_row([t['distribuidor'], t['sku'], t['link'], res['precio'] or '',
                                    fecha_hora, res['estado'], res['metodo'], res['detalle_error'],
                                    res.get('seller_id') or '', res.get('official_store_id') or ''])
        finally:
            if driver_holder['driver']:
                driver_holder['driver'].quit()
        _registrar_lecturas_monitor(ss, results, 'Monitor distribuidores')

        return {"status": "ok", "count": len(results), "results": results}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════
# INTELIGENCIA COMERCIAL — esquema unificado (fusión Distribución + Competencia ML)
# Entidades/Referencias_Mercado/Discovery_Sugerencias/Intel_Config son tablas nuevas.
# Monitor_Lecturas se EXTIENDE (no se duplica): se le agregan columnas al final,
# run_monitor()/init_distribucion() siguen sin tocarse.
# ══════════════════════════════════════════════════════

INTEL_SHEETS = {
    'Entidades': ['Entidad_ID','Nombre','Tipo','Provincia','Localidad','Estado','Responsable','Tolerancia_Default_Pct','Fecha_Alta','Fecha_Ultima_Revision','Observaciones','Link_ML','Seller_ID'],
    'Referencias_Mercado': ['Referencia_ID','SKU','Tipo','Entidad_ID','Entidad_Nombre','Link_Publicacion','PVP_Oficial','PVP_Override','Tolerancia_Pct','Activo','Seller_ID_Esperado','Fecha_Alta','Origen','Observaciones'],
    'Discovery_Sugerencias': ['Sugerencia_ID','Entidad_Origen','Titulo_Detectado','Link_Detectado','Precio_Detectado','SKU_Sugerido','Fecha_Deteccion','Estado_Revision','Referencia_ID_Generada'],
    'Intel_Config': ['Tipo','Tolerancia_Default_Pct'],
    # Etapa 1 competencia: histórico único en formato largo + huérfanos de la migración (competencia_db.py)
    competencia_db.HISTORIAL_SHEET: competencia_db.HISTORIAL_HEADERS,
    competencia_db.HUERFANOS_SHEET: competencia_db.HUERFANOS_HEADERS,
}

MONITOR_HEADERS_EXT = ['Referencia_ID','Tipo','Entidad','PVP_Comparado','Diferencia_Pct','Cumple']

@app.post("/intel-comercial/init")
def init_intel_comercial():
    try:
        ss = get_gs().open_by_key(SPREADSHEET_ID)
        existing = {ws.title for ws in ss.worksheets()}
        result = {}
        for name, headers in INTEL_SHEETS.items():
            if name not in existing:
                sheet = ss.add_worksheet(title=name, rows=1000, cols=len(headers))
                sheet.append_row(headers)
                result[name] = 'creada'
                continue
            sheet = ss.worksheet(name)
            current_headers = sheet.row_values(1)
            faltantes = [h for h in headers if h not in current_headers]
            if not faltantes:
                result[name] = 'ya existía'
                continue
            col = len(current_headers) + 1
            if col + len(faltantes) - 1 > sheet.col_count:
                sheet.add_cols(col + len(faltantes) - 1 - sheet.col_count)
            for i, h in enumerate(faltantes):
                sheet.update_cell(1, col + i, h)
            result[name] = f'extendida (+{len(faltantes)} columnas)'

        try:
            mon_ws = ss.worksheet('Monitor_Lecturas')
            headers = mon_ws.row_values(1)
            faltantes = [h for h in MONITOR_HEADERS_EXT if h not in headers]
            if not faltantes:
                result['Monitor_Lecturas'] = 'ya extendida'
            else:
                col = len(headers) + 1
                if col + len(faltantes) - 1 > mon_ws.col_count:
                    mon_ws.add_cols(col + len(faltantes) - 1 - mon_ws.col_count)
                for i, h in enumerate(faltantes):
                    mon_ws.update_cell(1, col + i, h)
                result['Monitor_Lecturas'] = f'extendida (+{len(faltantes)} columnas)'
        except Exception:
            headers_full = MONITOR_HEADERS + MONITOR_HEADERS_EXT
            mon_ws = ss.add_worksheet(title='Monitor_Lecturas', rows=2000, cols=len(headers_full))
            mon_ws.append_row(headers_full)
            result['Monitor_Lecturas'] = 'creada (esquema completo)'

        return {"status": "ok", "sheets": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════
# INTELIGENCIA COMERCIAL — bridges (Fase 1, solo lectura de origen, no editan
# Distribuidores/Distribuidor_SKU/Monitor_Lecturas; idempotentes por clave)
# ══════════════════════════════════════════════════════

def _next_seq_id(existing_ids, prefix):
    max_n = 0
    pat = re.compile(rf'^{prefix}-(\d+)$')
    for v in existing_ids:
        m = pat.match(str(v).strip())
        if m:
            n = int(m.group(1))
            if n > max_n:
                max_n = n
    return max_n

def _bridge_entidades_distribuidores(ss):
    try:
        dist_ws = ss.worksheet('Distribuidores')
    except Exception:
        raise HTTPException(status_code=400, detail="No existe la pestaña Distribuidores")
    try:
        ent_ws = ss.worksheet('Entidades')
    except Exception:
        raise HTTPException(status_code=400, detail="No existe la pestaña Entidades — correr /intel-comercial/init primero")

    dist_rows = dist_ws.get_all_records()
    ent_values = ent_ws.get_all_values()
    ent_headers = ent_values[0] if ent_values else INTEL_SHEETS['Entidades']
    eidx = {h: i for i, h in enumerate(ent_headers)}

    existing_keys = set()
    existing_ids = []
    for r in ent_values[1:]:
        nombre = r[eidx['Nombre']].strip() if len(r) > eidx.get('Nombre', -1) else ''
        tipo = r[eidx['Tipo']].strip() if len(r) > eidx.get('Tipo', -1) else ''
        existing_keys.add((nombre, tipo))
        if len(r) > eidx.get('Entidad_ID', -1) and r[eidx['Entidad_ID']]:
            existing_ids.append(r[eidx['Entidad_ID']])

    seq = _next_seq_id(existing_ids, 'ENT')
    creadas = 0
    ya_existian = 0
    nuevas = []
    for row in dist_rows:
        nombre = str(row.get('Distribuidor', '')).strip()
        if not nombre:
            continue
        key = (nombre, 'Distribuidor')
        if key in existing_keys:
            ya_existian += 1
            continue
        seq += 1
        nuevas.append([
            f'ENT-{seq:06d}', nombre, 'Distribuidor',
            row.get('Provincia', ''), row.get('Localidad', ''), row.get('Estado', ''),
            row.get('Responsable', ''), row.get('Tolerancia_PVP', ''),
            row.get('Fecha_Alta', ''), row.get('Fecha_Ultima_Revision', ''),
            row.get('Observaciones', ''), row.get('Link_ML', ''),
        ])
        existing_keys.add(key)
        creadas += 1
    if nuevas:
        ent_ws.append_rows(nuevas)
    return {"creadas": creadas, "ya_existian": ya_existian}

@app.post("/intel-comercial/entidades/bridge-distribuidores")
def bridge_entidades_distribuidores():
    try:
        ss = get_gs().open_by_key(SPREADSHEET_ID)
        res = _bridge_entidades_distribuidores(ss)
        return {"status": "ok", **res}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def _bridge_referencias_distribuidor_sku(ss):
    # Asegura que Entidades esté al día antes de resolver Entidad_ID por nombre.
    ent_result = _bridge_entidades_distribuidores(ss)

    try:
        sku_ws = ss.worksheet('Distribuidor_SKU')
    except Exception:
        raise HTTPException(status_code=400, detail="No existe la pestaña Distribuidor_SKU")
    try:
        ref_ws = ss.worksheet('Referencias_Mercado')
    except Exception:
        raise HTTPException(status_code=400, detail="No existe la pestaña Referencias_Mercado — correr /intel-comercial/init primero")
    ent_ws = ss.worksheet('Entidades')

    ent_values = ent_ws.get_all_values()
    ent_headers = ent_values[0] if ent_values else INTEL_SHEETS['Entidades']
    eidx = {h: i for i, h in enumerate(ent_headers)}
    entidad_id_by_key = {}
    for r in ent_values[1:]:
        nombre = r[eidx['Nombre']].strip() if len(r) > eidx.get('Nombre', -1) else ''
        tipo = r[eidx['Tipo']].strip() if len(r) > eidx.get('Tipo', -1) else ''
        eid = r[eidx['Entidad_ID']] if len(r) > eidx.get('Entidad_ID', -1) else ''
        if nombre:
            entidad_id_by_key[(nombre, tipo)] = eid

    sku_rows = sku_ws.get_all_records()

    ref_values = ref_ws.get_all_values()
    ref_headers = ref_values[0] if ref_values else INTEL_SHEETS['Referencias_Mercado']
    ridx = {h: i for i, h in enumerate(ref_headers)}
    existing_keys = set()
    existing_ids = []
    for r in ref_values[1:]:
        ent_nombre = r[ridx['Entidad_Nombre']].strip() if len(r) > ridx.get('Entidad_Nombre', -1) else ''
        sku = r[ridx['SKU']].strip() if len(r) > ridx.get('SKU', -1) else ''
        link = r[ridx['Link_Publicacion']].strip() if len(r) > ridx.get('Link_Publicacion', -1) else ''
        existing_keys.add((ent_nombre, sku, link))
        if len(r) > ridx.get('Referencia_ID', -1) and r[ridx['Referencia_ID']]:
            existing_ids.append(r[ridx['Referencia_ID']])

    seq = _next_seq_id(existing_ids, 'REF')
    creadas = 0
    ya_existian = 0
    sin_entidad = 0
    hoy = datetime.now().strftime('%d/%m/%Y')
    nuevas = []
    for row in sku_rows:
        distribuidor = str(row.get('Distribuidor', '')).strip()
        sku = str(row.get('SKU', '')).strip()
        if not distribuidor or not sku:
            continue
        link = str(row.get('Link_Publicacion', '')).strip()
        key = (distribuidor, sku, link)
        if key in existing_keys:
            ya_existian += 1
            continue
        entidad_id = entidad_id_by_key.get((distribuidor, 'Distribuidor'), '')
        if not entidad_id:
            sin_entidad += 1
            continue
        seq += 1
        nuevas.append([
            f'REF-{seq:06d}', sku, 'Distribuidor', entidad_id, distribuidor,
            link, row.get('PVP_Oficial', ''), row.get('PVP_Override', ''),
            '', row.get('Activo', ''), '', hoy, 'Manual', row.get('Descripcion', ''),
        ])
        existing_keys.add(key)
        creadas += 1
    if nuevas:
        ref_ws.append_rows(nuevas)
    return {"creadas": creadas, "ya_existian": ya_existian, "sin_entidad": sin_entidad, "entidades": ent_result}

@app.post("/intel-comercial/referencias/bridge-distribuidor-sku")
def bridge_referencias_distribuidor_sku():
    try:
        ss = get_gs().open_by_key(SPREADSHEET_ID)
        res = _bridge_referencias_distribuidor_sku(ss)
        return {"status": "ok", **res}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════
# INTELIGENCIA COMERCIAL — monitor unificado (Fase 2, validación inicial)
# Reusa leer_precio_publicacion/_monitor_launch_driver sin modificarlos. Itera
# Referencias_Mercado (no Distribuidor_SKU) y agrega filas a Monitor_Lecturas
# (histórico append-only, igual que run_monitor). No toca run_monitor,
# init_distribucion, Distribuidor_SKU, Distribuidores.
#
# Validación inicial deliberadamente excluye Tipo=Distribuidor (ver
# MONITOR_UNIFICADO_TIPOS) para no mezclar escrituras con run_monitor todavía.
# ══════════════════════════════════════════════════════

MONITOR_UNIFICADO_TIPOS = ['Competencia', 'Cuenta Propia', 'Mayorista']

_ACTIVO_TRUTHY = {'si', 'sí', 'true', '1', 'activo'}


def _es_activo(valor):
    """vacío = activo (compat. con comportamiento actual); si/sí/true/1/activo = activo; cualquier otro valor = inactivo."""
    v = str(valor or '').strip().lower()
    if not v:
        return True
    return v in _ACTIVO_TRUTHY


def _monitor_calc_comparacion(precio, pvp_comparado, tolerancia_pct):
    """Diferencia_Pct = (precio - pvp_comparado) / pvp_comparado; Cumple = dentro de tolerancia (simétrico).
    Backend no decide qué significa "cumplir" para cada Tipo — eso lo interpreta el frontend."""
    try:
        precio_f = float(precio) if precio not in (None, '') else None
        pvp_f = float(pvp_comparado) if pvp_comparado not in (None, '') else None
    except (TypeError, ValueError):
        return None, None
    if precio_f is None or pvp_f is None or pvp_f == 0:
        return None, None
    diferencia_pct = (precio_f - pvp_f) / pvp_f
    try:
        tol_f = float(tolerancia_pct) if tolerancia_pct not in (None, '') else None
    except (TypeError, ValueError):
        tol_f = None
    if tol_f is None:
        tol_f = 0.05
    cumple = abs(diferencia_pct) <= tol_f
    return diferencia_pct, cumple


def _resolver_tolerancia(referencia_tolerancia_pct, entidad_tolerancia_pct, tipo, intel_config_by_tipo):
    for v in (referencia_tolerancia_pct, entidad_tolerancia_pct):
        try:
            if v not in (None, ''):
                return float(v)
        except (TypeError, ValueError):
            pass
    cfg = intel_config_by_tipo.get(tipo)
    if cfg not in (None, ''):
        try:
            return float(cfg)
        except (TypeError, ValueError):
            pass
    return 0.05


def _referencias_targets(ss):
    ref_ws = ss.worksheet('Referencias_Mercado')
    ent_ws = ss.worksheet('Entidades')
    try:
        cfg_ws = ss.worksheet('Intel_Config')
        cfg_rows = cfg_ws.get_all_records()
    except Exception:
        cfg_rows = []
    intel_config_by_tipo = {}
    for r in cfg_rows:
        tipo = str(r.get('Tipo', '')).strip()
        if tipo:
            intel_config_by_tipo[tipo] = r.get('Tolerancia_Default_Pct', '')

    ent_by_id = {}
    for r in ent_ws.get_all_records():
        eid = str(r.get('Entidad_ID', '')).strip()
        if eid:
            ent_by_id[eid] = r

    targets = []
    for r in ref_ws.get_all_records():
        tipo = str(r.get('Tipo', '')).strip()
        if tipo not in MONITOR_UNIFICADO_TIPOS:
            continue
        if not _es_activo(r.get('Activo', '')):
            continue
        link = str(r.get('Link_Publicacion', '')).strip()
        if not link:
            continue
        referencia_id = str(r.get('Referencia_ID', '')).strip()
        sku = str(r.get('SKU', '')).strip()
        entidad_id = str(r.get('Entidad_ID', '')).strip()
        entidad_nombre = str(r.get('Entidad_Nombre', '')).strip()
        pvp_override = r.get('PVP_Override', '')
        pvp_oficial = r.get('PVP_Oficial', '')
        pvp_comparado = pvp_override if pvp_override not in (None, '') else pvp_oficial
        entidad = ent_by_id.get(entidad_id, {})
        tolerancia_pct = _resolver_tolerancia(
            r.get('Tolerancia_Pct', ''),
            entidad.get('Tolerancia_Default_Pct', ''),
            tipo,
            intel_config_by_tipo,
        )
        targets.append({
            'referencia_id': referencia_id, 'sku': sku, 'tipo': tipo,
            'entidad_nombre': entidad_nombre, 'link': link,
            'pvp_comparado': pvp_comparado, 'tolerancia_pct': tolerancia_pct,
        })
    return targets


@app.post("/intel-comercial/monitor/run")
def run_monitor_unificado():
    try:
        ss = get_gs().open_by_key(SPREADSHEET_ID)
        try:
            targets = _referencias_targets(ss)
        except Exception:
            raise HTTPException(status_code=400, detail="No existen las pestañas Referencias_Mercado/Entidades — correr /intel-comercial/init y los bridges primero")

        try:
            mon_ws = ss.worksheet('Monitor_Lecturas')
        except Exception:
            headers_full = MONITOR_HEADERS + MONITOR_HEADERS_EXT
            mon_ws = ss.add_worksheet(title='Monitor_Lecturas', rows=2000, cols=len(headers_full))
            mon_ws.append_row(headers_full)

        driver_holder = {'driver': None}
        results = []
        try:
            for t in targets:
                res = leer_precio_publicacion(t['link'], driver_holder)
                fecha_hora = datetime.now().strftime('%d/%m/%Y %H:%M')
                diferencia_pct, cumple = _monitor_calc_comparacion(res['precio'], t['pvp_comparado'], t['tolerancia_pct'])
                results.append({
                    'referencia_id': t['referencia_id'], 'sku': t['sku'], 'tipo': t['tipo'],
                    'entidad_nombre': t['entidad_nombre'], 'link': t['link'],
                    'precio_detectado': res['precio'], 'fecha_hora': fecha_hora,
                    'estado': res['estado'], 'metodo': res['metodo'], 'detalle_error': res['detalle_error'],
                    'seller_id': res.get('seller_id'), 'official_store_id': res.get('official_store_id'),
                    'pvp_comparado': t['pvp_comparado'], 'diferencia_pct': diferencia_pct, 'cumple': cumple,
                })
                mon_ws.append_row([
                    t['entidad_nombre'], t['sku'], t['link'], res['precio'] or '',
                    fecha_hora, res['estado'], res['metodo'], res['detalle_error'],
                    res.get('seller_id') or '', res.get('official_store_id') or '',
                    t['referencia_id'], t['tipo'], t['entidad_nombre'],
                    t['pvp_comparado'] if t['pvp_comparado'] not in (None, '') else '',
                    diferencia_pct if diferencia_pct is not None else '',
                    cumple if cumple is not None else '',
                ])
        finally:
            if driver_holder['driver']:
                driver_holder['driver'].quit()
        _registrar_lecturas_monitor(ss, results, 'Monitor unificado')

        return {"status": "ok", "count": len(results), "results": results}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════
# INTELIGENCIA COMERCIAL — CRUD (Fase 3, backend)
# Helpers genéricos por-fila-por-ID, reutilizables para cualquier pestaña con
# columna ID (Entidades, Referencias_Mercado, y futuras tablas similares).
# No toca run_monitor, leer_precio_publicacion, init_distribucion, los
# bridges de Fase 1 ni el monitor unificado de Fase 2.
# ══════════════════════════════════════════════════════

REFERENCIA_TIPOS_VALIDOS = ['Distribuidor', 'Competencia', 'Cuenta Propia', 'Mayorista']


def _find_row_by_id(ws, id_col_name, id_value):
    """Busca una fila por valor exacto de columna id_col_name.
    Devuelve (row_index 1-based de la hoja, dict {header: valor}) o (None, None) si no existe."""
    headers = ws.row_values(1)
    if id_col_name not in headers:
        return None, None
    id_idx = headers.index(id_col_name)
    rows = ws.get_all_values()[1:]
    for i, row in enumerate(rows, start=2):
        val = row[id_idx] if len(row) > id_idx else ''
        if str(val).strip() == str(id_value).strip():
            record = {headers[j]: (row[j] if j < len(row) else '') for j in range(len(headers))}
            return i, record
    return None, None


def _update_row_fields(ws, row_index, headers, updates):
    """Escribe solo las columnas presentes en updates (dict header->valor) en la fila row_index."""
    for key, value in updates.items():
        if key not in headers:
            continue
        col = headers.index(key) + 1
        ws.update_cell(row_index, col, value)


def _delete_row(ws, row_index):
    ws.delete_rows(row_index)


def _append_row_from_dict(ws, headers, values_dict):
    """Arma una fila en el orden de headers a partir de un dict parcial y la agrega al final."""
    row = {h: '' for h in headers}
    for k, v in values_dict.items():
        if k in row:
            row[k] = v
    ws.append_row([row[h] for h in headers])


@app.post("/intel-comercial/entidades")
async def crear_entidad(request: Request):
    try:
        body = await request.json()
        nombre = str(body.get('Nombre', '')).strip()
        tipo = str(body.get('Tipo', '')).strip()
        if not nombre:
            raise HTTPException(status_code=400, detail="Nombre es obligatorio")
        if not tipo:
            raise HTTPException(status_code=400, detail="Tipo es obligatorio")

        ss = get_gs().open_by_key(SPREADSHEET_ID)
        ent_ws = ss.worksheet('Entidades')
        headers = ent_ws.row_values(1)
        id_idx = headers.index('Entidad_ID')
        existing_ids = [r[id_idx] for r in ent_ws.get_all_values()[1:] if len(r) > id_idx and r[id_idx]]
        seq = _next_seq_id(existing_ids, 'ENT') + 1
        entidad_id = f'ENT-{seq:06d}'

        _append_row_from_dict(ent_ws, headers, {
            'Entidad_ID': entidad_id, 'Nombre': nombre, 'Tipo': tipo,
            'Provincia': body.get('Provincia', ''), 'Localidad': body.get('Localidad', ''),
            'Estado': body.get('Estado', ''), 'Responsable': body.get('Responsable', ''),
            'Tolerancia_Default_Pct': body.get('Tolerancia_Default_Pct', ''),
            'Fecha_Alta': datetime.now().strftime('%d/%m/%Y'),
            'Observaciones': body.get('Observaciones', ''), 'Link_ML': body.get('Link_ML', ''),
            'Seller_ID': body.get('Seller_ID', ''),
        })
        return {"status": "ok", "entidad_id": entidad_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/intel-comercial/entidades/{entidad_id}")
async def editar_entidad(entidad_id: str, request: Request):
    try:
        body = await request.json()
        ss = get_gs().open_by_key(SPREADSHEET_ID)
        ent_ws = ss.worksheet('Entidades')
        headers = ent_ws.row_values(1)
        row_index, record = _find_row_by_id(ent_ws, 'Entidad_ID', entidad_id)
        if row_index is None:
            raise HTTPException(status_code=404, detail=f"No existe Entidad_ID {entidad_id}")

        updates = {}
        for campo in ('Nombre', 'Tipo', 'Provincia', 'Localidad', 'Estado', 'Responsable',
                      'Tolerancia_Default_Pct', 'Fecha_Ultima_Revision', 'Observaciones', 'Link_ML'):
            if campo in body:
                updates[campo] = body[campo]

        if 'Nombre' in updates and not str(updates['Nombre']).strip():
            raise HTTPException(status_code=400, detail="Nombre no puede quedar vacío")
        if 'Tipo' in updates and not str(updates['Tipo']).strip():
            raise HTTPException(status_code=400, detail="Tipo no puede quedar vacío")

        _update_row_fields(ent_ws, row_index, headers, updates)
        return {"status": "ok", "entidad_id": entidad_id, "actualizado": list(updates.keys())}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/intel-comercial/referencias")
async def crear_referencia(request: Request):
    try:
        body = await request.json()
        sku = str(body.get('SKU', '')).strip()
        tipo = str(body.get('Tipo', '')).strip()
        entidad_id = str(body.get('Entidad_ID', '')).strip()
        link = str(body.get('Link_Publicacion', '')).strip()

        if not sku:
            raise HTTPException(status_code=400, detail="SKU es obligatorio")
        if tipo not in REFERENCIA_TIPOS_VALIDOS:
            raise HTTPException(status_code=400, detail=f"Tipo inválido: '{tipo}'. Valores permitidos: {', '.join(REFERENCIA_TIPOS_VALIDOS)}")
        if not link:
            raise HTTPException(status_code=400, detail="Link_Publicacion es obligatorio")
        if not entidad_id:
            raise HTTPException(status_code=400, detail="Entidad_ID es obligatorio")

        ss = get_gs().open_by_key(SPREADSHEET_ID)
        ent_ws = ss.worksheet('Entidades')
        _, entidad = _find_row_by_id(ent_ws, 'Entidad_ID', entidad_id)
        if entidad is None:
            raise HTTPException(status_code=400, detail=f"No existe Entidad_ID {entidad_id}")

        ref_ws = ss.worksheet('Referencias_Mercado')
        headers = ref_ws.row_values(1)
        id_idx = headers.index('Referencia_ID')
        existing_ids = [r[id_idx] for r in ref_ws.get_all_values()[1:] if len(r) > id_idx and r[id_idx]]
        seq = _next_seq_id(existing_ids, 'REF') + 1
        referencia_id = f'REF-{seq:06d}'

        _append_row_from_dict(ref_ws, headers, {
            'Referencia_ID': referencia_id, 'SKU': sku, 'Tipo': tipo,
            'Entidad_ID': entidad_id, 'Entidad_Nombre': entidad.get('Nombre', ''),
            'Link_Publicacion': link,
            'PVP_Oficial': body.get('PVP_Oficial', ''), 'PVP_Override': body.get('PVP_Override', ''),
            'Tolerancia_Pct': body.get('Tolerancia_Pct', ''), 'Activo': body.get('Activo', ''),
            'Seller_ID_Esperado': body.get('Seller_ID_Esperado', ''),
            'Fecha_Alta': datetime.now().strftime('%d/%m/%Y'),
            'Origen': body.get('Origen', 'Manual'), 'Observaciones': body.get('Observaciones', ''),
        })
        return {"status": "ok", "referencia_id": referencia_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/intel-comercial/referencias/{referencia_id}")
async def editar_referencia(referencia_id: str, request: Request):
    try:
        body = await request.json()
        ss = get_gs().open_by_key(SPREADSHEET_ID)
        ref_ws = ss.worksheet('Referencias_Mercado')
        headers = ref_ws.row_values(1)
        row_index, record = _find_row_by_id(ref_ws, 'Referencia_ID', referencia_id)
        if row_index is None:
            raise HTTPException(status_code=404, detail=f"No existe Referencia_ID {referencia_id}")

        updates = {}
        for campo in ('SKU', 'Tipo', 'Entidad_ID', 'Link_Publicacion', 'PVP_Oficial', 'PVP_Override',
                      'Tolerancia_Pct', 'Activo', 'Seller_ID_Esperado', 'Observaciones'):
            if campo in body:
                updates[campo] = body[campo]

        if 'SKU' in updates and not str(updates['SKU']).strip():
            raise HTTPException(status_code=400, detail="SKU no puede quedar vacío")
        if 'Tipo' in updates and str(updates['Tipo']).strip() not in REFERENCIA_TIPOS_VALIDOS:
            raise HTTPException(status_code=400, detail=f"Tipo inválido: '{updates['Tipo']}'. Valores permitidos: {', '.join(REFERENCIA_TIPOS_VALIDOS)}")
        if 'Link_Publicacion' in updates and not str(updates['Link_Publicacion']).strip():
            raise HTTPException(status_code=400, detail="Link_Publicacion no puede quedar vacío")

        if 'Entidad_ID' in updates:
            nuevo_entidad_id = str(updates['Entidad_ID']).strip()
            ent_ws = ss.worksheet('Entidades')
            _, entidad = _find_row_by_id(ent_ws, 'Entidad_ID', nuevo_entidad_id)
            if entidad is None:
                raise HTTPException(status_code=400, detail=f"No existe Entidad_ID {nuevo_entidad_id}")
            updates['Entidad_Nombre'] = entidad.get('Nombre', '')

        _update_row_fields(ref_ws, row_index, headers, updates)
        return {"status": "ok", "referencia_id": referencia_id, "actualizado": list(updates.keys())}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/intel-comercial/referencias/{referencia_id}")
def eliminar_referencia(referencia_id: str):
    try:
        ss = get_gs().open_by_key(SPREADSHEET_ID)
        ref_ws = ss.worksheet('Referencias_Mercado')
        row_index, record = _find_row_by_id(ref_ws, 'Referencia_ID', referencia_id)
        if row_index is None:
            raise HTTPException(status_code=404, detail=f"No existe Referencia_ID {referencia_id}")
        _delete_row(ref_ws, row_index)
        return {"status": "ok", "referencia_id": referencia_id, "eliminado": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════
# INTELIGENCIA COMERCIAL — "Mix" (Fase 5): carga masiva de links.
# Por cada {sku, link}: resuelve/crea la Entidad por Seller_ID (no por nombre),
# bloquea duplicados por (SKU, id de publicación normalizado) y no por URL cruda
# (la URL de ML trae params de tracking que cambian en cada copia), y dispara el
# mismo scraper (API primero, Selenium de fallback) que ya usa el monitor unificado.
# No calcula rentabilidad acá — el frontend ya tiene compMargenAt()+S.pmData.
# ══════════════════════════════════════════════════════

@app.post("/intel-comercial/mix/cargar")
async def mix_cargar(request: Request):
    try:
        body = await request.json()
        items = body.get('items', [])
        if not isinstance(items, list) or not items:
            raise HTTPException(status_code=400, detail="items debe ser una lista no vacía de {sku, link}")

        ss = get_gs().open_by_key(SPREADSHEET_ID)
        ent_ws = ss.worksheet('Entidades')
        ref_ws = ss.worksheet('Referencias_Mercado')
        ent_headers = ent_ws.row_values(1)
        ref_headers = ref_ws.row_values(1)

        ent_id_idx = ent_headers.index('Entidad_ID')
        ent_seq = _next_seq_id(
            [r[ent_id_idx] for r in ent_ws.get_all_values()[1:] if len(r) > ent_id_idx and r[ent_id_idx]], 'ENT')

        ref_id_idx = ref_headers.index('Referencia_ID')
        ref_rows = ref_ws.get_all_values()[1:]
        ref_seq = _next_seq_id(
            [r[ref_id_idx] for r in ref_rows if len(r) > ref_id_idx and r[ref_id_idx]], 'REF')

        sku_idx = ref_headers.index('SKU')
        link_idx = ref_headers.index('Link_Publicacion')
        existentes = set()
        for r in ref_rows:
            sku_v = (r[sku_idx].strip().lower() if len(r) > sku_idx else '')
            link_v = (r[link_idx] if len(r) > link_idx else '')
            ids_v = _monitor_extract_ids(link_v)
            pub_key = ids_v.get('product_id') or ids_v.get('item_id')
            if sku_v and pub_key:
                existentes.add((sku_v, str(pub_key)))

        driver_holder = {'driver': None}
        resultados = []
        try:
            for it in items:
                sku = str(it.get('sku', '')).strip()
                link = str(it.get('link', '')).strip()
                if not sku or not link:
                    resultados.append({'sku': sku, 'link': link, 'estado': 'Error',
                                        'detalle': 'SKU y Link son obligatorios'})
                    continue

                ids = _monitor_extract_ids(link)
                pub_key = ids.get('product_id') or ids.get('item_id')
                if not pub_key:
                    resultados.append({'sku': sku, 'link': link, 'estado': 'Error',
                                        'detalle': 'Link no reconocido (sin product_id ni item_id)'})
                    continue

                dup_key = (sku.lower(), str(pub_key))
                if dup_key in existentes:
                    resultados.append({'sku': sku, 'link': link, 'estado': 'Duplicado',
                                        'detalle': 'Ya existe una referencia con ese SKU y esa publicación'})
                    continue

                res = leer_precio_publicacion(link, driver_holder)

                entidad_id, entidad_nombre = '', ''
                seller_id = res.get('seller_id')
                if seller_id:
                    _, entidad_existente = _find_row_by_id(ent_ws, 'Seller_ID', str(seller_id))
                    if entidad_existente:
                        entidad_id = entidad_existente.get('Entidad_ID', '')
                        entidad_nombre = entidad_existente.get('Nombre', '')
                    else:
                        ent_seq += 1
                        entidad_id = f'ENT-{ent_seq:06d}'
                        entidad_nombre = fetch_seller(seller_id) or f'Vendedor {seller_id}'
                        _append_row_from_dict(ent_ws, ent_headers, {
                            'Entidad_ID': entidad_id, 'Nombre': entidad_nombre, 'Tipo': 'Competencia',
                            'Fecha_Alta': datetime.now().strftime('%d/%m/%Y'), 'Seller_ID': str(seller_id),
                        })

                ref_seq += 1
                referencia_id = f'REF-{ref_seq:06d}'
                _append_row_from_dict(ref_ws, ref_headers, {
                    'Referencia_ID': referencia_id, 'SKU': sku, 'Tipo': 'Competencia',
                    'Entidad_ID': entidad_id, 'Entidad_Nombre': entidad_nombre,
                    'Link_Publicacion': link, 'Seller_ID_Esperado': str(seller_id) if seller_id else '',
                    'Fecha_Alta': datetime.now().strftime('%d/%m/%Y'), 'Origen': 'Mix',
                })
                existentes.add(dup_key)

                resultados.append({
                    'sku': sku, 'link': link, 'estado': res.get('estado', 'Error'),
                    'precio_detectado': res.get('precio'), 'metodo': res.get('metodo', ''),
                    'entidad_id': entidad_id, 'entidad_nombre': entidad_nombre,
                    'referencia_id': referencia_id, 'detalle': res.get('detalle_error', ''),
                })
        finally:
            if driver_holder['driver'] is not None:
                try:
                    driver_holder['driver'].quit()
                except Exception:
                    pass

        return {"status": "ok", "resultados": resultados}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ══════════════════════════════════════════════════════
# COMPETENCIA — migración de la Etapa 1 (a los históricos/links unificados)
# Una sola vez. Dry-run (default) o real; la real exige el plan_hash del informe aprobado
# y corre en un hilo (el worker es único, no se bloquea el resto). Ver competencia_migracion.py.
# Protegido SIEMPRE con X-ERP-Key, incluso si ERP_API_KEY no está definida (aquí falla cerrado,
# a diferencia del modo permisivo del middleware).
# ══════════════════════════════════════════════════════

import threading
_migracion_lock = threading.Lock()


def _exigir_clave_estricta(request: Request):
    esperada = os.environ.get("ERP_API_KEY", "").strip()
    if not esperada:
        raise HTTPException(status_code=503, detail="ERP_API_KEY no está definida en el servidor: "
                                                    "la migración no corre sin clave.")
    from erp_auth import HEADER_CLAVE, clave_valida
    if not clave_valida(esperada, request.headers.get(HEADER_CLAVE)):
        raise HTTPException(status_code=401, detail="X-ERP-Key inválida o ausente")


def _migracion_competencia_job(job_id, ejecutar_real, plan_hash):
    import competencia_migracion
    log = job_status[job_id]["log"]
    try:
        ss = get_gs().open_by_key(SPREADSHEET_ID)
        res = competencia_migracion.correr(ss, plan_hash, ejecutar_real, log=log.append, archivo_local=False)
        job_status[job_id] = {"status": "done", "log": log, "resultado": res, "finished": datetime.now().isoformat()}
    except Exception as e:
        job_status[job_id] = {"status": "error", "message": str(e), "log": log}
    finally:
        _migracion_lock.release()


# ── Análisis de Competencia (Etapa 3): datos para la pantalla unificada. Solo lectura, con caché; protegido por X-ERP-Key (erp_auth).
def _analisis_leer_filas():
    import competencia_db as cdb
    import competencia_migracion as cm
    ss = get_gs().open_by_key(SPREADSHEET_ID)
    titulos = {ws.title for ws in ss.worksheets()}
    v = lambda n: cm._valores(ss, n, titulos)  # noqa: E731
    # Tiendas_Estado puede tener decenas de miles de filas: no se baja entera, solo se cuenta (una columna) para avisar si crece de más.
    estado_filas = max(len(ss.worksheet("Tiendas_Estado").col_values(1)) - 1, 0) if "Tiendas_Estado" in titulos else 0
    return {"refs": v("Referencias_Mercado"), "hist": v(cdb.HISTORIAL_SHEET), "eventos": v("Eventos_Competencia"),
            "conteo": v("Tiendas_Conteo"), "categorias": v("Categoria_Competidores"), "estado_filas": estado_filas}


_analisis_cache = None


@app.get("/competencia/analisis")
async def competencia_analisis(dias: int = 30, refrescar: bool = False):
    """Datos de la pantalla Análisis de Competencia: por referencia (SKU x competidor) último precio, anterior, desde cuándo rige, precio ganador y
    serie de `dias` días; eventos; conteo de tiendas; mapa de categorías. Caché 10 min (`refrescar=true` relee, máx. 1 cada 30 s)."""
    global _analisis_cache
    import competencia_analisis
    if _analisis_cache is None:
        _analisis_cache = competencia_analisis.CacheAnalisis(_analisis_leer_filas)
    try:
        return await run_in_threadpool(_analisis_cache.obtener, dias, refrescar)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"No se pudo leer el Sheet de competencia: {e}")


@app.get("/competencia/publicaciones-propias")
async def competencia_publicaciones_propias(sku: str):
    """NUESTRAS publicaciones de ML (cuentas IT y MT) de un SKU: para actuar (oferta / precio) desde la pantalla de competencia. Solo lectura; X-ERP-Key (erp_auth)."""
    import competencia_publicaciones
    try:
        return await run_in_threadpool(competencia_publicaciones.publicaciones_por_sku, sku)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.get("/competencia/precio-ml")
async def competencia_precio_ml(sku: str, refrescar: bool = False):
    """Precio REAL (con la oferta aplicada) de NUESTRAS publicaciones de ML de un SKU, por cuenta. Solo lectura; X-ERP-Key; caché de 5 min por SKU."""
    import competencia_publicaciones
    try:
        return await run_in_threadpool(competencia_publicaciones.precio_real_cacheado, sku, refrescar)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.post("/competencia/migracion/run")
async def competencia_migracion_run(request: Request):
    """Body: {"ejecutar": false|true, "plan_hash": "<hash del dry-run aprobado>"}. Sin `ejecutar` = dry-run."""
    _exigir_clave_estricta(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    ejecutar_real = bool(body.get("ejecutar", False))
    plan_hash = str(body.get("plan_hash", "")).strip()
    if ejecutar_real and not plan_hash:
        raise HTTPException(status_code=400, detail="ejecutar=true requiere plan_hash")
    if not _migracion_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Ya hay una migración/dry-run en curso")
    job_id = f"migcomp_{int(time.time())}"
    job_status[job_id] = {"status": "running", "log": [], "started": datetime.now().isoformat(),
                          "modo": "ejecutar" if ejecutar_real else "dry-run"}
    threading.Thread(target=_migracion_competencia_job, args=(job_id, ejecutar_real, plan_hash), daemon=True).start()
    return {"job_id": job_id, "status": "started", "modo": job_status[job_id]["modo"]}


@app.get("/competencia/migracion/status/{job_id}")
def competencia_migracion_status(job_id: str, request: Request):
    _exigir_clave_estricta(request)
    return job_status.get(job_id, {"status": "not_found"})


# ── Cambios masivos y reversibles sobre Referencias_Mercado (Etapa 2): desactivar las referencias de una entidad
# (Global Electronics: somos nosotros). Dry-run por defecto; la real exige la cantidad esperada. Misma clave estricta.

def _desactivar_entidad_sync(entidad, ejecutar, esperado):
    import competencia_referencias
    ss = get_gs().open_by_key(SPREADSHEET_ID)
    return competencia_referencias.desactivar_entidad(ss, entidad, ejecutar, esperado, operador="endpoint")


def _revertir_lote_sync(lote, ejecutar):
    import competencia_referencias
    ss = get_gs().open_by_key(SPREADSHEET_ID)
    return competencia_referencias.revertir_lote(ss, lote, ejecutar)


async def _cambio_referencias(request: Request, fn):
    _exigir_clave_estricta(request)
    if not _migracion_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Hay una migración/cambio masivo en curso")
    try:
        return await run_in_threadpool(fn)
    except Exception as e:
        if e.__class__.__name__ == "CambioError":
            raise HTTPException(status_code=400, detail=str(e))
        raise
    finally:
        _migracion_lock.release()


@app.post("/competencia/referencias/desactivar-entidad")
async def competencia_desactivar_entidad(request: Request):
    """Body: {"entidad": "GLOBAL ELECTRONICS GROUP", "ejecutar": false, "esperado": 1927}. Sin `ejecutar` = dry-run."""
    body = await request.json()
    entidad = str(body.get("entidad", "")).strip()
    ejecutar = bool(body.get("ejecutar", False))
    esperado = body.get("esperado")
    if ejecutar and esperado is None:
        raise HTTPException(status_code=400, detail="ejecutar=true requiere `esperado` (la cantidad que mostró el dry-run)")
    return await _cambio_referencias(request, lambda: _desactivar_entidad_sync(entidad, ejecutar, esperado))


def _borrar_lecturas_sync(entidad, ejecutar, esperado):
    import competencia_referencias
    ss = get_gs().open_by_key(SPREADSHEET_ID)
    return competencia_referencias.borrar_lecturas_entidad(ss, entidad, ejecutar, esperado, operador="endpoint")


def _borrar_respaldo_sync(nombre, ejecutar, confirmar):
    import competencia_referencias
    ss = get_gs().open_by_key(SPREADSHEET_ID)
    return competencia_referencias.borrar_pestana_respaldo(ss, nombre, ejecutar, confirmar, operador="endpoint")


@app.post("/competencia/historial/borrar-lecturas-entidad")
async def competencia_borrar_lecturas_entidad(request: Request):
    """Body: {"entidad": "GLOBAL ELECTRONICS GROUP", "ejecutar": false, "esperado": 7073}. IRREVERSIBLE: dry-run primero;
    no correrlo mientras el scraper está escribiendo."""
    body = await request.json()
    entidad, ejecutar, esperado = str(body.get("entidad", "")).strip(), bool(body.get("ejecutar", False)), body.get("esperado")
    if ejecutar and esperado is None:
        raise HTTPException(status_code=400, detail="ejecutar=true requiere `esperado` (la cantidad que mostró el dry-run)")
    return await _cambio_referencias(request, lambda: _borrar_lecturas_sync(entidad, ejecutar, esperado))


@app.post("/competencia/pestanas/borrar-respaldo")
async def competencia_borrar_respaldo(request: Request):
    """Body: {"nombre": "Respaldo_Hist_Competidores_20261005", "ejecutar": false, "confirmar": "<mismo nombre>"}. Solo borra
    pestañas con ese patrón de nombre."""
    body = await request.json()
    nombre, ejecutar, confirmar = str(body.get("nombre", "")).strip(), bool(body.get("ejecutar", False)), body.get("confirmar")
    if ejecutar and not confirmar:
        raise HTTPException(status_code=400, detail="ejecutar=true requiere `confirmar` con el nombre exacto de la pestaña")
    return await _cambio_referencias(request, lambda: _borrar_respaldo_sync(nombre, ejecutar, confirmar))


@app.post("/competencia/referencias/revertir-lote")
async def competencia_revertir_lote(request: Request):
    """Body: {"lote": "LOTE-...", "ejecutar": false}. Deshace un cambio masivo registrado en Cambios_Referencias."""
    body = await request.json()
    lote, ejecutar = str(body.get("lote", "")).strip(), bool(body.get("ejecutar", False))
    if not lote:
        raise HTTPException(status_code=400, detail="Falta `lote`")
    return await _cambio_referencias(request, lambda: _revertir_lote_sync(lote, ejecutar))

# ══════════════════════════════════════════════════════
# ML OFERTAS — dashboard de ofertas/promos activas (docs/business/
# COMERCIAL/canales/mercadolibre/REQ_MODULO_OFERTAS_ML.md). Fases 1 y 2
# (lectura + alertas) más Fase 3 (activar/sacar UNA oferta puntual,
# habilitada 2026-08-27 -- ver 00_LEEME.md §5 "Excepción — módulo de
# Ofertas ML"). Job propio en ml_ofertas.py para lectura, no comparte
# job_status con el resto; las acciones de escritura son síncronas
# (una publicación por vez, a propósito -- no hay endpoint masivo acá).
# ══════════════════════════════════════════════════════

@app.post("/ml-ofertas/run")
async def ml_ofertas_run(background_tasks: BackgroundTasks, incluir_propias: bool = False):
    job_id = f"mlofertas_{int(time.time())}"
    tc = float(tc_bna_requerido())
    background_tasks.add_task(ml_ofertas.iniciar_job, job_id, None, incluir_propias, tc)
    return {"job_id": job_id, "status": "started"}

@app.get("/ml-ofertas/status/{job_id}")
async def ml_ofertas_status(job_id: str):
    return ml_ofertas.estado_job(job_id) or {"status": "not_found"}

@app.post("/ml-ofertas/alertas/run")
async def ml_ofertas_alertas_run(
    background_tasks: BackgroundTasks, cuenta: str, item_ids_con_oferta: str,
    dias_ventas: int = 30, min_ventas: int = 5,
):
    """`item_ids_con_oferta` viaja como string separado por comas (el
    dashboard ya tiene esa lista en memoria tras `/ml-ofertas/run`, así
    evitamos volver a pedirla acá)."""
    job_id = f"mlofertasalertas_{int(time.time())}"
    ids = [i for i in item_ids_con_oferta.split(",") if i]
    background_tasks.add_task(ml_ofertas.iniciar_job_alertas, job_id, cuenta, ids, dias_ventas, min_ventas)
    return {"job_id": job_id, "status": "started"}

@app.get("/ml-ofertas/alertas/status/{job_id}")
async def ml_ofertas_alertas_status(job_id: str):
    return ml_ofertas.estado_job(job_id) or {"status": "not_found"}

@app.post("/ml-ofertas/costos-envio/run")
async def ml_ofertas_costos_envio_run(background_tasks: BackgroundTasks, dias: int = 60):
    """Congela `shipping_id` de la venta más reciente de cada publicación
    (ambas cuentas) -- pedido de Maxx 2026-09-01: correrlo cada tanto,
    no en vivo por ítem. El costo real de envío en sí se resuelve recién
    por ítem puntual (`resolver_item_para_gestion`), no acá."""
    job_id = f"mlofertascostosenvio_{int(time.time())}"
    background_tasks.add_task(ml_ofertas.iniciar_job_costos_envio, job_id, None, dias)
    return {"job_id": job_id, "status": "started"}

@app.get("/ml-ofertas/costos-envio/status/{job_id}")
async def ml_ofertas_costos_envio_status(job_id: str):
    return ml_ofertas.estado_job(job_id) or {"status": "not_found"}

# ── Fase 3 — escritura (activar/sacar UNA oferta, UNA publicación por
# vez). Historial en la pestaña "Historial Ofertas ML" del mismo Sheet que
# usa el resto del ERP (SPREADSHEET_ID) -- mismo patrón que "Historial
# Competidores" más arriba: se crea sola la primera vez que hace falta. ──

HIST_OFERTAS_SHEET_NAME = "Historial Ofertas ML"
HIST_OFERTAS_HEADERS = ["Fecha", "Cuenta", "Item ID", "SKU", "Accion", "Tipo/Promocion",
                         "Precio Anterior", "Precio Nuevo", "Margen % Resultante", "Bajo Umbral", "Operador", "Hora", "Origen"]

_ORIGEN_PONER_PRECIO = "Precios y ofertas ML"


def _hora_argentina() -> str:
    return datetime.now(timezone(timedelta(hours=-3))).strftime("%H:%M:%S")


def _registrar_historial_oferta(fila: dict):
    fila = {"Hora": _hora_argentina(), **fila}       # el registro lleva fecha Y hora (quién y cuándo)
    gs = get_gs()
    ss = gs.open_by_key(SPREADSHEET_ID)
    try:
        ws = ss.worksheet(HIST_OFERTAS_SHEET_NAME)
    except Exception:
        ws = ss.add_worksheet(title=HIST_OFERTAS_SHEET_NAME, rows=20000, cols=len(HIST_OFERTAS_HEADERS))
        ws.append_row(HIST_OFERTAS_HEADERS)
    ws.append_row([fila.get(h, "") for h in HIST_OFERTAS_HEADERS])

# Los 4 endpoints de acá abajo hacen red/SQL bloqueante de verdad (ML +
# Táctica, esta última por el túnel Tailscale de `entrypoint.sh`, ya de por
# sí más lento/frágil que una conexión directa). Uvicorn corre un solo
# worker (ver `entrypoint.sh`) -- si el código bloqueante corre directo
# adentro de un `async def`, congela el event loop ENTERO mientras dura,
# así que ningún otro pedido concurrente se atiende (ni el polling de
# `/ml-ofertas/status/{id}` de un job en curso, ni otro click del usuario).
# Confirmado en producción 2026-08-27: mientras corría el escaneo de
# ofertas propias, un buscador puntual tiró "Failed to fetch" -- exactamente
# el síntoma de esto. `run_in_threadpool` saca el trabajo bloqueante del
# hilo del event loop.

def _promociones_item_sync(item_id: str, cuenta: str) -> dict:
    ml = ml_ofertas.MLOfertasClient()
    return {"promociones": ml_ofertas.listar_promociones_item(ml, cuenta, item_id)}

@app.get("/ml-ofertas/item/{item_id}/promociones")
async def ml_ofertas_item_promociones(item_id: str, cuenta: str):
    return await run_in_threadpool(_promociones_item_sync, item_id, cuenta)

def _costo_envio_item_sync(item_id: str, cuenta: str) -> dict:
    """Liviano a propósito -- solo resuelve UN ítem contra la cache que
    `iniciar_job_costos_envio` congeló (un dict-lookup + a lo sumo UNA
    llamada a /shipments/{id}), nunca el catálogo entero. Se llama en
    paralelo con /promociones cada vez que se abre el panel de gestión
    (misma cuenta/MLA que ya se está pidiendo ahí), tanto desde la tabla
    principal como desde el buscador puntual -- por eso vive aparte y no
    adentro de `_armar_fila`/`ofertas_activas` (eso sí es masivo, cientos
    de ítems por corrida, y encarecería esa corrida sin necesidad)."""
    ml = ml_ofertas.MLOfertasClient()
    return {"costo_envio_real": ml_ofertas.costo_envio_real_item(ml, item_id, cuenta)}

@app.get("/ml-ofertas/item/{item_id}/costo-envio")
async def ml_ofertas_item_costo_envio(item_id: str, cuenta: str):
    return await run_in_threadpool(_costo_envio_item_sync, item_id, cuenta)

def _buscar_item_sync(item_id: str, cuenta: str) -> dict:
    """Buscador puntual -- para activar una oferta en un MLA que hoy NO
    tiene nada activo (no aparece en el escaneo de campañas de /ml-ofertas/
    run, que por diseño solo trae publicaciones que ya tienen algo)."""
    ml = ml_ofertas.MLOfertasClient()
    tc = tc_bna_requerido()
    try:
        r = ml_ofertas.resolver_item_para_gestion(ml, *costos_ecom.proveedores_de_costo_e_iva(), item_id, cuenta, tc)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"No se pudo consultar Mercado Libre: {e}")
    if not r.get("encontrado"):
        raise HTTPException(status_code=404, detail="Publicación no encontrada en esa cuenta")
    r.pop("encontrado")
    r["costo_sin_iva"] = float(r["costo_sin_iva"]) if r["costo_sin_iva"] is not None else None
    r["iva_factor"] = float(r["iva_factor"]) if r["iva_factor"] is not None else None
    r["tc"] = float(r["tc"])
    return r

@app.get("/ml-ofertas/item/{item_id}/buscar")
async def ml_ofertas_item_buscar(item_id: str, cuenta: str):
    return await run_in_threadpool(_buscar_item_sync, item_id, cuenta)

def _activar_item_sync(item_id: str, cuenta: str, precio: Decimal, precio_tachado: Decimal) -> dict:
    ml = ml_ofertas.MLOfertasEscritura()
    return ml.activar_oferta_propia(item_id, cuenta, precio, precio_tachado)

@app.post("/ml-ofertas/item/{item_id}/activar")
async def ml_ofertas_item_activar(item_id: str, request: Request, background_tasks: BackgroundTasks):
    """El registro en "Historial Ofertas ML" va por `background_tasks`, NO
    antes de responder -- confirmado en real (2026-08-27) que la primera
    escritura en una pestaña nueva del Sheet (crearla + header + fila) son
    varias llamadas seguidas a la API de Sheets, lentas la primera vez, y
    empujaban la respuesta más allá del timeout del navegador/Railway: la
    oferta SÍ se sacaba en ML pero el frontend recibía "Failed to fetch"
    igual, sin saber que había funcionado."""
    body = await request.json()
    cuenta = body["cuenta"]
    precio = Decimal(str(body["precio"]))
    precio_tachado = Decimal(str(body["precio_tachado"]))
    r = await run_in_threadpool(_activar_item_sync, item_id, cuenta, precio, precio_tachado)
    if r.get("ok"):
        background_tasks.add_task(_registrar_historial_oferta, {
            "Fecha": date.today().isoformat(), "Cuenta": cuenta, "Item ID": item_id, "SKU": body.get("sku", ""),
            "Accion": "Activar", "Tipo/Promocion": "PRICE_DISCOUNT",
            "Precio Anterior": body.get("precio_anterior", ""), "Precio Nuevo": f"{precio} (tachado {precio_tachado})",
            "Margen % Resultante": body.get("margen_pct", ""), "Bajo Umbral": "Sí" if body.get("bajo_umbral") else "No",
            "Operador": body.get("operador", ""),
        })
    return r

def _sacar_item_sync(item_id: str, cuenta: str, promotion_type: str, promotion_id: str | None) -> dict:
    ml = ml_ofertas.MLOfertasEscritura()
    return ml.sacar_de_promocion(item_id, cuenta, promotion_type, promotion_id)

@app.post("/ml-ofertas/item/{item_id}/sacar")
async def ml_ofertas_item_sacar(item_id: str, request: Request, background_tasks: BackgroundTasks):
    """Mismo motivo que `/activar` para diferir el historial -- ver su docstring."""
    body = await request.json()
    cuenta = body["cuenta"]
    promotion_type = body["promotion_type"]
    promotion_id = body.get("promotion_id")
    r = await run_in_threadpool(_sacar_item_sync, item_id, cuenta, promotion_type, promotion_id)
    if r.get("ok"):
        background_tasks.add_task(_registrar_historial_oferta, {
            "Fecha": date.today().isoformat(), "Cuenta": cuenta, "Item ID": item_id, "SKU": body.get("sku", ""),
            "Accion": "Sacar", "Tipo/Promocion": promotion_type + (f" ({promotion_id})" if promotion_id else ""),
            "Precio Anterior": body.get("precio_anterior", ""), "Precio Nuevo": "",
            "Margen % Resultante": "", "Bajo Umbral": "", "Operador": body.get("operador", ""),
        })
    return r

def _activar_campana_sync(item_id: str, cuenta: str, precio_pm: Decimal, descuento_pct: Decimal, promotion_id: str | None) -> dict:
    ml = ml_ofertas.MLOfertasEscritura()
    return ml_ofertas.activar_en_campana_tradicional(ml, cuenta, item_id, precio_pm, descuento_pct, promotion_id)

@app.post("/ml-ofertas/item/{item_id}/activar-campana")
async def ml_ofertas_item_activar_campana(item_id: str, request: Request, background_tasks: BackgroundTasks):
    """"Oferta Tradicional" -- flujo real de Maxx confirmado 2026-08-28
    (80% de su uso): fija el tachado en el valor que, con `descuento_pct`
    de descuento (25% default -- el mismo % que se aplica en la sección
    de Promociones de ML), da `precio_pm` como precio final. Ver
    `activar_en_campana_tradicional` por la fórmula corregida 2026-08-28
    (no es "inflar el mismo %", ver su docstring). Dos escrituras reales
    de ML por dentro (`fijar_precio_base` + `meter_en_campana`, ver sus
    docstrings) -- mismo motivo que /activar para diferir el historial."""
    body = await request.json()
    cuenta = body["cuenta"]
    precio_pm = Decimal(str(body["precio_pm"]))
    descuento_pct = Decimal(str(body.get("descuento_pct", 25)))
    promotion_id = body.get("promotion_id")
    r = await run_in_threadpool(_activar_campana_sync, item_id, cuenta, precio_pm, descuento_pct, promotion_id)
    if r.get("ok"):
        background_tasks.add_task(_registrar_historial_oferta, {
            "Fecha": date.today().isoformat(), "Cuenta": cuenta, "Item ID": item_id, "SKU": body.get("sku", ""),
            "Accion": "Activar en campaña", "Tipo/Promocion": f"SELLER_CAMPAIGN ({r.get('nombre_campana') or r.get('promotion_id')})",
            "Precio Anterior": body.get("precio_anterior", ""),
            "Precio Nuevo": f"{r.get('precio')} (tachado {r.get('original_price') or r.get('precio_tachado_pedido')})",
            "Margen % Resultante": body.get("margen_pct", ""), "Bajo Umbral": "Sí" if body.get("bajo_umbral") else "No",
            "Operador": body.get("operador", ""),
        })
    return r


# ══════════════════════════════════════════════════════
# AYALA CORE — motor de precios propio, Etapa 1 (solo lectura). Ver
# docs/business/COMERCIAL/canales/mercadolibre/AYALA_CORE.md (constitución
# del módulo). Esta etapa NO escribe nada a ML -- sirve para validar el
# motor (`ayala_core.py`) contra el ejemplo real de la planilla de Maxx
# antes de habilitar corrección de precio (Etapa 2).
# ══════════════════════════════════════════════════════

@app.get("/ayala-core/skus")
async def ayala_core_skus():
    return {"skus": ayala_core.SKUS_PILOTO}

def _renta_base_valida(renta_base: str) -> str:
    if renta_base not in ayala_core.RENTA_BASES:
        raise HTTPException(status_code=422, detail=f"renta_base debe ser uno de {', '.join(ayala_core.RENTA_BASES)} (vino {renta_base!r}).")
    return renta_base


def _ayala_core_renta_dict(
    renta_contado: float, renta_reducida: float, renta_3: float, renta_6: float, renta_9: float, renta_12: float,
    renta_18: float | None = None, renta_24: float | None = None,
) -> dict[str | int, Decimal]:
    """Arma el dict de renta por condición que pide `calcular_precios_
    todas_condiciones` a partir de los 6 query params planos (uno por
    condición, ver `ayala_core.RENTA_POR_CONDICION_DEFAULT` -- reemplaza
    la cascada Contado/diferencial, pedido de Maxx 2026-09-04)."""
    out = {
        "contado": Decimal(str(renta_contado)), "reducida": Decimal(str(renta_reducida)),
        3: Decimal(str(renta_3)), 6: Decimal(str(renta_6)), 9: Decimal(str(renta_9)), 12: Decimal(str(renta_12)),
    }
    # 18 y 24 cuotas solo existen en la Web (Mercado Pago); sin valor propio, la renta de 12 cuotas. Mercado Libre ignora estas claves.
    out[18] = Decimal(str(renta_18)) if renta_18 is not None else out[12]
    out[24] = Decimal(str(renta_24)) if renta_24 is not None else out[12]
    return out

import mercados as mercados_mod
_TARIFAS_CACHE: dict = {"en": 0.0, "payload": None, "info": None}


def _tarifas_actuales() -> tuple[dict, dict]:
    """Tarifas de la pestaña «Mercados» (foto guardada; sin foto, los valores iniciales del código). Memoria de 60 s para no ir a la base en cada cálculo."""
    from rentabilidad import db as _db
    if _TARIFAS_CACHE["payload"] is None or time.time() - _TARIFAS_CACHE["en"] > 60:
        p, info = mercados_mod.foto_o_iniciales(_db.sesion)
        _TARIFAS_CACHE.update(en=time.time(), payload=p, info=info)
    return _TARIFAS_CACHE["payload"], _TARIFAS_CACHE["info"]


def _preparar_mercado(mercado: str, usar_costo_orden=None, usar_cheque=None, usar_iibb=None, costo_orden=None, cheque_pct=None, iibb_pct=None, recargo_cuotas=None) -> dict | None:
    """Parámetros del mercado pedido, o None si es Mercado Libre sin ningún cambio (entonces corre la cuenta de siempre, sin tocar nada)."""
    if mercado not in mercados_mod.MERCADOS:
        raise HTTPException(status_code=422, detail=f"Mercado desconocido: {mercado!r}.")
    cambios = any(x is not None for x in (usar_costo_orden, usar_cheque, usar_iibb, costo_orden, cheque_pct, iibb_pct))
    if mercado == "ml" and not cambios:
        return None
    payload, info = _tarifas_actuales()
    filas = payload["filas"]
    com = mercados_mod.comunes(filas)
    par = mercados_mod.parametros_mercado(mercado, filas, recargo_cuotas=Decimal(str(recargo_cuotas)) if recargo_cuotas is not None else None)
    v = com["valores"]
    act = mercados_mod.ACTIVOS_POR_DEFECTO[mercado]
    usados = {
        "orden": act["orden"] if usar_costo_orden is None else bool(usar_costo_orden), "cheque": act["cheque"] if usar_cheque is None else bool(usar_cheque),
        "iibb": act["iibb"] if usar_iibb is None else bool(usar_iibb),
        "costo_orden": Decimal(str(costo_orden)) if costo_orden is not None else v["costo_orden"],
        "cheque_pct": Decimal(str(cheque_pct)) if cheque_pct is not None else v["cheque_pct"],
        "iibb_pct": Decimal(str(iibb_pct)) if iibb_pct is not None else v["iibb_pct"],
    }
    return {"mercado": mercado, "par": par, "usados": usados, "avisos": par["avisos"] + com["avisos"], "tarifas": info}


def _mercado_respuesta(m: dict, envio_manual) -> dict:
    """Lo que la pantalla necesita para mostrar el mercado: condiciones, comisión desglosada (base + cuotas + recargo), descuentos usados y avisos."""
    par, u = m["par"], m["usados"]
    f = lambda x: None if x is None else float(x)
    return {
        "mercado": m["mercado"], "mercado_nombre": par["nombre"], "condiciones": par["condiciones"], "etiqueta_contado": par["etiqueta_contado"],
        "envio_estimado_como_ml": envio_manual is None and m["mercado"] != "ml",
        "parametros": {"comision_pct": f(par["comision_pct"]), "financiero": {k: f(v) for k, v in par["financiero"].items()}, "recargo_cuotas": f(par["recargo_cuotas"]),
                       "desglose": {k: {kk: f(vv) for kk, vv in d.items()} for k, d in par["desglose"].items()},
                       "costo_orden": f(u["costo_orden"]) if u["orden"] else 0, "cheque_pct": f(u["cheque_pct"]) if u["cheque"] else 0, "iibb_pct": f(u["iibb_pct"]) if u["iibb"] else 0,
                       "usa": {"orden": u["orden"], "cheque": u["cheque"], "iibb": u["iibb"]}},
        "avisos_mercado": [a["texto"] for a in m["avisos"]], "notas_mercado": [n["texto"] for n in m["par"]["notas"]],
    }


def _iva_manual(iva: float | None) -> Decimal | None:
    """«IVA del SKU» cargado a mano: solo 10,5 % o 21 % (las dos alícuotas del ERP). Devuelve el factor (1,105 / 1,21)."""
    if iva is None:
        return None
    if round(iva, 3) == 21:
        return Decimal("1.21")
    if round(iva, 3) == 10.5:
        return Decimal("1.105")
    raise HTTPException(status_code=422, detail="El IVA del SKU tiene que ser 10,5 o 21.")


def _cantidad_valida(cantidad) -> int:
    """Unidades por publicación (pack): entero de 1 a 999."""
    try:
        n = int(cantidad)
    except (TypeError, ValueError):
        n = 0
    if n < 1 or n > 999 or n != cantidad:
        raise HTTPException(status_code=422, detail="La cantidad por publicación tiene que ser un entero entre 1 y 999.")
    return n

def _motivo_sin_costo(costo_p, sku: str) -> str:
    """El motivo en texto de por qué un SKU no tiene costo, leído de la foto que ya usa el proveedor (nunca baja nada de Ecom)."""
    try:
        return costo_p._catalogo_fn().motivo_sin_costo(sku)
    except Exception:
        return "no figura en el catálogo de costos de Ecom"


def _ayala_core_motor_sync(
    sku: str, renta_por_condicion: dict[str | int, Decimal],
    envio_real: Decimal | None, envio_full: bool, item_id: str | None, cuenta: str | None,
    tc_override: Decimal | None = None, costo_override: Decimal | None = None,
    _proveedores=None, _tc: Decimal | None = None, cantidad: int = 1, _mercado: dict | None = None,
    iva_manual: Decimal | None = None, iva_solo_si_falta: bool = False,
    renta_base: str = "con_iva",
) -> dict:
    # Pedido de Maxx 2026-09-16: mismo criterio que el TC manual -- poder
    # pisar el costo sin IVA (USD) a mano para simular. Sin
    # `costo`, viene del catálogo de Ecom (y falla SIN_COSTO si el SKU
    # no está ahí). Con `costo`, ni siquiera se
    # consulta Ecom -- también sirve para simular un SKU que todavía no
    # tiene costo cargado ahí.
    costo_p, iva_p = _proveedores or costos_ecom.proveedores_de_costo_e_iva()
    if costo_override is not None:
        costo_usd = costo_override
    else:
        costo_usd = costo_p.obtener(sku)
        if costo_usd is None and costos_ecom.refrescar_por_faltante():     # tal vez es un artículo tocado después de la última foto: se refresca UNA vez (máx. cada 10 min)
            costo_usd = costo_p.obtener(sku)
        if costo_usd is None:
            raise HTTPException(status_code=404, detail=f"SIN_COSTO para SKU {sku!r}: {_motivo_sin_costo(costo_p, sku)}")
    # IVA: el de siempre (Táctica, con respaldo del artículo en Ecom). `iva_manual` pisa solo si lo pidió la persona (SKU puntual) o, en un lote, solo si el SKU no tiene IVA en ninguna fuente.
    iva_factor = None if (iva_manual is not None and not iva_solo_si_falta) else iva_p.factor(sku)
    if iva_factor is None and iva_manual is None and costos_ecom.refrescar_por_faltante():
        iva_factor = iva_p.factor(sku)
    if iva_factor is None and iva_manual is not None:
        iva_factor = iva_manual
    if iva_factor is None:
        raise HTTPException(status_code=404, detail=f"SIN_IVA para SKU {sku!r}: sin IVA en Ecom ni en Táctica: corregilo en Ecom o cargalo a mano (campo «IVA del SKU» en Opciones avanzadas)")
    # Pedido de Maxx 2026-09-15: poder pisar el TC de BNA a mano para
    # simular con un valor propio -- sin `tc`, se sigue usando el TC en
    # vivo como siempre.
    tc = tc_override if tc_override is not None else (_tc if _tc is not None else tc_rapido_requerido())
    # Pack (Bloque 2, PR 3): el costo de la publicación es el del SKU × la cantidad de unidades que trae. La cuenta de precios no cambia; con cantidad=1 todo da igual que antes.
    cantidad = _cantidad_valida(cantidad)
    costo_sin_iva = costo_usd * tc * cantidad

    item_info = None
    envio_usado = envio_real
    if item_id:
        if not cuenta:
            raise HTTPException(status_code=422, detail="Falta 'cuenta' para resolver item_id")
        ml = ml_ofertas.MLOfertasClient()
        d = ml.detalle_item_completo(item_id, cuenta) or {}
        if not d.get("id"):
            raise HTTPException(status_code=404, detail="Publicación no encontrada en esa cuenta")
        condicion_detectada = ayala_core.resolver_condicion_pago(ml, d, cuenta)
        if envio_usado is None:
            envio_info = ml_ofertas.costo_envio_real_item(ml, item_id, cuenta)
            # Mismo bug/fix que ayala_core.descubrir_publicaciones: la clave
            # real es "costo_envio_real", no "list_cost".
            envio_usado = Decimal(str(envio_info["costo_envio_real"])) if envio_info else Decimal(0)
        # Corregido 2026-09-15: ver ayala_core.resolver_precio_real -- con
        # una campaña/oferta activa, d['price'] es el tachado, no lo que
        # cobra el vendedor.
        precio_actual, tachado_actual = ayala_core.resolver_precio_real(ml, d["id"], cuenta, d)
        item_info = {
            "item_id": d["id"], "titulo": d.get("title", ""), "precio_actual": precio_actual,
            "condicion_detectada": condicion_detectada,
            "precio_tachado_actual": tachado_actual,
        }
    if envio_usado is None:
        envio_usado = Decimal(0)

    errores_condicion: dict = {}
    desglose_m: dict = {}
    if _mercado is None:
        precios = ayala_core.calcular_precios_todas_condiciones(
            costo_sin_iva=costo_sin_iva, iva_factor=iva_factor, envio_real=envio_usado,
            renta_por_condicion=renta_por_condicion, envio_full=envio_full, renta_base=renta_base,
        )
    else:
        u = _mercado["usados"]
        precios, errores_condicion = mercados_mod.calcular_mercado(
            _mercado["par"], costo_sin_iva=costo_sin_iva, iva_factor=iva_factor, envio_real=envio_usado,
            renta_por_condicion={str(k): v for k, v in renta_por_condicion.items()}, envio_full=envio_full,
            costo_orden=u["costo_orden"] if u["orden"] else Decimal(0), cheque_pct=u["cheque_pct"] if u["cheque"] else Decimal(0),
            iibb_pct=u["iibb_pct"] if u["iibb"] else Decimal(0), renta_base=renta_base)
        desglose_m = {c: {k: float(v) for k, v in mercados_mod.desglose(
            precios[c], costo_sin_iva=costo_sin_iva, iva_factor=iva_factor, envio_real=envio_usado, comision_pct=_mercado["par"]["comision_pct"],
            financiero_pct=_mercado["par"]["financiero"][c], iibb_pct=u["iibb_pct"] if u["iibb"] else Decimal(0), cheque_pct=u["cheque_pct"] if u["cheque"] else Decimal(0),
            costo_orden=u["costo_orden"] if u["orden"] else Decimal(0), envio_full=envio_full,
            costo_fijo_tramos=_mercado["par"].get("costo_fijo_tramos")).items()} for c in precios}
    # «Ver cuenta»: la cuenta línea por línea de cada condición (solo mostrar). Mercado Libre sin cambios usa los parámetros de siempre.
    if _mercado is None:
        cp = {"comision": ayala_core.COMISION_ML_DEFAULT, "iibb": ayala_core.IIBB_PCT_DEFAULT, "cheque": ayala_core.IMP_CHEQUE_PCT_DEFAULT, "orden": ayala_core.COSTO_ORDEN_ECOM_DEFAULT, "tramos": ayala_core.COSTO_FIJO_ML_TRAMOS}
        fin = lambda c: ayala_core._financiero_pct(int(c) if c.isdigit() else c)
    else:
        u = _mercado["usados"]
        cp = {"comision": _mercado["par"]["comision_pct"], "iibb": u["iibb_pct"] if u["iibb"] else Decimal(0), "cheque": u["cheque_pct"] if u["cheque"] else Decimal(0),
              "orden": u["costo_orden"] if u["orden"] else Decimal(0), "tramos": _mercado["par"].get("costo_fijo_tramos")}
        fin = lambda c: _mercado["par"]["financiero"][c]
    cuentas_m = {}
    for c, pr in precios.items():
        cu = mercados_mod.cuenta_paso_a_paso(pr, costo_sin_iva=costo_sin_iva, iva_factor=iva_factor, envio_real=envio_usado, comision_pct=cp["comision"], financiero_pct=fin(c),
                                             iibb_pct=cp["iibb"], cheque_pct=cp["cheque"], costo_orden=cp["orden"], envio_full=envio_full, costo_fijo_tramos=cp["tramos"])
        cuentas_m[c] = {"lineas": [{k: (float(v) if isinstance(v, Decimal) else v) for k, v in ln.items()} for ln in cu["lineas"]], "renta": float(cu["renta"]),
                        "renta_pct_con_iva": float(cu["renta_pct_con_iva"]), "renta_pct_sin_iva": float(cu["renta_pct_sin_iva"])}
    if item_info is not None:
        item_info["precio_calculado"] = precios.get(str(item_info["condicion_detectada"]))

    iva_origen = "ECOM" if getattr(iva_p, "tactica_caida", False) else "TACTICA"
    return {
        "sku": sku, "cantidad": cantidad, "costo_sin_iva_usd": float(costo_usd), "iva_factor": float(iva_factor), "iva_origen": iva_origen,
        "tc": float(tc), "costo_sin_iva_ars": float(costo_sin_iva), "envio_real": float(envio_usado),
        "envio_full": envio_full,
        "renta_por_condicion": {str(k): float(v) for k, v in renta_por_condicion.items()},
        "precios": {k: float(v) for k, v in precios.items()},
        "precios_unitarios": {k: round(float(v) / cantidad, 2) for k, v in precios.items()},
        "item": item_info,
        **(_mercado_respuesta(_mercado, envio_real) if _mercado is not None else {"mercado": "ml", "condiciones": list(mercados_mod.MERCADOS["ml"]["condiciones"]), "comision_pct": float(ayala_core.COMISION_ML_DEFAULT)}),
        "errores_condicion": errores_condicion,
        "desglose_mercado": desglose_m,
        "renta_base": renta_base,
        "cuentas": cuentas_m,
    }

# ══════════════════════════════════════════════════════
# MERCADOS — tarifas de la pestaña «Mercados» del Sheet del ERP (Bloque 2, PR 4). Solo lectura de ML/Ecom; lo único que se escribe es la creación de las
# pestañas «Mercados» y «Envios» en el Sheet del ERP (permitido), y solo si no existen.
# ══════════════════════════════════════════════════════

def _info_mercados() -> dict:
    return {k: {"nombre": v["nombre"], "condiciones": v["condiciones"], "etiqueta_contado": v["etiqueta_contado"], "usa_por_defecto": mercados_mod.ACTIVOS_POR_DEFECTO[k]}
            for k, v in mercados_mod.MERCADOS.items()}

# ── Sheet de las tarifas de mercados ──
# La pestaña «Mercados» (y «Envios») vive en el Sheet que indica la variable de entorno `MERCADOS_SHEET_ID` (el ID de la URL del Sheet, entre `/d/` y `/edit`). Sin esa variable
# no se lee ni se escribe ningún Sheet: las tarifas salen de los valores iniciales del código y la pantalla oculta «Crear pestañas». La cuenta de servicio de Google tiene que
# ser Editora de ese Sheet.
MERCADOS_SHEET_VARIABLE = "MERCADOS_SHEET_ID"
_SHEET_NOMBRE_CACHE: dict = {"id": None, "nombre": None, "en": 0.0}


def _mercados_sheet_id() -> str:
    return (os.environ.get(MERCADOS_SHEET_VARIABLE) or "").strip()


def _mercados_sheet_info() -> dict:
    sid = _mercados_sheet_id()
    if not sid:
        return {"configurado": False, "nombre": None, "variable": MERCADOS_SHEET_VARIABLE}
    c = _SHEET_NOMBRE_CACHE
    if c["id"] != sid or time.time() - c["en"] > 3600:
        try:
            nombre = get_gs().open_by_key(sid).title
        except Exception:  # noqa: BLE001 -- sin acceso: se informa sin nombre, nunca se cae la pantalla
            nombre = None
        c.update(id=sid, nombre=nombre, en=time.time())
    return {"configurado": True, "nombre": c["nombre"], "variable": MERCADOS_SHEET_VARIABLE}


def _exigir_mercados_sheet() -> str:
    sid = _mercados_sheet_id()
    if not sid:
        raise HTTPException(status_code=409, detail=f"Falta configurar la variable de entorno {MERCADOS_SHEET_VARIABLE} (el ID del Sheet de configuración) en el servidor.")
    return sid


def _estado_tarifas() -> dict:
    payload, info = _tarifas_actuales()
    filas = payload["filas"]
    com = mercados_mod.comunes(filas)
    avisos = []
    # Sin leer del Sheet es información (se usan los valores iniciales del código), no un aviso de configuración.
    informacion = ["Usando los valores iniciales del código (la pestaña «Mercados» todavía no se leyó del Sheet)."] if info["origen"] == "codigo" else []
    if info.get("error_msg"):
        avisos.append({"tipo": "error", "texto": f"Falló la última lectura de tarifas ({info['error_msg']}); se muestran las de {info.get('obtenido_en') or 'los valores iniciales'}."})
    por_mercado, notas_por_mercado = {}, {}
    for k in mercados_mod.MERCADOS:
        par = mercados_mod.parametros_mercado(k, filas)
        por_mercado[k] = [a["texto"] for a in par["avisos"]]
        notas_por_mercado[k] = [n["texto"] for n in par["notas"]]
    web = mercados_mod.parametros_mercado("web", filas)
    return {"tarifas": info, "comunes": {**{k: float(v) for k, v in com["valores"].items()}, "recargo_cuotas": float(web["recargo_cuotas"] or 0)}, "avisos": avisos + com["avisos"], "informacion": informacion, "notas_por_mercado": notas_por_mercado, "avisos_por_mercado": por_mercado,
            "mercados": _info_mercados(), "filas": len(filas), "sheet": _mercados_sheet_info()}

@app.get("/mercados/tarifas")
async def mercados_tarifas():
    """«Tarifas: hace X · Actualizar»: la foto guardada de la pestaña «Mercados» (sin foto, los valores iniciales del código, con aviso)."""
    return await run_in_threadpool(_estado_tarifas)

def _actualizar_tarifas_sync() -> dict:
    from rentabilidad import db as _db
    sid = _exigir_mercados_sheet()
    try:
        mercados_mod.actualizar_foto(_db.sesion, lambda: mercados_mod.leer_hoja(get_gs(), sid))
    except Exception as e:
        _TARIFAS_CACHE.update(en=0.0)
        raise HTTPException(status_code=502, detail=f"No se pudo leer la pestaña «Mercados»: {mercados_mod.ml_foto.mensaje_para_usuario(e)}")
    _TARIFAS_CACHE.update(en=0.0)
    return _estado_tarifas()

@app.post("/mercados/tarifas/actualizar")
async def mercados_tarifas_actualizar():
    return await run_in_threadpool(_actualizar_tarifas_sync)

@app.post("/mercados/init")
async def mercados_init():
    """Crea las pestañas «Mercados» (con los valores iniciales) y «Envios» (vacía, con encabezados) en el Sheet del ERP si no existen. No pisa nada."""
    sid = _exigir_mercados_sheet()
    try:
        return {"sheet": _mercados_sheet_info(), "pestanas": await run_in_threadpool(lambda: mercados_mod.crear_pestanas(get_gs(), sid))}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"No se pudieron crear las pestañas: {mercados_mod.ml_foto.mensaje_para_usuario(e)}")

@app.get("/ayala-core/catalogo-skus")
async def ayala_core_catalogo_skus():
    """TODOS los SKU de la foto de costos de Ecom (miles), para el selector del Motor: se carga una sola vez y se busca en el navegador. `[sku, estado_costo, tiene_iva_en_ecom]`;
    `estado_costo`: ok, sin_costo, ambiguo. Solo lee la foto en memoria/base: no consulta Ecom."""
    try:
        cat = await run_in_threadpool(costos_ecom.obtener_catalogo)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"No hay catálogo de costos de Ecom ({type(e).__name__}).")
    skus = cat.todos_los_skus()
    return {"obtenido_en": cat.obtenido_en, "total": len(skus), "skus": [[s, e, iva] for s, e, iva in skus]}


@app.get("/ayala-core/catalogo-skus/diagnostico")
async def ayala_core_catalogo_diagnostico():
    """Los SKU del catálogo que hoy NO calculan y por qué (sin costo, variantes con costos distintos, sin IVA en Ecom ni en Táctica). Solo lectura: no toca ningún SKU."""
    def _calc():
        cat = costos_ecom.obtener_catalogo()
        prov = costos_ecom.IvaConRespaldoEcom()
        try:
            prov.precargar()
        except Exception:
            pass
        filas = []
        for sku, estado, _iva in cat.todos_los_skus():
            if estado != "ok":
                filas.append({"sku": sku, "motivo": estado, "detalle": cat.motivo_sin_costo(sku)})
                continue
            f, _o = prov.factor_con_origen(sku)
            if f is None:
                filas.append({"sku": sku, "motivo": "sin_iva", "detalle": "sin IVA en Ecom ni en Táctica: corregilo en Ecom o cargalo a mano"})
        resumen: dict[str, int] = {}
        for r in filas:
            resumen[r["motivo"]] = resumen.get(r["motivo"], 0) + 1
        return {"obtenido_en": cat.obtenido_en, "total_catalogo": len(cat.todos_los_skus()), "no_calculan": len(filas), "resumen": resumen, "filas": filas, "tactica_caida": prov.tactica_caida}
    try:
        return await run_in_threadpool(_calc)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"No hay catálogo de costos de Ecom ({type(e).__name__}).")


@app.get("/ayala-core/motor-lote")
async def ayala_core_motor_lote(
    skus: str = "",
    renta_contado: float = float(ayala_core.RENTA_POR_CONDICION_DEFAULT["contado"]),
    renta_reducida: float = float(ayala_core.RENTA_POR_CONDICION_DEFAULT["reducida"]),
    renta_3: float = float(ayala_core.RENTA_POR_CONDICION_DEFAULT[3]),
    renta_6: float = float(ayala_core.RENTA_POR_CONDICION_DEFAULT[6]),
    renta_9: float = float(ayala_core.RENTA_POR_CONDICION_DEFAULT[9]),
    renta_12: float = float(ayala_core.RENTA_POR_CONDICION_DEFAULT[12]),
    envio_real: float | None = None,
    envio_full: bool = False,
    tc: float | None = None,
    cantidad: int = 1,
    mercado: str = "ml",
    usar_costo_orden: bool | None = None,
    usar_cheque: bool | None = None,
    usar_iibb: bool | None = None,
    costo_orden: float | None = None,
    cheque_pct: float | None = None,
    iibb_pct: float | None = None,
    recargo_cuotas: float | None = None,
    renta_18: float | None = None,
    renta_24: float | None = None,
    iva: float | None = None,
    renta_base: str = "con_iva",
):
    """Los SKU pedidos (coma-separados; vacío = todos los piloto) en UNA sola respuesta, con la MISMA cuenta que `/ayala-core/sku/{sku}/motor`
    (`_ayala_core_motor_sync`, ningún cambio de fórmula). Los costos de Ecom, el IVA de Táctica y el TC salen de las fotos que ya están en memoria:
    este endpoint no lee Ecom, Táctica ni el BNA en vivo. Devuelve además con qué datos se calculó (edad de cada foto) y cuánto tardó cada parte."""
    renta_por_condicion = _ayala_core_renta_dict(renta_contado, renta_reducida, renta_3, renta_6, renta_9, renta_12, renta_18, renta_24)
    lista = [x.strip() for x in skus.split(",") if x.strip()] or list(ayala_core.SKUS_PILOTO)
    return await run_in_threadpool(
        _ayala_core_motor_lote_sync, lista, renta_por_condicion,
        Decimal(str(envio_real)) if envio_real is not None else None, envio_full, Decimal(str(tc)) if tc is not None else None, cantidad,
        (mercado, usar_costo_orden, usar_cheque, usar_iibb, costo_orden, cheque_pct, iibb_pct, recargo_cuotas), _iva_manual(iva), _renta_base_valida(renta_base),
    )

def _ayala_core_motor_lote_sync(
    skus: list[str], renta_por_condicion: dict[str | int, Decimal], envio_real: Decimal | None, envio_full: bool, tc_override: Decimal | None,
    cantidad: int = 1, mk: tuple | None = None, iva_manual: Decimal | None = None, renta_base: str = "con_iva",
) -> dict:
    cantidad = _cantidad_valida(cantidad)
    m = _preparar_mercado(*mk) if mk else None
    t0 = time.perf_counter()
    prov = costos_ecom.proveedores_de_costo_e_iva()
    try:
        prov[0].precargar()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"No hay catálogo de costos de Ecom ({type(e).__name__}).")
    prov[1].precargar()
    t1 = time.perf_counter()
    info_tc = tc_info_rapido()
    tc = tc_override if tc_override is not None else info_tc["tc"]
    t2 = time.perf_counter()
    resultados = []
    for sku in skus:
        try:
            resultados.append(_ayala_core_motor_sync(sku, renta_por_condicion, envio_real, envio_full, None, None, tc_override=None, _proveedores=prov, _tc=tc, cantidad=cantidad, _mercado=m, iva_manual=iva_manual, iva_solo_si_falta=True, renta_base=renta_base))
        except HTTPException as e:
            resultados.append({"sku": sku, "error": e.detail})
    t3 = time.perf_counter()
    est = costos_ecom.estado()
    iva = costos_ecom.estado_iva_tactica()
    return {
        "resultados": resultados,
        "calculado_con": {
            "costos_obtenido_en": est.get("obtenido_en"), "costos_antiguedad_seg": est.get("antiguedad_seg"),
            "iva": "ECOM" if prov[1].tactica_caida else "TACTICA", "iva_tactica_antiguedad_seg": iva.get("antiguedad_seg"),
            "iva_tactica_error": iva.get("ultimo_error") if prov[1].tactica_caida else None,
            "tc": float(tc), "tc_origen": "manual" if tc_override is not None else info_tc["source"],
            "mercado": (m or {}).get("mercado", "ml"), "tarifas": (m or {}).get("tarifas"), "avisos_mercado": [a["texto"] for a in (m or {}).get("avisos", [])],
            "notas_mercado": [n["texto"] for n in ((m or {}).get("par") or {}).get("notas", [])],
        },
        "tiempos_ms": {"fotos": round((t1 - t0) * 1000, 1), "tc": round((t2 - t1) * 1000, 1), "calculo": round((t3 - t2) * 1000, 1), "total": round((t3 - t0) * 1000, 1)},
    }

@app.get("/ayala-core/sku/{sku}/motor")
async def ayala_core_sku_motor(
    sku: str,
    renta_contado: float = float(ayala_core.RENTA_POR_CONDICION_DEFAULT["contado"]),
    renta_reducida: float = float(ayala_core.RENTA_POR_CONDICION_DEFAULT["reducida"]),
    renta_3: float = float(ayala_core.RENTA_POR_CONDICION_DEFAULT[3]),
    renta_6: float = float(ayala_core.RENTA_POR_CONDICION_DEFAULT[6]),
    renta_9: float = float(ayala_core.RENTA_POR_CONDICION_DEFAULT[9]),
    renta_12: float = float(ayala_core.RENTA_POR_CONDICION_DEFAULT[12]),
    envio_real: float | None = None,
    envio_full: bool = False,
    item_id: str | None = None,
    cuenta: str | None = None,
    tc: float | None = None,
    costo: float | None = None,
    cantidad: int = 1,
    mercado: str = "ml",
    usar_costo_orden: bool | None = None,
    usar_cheque: bool | None = None,
    usar_iibb: bool | None = None,
    costo_orden: float | None = None,
    cheque_pct: float | None = None,
    iibb_pct: float | None = None,
    recargo_cuotas: float | None = None,
    renta_18: float | None = None,
    renta_24: float | None = None,
    iva: float | None = None,
    renta_base: str = "con_iva",
):
    renta_por_condicion = _ayala_core_renta_dict(renta_contado, renta_reducida, renta_3, renta_6, renta_9, renta_12, renta_18, renta_24)
    m = _preparar_mercado(mercado, usar_costo_orden, usar_cheque, usar_iibb, costo_orden, cheque_pct, iibb_pct, recargo_cuotas)
    return await run_in_threadpool(
        _ayala_core_motor_sync, sku, renta_por_condicion,
        Decimal(str(envio_real)) if envio_real is not None else None, envio_full, item_id, cuenta,
        Decimal(str(tc)) if tc is not None else None,
        Decimal(str(costo)) if costo is not None else None,
        None, None, cantidad, m, _iva_manual(iva), renta_base=_renta_base_valida(renta_base),
    )


@app.post("/ayala-core/publicaciones/run")
async def ayala_core_publicaciones_run(
    background_tasks: BackgroundTasks, cuentas: str = "", skus: str = "",
    renta_contado: float = float(ayala_core.RENTA_POR_CONDICION_DEFAULT["contado"]),
    renta_reducida: float = float(ayala_core.RENTA_POR_CONDICION_DEFAULT["reducida"]),
    renta_3: float = float(ayala_core.RENTA_POR_CONDICION_DEFAULT[3]),
    renta_6: float = float(ayala_core.RENTA_POR_CONDICION_DEFAULT[6]),
    renta_9: float = float(ayala_core.RENTA_POR_CONDICION_DEFAULT[9]),
    renta_12: float = float(ayala_core.RENTA_POR_CONDICION_DEFAULT[12]),
    tc: float | None = None,
    renta_base: str = "con_iva",
):
    """Escaneo caro (recorre TODO el catálogo activo de las cuentas
    pedidas) -- por eso corre en background, mismo patrón que
    `/ml-ofertas/run`. `cuentas` y `skus` viajan como string separado por
    comas; vacío = las dos cuentas / los 5 SKU piloto. `tc` opcional --
    pedido de Maxx 2026-09-15: pisar el TC de BNA a mano, sin el parámetro
    sigue siendo el TC en vivo."""
    job_id = f"ayalacore_pub_{int(time.time())}"
    tc = tc if tc is not None else float(tc_bna_requerido())
    lista_cuentas = [c for c in cuentas.split(",") if c] or None
    lista_skus = [s for s in skus.split(",") if s] or None
    renta_por_condicion = _ayala_core_renta_dict(renta_contado, renta_reducida, renta_3, renta_6, renta_9, renta_12)
    background_tasks.add_task(
        ayala_core.iniciar_job_publicaciones, job_id, lista_cuentas, tc, renta_por_condicion, lista_skus, _renta_base_valida(renta_base),
    )
    return {"job_id": job_id, "status": "started"}

@app.get("/ayala-core/publicaciones/status/{job_id}")
async def ayala_core_publicaciones_status(job_id: str):
    return ayala_core.estado_job(job_id) or {"status": "not_found"}

@app.post("/ayala-core/base-mla/run")
async def ayala_core_base_mla_run(background_tasks: BackgroundTasks, cuentas: str = "", skus: str = ""):
    """Job liviano (sin Táctica) para la pestaña "Base MLA" del Excel de
    Matías -- pedido de Maxx 2026-09-16, ver ayala_core.descubrir_
    publicaciones_base. Mismo formato de cuentas/skus separados por coma
    que /ayala-core/publicaciones/run."""
    job_id = f"ayalacore_basemla_{int(time.time())}"
    lista_cuentas = [c for c in cuentas.split(",") if c] or None
    lista_skus = [s for s in skus.split(",") if s] or None
    background_tasks.add_task(ayala_core.iniciar_job_base_mla, job_id, lista_cuentas, lista_skus)
    return {"job_id": job_id, "status": "started"}

@app.get("/ayala-core/base-mla/status/{job_id}")
async def ayala_core_base_mla_status(job_id: str):
    return ayala_core.estado_job(job_id) or {"status": "not_found"}

def _ayala_core_precio_vivo_sync(item_ids: list[str], cuenta: str) -> dict:
    ml = ml_ofertas.MLOfertasClient()
    return {"resultados": ayala_core.precio_vivo_mlas(ml, item_ids, cuenta)}

@app.get("/ayala-core/mla/precio-vivo")
async def ayala_core_mla_precio_vivo(item_ids: str, cuenta: str):
    """Precio real en vivo (no tachado) de una o varias publicaciones
    puntuales -- pedido de Maxx 2026-09-16 (control de planchas de
    sublimación en su Excel vía Apps Script). `item_ids` separados por
    coma: sirve tanto para "una sola" (el MLA que elegiste en el
    desplegable) como para "ver todas" (todos los MLA de una condición+
    cuenta). Síncrono, no background job -- pensado para listas chicas
    (una publicación puntual, o a lo sumo las ~14 de una condición),
    nunca el catálogo completo (eso es /ayala-core/base-mla/run)."""
    ids = [i.strip() for i in item_ids.split(",") if i.strip()]
    if not ids:
        raise HTTPException(status_code=422, detail="Falta 'item_ids'")
    return await run_in_threadpool(_ayala_core_precio_vivo_sync, ids, cuenta)

def _leer_precios_excel_matias() -> dict:
    """Precios por SKU+condición que Maxx define a mano en el Excel real
    ("VENTAS POR CANALES MATIAS", pestaña "ERP AYALA") -- pedido 2026-09-16:
    mientras maneje los precios ahí en vez del motor de Ayala Core, la
    pantalla "Motor de Precios" los precarga en el campo "Manual" (sin
    tildar "Usar" -- eso lo sigue decidiendo él, mismo mecanismo de
    "precio forzado" que ya existía). El parseo en sí (puro, testeable) vive
    en `ayala_core.parsear_precios_excel_matias` -- acá solo la lectura."""
    return _leer_excel_matias()["precios"]


def _leer_excel_matias() -> dict:
    """Una sola lectura de la pestaña: `precios` (SKU con algún precio cargado) y `skus` (TODOS los SKU de la pestaña, con o sin precio)."""
    ss = get_gs().open_by_key(EXCEL_MATIAS_ID)
    ws = ss.worksheet(EXCEL_MATIAS_TAB)
    filas = ws.get_all_values()
    return {"precios": ayala_core.parsear_precios_excel_matias(filas), "skus": ayala_core.listar_skus_excel_matias(filas)}

@app.get("/ayala-core/precios-excel")
async def ayala_core_precios_excel():
    try:
        return await run_in_threadpool(_leer_excel_matias)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error leyendo el Excel: {e}")

def _ayala_core_competencia_sync(product_id: str, cuenta: str) -> dict:
    ml = ml_ofertas.MLOfertasClient()
    return {"ofertas": ayala_core.resolver_competencia_por_producto(ml, product_id, cuenta)}

@app.get("/ayala-core/producto/{product_id}/competencia")
async def ayala_core_competencia(product_id: str, cuenta: str = "IT"):
    """Ofertas de la competencia real para una ficha de catálogo --
    pedido de Maxx 2026-09-03 para comparar "en las mismas condiciones"
    contra una referencia real, no solo contra el costo. `product_id` es
    el ID de la ficha (el que aparece después de `/p/` en la página de
    "Opciones de compra" de ML), NO el `item_id` de un vendedor puntual --
    `GET /items/{id}` está gateado por ownership para publicaciones
    ajenas, confirmado en vivo 2026-09-03 (ver docstring de
    `resolver_competencia_por_producto`)."""
    return await run_in_threadpool(_ayala_core_competencia_sync, product_id, cuenta)

def _ayala_core_aplicar_precio_sync(item_id: str, cuenta: str, precio: Decimal, precio_tachado: Decimal | None) -> dict:
    """Etapa 2 (escritura), una publicación por vez -- pedido de Maxx
    2026-09-03, confirmado el diseño ("me sirve así el tilde": tildar
    varias, un solo botón, pero por dentro se escribe de a una, cada una
    con su propio resultado, nunca un lote silencioso).

    **`precio_tachado` opcional sumado 2026-09-04** (pedido de Maxx: "que
    me deje poner el precio tachado"). Sin tachado sigue igual que antes:
    `fijar_precio_base` (mismo PUT verificado con GET aparte que ya usa
    Ofertas ML), precio de lista directo. Con tachado usa
    `activar_oferta_propia` en vez -- es el ÚNICO camino confirmado en
    vivo (ver su docstring, `ml_ofertas.py`) para que ML acepte
    `original_price`: un PUT que solo manda `price` (sin otro atributo)
    ahora siempre devuelve 400, y ML puede aceptar el PUT con 200 OK sin
    aplicar el tachado igual (reputación no verde, ítem no nuevo,
    descuento fuera de 5%-80%, publicación en un DEAL activo, etc.) --
    por eso el resultado trae `modo` (`con_tachado`/`sin_tachado_ml`/
    `sin_tachado_bids`), no asumir que "ok":true significa que el
    tachado quedó puesto, mostrarle a Maxx el `aviso` si vino."""
    ml = ml_ofertas.MLOfertasEscritura()
    if precio_tachado is not None:
        return ml.activar_oferta_propia(item_id, cuenta, precio, precio_tachado)
    return ml.fijar_precio_base(item_id, cuenta, precio)

@app.post("/ayala-core/item/{item_id}/aplicar-precio")
async def ayala_core_aplicar_precio(item_id: str, request: Request, background_tasks: BackgroundTasks):
    body = await request.json()
    cuenta = body["cuenta"]
    precio = Decimal(str(body["precio"]))
    precio_tachado_raw = body.get("precio_tachado")
    precio_tachado = Decimal(str(precio_tachado_raw)) if precio_tachado_raw not in (None, "") else None
    # «Poner precio» de Precios y ofertas ML: el operador elige el precio (nada se multiplica), operador OBLIGATORIO también acá (no solo en la pantalla), solo precio de lista
    # y se registra solo si ML lo aceptó y el GET de verificación lo confirmó.
    es_poner_precio = body.get("origen") == _ORIGEN_PONER_PRECIO
    if es_poner_precio:
        if not str(body.get("operador", "")).strip():
            raise HTTPException(status_code=422, detail="Falta el operador: sin operador no se cambia ningún precio.")
        if precio <= 0 or precio_tachado is not None:
            raise HTTPException(status_code=422, detail="«Poner precio» fija solo el precio de lista, mayor a 0 y sin tachado.")
    r = await run_in_threadpool(_ayala_core_aplicar_precio_sync, item_id, cuenta, precio, precio_tachado)
    if es_poner_precio and not r.get("ok"):
        return r
    background_tasks.add_task(_registrar_historial_oferta, {
        "Fecha": date.today().isoformat(), "Cuenta": cuenta, "Item ID": item_id, "SKU": body.get("sku", ""),
        "Accion": "Poner precio" if es_poner_precio else "Ayala Core -- aplicar precio",
        "Tipo/Promocion": "Precio de lista" if es_poner_precio else "Ayala Core",
        "Precio Anterior": body.get("precio_anterior", ""),
        "Precio Nuevo": f"{precio}" + (f" (tachado {precio_tachado})" if precio_tachado is not None else ""),
        "Margen % Resultante": body.get("margen_pct", "") if es_poner_precio else "",
        "Bajo Umbral": ("Sí" if body.get("bajo_umbral") else "No"),
        "Operador": body.get("operador", ""), "Origen": body.get("origen") or "Ayala Core",
    })
    return r
