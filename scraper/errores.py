"""Errores del navegador y de la corrida (sin dependencias: se usan desde ml_selenium y corrida)."""


class NavegadorCaido(Exception):
    """Chrome se cayó demasiadas veces seguidas: no tiene sentido seguir (la corrida escribe lo que tenga y corta)."""


class CorridaCortada(Exception):
    """La corrida se cortó antes de terminar (navegador caído, tiempo máximo...). Lo leído hasta ahí YA se escribió;
    con --reanudar se retoma lo que falta."""


# Mensajes de Selenium/chromedriver cuando la SESIÓN del navegador murió (Chrome cerrado, crasheado, PC suspendida...).
# Ojo: 'net::ERR_INTERNET_DISCONNECTED' es un problema de red de UNA página, no de sesión: por eso no se usa 'disconnected' a secas.
_SESION = ('invalid session id', 'session deleted', 'browser has closed the connection', 'chrome not reachable',
           'target window already closed', 'no such window', 'web view not found', 'not connected to devtools',
           'unable to discover open pages', 'session not created', 'user data directory is already in use')
_CHROMEDRIVER_MUERTO = ('failed to establish a new connection', 'remote end closed connection', 'connection aborted',
                        'connection refused', 'max retries exceeded with url: /session')


def es_error_de_sesion(exc):
    m = str(exc).lower()
    if any(f in m for f in _SESION):
        return True
    return any(f in m for f in _CHROMEDRIVER_MUERTO) and ('localhost' in m or '127.0.0.1' in m or '/session' in m)


def es_timeout(exc):
    return type(exc).__name__ == 'TimeoutException' or 'timed out receiving message from renderer' in str(exc).lower()
