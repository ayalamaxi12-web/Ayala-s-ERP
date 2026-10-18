"""Sube un snapshot del tablero "Proyección 2027" al backend (POST /proyeccion-2027/snapshot).

El JSON lo genera `export_dashboard_data.py` (contrato de datos v1.0) y tiene datos sensibles: NO se commitea.
Solo lectura para el ERP: esto únicamente guarda una versión nueva (se conservan las últimas 20); no escribe en ningún canal.

Uso:
    ERP_API_KEY=... python scripts/subir_proyeccion.py dashboard_data.json --url https://<backend>.up.railway.app
    python scripts/subir_proyeccion.py dashboard_data.json --url ... --clave ...   # respaldo: queda en el historial de la shell, preferí la variable
"""
import argparse
import os
import sys

import requests


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("json", help="dashboard_data.json generado por export_dashboard_data.py")
    ap.add_argument("--url", default=os.environ.get("BACKEND_URL"), help="URL base del backend (o variable BACKEND_URL)")
    ap.add_argument("--clave", default=None, help="X-ERP-Key; solo respaldo (queda en el historial de la shell): lo normal es la variable ERP_API_KEY")
    a = ap.parse_args()
    clave = os.environ.get("ERP_API_KEY", "").strip() or a.clave  # la variable de entorno manda; --clave es solo respaldo
    if not a.url or not clave:
        sys.exit("Falta --url (o BACKEND_URL) o la clave: definí la variable ERP_API_KEY (o usá --clave como respaldo).")
    with open(a.json, "rb") as f:
        cuerpo = f.read()
    r = requests.post(a.url.rstrip("/") + "/proyeccion-2027/snapshot", data=cuerpo,
                      headers={"X-ERP-Key": clave, "Content-Type": "application/json"}, timeout=120)
    if r.ok:
        d = r.json()
        print(f"OK: versión {d['version']} cargada ({d['tamano_bytes']} bytes; se conservan las últimas {d['conservar']}).")
    else:
        sys.exit(f"Error {r.status_code}: {r.text[:800]}")


if __name__ == "__main__":
    main()
