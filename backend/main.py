"""
Ayala's ERP - Backend API
FastAPI server para ML Tracker y ML Vendedor
"""

from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
import requests, re, time, os, gspread
from datetime import datetime
from google.oauth2.service_account import Credentials
import json

app = FastAPI(title="Ayala's ERP API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ——— CONFIG ———
SPREADSHEET_ID = '15b9kMzQFHdBOE5_7vWgriiiulHI6Yc9upJBUBBiXepY'
ML_TOKEN       = os.getenv('ML_TOKEN', 'APP_USR-5759955230156669-050612-d748863eef974646587daa470e41ded3-115764017')
REFRESH_TOKEN  = os.getenv('ML_REFRESH_TOKEN', 'TG-69fb6d882d06f40001c2331d-115764017')
APP_ID         = os.getenv('ML_APP_ID', '5759955230156669')
CLIENT_SECRET  = os.getenv('ML_CLIENT_SECRET', '49Z7KYX21nFbxHfHrRVE43bX4vGhwOiX')

job_status = {}
_token_cache = {'token': ML_TOKEN, 'expiry': 0}

# ——— TOKEN ———
def get_ml_token():
    if time.time() < _token_cache['expiry']:
        return _token_cache['token']
    try:
        res = requests.post('https://api.mercadolibre.com/oauth/token', data={
            'grant_type': 'refresh_token',
            'client_id': APP_ID,
            'client_secret': CLIENT_SECRET,
            'refresh_token': REFRESH_TOKEN,
        }, timeout=10)
        if res.status_code == 200:
            d = res.json()
            _token_cache['token'] = d['access_token']
            _token_cache['expiry'] = time.time() + d.get('expires_in', 21600) - 300
            return _token_cache['token']
    except Exception as e:
        print(f"Token error: {e}")
    return _token_cache['token']

def ml_headers():
    return {'Authorization': f'Bearer {get_ml_token()}', 'User-Agent': 'Mozilla/5.0'}

# ——— SHEETS ———
def get_gs():
    creds_json = os.getenv('GOOGLE_CREDENTIALS_JSON')
    if creds_json:
        creds = Credentials.from_service_account_info(
            json.loads(creds_json),
            scopes=['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive']
        )
    else:
        creds = Credentials.from_service_account_file('credentials.json', scopes=[
            'https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive'
        ])
    return gspread.authorize(creds)

# ——— ML UTILS ———
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

# ——— ENDPOINTS ———
@app.get("/")
def root():
    return {"app": "Ayala's ERP", "version": "1.0.0", "status": "online"}

@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now().isoformat()}

# ML TRACKER
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
        ok = errors = 0
        batch = []

        for i, row in enumerate(all_values[1:]):
            url = row[0].strip() if row else ''
            if not url: continue
            row_num = i + 2
            try:
                ids = extract_ids(url)
                log.append(f"🔍 Fila {row_num}: item={ids['item_id']} prod={ids['product_id']}")
                data = None
                if ids['item_id']: data = fetch_item(ids['item_id'])
                log.append(f"📦 fetch_item result: {str(data)[:100] if data else 'None'}")
                if not data and ids['product_id']: data = fetch_product(ids['product_id'])
                tipo = 'item' if ids['item_id'] and data else 'product'
                parsed = parse_item(data, tipo)
                if not parsed:
                    log.append(f"⚠️ Fila {row_num}: sin datos parseados. data={str(data)[:100]}")
                    batch.append({'range': f'B{row_num}', 'values': [['❌ Sin datos']]})
                    errors += 1; continue
                nick = parsed['seller_nick'] or (fetch_seller(parsed['seller_id']) if parsed['seller_id'] else '')
                now = datetime.now().strftime('%d/%m/%Y %H:%M')
                batch.append({'range': f'B{row_num}:H{row_num}', 'values': [[
                    parsed['title'], nick, parsed['price'],
                    parsed['orig_price'] or '', parsed['discount'] or 'Sin descuento',
                    parsed['cuotas'], now
                ]]})
                log.append(f"✅ {parsed['title'][:40]} | ${parsed['price']:,}")
                ok += 1
                time.sleep(0.5)
            except Exception as e:
                import traceback
                log.append(f"❌ Fila {row_num}: {type(e).__name__}: {e} | {traceback.format_exc()[-200:]}")
                errors += 1

        if batch:
            log.append(f"📝 Escribiendo {len(batch)} filas en Sheets...")
            sheet.batch_update(batch)

        job_status[job_id] = {"status": "done", "ok": ok, "errors": errors,
                               "log": log, "finished": datetime.now().isoformat()}
    except Exception as e:
        job_status[job_id] = {"status": "error", "message": str(e), "log": log}

@app.get("/ml/tracker/status/{job_id}")
def tracker_status(job_id: str):
    return job_status.get(job_id, {"status": "not_found"})

# ML VENDEDOR
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
            job_status[job_id] = {"status": "error", "message": "No existe pestaña Vendedores", "log": log}
            return

        rows = cfg.get_all_values()
        vendedores = [{'nombre': r[0].strip(), 'url': r[1].strip(), 'row': i+2}
                      for i, r in enumerate(rows[1:]) if len(r) > 1 and r[0].strip() and r[1].strip()]

        if not vendedores:
            job_status[job_id] = {"status": "done", "log": ["Sin vendedores"]}
            return

        options = Options()
        options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
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
            n = re.sub(r'[^\d]', '', t)
            return int(n) if n else 0

        def scroll(drv):
            last = drv.execute_script("return document.body.scrollHeight")
            for _ in range(15):
                drv.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1.2)
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
                    try:
                        orig = parse_price(card.find_element(By.CSS_SELECTOR, 's.andes-money-amount--previous .andes-money-amount__fraction').text)
                    except: pass
                    price = 0
                    try:
                        price = parse_price(card.find_element(By.CSS_SELECTOR, '.poly-price__current .andes-money-amount__fraction').text)
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
                all_items = []
                page = 1
                seen = set()
                driver.get(v['url'])
                time.sleep(2.5)
                while True:
                    cur = driver.current_url
                    if cur in seen: break
                    seen.add(cur)
                    try: WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, '.poly-card, .ui-search-result')))
                    except: break
                    scroll(driver)
                    items = scrape(driver)
                    if not items: break
                    all_items.extend(items)
                    log.append(f"  Pág {page}: {len(items)} items | Total: {len(all_items)}")
                    if not click_next(driver): break
                    page += 1
                    time.sleep(1)

                seen_t = set()
                unique = [item for item in all_items if item['title'] not in seen_t and not seen_t.add(item['title'])]

                sn = f'V - {v["nombre"]}'[:50]
                try:
                    ws = ss.worksheet(sn); ws.clear()
                except:
                    ws = ss.add_worksheet(title=sn, rows=5000, cols=8)

                ws.update(values=[['Titulo','Precio ($)','Precio Tachado ($)','Descuento','Cuotas','Link']], range_name='A1:F1')
                rows_d = [[i['title'],i['price'],i['orig_price'],i['discount'],i['cuotas'],i['link']] for i in unique]
                for ci in range(0, len(rows_d), 500):
                    chunk = rows_d[ci:ci+500]; s = ci+2
                    ws.update(values=chunk, range_name=f'A{s}:F{s+len(chunk)-1}'); time.sleep(0.3)

                cfg.update(values=[[datetime.now().strftime('%d/%m/%Y %H:%M')]], range_name=f'C{v["row"]}')
                log.append(f"✅ {v['nombre']}: {len(unique)} productos")
                time.sleep(1)
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
