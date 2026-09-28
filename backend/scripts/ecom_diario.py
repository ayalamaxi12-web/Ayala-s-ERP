"""Corrida diaria de Rentabilidad ECOM desde la API de Ecom.

Recalcula el ciclo en curso (23 → 22) hasta ayer y lo guarda — ver
`rentabilidad/cierre_ecom_diario.py` para el detalle.

Corre en proceso (no llama al backend por HTTP: un ciclo completo son miles
de órdenes y no entra en el timeout de un request). Necesita el mismo
entorno que el backend: RENT_DATABASE_URL, RENT_ECOM_EMAIL,
RENT_ECOM_PASSWORD, GOOGLE_CREDENTIALS_JSON y los RENT_SHEET_* (y la SQL de
Táctica para el factor de IVA informativo; si no está, ese dato queda vacío).

Uso (desde backend/):
    python scripts/ecom_diario.py                      # ciclo en curso hasta ayer, TC del BNA del día
    python scripts/ecom_diario.py --tc 1540            # TC manual
    python scripts/ecom_diario.py --hasta 2026-06-01 --desde 2026-06-01 --solo-consulta
"""
import argparse
import os
import sys
from datetime import date
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rentabilidad import api  # noqa: E402
from rentabilidad.adapters import IvaProvider  # noqa: E402
from rentabilidad.cierre_ecom_diario import DIA_CORTE, ayer_en_argentina, correr, formatear  # noqa: E402
from rentabilidad.db import sesion  # noqa: E402
from rentabilidad.ingesta_ecom_api import EcomApiAdapter  # noqa: E402
from rentabilidad.tc_bna import obtener_tc_bna  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hasta", type=date.fromisoformat, help="último día a traer (default: ayer, hora Argentina)")
    ap.add_argument("--desde", type=date.fromisoformat, help="primer día (default: inicio del ciclo 23→22 de --hasta)")
    ap.add_argument("--tc", help="tipo de cambio manual (default: BNA del momento)")
    ap.add_argument("--dia-corte", type=int, default=DIA_CORTE)
    ap.add_argument("--solo-consulta", action="store_true", help="calcula y muestra, no guarda nada")
    args = ap.parse_args()

    api.migrar_y_sembrar()
    # TC: siempre el del BNA del día (decisión de Maxx, 2026-09-28); --tc
    # queda para correr a mano un caso puntual. El origen sale al pie del
    # resumen y del informe para poder verificarlo.
    tc = Decimal(args.tc) if args.tc else obtener_tc_bna()
    tc_origen = api.origen_tc(args.tc)
    hasta = args.hasta or ayer_en_argentina()
    fetch = api._fetch_fn_con_cache()
    try:
        with sesion() as db:
            resumen = correr(
                db, EcomApiAdapter(), tc,
                IvaProvider(consultar=api._consultar_catalogo_tactica_con_cache()),
                api._providers_ecom(fetch), hasta=hasta, desde=args.desde,
                guardar=not args.solo_consulta, dia_corte=args.dia_corte, tc_origen=tc_origen,
            )
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    print(formatear(resumen))
    return 0


if __name__ == "__main__":
    sys.exit(main())
