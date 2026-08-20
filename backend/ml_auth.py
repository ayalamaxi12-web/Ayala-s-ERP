"""
Autenticación OAuth de Mercado Libre — dos cuentas vendedoras (IT/MT).

Extraído de `main.py` (2026-08-20) para que módulos nuevos que necesiten
tokens de ML (ej. `ml_full.py`) puedan importarlo sin depender de `main.py`
y sin duplicar la lógica de refresh. Comportamiento idéntico al original,
solo movido de archivo.
"""
import os
import time

import requests

SELLERS = {"IT": "115764017", "MT": "34801784"}

ML_TOKEN = os.getenv('ML_TOKEN', '')
REFRESH_TOKEN = os.getenv('ML_REFRESH_TOKEN', '')
APP_ID = os.getenv('ML_APP_ID', '')
CLIENT_SECRET = os.getenv('ML_CLIENT_SECRET', '')
ML_TOKEN_2 = os.getenv('ML_TOKEN_2', '')
REFRESH_TOKEN_2 = os.getenv('ML_REFRESH_TOKEN_2', '')

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


def ml_headers(account: str = "IT"):
    token = get_ml_token_2() if account == "MT" else get_ml_token()
    return {'Authorization': f'Bearer {token}', 'User-Agent': 'Mozilla/5.0'}


def token_de(account: str) -> str:
    return get_ml_token_2() if account == "MT" else get_ml_token()
