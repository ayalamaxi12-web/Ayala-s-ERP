"""
Ayala's ERP - Backend API
"""
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import requests, re, time, os, gspread
from datetime import datetime
from google.oauth2.service_account import Credentials
import json

app = FastAPI(title="Ayala's ERP API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

SPREADSHEET_ID = '15b9kMzQFHdBOE5_7vWgriiiulHI6Yc9upJBUBBiXepY'
ML_TOKEN       = os.getenv('ML_TOKEN', '')
REFRESH_TOKEN  = os.getenv('ML_REFRESH_TOKEN', '')
APP_ID         = os.getenv('ML_APP_ID', '')
CLIENT_SECRET  = os.getenv('ML_CLIENT_SECRET', '')
ML_TOKEN_2     = os.getenv('ML_TOKEN_2', '')
REFRESH_TOKEN_2= os.getenv('ML_REFRESH_TOKEN_2', '')

job_status = {}
_token_cache = {'token': ML_TOKEN, 'expiry': 0}
_token_cache_2 = {'token': ML_TOKEN_2, 'expiry': 0}

def get_ml_token():
    if time.time() < _token_cache['expiry']:
        return _token_cache['token']
    try:
        res = requests.post('https://api.mercadolibre.com/oauth/token', data={
            'grant_type': 'refresh_token', 'client_id': APP_ID,
            'client_secret': CLIENT_SECRET, 'refresh_token': os.getenv('ML_REFRESH_TOKEN', REFRESH_TOKEN),
        }, timeout=10)
        if res.status_code == 200:
            d = res.json()
            _token_cache['token'] = d['access_token']
            _token_cache['expiry'] = time.time() + d.get('expires_in', 21600) - 300
            if 'refresh_token' in d: os.environ['ML_REFRESH_TOKEN'] = d['refresh_token']
            return _token_cache['token']
        else:
            print(f"Token refresh error: {res.status_code} {res.text}")
    except Exception as e:
        print(f"Token error: {e}")
    return _token_cache['token']

def get_ml_token_2():
    if time.time() < _token_cache_2['expiry']:
        return _token_cache_2['token']
    try:
        res = requests.post('https://api.mercadolibre.com/oauth/token', data={
            'grant_type': 'refresh_token', 'client_id': APP_ID,
            'client_secret': CLIENT_SECRET, 'refresh_token': os.getenv('ML_REFRESH_TOKEN_2', REFRESH_TOKEN_2),
        }, timeout=10)
        if res.status_code == 200:
            d = res.json()
            _token_cache_2['token'] = d['access_token']
            _token_cache_2['expiry'] = time.time() + d.get('expires_in', 21600) - 300
            if 'refresh_token' in d: os.environ['ML_REFRESH_TOKEN_2'] = d['refresh_token']
            return _token_cache_2['token']
        else:
            print(f"Token2 refresh error: {res.status_code} {res.text}")
    except Exception as e:
        print(f"Token2 error: {e}")
    return _token_cache_2['token']

def ml_headers():
    return {'Authorization': f'Bearer {get_ml_token()}', 'User-Agent': 'Mozilla/5.0'}

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
        ok = errors = 0; batch = []
        for i, row in enumerate(all_values[1:]):
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
                ok += 1; time.sleep(0.5)
            except Exception as e:
                log.append(f"❌ Fila {row_num}: {e}"); errors += 1
        if batch: sheet.batch_update(batch)
        job_status[job_id] = {"status": "done", "ok": ok, "errors": errors, "log": log, "finished": datetime.now().isoformat()}
    except Exception as e:
        job_status[job_id] = {"status": "error", "message": str(e), "log": log}

@app.get("/ml/tracker/status/{job_id}")
def tracker_status(job_id: str):
    return job_status.get(job_id, {"status": "not_found"})

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
            for v in vendedores:
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
# FRAVEGA PROXY
# ══════════════════════════════════════════════════════

FVG_BASE_CATALOG = "https://seller-center-integration.production.fravega.com"
FVG_BASE_ORDERS  = "https://seller-center-api.fravega.com"

def fvg_headers(request: Request):
    return {
        "Content-Type": "application/json", "accept": "application/json",
        "seller-id": request.headers.get("seller-id", ""),
        "x-fvg-api-key": request.headers.get("x-fvg-api-key", ""),
        "x-fvg-api-token": request.headers.get("x-fvg-api-token", ""),
    }

def fvg_safe_json(r):
    try:
        return {"status": r.status_code, "body": r.json()}
    except Exception:
        return {"status": r.status_code, "body": r.text[:2000]}

@app.get("/fvg/debug")
async def fvg_debug(request: Request):
    results = {}
    hdrs = fvg_headers(request)
    for path in ["/api/v1/item?page=1&size=1", "/api/item?page=1&size=1", "/api/v1/items?page=1&size=1"]:
        try:
            r = requests.get(f"{FVG_BASE_CATALOG}{path}", headers=hdrs, timeout=10)
            results[path] = {"status": r.status_code, "body": r.text[:500]}
        except Exception as e:
            results[path] = {"error": str(e)}
    return results

@app.get("/fvg/items")
async def fvg_list_items(request: Request, page: int = 1, size: int = 20):
    try:
        r = requests.get(f"{FVG_BASE_CATALOG}/api/item?page={page}&size={size}&sellerId={request.headers.get('seller-id','')}",
                         headers=fvg_headers(request), timeout=20)
        return fvg_safe_json(r)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/fvg/items/{ref_id}")
async def fvg_get_item(ref_id: str, request: Request):
    try:
        r = requests.get(f"{FVG_BASE_CATALOG}/api/item/refId/{ref_id}", headers=fvg_headers(request), timeout=20)
        return fvg_safe_json(r)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/fvg/items/{ref_id}/price")
async def fvg_update_price(ref_id: str, request: Request):
    body = await request.json()
    try:
        r = requests.put(f"{FVG_BASE_CATALOG}/api/item/refId/{ref_id}/price", headers=fvg_headers(request), json=body, timeout=20)
        return fvg_safe_json(r)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/fvg/items/{ref_id}/stock")
async def fvg_update_stock(ref_id: str, request: Request):
    body = await request.json()
    try:
        r = requests.put(f"{FVG_BASE_CATALOG}/api/item/refId/{ref_id}/stock", headers=fvg_headers(request), json=body, timeout=20)
        return fvg_safe_json(r)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/fvg/orders/{order_id}")
async def fvg_get_order(order_id: str, request: Request):
    try:
        r = requests.get(f"{FVG_BASE_ORDERS}/api/v1/orders/{order_id}", headers=fvg_headers(request), timeout=20)
        return fvg_safe_json(r)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/fvg/invoice")
async def fvg_invoice(request: Request):
    body = await request.json()
    try:
        r = requests.post(f"{FVG_BASE_ORDERS}/api/v1/invoice", headers=fvg_headers(request), json=body, timeout=20)
        return fvg_safe_json(r)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
        for ws in vendor_sheets:
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

_tc_cache = {'value': 0, 'expiry': 0}

@app.get("/tc/bna")
async def get_tc_bna():
    """Scrappea el tipo de cambio venta del Dólar del BNA"""
    if time.time() < _tc_cache['expiry'] and _tc_cache['value'] > 0:
        return {"tc": _tc_cache['value'], "source": "cache"}
    try:
        r = requests.get("https://bna.com.ar/Personas",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            timeout=10)
        html = r.text
        # Find the billetes table - Dolar U.S.A venta (last td of first tr in tbody)
        import re
        # Pattern: Dolar U.S.A ... compra ... venta
        m = re.search(r'Dolar U\.S\.A</td>\s*<td>([\d,\.]+)</td>\s*<td>([\d,\.]+)</td>', html)
        if m:
            venta_str = m.group(2).replace('.', '').replace(',', '.')
            tc = float(venta_str)
            _tc_cache['value'] = tc
            _tc_cache['expiry'] = time.time() + 3600  # cache 1 hora
            return {"tc": tc, "source": "bna", "fecha": datetime.now().strftime('%d/%m/%Y %H:%M')}
        # Fallback pattern
        m2 = re.search(r'<td class="tit">Dolar U\.S\.A</td>\s*<td>([\d,\.]+)</td>\s*<td>([\d,\.]+)</td>', html)
        if m2:
            venta_str = m2.group(2).replace('.', '').replace(',', '.')
            tc = float(venta_str)
            _tc_cache['value'] = tc
            _tc_cache['expiry'] = time.time() + 3600
            return {"tc": tc, "source": "bna", "fecha": datetime.now().strftime('%d/%m/%Y %H:%M')}
        return {"tc": 0, "error": "No se pudo parsear el TC", "source": "error"}
    except Exception as e:
        return {"tc": 0, "error": str(e), "source": "error"}


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
    """Intento rápido por API para item individual (no catálogo). Devuelve (precio o None, detalle)."""
    try:
        r = requests.get(f"https://api.mercadolibre.com/items/{item_id}", headers=ml_headers(), timeout=10)
        if r.status_code == 200:
            price = r.json().get('price')
            if price:
                return price, ''
            return None, 'API 200 pero sin precio en la respuesta'
        try:
            msg = r.json().get('message', r.text[:120])
        except Exception:
            msg = r.text[:120]
        return None, f'API {r.status_code}: {msg}'
    except Exception as e:
        return None, f'API error: {e}'

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
        price, api_detail = _monitor_try_api_item(ids['item_id'])
        if price:
            return {'precio': price, 'estado': 'OK', 'metodo': 'API',
                    'seller_id': None, 'official_store_id': None, 'detalle_error': ''}
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
    'Entidades': ['Entidad_ID','Nombre','Tipo','Provincia','Localidad','Estado','Responsable','Tolerancia_Default_Pct','Fecha_Alta','Fecha_Ultima_Revision','Observaciones','Link_ML'],
    'Referencias_Mercado': ['Referencia_ID','SKU','Tipo','Entidad_ID','Entidad_Nombre','Link_Publicacion','PVP_Oficial','PVP_Override','Tolerancia_Pct','Activo','Seller_ID_Esperado','Fecha_Alta','Origen','Observaciones'],
    'Discovery_Sugerencias': ['Sugerencia_ID','Entidad_Origen','Titulo_Detectado','Link_Detectado','Precio_Detectado','SKU_Sugerido','Fecha_Deteccion','Estado_Revision','Referencia_ID_Generada'],
    'Intel_Config': ['Tipo','Tolerancia_Default_Pct'],
}

MONITOR_HEADERS_EXT = ['Referencia_ID','Tipo','Entidad','PVP_Comparado','Diferencia_Pct','Cumple']

@app.post("/intel-comercial/init")
def init_intel_comercial():
    try:
        ss = get_gs().open_by_key(SPREADSHEET_ID)
        existing = {ws.title for ws in ss.worksheets()}
        result = {}
        for name, headers in INTEL_SHEETS.items():
            if name in existing:
                result[name] = 'ya existía'
                continue
            sheet = ss.add_worksheet(title=name, rows=1000, cols=len(headers))
            sheet.append_row(headers)
            result[name] = 'creada'

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
