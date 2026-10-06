"""Scraper de competencia (Etapa 2). Corre en la PC de Maxx (Windows), programado a las 17:30 con Tareas de Windows.

  python scraper.py --configurar-login            # UNA vez: te logueás en ML en el Chrome del scraper
  python scraper.py --probar 20                   # lee ~20 links reales y NO escribe nada (validar antes de la 1ª corrida)
  python scraper.py                               # corrida diaria: TODOS los vendedores
  python scraper.py --vendedor tecnovibe          # actualizar UN vendedor al momento
  python scraper.py --solo perfiles|publicaciones # solo tiendas completas, o solo links puntuales
  python scraper.py --sin-escribir                # corre y muestra qué haría, sin tocar ningún Sheet

Códigos de salida: 0 ok · 1 error · 2 Mercado Libre pidió login/verificación (corrida cortada, ver el log)."""
import argparse
import json
import os
import sys
import traceback
from datetime import datetime

import config


class _Tee:
    def __init__(self, ruta):
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        self.f = open(ruta, 'a', encoding='utf-8')

    def __call__(self, *a):
        linea = ' '.join(str(x) for x in a)
        print(linea)
        self.f.write(f"{datetime.now().strftime('%H:%M:%S')} {linea}\n")
        self.f.flush()


def _cliente():
    import gspread
    from google.oauth2.service_account import Credentials
    if not os.path.exists(config.CREDENTIALS_FILE):
        sys.exit(f'Falta {config.CREDENTIALS_FILE}\nCopiá ahí el credentials.json de la cuenta de servicio (NO va al repo).')
    creds = Credentials.from_service_account_file(config.CREDENTIALS_FILE, scopes=[
        'https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive'])
    return gspread.authorize(creds), creds.service_account_email


def _abrir(cliente, id_, email, nombre):
    import gspread
    try:
        return cliente.open_by_key(id_)
    except (gspread.exceptions.APIError, gspread.exceptions.SpreadsheetNotFound) as e:
        sys.exit(f'No puedo abrir {nombre}: {e}\nCompartí esa planilla con {email} (lector para la de Maca, editor para la del ERP).')


def _filas_maca(planilla):
    return {'A': planilla.worksheet(config.TAB_CATEGORIAS).get_all_values(),
            'B': planilla.worksheet(config.TAB_SKU).get_all_values()}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--configurar-login', action='store_true')
    ap.add_argument('--probar', nargs='?', const=20, type=int, metavar='N')
    ap.add_argument('--vendedor')
    ap.add_argument('--solo', choices=['perfiles', 'publicaciones'])
    ap.add_argument('--sin-escribir', action='store_true')
    ap.add_argument('--sin-descubrimiento', action='store_true')
    ap.add_argument('--headless', action='store_true', help='Chrome sin ventana (ML puede bloquearlo: probar antes)')
    a = ap.parse_args(argv)

    if a.configurar_login:
        from ml_selenium import configurar_login
        configurar_login()
        return 0

    log = _Tee(os.path.join(config.CARPETA_LOGS, f"corrida_{datetime.now().strftime('%Y%m%d_%H%M')}.log"))
    from ml_selenium import LectorML
    cliente, email = _cliente()
    maca = _abrir(cliente, config.PLANILLA_MACA_ID, email, 'la planilla de Maca')
    filas = _filas_maca(maca)
    from ml_api import ApiCatalogo
    api = ApiCatalogo(log=log)
    log('Vía API de catálogo: ' + ('configurada (ERP_BACKEND_URL / ERP_API_KEY)' if api.disponible() else 'NO configurada (solo páginas)'))
    lector = LectorML(headless=a.headless, log=log, api=api)
    try:
        if a.probar:
            import prueba
            inf = prueba.correr_prueba(filas, lector, a.probar, log)
            ruta = prueba.guardar_informe(inf)
            log(prueba.resumen_texto(inf))
            log(f'\nInforme completo: {ruta}\n(No se escribió nada. Pasame ese archivo o pegá el resumen de arriba.)')
            return 0
        import corrida
        erp = _abrir(cliente, config.SPREADSHEET_ID, email, 'el Sheet del ERP')
        log(f"=== Corrida {datetime.now():%d/%m/%Y %H:%M} · vendedor={a.vendedor or 'todos'} · solo={a.solo or 'todo'} "
            f"· {'SIN escribir' if a.sin_escribir else 'escribiendo'} ===")
        try:
            res = corrida.correr(erp, filas, lector, vendedor=a.vendedor, solo=a.solo, escribir=not a.sin_escribir,
                                 descubrir=not a.sin_descubrimiento, log=log)
            codigo = 0
        except corrida.CorridaBloqueada as e:
            log(f'\n⚠ CORRIDA CORTADA: {e}. Abrí Chrome con --configurar-login, resolvé el login/verificación y volvé a correr.')
            res, codigo = {'bloqueo': str(e)}, 2
        ruta = os.path.join(config.CARPETA_LOGS, f"corrida_{datetime.now().strftime('%Y%m%d_%H%M')}.json")
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump(res, f, ensure_ascii=False, indent=1, default=str)
        log(corrida.texto_resumen(res) if 'sync' in res else str(res))
        return codigo
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        log(traceback.format_exc())
        return 1
    finally:
        lector.cerrar()


if __name__ == '__main__':
    sys.exit(main())
