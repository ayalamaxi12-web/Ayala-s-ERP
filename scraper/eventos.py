"""Eventos de competencia para la pantalla de la Etapa 3. Lógica pura (sin red ni Sheets).

Tipos: Bajo, Subio, Publicacion_caida, Reaparecio, Vendedor_sin_resultados, Stock_bajo.
Se guardan en la pestaña `Eventos_Competencia`, una fila por evento, idempotentes por (Fecha, Tipo, objetivo)."""
import config

EVENTOS_SHEET = 'Eventos_Competencia'
EVENTOS_HEADERS = ['Fecha', 'Hora', 'Tipo', 'Referencia_ID', 'SKU', 'Entidad', 'Rol', 'Valor_Anterior',
                   'Valor_Nuevo', 'Variacion_Pct', 'Detalle', 'Link']

BAJO, SUBIO, CAIDA, REAPARECIO = 'Bajo', 'Subio', 'Publicacion_caida', 'Reaparecio'
SIN_RESULTADOS, STOCK_BAJO = 'Vendedor_sin_resultados', 'Stock_bajo'


def evento_precio(anterior, nuevo, umbral_pct=None):
    """Cualquier cambio de precio contra la última lectura anterior con precio (umbral 0 = todo cambio).
    Sin lectura anterior (primera vez) no hay evento. -> dict parcial o None."""
    umbral = config.UMBRAL_CAMBIO_PRECIO_PCT if umbral_pct is None else umbral_pct
    if anterior in (None, 0) or nuevo is None:
        return None
    var = (nuevo - anterior) / anterior * 100
    if nuevo == anterior or abs(var) < umbral:
        return None
    return {'Tipo': BAJO if nuevo < anterior else SUBIO, 'Valor_Anterior': anterior, 'Valor_Nuevo': nuevo,
            'Variacion_Pct': round(var, 2)}


def transicion_caida(ultimo_tipo, pagina_ok_con_precio, pagina_dice_caida):
    """Evita avisar todos los días de lo mismo.
    - La página cargó bien y dice 'no disponible/finalizada/pausada' y NO estaba ya caída -> Publicacion_caida.
    - Hay precio de nuevo y estaba caída -> Reaparecio.
    Un timeout/captcha/error de red NO es caída (se resuelve antes de llamar acá)."""
    ya_caida = ultimo_tipo == CAIDA
    if pagina_dice_caida and not ya_caida:
        return CAIDA
    if pagina_ok_con_precio and ya_caida:
        return REAPARECIO
    return None


def evento_stock_bajo(stock, umbral=None, activo=None):
    """Stock menor al umbral (5). DESACTIVADO mientras la columna de stock no tenga el dato real
    (config.STOCK_ALERTAS_ACTIVAS). -> dict parcial o None."""
    activo = config.STOCK_ALERTAS_ACTIVAS if activo is None else activo
    umbral = config.STOCK_BAJO_UMBRAL if umbral is None else umbral
    if not activo or stock is None or stock >= umbral:
        return None
    return {'Tipo': STOCK_BAJO, 'Valor_Nuevo': stock, 'Detalle': f'Stock {stock} < {umbral}'}


def ultimo_tipo_por_referencia(filas_eventos):
    """De las filas de Eventos_Competencia (con encabezado) -> {Referencia_ID: último Tipo de caída/reaparición}.
    Solo mira Publicacion_caida / Reaparecio: el último gana (el orden de la hoja es cronológico)."""
    if not filas_eventos:
        return {}
    h = {x: i for i, x in enumerate(filas_eventos[0])}
    out = {}
    for f in filas_eventos[1:]:
        t = f[h['Tipo']] if len(f) > h['Tipo'] else ''
        r = f[h['Referencia_ID']] if len(f) > h['Referencia_ID'] else ''
        if r and t in (CAIDA, REAPARECIO):
            out[r] = t
    return out
