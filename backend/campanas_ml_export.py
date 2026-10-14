"""C3 — hoja "ERP Análisis" que se agrega al Excel de la campaña (la MISMA estructura para los dos tipos de campaña).

Todos los números salen del análisis del backend (motor de márgenes), nunca del cálculo del navegador. La hoja nueva no toca
"Promociones": el Excel vuelve a subirse a ML tal cual, y el usuario copia la columna VALOR A COPIAR en la columna de ML.

VALOR A COPIAR según el tipo de campaña:
  · con reparto  → SELLER_PERCENTAGE = descuento total − aporte de ML (en %, puede tener decimales); alternativa en $: SELLER_AMOUNT.
  · simple       → DISCOUNT_PERCENTAGE = el descuento total (entero 5–80); no hay monto alternativo.
ML pide el descuento TOTAL entero entre 5 y 80: si no cumple, o ML ya aporta más que el total, no hay valor a copiar.
Las filas que no se tocaron llevan EXACTAMENTE el valor que trae ML (copiar la columna entera es inocuo)."""
from __future__ import annotations

NOMBRE_HOJA = "ERP Análisis"
PCT_MIN, PCT_MAX = 5, 80

ENCABEZADOS = [
    "ITEM_ID", "SKU", "TÍTULO", "CUENTA", "PM", "EDITABLE EN ML", "CAMBIÓ vs EXCEL", "PRECIO DE LISTA",
    "DESCUENTO TOTAL % (ERP)", "COLUMNA DE ML", "VALOR A COPIAR", "MONTO ALTERNATIVO $ (SELLER_AMOUNT)",
    "% VENDEDOR", "% ML", "$ ML", "PRECIO QUE PAGA EL CLIENTE", "PRECIO DEL VENDEDOR (CLIENTE + ML)",
    "PRECIO PM ML", "DIF. vs PM %", "COSTO $", "COMISIÓN %", "ORIGEN COMISIÓN",
    "MARGEN CONTADO %", "MARGEN 3 CUOTAS %", "MARGEN 6 CUOTAS %", "MARGEN 9 CUOTAS %", "MARGEN 12 CUOTAS %",
    "RECIBÍS ESTIMADO $", "RECIBÍS SEGÚN ML $", "AVISOS",
]


def valor_a_copiar(tipo: str, total, orig, meli_monto) -> tuple[float | None, float | None, str | None]:
    """(valor en %, monto alternativo en $, motivo si no hay). `total` = descuento total jugado (%)."""
    if total is None or not orig:
        return None, None, "sin descuento"
    if abs(total - round(total)) > 1e-6 or not (PCT_MIN <= total <= PCT_MAX):
        return None, None, f"ML pide el descuento total entero entre {PCT_MIN} y {PCT_MAX}"
    if tipo == "simple":
        return float(round(total)), None, None
    seller_monto = orig * total / 100 - (meli_monto or 0)
    if seller_monto < -0.005:
        return None, None, "el aporte de ML supera ese descuento total"
    return round(seller_monto / orig * 100, 3), round(seller_monto, 2), None


def _pct(f, plan):
    m = (f.get("margenes") or {}).get(plan)
    return None if m is None else m["margen"]


def construir(analisis: dict, tipo: str, originales: dict[int, dict]) -> tuple[list[str], list[list]]:
    """`analisis`: salida de `campanas_ml.analizar` (valores del backend). `originales`: filas leídas del Excel, por número de fila."""
    col = "SELLER_PERCENTAGE" if tipo == "reparto" else "DISCOUNT_PERCENTAGE"
    filas = []
    for f in analisis["filas"]:
        o = originales.get(f["fila"], {})
        total = f.get("descuento_total_pct")
        orig_total = o.get("DISCOUNT_PERCENTAGE")
        cambio = total is not None and orig_total is not None and abs(total - orig_total) > 1e-6
        valor, monto, motivo = valor_a_copiar(tipo, total, f.get("precio_original"), f.get("meli_monto")) if f.get("editable") else (None, None, "celda no editable en ML")
        if valor is not None and not cambio and o.get("SELLER_PERCENTAGE") is not None:
            # Sin cambios: se copia EXACTAMENTE lo que trae ML (su % viene redondeado a 3 decimales y no tiene por qué coincidir con la resta).
            valor, monto = o["SELLER_PERCENTAGE"], (o.get("SELLER_AMOUNT") if tipo == "reparto" else None)
        avisos = list(f.get("avisos") or [])
        if motivo and f.get("editable"):
            avisos.insert(0, "SIN VALOR A COPIAR: " + motivo)
        rm, rml = f.get("recibis_motor"), f.get("recibis_ml")
        filas.append([
            f["item_id"], f.get("sku") or "", f.get("titulo") or "", f.get("cuenta") or "", f.get("pm") or "",
            "SI" if f.get("editable") else "NO", ("SI" if cambio else "NO") if f.get("editable") else "—", f.get("precio_original"),
            total, col, (valor, "copiar") if valor is not None else ("—", "txt"), monto if monto is not None else "",
            f.get("seller_pct"), f.get("meli_pct"), f.get("meli_monto"), f.get("precio_cliente"), f.get("precio_vendedor"),
            f.get("precio_pm"), f.get("dif_vs_pm_pct"), f.get("costo"), f.get("comision_pct"), f.get("comision_origen") or "",
            _pct(f, "contado"), _pct(f, "3"), _pct(f, "6"), _pct(f, "9"), _pct(f, "12"),
            rm, rml, " | ".join(avisos),
        ])
    return ENCABEZADOS, filas
