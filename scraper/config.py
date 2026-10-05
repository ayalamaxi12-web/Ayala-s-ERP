"""Configuración del scraper de competencia (Etapa 2). Todo lo que se ajusta a mano vive acá."""
import os
import sys

# El scraper reusa la lógica de la Etapa 1 (backend/competencia_db.py, sin dependencias pesadas).
_BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'backend')
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

AQUI = os.path.dirname(os.path.abspath(__file__))

# ── Hojas de Google ───────────────────────────────────────────────────────────
SPREADSHEET_ID = '15b9kMzQFHdBOE5_7vWgriiiulHI6Yc9upJBUBBiXepY'           # la del ERP (Referencias_Mercado, etc.)
PLANILLA_MACA_ID = '1fLJiw-yaK0vsoqIuOlDHWH4qPdeo4p6FtV7KPZQKAZc'        # la define Maca: A-CATEGORIAS / B-SKU-COMPETENCIA
TAB_CATEGORIAS = 'A-CATEGORIAS'
TAB_SKU = 'B-SKU-COMPETENCIA'

# ── Archivos locales (fuera de git: ver .gitignore) ───────────────────────────
CREDENTIALS_FILE = os.environ.get('SCRAPER_CREDENTIALS', os.path.join(AQUI, 'credentials.json'))
PERFIL_CHROME = os.environ.get('SCRAPER_PERFIL_CHROME', os.path.join(AQUI, 'perfil_chrome'))
CARPETA_LOGS = os.path.join(AQUI, 'logs')

# ── Reglas de negocio ─────────────────────────────────────────────────────────
# Tiendas de la planilla de Maca -> entidad que YA existe en la base (sin esto se crearía una nueva).
# Clave = slug de la tienda en minúsculas. Confirmado por Maxx 2026-10-05.
ALIAS_TIENDAS = {
    'tecnovibe': 'TECNOVIBEARG',
    'american-computers': 'AMERICANCOMPUTERS',
    'elephant-cartridge': 'ELEPHANT CARTDRIGE',   # sic: así está escrito en la base
}

# No se scrapea a uno mismo (Maxx 2026-10-05): se compara por nombre de entidad normalizado (contiene).
EXCLUIR_ENTIDADES = ['global electronics']

# Stock bajo: la lógica está lista pero DESACTIVADA. La columna de stock de B-SKU-COMPETENCIA todavía no
# tiene la fórmula real (Maca se la va a poner). Activar recién cuando el dato sea confiable.
STOCK_ALERTAS_ACTIVAS = False
STOCK_BAJO_UMBRAL = 5          # "menos de 5 unidades"

# Cambio de precio: se registra CUALQUIER cambio (el filtro fino va en la pantalla, Etapa 3).
UMBRAL_CAMBIO_PRECIO_PCT = 0.0

# Pausas para no saturar a ML (segundos).
PAUSA_ENTRE_PUBLICACIONES = (2.0, 4.0)
PAUSA_ENTRE_PAGINAS = (1.5, 3.0)
