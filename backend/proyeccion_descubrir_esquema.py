"""TEMPORAL -- GET /proyeccion-2027/descubrir-esquema. Se usa UNA vez y se elimina en un PR aparte.

Para qué: el requerimiento "mercadería pedida y en tránsito" necesita saber cómo se llaman las tablas/columnas de pedidos en Táctica, y el
repo no lo documenta. Este endpoint corre UNA consulta fija contra INFORMATION_SCHEMA.COLUMNS (solo metadatos: nombres de tablas, columnas
y tipos; ninguna fila de datos de negocio) y devuelve TABLE_NAME, COLUMN_NAME y DATA_TYPE.

Garantías:
  - Solo lectura: un único SELECT con texto fijo (`_SQL`), sin parámetros ni nada que venga del usuario. No hay escritura en Táctica.
  - X-ERP-Key obligatoria; falla CERRADO (503) si `ERP_API_KEY` no está definida en el servidor.
  - Timeout de login (20 s) y de consulta (30 s), y tope de filas (`TOPE_FILAS`; si se pasa, `truncado: true`).
  - Ante un error de conexión/consulta no se devuelve el texto de la excepción (podría traer servidor o usuario): solo la clase del error.

Para borrarlo: este archivo, su test (`test_proyeccion_descubrir_esquema.py`), las 2 líneas de `main.py` y la entrada de `erp_auth._RUTAS_GET_PROTEGIDAS`.
"""
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from erp_auth import HEADER_CLAVE, clave_valida
from rentabilidad import config

router = APIRouter(prefix="/proyeccion-2027", tags=["proyeccion-2027"])

LOGIN_TIMEOUT_SEG = 20
QUERY_TIMEOUT_SEG = 30
TOPE_FILAS = 3000

# Texto fijo: NO se arma con datos del request. (Sin ';' final: es una sola sentencia.)
_SQL = """
SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME LIKE '%requer%' OR TABLE_NAME LIKE '%pedido%' OR TABLE_NAME LIKE '%compra%'
   OR TABLE_NAME LIKE '%import%' OR TABLE_NAME LIKE '%transit%' OR TABLE_NAME LIKE '%embarque%'
ORDER BY TABLE_NAME, ORDINAL_POSITION
"""


def _exigir_clave(request: Request):
    esperada = os.environ.get("ERP_API_KEY", "").strip()
    if not esperada:
        raise HTTPException(status_code=503, detail="ERP_API_KEY no está definida en el servidor: este endpoint no responde sin clave.")
    if not clave_valida(esperada, request.headers.get(HEADER_CLAVE)):
        raise HTTPException(status_code=401, detail="X-ERP-Key inválida o ausente")


def _conectar():
    """Import perezoso de pymssql (igual que ingesta_tactica / adapters) y mismas variables RENT_TACTICA_SQL_*."""
    import pymssql

    return pymssql.connect(
        server=config.requerido("RENT_TACTICA_SQL_SERVER"),
        user=config.requerido("RENT_TACTICA_SQL_USER"),
        password=config.requerido("RENT_TACTICA_SQL_PASSWORD"),
        database=config.requerido("RENT_TACTICA_SQL_DATABASE"),
        login_timeout=LOGIN_TIMEOUT_SEG,
        timeout=QUERY_TIMEOUT_SEG,
        as_dict=True,
    )


def _leer():
    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute(_SQL)  # sin segundo argumento: no hay parámetros y pymssql no interpola los '%' de los LIKE
        filas = cur.fetchmany(TOPE_FILAS + 1)
    finally:
        conn.close()
    truncado = len(filas) > TOPE_FILAS
    return [{"TABLE_NAME": f["TABLE_NAME"], "COLUMN_NAME": f["COLUMN_NAME"], "DATA_TYPE": f["DATA_TYPE"]} for f in filas[:TOPE_FILAS]], truncado


@router.get("/descubrir-esquema")
def descubrir_esquema(request: Request):
    _exigir_clave(request)
    try:
        filas, truncado = _leer()
    except config.ConfiguracionFaltante:
        raise  # main.py lo convierte en 503 con el nombre de la variable que falta (no el valor)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"No se pudo consultar Táctica ({type(e).__name__}).")
    return JSONResponse({"total": len(filas), "truncado": truncado, "tope": TOPE_FILAS, "filas": filas}, headers={"Cache-Control": "no-store"})
