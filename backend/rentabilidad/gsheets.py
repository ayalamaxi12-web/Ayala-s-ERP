"""Cliente de Google Sheets y utilidades genéricas de lectura para los
adaptadores de Rentabilidad.

Implementación propia para este módulo (no se importa `get_gs()` de
`backend/main.py` para mantener `rentabilidad/` desacoplado del resto del
backend), aunque sigue la misma convención de credenciales ya usada en el
resto del repo (`GOOGLE_CREDENTIALS_JSON` o `credentials.json` local).
"""
import json
import os
from typing import Sequence

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_client():
    """Devuelve un cliente gspread autorizado. Import perezoso de gspread/
    google-auth para que el resto de `rentabilidad/` (modelos, calculadores)
    no dependa de esas libs ni de credenciales para correr sus tests."""
    import gspread
    from google.oauth2.service_account import Credentials

    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        creds = Credentials.from_service_account_info(json.loads(creds_json), scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    return gspread.authorize(creds)


def leer_valores(spreadsheet_id: str, tab: str) -> list[list[str]]:
    """Todas las filas crudas (incluida la de headers) de una pestaña."""
    client = get_client()
    ws = client.open_by_key(spreadsheet_id).worksheet(tab)
    return ws.get_all_values()


# ── Helpers de columna por título — implementación propia, no un port del
# `hdrMap`/`findCol` de docs/index.html (adjustment #8: sin reutilizar JS). ──

def encontrar_fila_headers(filas: Sequence[Sequence[str]], candidatos: Sequence[str], max_filas: int = 5) -> int:
    """Primera fila (dentro de las primeras `max_filas`) que contiene alguno
    de los `candidatos` (comparación case-insensitive, substring)."""
    candidatos_l = [c.lower() for c in candidatos]
    for i, fila in enumerate(filas[:max_filas]):
        celdas_l = [str(c or "").lower() for c in fila]
        if any(cand in celda for celda in celdas_l for cand in candidatos_l):
            return i
    return 0


def mapa_columnas(headers: Sequence[str]) -> dict[str, int]:
    return {str(h or "").strip().lower(): i for i, h in enumerate(headers)}


def indice_columna(mapa: dict[str, int], titulos_posibles: Sequence[str]) -> int | None:
    """Primer índice cuyo header coincide (exacto o substring) con alguno de
    los títulos candidatos, en el orden dado."""
    for titulo in titulos_posibles:
        t = titulo.lower()
        if t in mapa:
            return mapa[t]
        for header, idx in mapa.items():
            if t in header:
                return idx
    return None


def valor(fila: Sequence[str], idx: int | None) -> str:
    if idx is None or idx >= len(fila):
        return ""
    return str(fila[idx] or "").strip()
