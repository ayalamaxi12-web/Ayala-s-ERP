"""Corrida diaria de Rentabilidad ECOM desde la API de Ecom.

Recalcula el ciclo en curso (23 → 22) hasta ayer y lo guarda — ver
`rentabilidad/cierre_ecom_diario.py` para el detalle.

Corre en proceso (no llama al backend por HTTP: un ciclo completo son miles
de órdenes y no entra en el timeout de un request). Necesita el mismo
entorno que el backend: RENT_DATABASE_URL, RENT_ECOM_EMAIL,
RENT_ECOM_PASSWORD, GOOGLE_CREDENTIALS_JSON y los RENT_SHEET_*.

**No depende de Táctica** (decisión de Maxx, 2026-09-28): el factor de IVA
informativo sale de la propia API de Ecom, así que no hace falta el túnel
de Tailscale ni la SQL de Táctica para correr.

Cada paso deja una línea con hora en el log (stderr, sin buffer) para ver
dónde está si algo tarda, y la corrida entera tiene un límite de tiempo
(`--max-minutos`): si se pasa, termina con error diciendo en qué paso quedó.

Uso (desde backend/):
    python scripts/ecom_diario.py                      # ciclo en curso hasta ayer, TC del BNA del día
    python scripts/ecom_diario.py --tc 1540            # TC manual
    python scripts/ecom_diario.py --hasta 2026-06-01 --desde 2026-06-01 --solo-consulta
"""
import argparse
import os
import signal
import sys
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

# Timeouts de Postgres para TODAS las conexiones del proceso, incluida la de
# Alembic (que arma su propio engine): libpq lee estas variables al conectar.
# - PGCONNECT_TIMEOUT: base inalcanzable → error en 10s, no espera infinita.
# - lock_timeout: si otra conexión (ej. el backend migrando o con una
#   transacción abierta) tiene tomada una tabla, error en 60s en vez de
#   quedar esperando el lock para siempre.
os.environ.setdefault("PGCONNECT_TIMEOUT", "10")
os.environ.setdefault("PGOPTIONS", "-c lock_timeout=60000")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ART = timezone(timedelta(hours=-3))
_INICIO = time.monotonic()
_paso_actual = "arrancando"


def log(msg: str) -> None:
    """Directo a stderr y sin buffer: el `fileConfig` de Alembic apaga los
    loggers existentes, y `print` a stdout sin TTY queda en buffer hasta el
    final — por eso antes no se veía nada después de las migraciones."""
    global _paso_actual
    _paso_actual = msg
    print(f"[{datetime.now(_ART):%H:%M:%S} +{time.monotonic() - _INICIO:6.1f}s] {msg}", file=sys.stderr, flush=True)


def _limite_de_tiempo(signum, frame):
    raise TimeoutError(f"La corrida superó el tiempo máximo. Último paso: {_paso_actual}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hasta", type=date.fromisoformat, help="último día a traer (default: ayer, hora Argentina)")
    ap.add_argument("--desde", type=date.fromisoformat, help="primer día (default: inicio del ciclo 23→22 de --hasta)")
    ap.add_argument("--tc", help="tipo de cambio manual (default: BNA del momento)")
    ap.add_argument("--dia-corte", type=int, default=None)
    ap.add_argument("--solo-consulta", action="store_true", help="calcula y muestra, no guarda nada")
    ap.add_argument("--max-minutos", type=int, default=45, help="límite total de la corrida (default: 45)")
    args = ap.parse_args()

    signal.signal(signal.SIGALRM, _limite_de_tiempo)
    signal.alarm(args.max_minutos * 60)

    try:
        log("Inicio de la corrida diaria de Rentabilidad ECOM")
        from rentabilidad import api
        from rentabilidad.adapters import IvaProvider
        from rentabilidad.cierre_ecom_diario import DIA_CORTE, ayer_en_argentina, correr, formatear
        from rentabilidad.db import sesion
        from rentabilidad.ingesta_ecom_api import EcomApiAdapter
        from rentabilidad.tc_bna import obtener_tc_bna

        log("Migraciones de la base (Alembic)")
        api.migrar_y_sembrar()
        log("Migraciones OK")

        # TC: siempre el del BNA del día (decisión de Maxx, 2026-09-28); --tc
        # queda para correr a mano un caso puntual. El origen sale al pie del
        # resumen y del informe para poder verificarlo.
        if args.tc:
            tc = Decimal(args.tc)
            log(f"TC manual: {tc}")
        else:
            log("Consultando TC del BNA")
            tc = obtener_tc_bna()
            log(f"TC del BNA: {tc}")
        tc_origen = api.origen_tc(args.tc)
        hasta = args.hasta or ayer_en_argentina()
        fetch = api._fetch_fn_con_cache(log=log)
        providers = api._providers_ecom(fetch)
        # PM / subcategoría / CATEGORÍA salen de GRAL CATEGORIAS: la pantalla
        # desglosa por categoría. Se prueba una vez al arrancar para que, si
        # falta la configuración, el log lo diga en vez de guardar todo vacío.
        log("Verificando GRAL CATEGORIAS (PM / subcategoría / categoría)")
        try:
            filas = providers["clasificacion_provider"]._indices()["A"]
            log(f"GRAL CATEGORIAS OK: {len(filas)} SKUs")
        except Exception as e:
            log(f"AVISO: no se pudo leer GRAL CATEGORIAS ({type(e).__name__}: {e}) — PM, subcategoría y "
                "categoría van a quedar vacíos. Revisar RENT_SHEET_CATEGORIAS_ID y GOOGLE_CREDENTIALS_JSON en el Cron.")
        # Ecom no depende de Táctica: el factor de IVA viene de la API de Ecom.
        # `IvaProvider` queda solo como respaldo y sin consultar la SQL.
        iva_sin_tactica = IvaProvider(consultar=lambda: [])
        with sesion() as db:
            resumen = correr(
                db, EcomApiAdapter(log=log), tc, iva_sin_tactica,
                providers, hasta=hasta, desde=args.desde,
                guardar=not args.solo_consulta, dia_corte=args.dia_corte or DIA_CORTE,
                tc_origen=tc_origen, log=log,
            )
            if not args.solo_consulta:
                log("Commit a la base")
        log("Listo")
    except ValueError as e:
        log(f"ERROR: {e}")
        return 2
    except Exception as e:
        log(f"ERROR ({type(e).__name__}) en el paso '{_paso_actual}': {e}")
        raise
    finally:
        signal.alarm(0)
    print(formatear(resumen), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
