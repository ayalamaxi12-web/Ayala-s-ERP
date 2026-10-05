"""Modo prueba: lee ~N links reales y NO escribe nada (ni al Sheet del ERP ni a ninguna otra parte).
Sirve para validar, antes de la primera corrida real, qué muestra Mercado Libre en cada tipo de link."""
import json
import os
import time
from datetime import datetime

import config
import competencia_db as cdb
import planilla_maca as pm
import sincronizar as sy


def tipo_link(url):
    i = sy.ident_publicacion(url)
    return {'P': 'catalogo_con_wid', 'Pn': 'catalogo_sin_wid', 'I': 'item'}.get(i[0] if i else '', 'otro')


def elegir_muestra(perfiles, skus, n=20):
    """Muestra repartida: hasta 4 tiendas distintas y publicaciones de cada tipo (8 con wid, 5 sin wid, 2 directas),
    completando hasta n. Determinista (mismo orden cada vez)."""
    tiendas, vistos = [], set()
    for p in perfiles:
        if p['slug'] not in vistos and not sy.es_excluida(config.ALIAS_TIENDAS.get(p['slug']) or sy.nombre_desde_slug(p['slug'])):
            vistos.add(p['slug'])
            tiendas.append(p)
    tiendas = tiendas[:4]
    por_tipo = {'catalogo_con_wid': [], 'catalogo_sin_wid': [], 'item': []}
    vistos_url = set()
    for d in skus:
        for l in d['links']:
            t = tipo_link(l['url'])
            if t in por_tipo and l['url'] not in vistos_url:
                vistos_url.add(l['url'])
                por_tipo[t].append({'sku': d['sku'], 'rol': l['rol_nombre'], 'url': l['url'], 'tipo': t})
    cupo = {'catalogo_con_wid': 8, 'catalogo_sin_wid': 5, 'item': 2}
    pubs = []
    for t, c in cupo.items():
        paso = max(1, len(por_tipo[t]) // c) if por_tipo[t] else 1
        pubs += por_tipo[t][::paso][:c]
    resto = [x for t in por_tipo.values() for x in t if x not in pubs]
    pubs += resto[:max(0, n - len(tiendas) - len(pubs))]
    return tiendas, pubs[:max(0, n - len(tiendas))]


def correr_prueba(filas_maca, lector, n=20, log=print):
    perfiles, _ = pm.leer_perfiles(filas_maca['A'])
    skus, _, _ = pm.leer_skus(filas_maca['B'])
    tiendas, pubs = elegir_muestra(perfiles, skus, n)
    informe = {'fecha': datetime.now().isoformat(timespec='seconds'), 'tiendas': [], 'publicaciones': []}
    bloqueado = False
    for p in tiendas:
        log(f"Tienda {p['slug']}: {p['url_listado']}")
        t = lector.leer_tienda(p['url_listado'], max_paginas=1)
        informe['tiendas'].append({'slug': p['slug'], 'url': p['url_listado'], 'estado': t['estado'],
                                   'tarjetas': len(t['items']), 'detalle': t.get('detalle', ''),
                                   'ejemplos': [{k: x[k] for k in ('title', 'price', 'link')} for x in t['items'][:3]]})
        if t['estado'] == 'bloqueado':
            bloqueado = True
            break
    for x in ([] if bloqueado else pubs):
        log(f"{x['tipo']:>17}  {x['sku']}  {x['url'][:70]}")
        r = lector.leer_publicacion(x['url'], None, diagnostico=True)
        informe['publicaciones'].append(dict(x, estado=r['estado'], precio=r.get('precio'), vendedor=r.get('vendedor'),
                                             detalle=r.get('detalle'), url_final=r.get('url_final'), intentos=r.get('intentos', [])))
        if r['estado'] == 'Bloqueado':
            break
        time.sleep(2)
    return informe


def guardar_informe(informe):
    os.makedirs(config.CARPETA_LOGS, exist_ok=True)
    ruta = os.path.join(config.CARPETA_LOGS, f"prueba_scraper_{datetime.now().strftime('%Y%m%d_%H%M')}.json")
    with open(ruta, 'w', encoding='utf-8') as f:
        json.dump(informe, f, ensure_ascii=False, indent=1)
    return ruta


def resumen_texto(informe):
    L = ['', '=== RESULTADO DEL MODO PRUEBA (no se escribió nada) ===']
    for t in informe['tiendas']:
        L.append(f"TIENDA {t['slug']:<22} {t['estado']:<14} tarjetas={t['tarjetas']}")
    from collections import Counter
    c = Counter((p['tipo'], p['estado']) for p in informe['publicaciones'])
    for (tipo, est), k in sorted(c.items()):
        L.append(f'{tipo:<18} {est:<14} {k}')
    L.append('')
    for p in informe['publicaciones']:
        L.append(f"{p['tipo']:<17} {p['estado']:<13} precio={p['precio']} vendedor={p['vendedor']!r} {p['detalle'] or ''}")
    return '\n'.join(L)
