"""Mapa subcategoría -> tienda Rey/Media/Barato (pestaña A-CATEGORIAS de Maca), guardado en el Sheet del ERP (`Categoria_Competidores`).

Antes solo vivía en la planilla de Maca y el scraper lo leía en cada corrida sin guardarlo: la pantalla "Análisis de Competencia" no podía
mostrar la vista por categoría. Se sincroniza con upsert por (Subcategoria, Rol, Slug); NUNCA borra ni desactiva filas (lo que Maca saque de
la planilla queda con su `Actualizado` viejo y la pantalla lo marca como desactualizado). La categoría la define Maca: acá no se clasifica nada."""
import config  # noqa: F401
import competencia_db as cdb
import sheets_io as sio

CATEGORIAS_SHEET = 'Categoria_Competidores'
CATEGORIAS_HEADERS = ['Subcategoria', 'Rol', 'Entidad_ID', 'Entidad', 'Slug', 'SKUs_Nuestros', 'Actualizado']
CLAVES = ['Subcategoria', 'Rol', 'Slug']


def filas(perfiles, hoy):
    """Una fila por (subcategoría, rol, tienda) de los perfiles resueltos por la sincronización. Excluye las entidades excluidas (Global Electronics)."""
    out, vistos = [], set()
    for p in perfiles:
        if p.get('excluida'):
            continue
        k = (p['subcategoria'], p['rol_nombre'], p['slug'])
        if k in vistos:
            continue
        vistos.add(k)
        out.append({'Subcategoria': p['subcategoria'], 'Rol': p['rol_nombre'], 'Entidad_ID': p.get('entidad_id', ''),
                    'Entidad': p.get('entidad_nombre', ''), 'Slug': p['slug'], 'SKUs_Nuestros': p.get('skus_nuestros', ''), 'Actualizado': hoy})
    return out


def registrar(ss, perfiles, hoy):
    """-> (nuevas, actualizadas). Crea la pestaña si no existe."""
    datos = filas(perfiles, hoy)
    if not datos:
        return 0, 0
    ws = cdb.asegurar_pestana(ss, CATEGORIAS_SHEET, CATEGORIAS_HEADERS, 500)
    h = sio.asegurar_columnas(ws, CATEGORIAS_HEADERS)
    return sio.upsert(ws, h, datos, CLAVES)
