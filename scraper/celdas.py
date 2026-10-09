"""Medidor de celdas de Google Sheets: el límite es 10M por archivo y cuentan también las celdas vacías de cada pestaña
(filas x columnas del grid). Se mide con UNA llamada de metadata (no lee datos)."""
import config


def medir(ss):
    """-> {'total', 'limite', 'pct', 'nivel': 'ok'|'60'|'80', 'mayores': [(pestaña, celdas)] } o None si no se pudo medir."""
    try:
        meta = ss.fetch_sheet_metadata({'fields': 'sheets.properties(title,gridProperties)'})
        hojas = []
        for s in meta.get('sheets', []):
            g = s['properties'].get('gridProperties', {})
            hojas.append((s['properties']['title'], int(g.get('rowCount', 0)) * int(g.get('columnCount', 0))))
    except Exception as e:  # noqa: BLE001  (el medidor nunca debe tirar una corrida)
        return {'error': str(e)}
    total = sum(c for _, c in hojas)
    pct = total / config.LIMITE_CELDAS * 100
    a60, a80 = config.AVISOS_CELDAS_PCT
    return {'total': total, 'limite': config.LIMITE_CELDAS, 'pct': round(pct, 1),
            'nivel': '80' if pct >= a80 else '60' if pct >= a60 else 'ok',
            'mayores': sorted(hojas, key=lambda x: -x[1])[:3]}


def texto(m):
    if not m:
        return ''
    if 'error' in m:
        return f"Celdas usadas: no se pudo medir ({m['error'][:80]})"
    t = (f"Celdas usadas: {m['total'] / 1e6:.2f}M / {m['limite'] / 1e6:.0f}M ({m['pct']:.0f}%) · mayores: "
         + ', '.join(f'{n} ({c / 1e3:.0f}K)' for n, c in m['mayores']))
    if m['nivel'] == '80':
        t += '\n   ⚠⚠ Más del 80% del límite de Google Sheets: hay que liberar espacio o pasar el histórico a la base de datos YA.'
    elif m['nivel'] == '60':
        t += '\n   ⚠ Más del 60% del límite de Google Sheets: planificar la limpieza / el pase a la base de datos.'
    return t
