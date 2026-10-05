"""Ofertas de un producto de catálogo vía el backend (`/ml-proxy`, que usa el token del servidor). Vía OPCIONAL.

Si funciona, en 2 llamadas da el precio de la oferta del wid (la que sigue Maca) y el de la ganadora, sin abrir la página.
Se sabía que ML devuelve 403 en publicaciones ajenas; si este endpoint también lo hace, la vía se apaga sola (circuito
abierto tras 3 fallos seguidos) y el scraper sigue con las páginas. El modo prueba registra qué respondió, así se sabe."""
import re

import config


class ApiCatalogo:
    def __init__(self, base=None, clave=None, log=print, http=None):
        self.base = (base if base is not None else config.ERP_BACKEND_URL).rstrip('/')
        self.clave = clave if clave is not None else config.ERP_API_KEY
        self.log, self.fallos, self.apagada = log, 0, False
        if http is None:
            import requests
            http = requests.get
        self._get = http

    def disponible(self):
        return bool(self.base and self.clave) and not self.apagada

    def _pedir(self, path):
        r = self._get(f'{self.base}/ml-proxy', params={'path': path}, headers={'X-ERP-Key': self.clave}, timeout=30)
        try:
            j = r.json()
        except Exception:  # noqa: BLE001
            j = {}
        return r.status_code, j

    def leer(self, product_id, wid):
        """-> {'estado': 'OK'|'No esta'|'Error', 'precio', 'seller_id', 'precio_ganador', 'seller_ganador', 'detalle', 'http'}"""
        if not self.disponible():
            return {'estado': 'Error', 'detalle': 'API no configurada o apagada', 'http': None}
        wid = str(wid or '').upper()
        ofertas, offset = [], 0
        for _ in range(10):
            st, j = self._pedir(f'products/{product_id}/items?limit=100&offset={offset}')
            if st != 200 or not isinstance(j, dict) or 'results' not in j:
                self._fallo()
                msg = (j.get('message') or j.get('error') or '') if isinstance(j, dict) else ''
                return {'estado': 'Error', 'detalle': f'API {j.get("status", st) if isinstance(j, dict) else st}: {msg}'[:160],
                        'http': (j.get('status') if isinstance(j, dict) else None) or st}
            res = j.get('results') or []
            ofertas += [o for o in res if isinstance(o, dict)]
            offset += len(res)
            if not res or offset >= (j.get('paging') or {}).get('total', len(ofertas)):
                break
        self.fallos = 0
        out = {'estado': 'No esta', 'http': 200, 'ofertas': len(ofertas), 'precio': None, 'seller_id': None,
               'precio_ganador': None, 'seller_ganador': None,
               'detalle': f'El wid {wid} no está entre las {len(ofertas)} ofertas del producto'}
        mia = next((o for o in ofertas if str(o.get('item_id', '')).upper() == wid), None)
        if mia and mia.get('price'):
            out.update(estado='OK', precio=mia['price'], seller_id=mia.get('seller_id'), detalle='')
        st, j = self._pedir(f'products/{product_id}')
        gan = (j.get('buy_box_winner') or {}) if st == 200 and isinstance(j, dict) else {}
        if gan.get('price'):
            out['precio_ganador'], out['seller_ganador'] = gan['price'], gan.get('seller_id')
        return out

    def _fallo(self):
        self.fallos += 1
        if self.fallos >= 3 and not self.apagada:
            self.apagada = True
            self.log('  (API de catálogo apagada para esta corrida: 3 respuestas de error seguidas)')


def product_id_de(url):
    m = re.search(r'/(?:p|up)/(ML[A-Z]U?\d+)', str(url), re.I)
    return m.group(1).upper() if m else ''
