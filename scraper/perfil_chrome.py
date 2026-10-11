"""Perfil de Chrome del scraper y login manual de Mercado Libre.

`--configurar-login` abre un Chrome COMÚN (sin Selenium, sin banderas de automatización) con el perfil del scraper: así ML lo trata como un
navegador normal (menos captchas, el login se mantiene) y no hay ningún proceso de Python/chromedriver atado a esa ventana que pueda cerrarla.
Vos te logueás y resolvés los captchas ahí; el scraper después reutiliza el MISMO perfil (las cookies quedan guardadas en la carpeta).

Además limpia procesos de Chrome "huérfanos" que se quedan con el perfil tomado después de una caída: era lo que hacía que reabrir
Chrome fallara o que la ventana se abriera y se cerrara sola."""
import os
import shutil
import subprocess
import sys
import time

import config

CHROME_EXE_ENV = 'CHROME_EXE'


def _es_windows():
    return sys.platform.startswith('win')


def buscar_chrome(env=None, existe=os.path.exists, which=shutil.which):
    """Ruta de chrome.exe: variable CHROME_EXE, rutas habituales de Windows, o el PATH. None si no está."""
    env = os.environ if env is None else env
    if env.get(CHROME_EXE_ENV) and existe(env[CHROME_EXE_ENV]):
        return env[CHROME_EXE_ENV]
    for base in (env.get('PROGRAMFILES'), env.get('PROGRAMFILES(X86)'), env.get('LOCALAPPDATA')):
        if base:
            ruta = os.path.join(base, 'Google', 'Chrome', 'Application', 'chrome.exe')
            if existe(ruta):
                return ruta
    return which('chrome') or which('google-chrome') or which('chromium')


def pids_del_perfil(perfil_dir, ejecutar=subprocess.run, es_windows=None):
    """PIDs de procesos chrome.exe que usan ESE perfil (y solo ese: tu Chrome de todos los días no se toca). Solo Windows."""
    if not (_es_windows() if es_windows is None else es_windows):
        return []
    perfil = os.path.abspath(perfil_dir).replace("'", "''")
    script = ("$p = '" + perfil + "'; "
              "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
              "Where-Object { $_.CommandLine -and $_.CommandLine.Contains($p) } | ForEach-Object { $_.ProcessId }")
    try:
        r = ejecutar(['powershell', '-NoProfile', '-NonInteractive', '-Command', script], capture_output=True, text=True, timeout=40)
    except Exception:  # noqa: BLE001
        return []
    return [int(x) for x in (r.stdout or '').split() if x.isdigit()]


def liberar_perfil(perfil_dir, log=print, ejecutar=subprocess.run, es_windows=None):
    """Cierra los Chrome que tienen tomado el perfil del scraper (restos de una caída). -> cantidad de procesos cerrados."""
    pids = pids_del_perfil(perfil_dir, ejecutar, es_windows)
    for pid in pids:
        try:
            ejecutar(['taskkill', '/PID', str(pid), '/F', '/T'], capture_output=True, text=True, timeout=30)
        except Exception:  # noqa: BLE001
            pass
    if pids:
        log(f'  (se cerraron {len(pids)} procesos de Chrome que tenían tomado el perfil del scraper)')
        time.sleep(2)
    return len(pids)


def comando_chrome(chrome, perfil_dir, url):
    """Chrome COMÚN con el perfil del scraper: sin Selenium ni banderas de automatización."""
    return [chrome, f'--user-data-dir={os.path.abspath(perfil_dir)}', '--profile-directory=Default', '--no-first-run',
            '--no-default-browser-check', url]


def vaciar_teclado():
    """Descarta lo tecleado mientras Chrome abría (un ENTER suelto en el buffer haría que input() vuelva solo). Solo Windows."""
    try:
        import msvcrt
        while msvcrt.kbhit():
            msvcrt.getch()
    except Exception:  # noqa: BLE001
        pass


def esperar_listo(input_fn=input, log=print, vaciar=vaciar_teclado, reloj=time.time):
    """Espera a que escribas LISTO (no alcanza con un ENTER suelto: un ENTER tecleado antes, o un buffer con restos, no cierra nada)."""
    vaciar()
    while True:
        try:
            r = input_fn('>>> Cuando termines de loguearte y resolver captchas, escribí LISTO y apretá ENTER (Chrome sigue abierto hasta entonces): ')
        except EOFError:
            log('No hay una consola interactiva (stdin cerrado). Corré este comando desde una ventana de CMD abierta a mano.')
            return False
        if r.strip().lower() in ('listo', 'l'):
            return True
        log('   (eso no es LISTO: sigo esperando; Chrome no se cierra)')


def configurar_login(perfil_dir=None, url='https://www.mercadolibre.com.ar/', input_fn=input, log=print, popen=subprocess.Popen,
                     chrome=None, esperar_cierre_seg=120):
    """-> 'ok' | 'sin_chrome' | 'cancelado'. Abre Chrome común con el perfil del scraper y espera a que digas LISTO."""
    perfil = perfil_dir or config.PERFIL_CHROME
    os.makedirs(perfil, exist_ok=True)
    chrome = chrome or buscar_chrome()
    if not chrome:
        return 'sin_chrome'
    liberar_perfil(perfil, log)
    log(f'Abriendo Chrome (el común, sin automatización) con el perfil del scraper: {os.path.abspath(perfil)}')
    popen(comando_chrome(chrome, perfil, url))
    log('')
    log('1) Iniciá sesión en Mercado Libre con tu cuenta y tildá "Mantener sesión iniciada".')
    log('2) Resolvé cualquier captcha o verificación que te pida.')
    log('3) Entrá a las tiendas que suelen pedir captcha (por ejemplo GEOTEK: https://listado.mercadolibre.com.ar/tienda/geotek) y resolvelo ahí:')
    log('   un captcha resuelto en una sesión normal suele dejar de pedirse por un tiempo.')
    log('4) Abrí cualquier publicación y confirmá que ves los precios.')
    if not esperar_listo(input_fn, log):
        return 'cancelado'
    log('Cerrá ahora la ventana de Chrome con la X (así se guarda la sesión). Espero hasta que se cierre...')
    fin = time.time() + esperar_cierre_seg
    while time.time() < fin and pids_del_perfil(perfil):
        time.sleep(2)
    if pids_del_perfil(perfil):
        log('Chrome sigue abierto: cerralo vos antes de correr el scraper (si no, el scraper no puede usar el perfil).')
    else:
        log('Listo: sesión guardada. Probá con: python scraper.py --vendedor geotek --solo perfiles --sin-escribir')
    return 'ok'
