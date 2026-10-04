"""Migración de la base de competencia (Etapa 1): V-* / Historial Competidores / Monitor_Lecturas / General /
ML Competencia  ->  Referencias_Mercado + Historial_Precios (+ Migracion_Huerfanos).

Uso (desde backend/):
  python scripts/migrar_competencia.py                       # DRY-RUN contra el Sheet real (solo lectura)
  python scripts/migrar_competencia.py --api-key <KEY de Sheets>   # DRY-RUN solo lectura, sin cuenta de servicio
  python scripts/migrar_competencia.py --from-file competencia_export.json   # DRY-RUN con el export del navegador
  python scripts/migrar_competencia.py --from-dir export/    # DRY-RUN contra exports JSON (sin credenciales)
  python scripts/migrar_competencia.py --ejecutar --plan-hash <hash del dry-run>

Nada se borra ni se edita: las pestañas viejas quedan intactas y es idempotente (re-correr no duplica).
--ejecutar exige el plan_hash del informe de dry-run aprobado: si los datos cambiaron desde entonces,
el hash no coincide y no escribe."""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import competencia_db as cdb  # noqa: E402

SPREADSHEET_ID = '15b9kMzQFHdBOE5_7vWgriiiulHI6Yc9upJBUBBiXepY'
ENT_HEADERS = ['Entidad_ID', 'Nombre', 'Tipo', 'Provincia', 'Localidad', 'Estado', 'Responsable',
               'Tolerancia_Default_Pct', 'Fecha_Alta', 'Fecha_Ultima_Revision', 'Observaciones', 'Link_ML', 'Seller_ID']
REF_HEADERS = ['Referencia_ID', 'SKU', 'Tipo', 'Entidad_ID', 'Entidad_Nombre', 'Link_Publicacion', 'PVP_Oficial',
               'PVP_Override', 'Tolerancia_Pct', 'Activo', 'Seller_ID_Esperado', 'Fecha_Alta', 'Origen', 'Observaciones']


def get_gs():
    import gspread
    from google.oauth2.service_account import Credentials
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    cj = os.getenv('GOOGLE_CREDENTIALS_JSON')
    creds = (Credentials.from_service_account_info(json.loads(cj), scopes=scopes) if cj
             else Credentials.from_service_account_file('credentials.json', scopes=scopes))
    return gspread.authorize(creds)


def _valores(ss, nombre):
    try:
        return ss.worksheet(nombre).get_all_values()
    except Exception:
        return []


def leer_sheet(ss):
    titulos = [ws.title for ws in ss.worksheets()]
    f = {'refs': _valores(ss, 'Referencias_Mercado'), 'ents': _valores(ss, 'Entidades'),
         'general': _valores(ss, 'General'), 'ml_competencia': _valores(ss, 'ML Competencia'),
         'hist_competidores': _valores(ss, cdb.HIST_H2_NOMBRE), 'monitor': _valores(ss, 'Monitor_Lecturas'),
         'historial_existente': _valores(ss, cdb.HISTORIAL_SHEET),
         'huerfanos_existentes': _valores(ss, cdb.HUERFANOS_SHEET), 'v_tabs': {}}
    for t in titulos:
        if t.startswith('V - '):
            f['v_tabs'][t] = _valores(ss, t)
            time.sleep(0.5)  # cuota de la API de Sheets
    return f


class _SsApi:
    """Lectura de solo-lectura vía la API REST de Sheets con la API key (la misma de Configuración del ERP)."""
    def __init__(self, key):
        import requests
        self.key, self.r = key, requests.Session()

    def _get(self, path):
        for i in range(5):
            r = self.r.get(f'https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}{path}', timeout=60)
            if r.status_code == 429:
                time.sleep(10 * (i + 1)); continue
            r.raise_for_status()
            return r.json()

    def titulos(self):
        return [s['properties']['title'] for s in self._get(f'?fields=sheets.properties.title&key={self.key}')['sheets']]

    def valores(self, nombre):
        import urllib.parse
        try:
            return self._get(f'/values/{urllib.parse.quote(nombre)}?key={self.key}').get('values', [])
        except Exception:
            return []


def leer_sheet_api(key):
    api = _SsApi(key)
    t = api.titulos()
    v = api.valores
    f = {'refs': v('Referencias_Mercado'), 'ents': v('Entidades'), 'general': v('General'),
         'ml_competencia': v('ML Competencia'), 'hist_competidores': v(cdb.HIST_H2_NOMBRE),
         'monitor': v('Monitor_Lecturas'), 'historial_existente': v(cdb.HISTORIAL_SHEET),
         'huerfanos_existentes': v(cdb.HUERFANOS_SHEET), 'v_tabs': {}}
    for n in t:
        if n.startswith('V - '):
            f['v_tabs'][n] = v(n)
    return f


_CLAVES = ('refs', 'ents', 'general', 'ml_competencia', 'hist_competidores', 'monitor',
           'historial_existente', 'huerfanos_existentes')


def leer_archivo(path):
    """Un solo JSON (export desde el navegador): {refs, ents, ..., v_tabs: {'V - X': filas}, _errores: [...]}."""
    d = json.load(open(path, encoding='utf-8'))
    if d.get('_errores'):
        sys.exit(f"El export tiene pestañas que no se pudieron leer: {d['_errores']}. Volver a exportar.")
    f = {k: d.get(k) or [] for k in _CLAVES}
    f['v_tabs'] = d.get('v_tabs') or {}
    return f


def leer_dir(d):
    def j(n):
        p = os.path.join(d, n + '.json')
        return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else []
    f = {k: j(k) for k in ('refs', 'ents', 'general', 'ml_competencia', 'hist_competidores', 'monitor',
                           'historial_existente', 'huerfanos_existentes')}
    f['v_tabs'] = {n[:-5]: json.load(open(os.path.join(d, n), encoding='utf-8'))
                   for n in sorted(os.listdir(d)) if n.startswith('V - ') and n.endswith('.json')}
    return f


def imprimir_informe(rep):
    print('\n=== INFORME DE MIGRACIÓN (DRY-RUN) ===')
    print(f"{'Fuente':<26}{'Origen':>9}{'Nuevas':>9}{'Fusion.':>9}{'YaExist.':>9}{'Huérf.':>9}")
    for n, d in sorted(rep['fuentes'].items()):
        print(f"{n:<26}{d['origen']:>9}{d['nuevas']:>9}{d['fusionadas']:>9}{d['ya_existian']:>9}{d['huerfanas']:>9}")
    t = rep['totales']
    print(f"{'TOTAL':<26}{t['origen']:>9}{t['nuevas']:>9}{t['fusionadas']:>9}{t['ya_existian']:>9}{t['huerfanas']:>9}")
    print(f"\nCierre exacto (origen = nuevas + fusionadas + ya existían + huérfanas): {'SÍ' if rep['cierra'] else 'NO ⚠'}")
    print(f"Entidades nuevas: {rep['entidades_nuevas']} · Referencias nuevas: {rep['referencias_nuevas']} · "
          f"Lecturas a escribir: {rep['lecturas_a_escribir']} · Huérfanos a escribir: {rep['huerfanos_a_escribir']}")
    print(f"Links sin identificador ML: {rep['links_sin_identificador']}")
    print(f"Lecturas SIN precio por fuente (diagnóstico del lector 'refresh'/403): {rep['sin_precio_por_fuente']}")
    print(f"Mismo día con precios distintos: {rep['conflictos_precio_mismo_dia']} "
          f"(entre fuentes distintas: {rep['conflictos_precio_entre_fuentes']}) — se conservan ambas")
    print(f"Conflictos de SKU con referencias existentes (no se tocan): {len(rep['conflictos_sku'])}")
    print(f"SKU completables en referencias existentes sin SKU (no se tocan): {len(rep['sku_completables'])}")
    if rep['motivos_huerfanos']:
        print('\nHuérfanos por motivo:')
        for k, v in sorted(rep['motivos_huerfanos'].items(), key=lambda x: -x[1]):
            print(f'  {v:>7}  {k}')
    if rep['columnas_no_reconocidas']:
        print('\nColumnas de pestañas V-* que no encajan en ningún formato conocido (revisar):')
        for tab, cols in rep['columnas_no_reconocidas'].items():
            print(f'  {tab}: {cols[:8]}')
    print(f"\nplan_hash: {rep['plan_hash']}\n")


def _append(ws, headers_hoja, dicts, headers_default):
    headers = headers_hoja or headers_default
    filas = [cdb.fila_desde_dict(headers, d) for d in dicts]
    for i in range(0, len(filas), 500):
        ws.append_rows(filas[i:i + 500], value_input_option='RAW')
        time.sleep(0.4)


def ejecutar(ss, plan):
    ent_ws = cdb.asegurar_pestana(ss, 'Entidades', ENT_HEADERS, 1000)
    ref_ws = cdb.asegurar_pestana(ss, 'Referencias_Mercado', REF_HEADERS, 1000)
    h_ws = cdb.asegurar_pestana(ss, cdb.HISTORIAL_SHEET, cdb.HISTORIAL_HEADERS, 20000)
    o_ws = cdb.asegurar_pestana(ss, cdb.HUERFANOS_SHEET, cdb.HUERFANOS_HEADERS, 5000)
    ref_h = ref_ws.row_values(1)
    if cdb.REFERENCIAS_COL_EXTRA not in ref_h:  # agrega 'Cantidad' al final: no mueve ninguna columna existente
        if len(ref_h) + 1 > ref_ws.col_count:
            ref_ws.add_cols(1)
        ref_ws.update_cell(1, len(ref_h) + 1, cdb.REFERENCIAS_COL_EXTRA)
        ref_h.append(cdb.REFERENCIAS_COL_EXTRA)
    _append(ent_ws, ent_ws.row_values(1), plan.entidades_nuevas, ENT_HEADERS)
    _append(ref_ws, ref_h, plan.refs_nuevas, REF_HEADERS)
    _append(h_ws, h_ws.row_values(1), plan.lecturas, cdb.HISTORIAL_HEADERS)
    _append(o_ws, o_ws.row_values(1), plan.huerfanos, cdb.HUERFANOS_HEADERS)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--ejecutar', action='store_true', help='escribe de verdad (default: dry-run, solo lectura)')
    ap.add_argument('--plan-hash', help='hash del informe de dry-run aprobado (obligatorio con --ejecutar)')
    ap.add_argument('--from-dir', help='leer exports JSON en vez del Sheet (solo dry-run)')
    ap.add_argument('--from-file', help='un solo JSON exportado desde el navegador (solo dry-run)')
    ap.add_argument('--api-key', help='API key de Sheets (solo lectura): dry-run sin cuenta de servicio')
    ap.add_argument('--informe', default='informe_migracion_competencia.json')
    a = ap.parse_args()
    if (a.from_dir or a.from_file or a.api_key) and a.ejecutar:
        sys.exit('--from-dir, --from-file y --api-key son solo para dry-run (--ejecutar escribe con la cuenta de servicio).')
    if a.ejecutar and not a.plan_hash:
        sys.exit('--ejecutar requiere --plan-hash del dry-run aprobado.')

    ss = None if (a.from_dir or a.from_file or a.api_key) else get_gs().open_by_key(SPREADSHEET_ID)
    fuentes = (leer_archivo(a.from_file) if a.from_file else leer_dir(a.from_dir) if a.from_dir else leer_sheet_api(a.api_key) if a.api_key else leer_sheet(ss))
    plan = cdb.planificar(fuentes)
    imprimir_informe(plan.rep)
    json.dump({k: v for k, v in plan.rep.items()}, open(a.informe, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'Informe completo en {a.informe}')
    if not a.ejecutar:
        print('DRY-RUN: no se escribió nada.')
        return
    if not plan.rep['cierra']:
        sys.exit('El informe no cierra: no se ejecuta.')
    if plan.rep['plan_hash'] != a.plan_hash:
        sys.exit(f"plan_hash distinto ({plan.rep['plan_hash']} vs {a.plan_hash}): los datos cambiaron desde el dry-run; "
                 'volver a correr el dry-run y aprobar.')
    ejecutar(ss, plan)
    # Verificación contra el Sheet: re-planificar tiene que dar todo "ya existía" y 0 por escribir.
    post = cdb.planificar(leer_sheet(ss))
    r = post.rep
    ok = (r['lecturas_a_escribir'] == 0 and r['referencias_nuevas'] == 0 and r['huerfanos_a_escribir'] == 0
          and r['cierra'] and r['totales']['nuevas'] == 0)
    print('VERIFICACIÓN post-migración (re-lectura): ' + ('OK, todo cerró exacto' if ok else 'NO CIERRA ⚠'))
    if not ok:
        imprimir_informe(r)
        sys.exit(1)


if __name__ == '__main__':
    main()
