"""Informe de rentabilidad (ECOM + Táctica) de un cierre guardado, en HTML.

Lee solo endpoints de lectura de `/rentabilidad/*` del backend (que a su vez
leen el Postgres de Railway), así que no necesita VPN ni la SQL de Táctica.
Pensado para correr desde una Rutina en la nube: stdlib pura, sin dependencias.

Uso:
    python3 backend/scripts/informe_rentabilidad.py [--periodo 2026-08-23_2026-09-22] \
        [--backend https://ayala-s-erp-production.up.railway.app] \
        [--html informe.html] [--txt informe.txt] [--meta informe.json]

Sin --periodo toma el cierre más reciente que tenga ECOM y Táctica guardados.
`--meta` escribe un JSON con {periodo, asunto} para armar el mail.
"""
import argparse
import collections
import json
import urllib.request
from datetime import date
from decimal import Decimal as D

BACKEND = "https://ayala-s-erp-production.up.railway.app"
ROJO = "#c0392b"


def get(base, path):
    with urllib.request.urlopen(base + "/rentabilidad" + path, timeout=300) as r:
        return json.loads(r.read())


def m(v):
    v = D(v)
    return f"{'-' if v < 0 else ''}$ {abs(v):,.0f}".replace(",", ".")


def pc(v):
    return "—" if v is None else f"{D(v) * 100:.1f}%".replace(".", ",")


def n(v):
    return f"{v:,}".replace(",", ".")


def ratio(a, b):
    return a / b if b else None


def red(s):
    return f'<font color="{ROJO}">{s}</font>' if str(s).startswith("-") else str(s)


def table(hdr, rows, right=()):
    o = ['<table border="1" cellpadding="4" cellspacing="0" style="border-collapse:collapse;border-color:#ddd;font-size:13px">',
         "<tr>" + "".join(f'<th bgcolor="#f0f2f5" align="left">{h}</th>' for h in hdr) + "</tr>"]
    for row in rows:
        o.append("<tr>" + "".join(f'<td align="right">{c}</td>' if i in right else f"<td>{c}</td>" for i, c in enumerate(row)) + "</tr>")
    return "".join(o) + "</table>"


def agrupar(filas, clave, fact, rent):
    """{clave: [fact sin IVA, rentabilidad, líneas]}"""
    d = collections.defaultdict(lambda: [D(0), D(0), 0])
    for x in filas:
        a = d[clave(x)]
        a[0] += D(x[fact] or 0)
        a[1] += D(x[rent] or 0)
        a[2] += 1
    return d


def desde_agregacion(filas, vacio):
    return {(x["dimension_valor"] or vacio): [D(x["suma_2"]), D(x["suma_resultado"]), x["cantidad_lineas"]] for x in filas}


def top(d, idx, etiqueta, unidad, k=10):
    it = sorted(d.items(), key=lambda kv: kv[1][idx], reverse=True)[:k]
    return table(["#", etiqueta, "Fact. sin IVA", "Rentab. $", "Rentab. %", unidad],
                 [[i, key, m(a[0]), red(m(a[1])), red(pc(ratio(a[1], a[0]))), n(a[2])] for i, (key, a) in enumerate(it, 1)],
                 {0, 2, 3, 4, 5})


def negativos(d, etiqueta, unidad, k=None):
    it = sorted([(key, a) for key, a in d.items() if a[1] < 0], key=lambda kv: kv[1][1])
    if not it:
        return "<p>Ninguno.</p>", it
    return table([etiqueta, "Fact. sin IVA", "Rentab. $", "Rentab. %", unidad],
                 [[key, m(a[0]), red(m(a[1])), red(pc(ratio(a[1], a[0]))), n(a[2])] for key, a in it[:k]],
                 {1, 2, 3, 4}), it


def resumen_incidencias(inc):
    cnt = collections.Counter((x["codigo"], x["severidad"], x["detalle"]) for x in inc)
    return table(["Código", "Severidad", "Qué indica", "Cantidad"],
                 [[c, s, d, n(k)] for (c, s, d), k in sorted(cnt.items(), key=lambda kv: -kv[1])], {3})


def totales_tabla(con_iva, sin_iva, costo, rent, lineas, unidad):
    return table(["Concepto", "Valor"], [
        ["Facturación con IVA", m(con_iva)], ["Facturación sin IVA", m(sin_iva)], ["Costo", m(abs(D(costo)))],
        ["<b>Rentabilidad $</b>", f"<b>{m(rent)}</b>"], ["<b>Rentabilidad %</b>", f"<b>{pc(ratio(D(rent), D(sin_iva)))}</b>"],
        [unidad, n(lineas)]], {1})


def seccion_ecom(base, P, a):
    tot = get(base, f"/agregaciones/ecom?periodo={P}&dimension=periodo")[0]
    canal = get(base, f"/agregaciones/ecom?periodo={P}&dimension=canal")
    pm = desde_agregacion(get(base, f"/agregaciones/ecom?periodo={P}&dimension=pm"), "(sin PM)")
    sub = desde_agregacion(get(base, f"/agregaciones/ecom?periodo={P}&dimension=subcategoria"), "(sin subcategoría)")
    filas = [x for x in get(base, "/historico/ecom") if x["periodo"] == P]
    inc = get(base, f"/incidencias?periodo={P}&entidad=ecom")

    unico = [x for x in filas if "," not in (x["skus_vendidos"] or "")]
    multi = [x for x in filas if "," in (x["skus_vendidos"] or "")]
    sku = agrupar(unico, lambda x: (x["skus_vendidos"] or "(sin SKU)").strip(), "precio_sin_iva", "rentabilidad")
    cat = agrupar(filas, lambda x: x["categoria"] or "(sin categoría)", "precio_sin_iva", "rentabilidad")
    # Duplicados = misma orden más de una vez (control V-16).
    vistos, extra = set(), []
    for x in filas:
        (extra.append(x) if x["numero_orden"] in vistos else vistos.add(x["numero_orden"]))
    dup_ids = sorted({x["numero_orden"] for x in extra})
    ex = [sum(D(x[k] or 0) for x in extra) for k in ("precio_final", "precio_sin_iva", "rentabilidad")]
    T2, R = D(tot["suma_2"]), D(tot["suma_resultado"])

    a('<h2 style="border-bottom:2px solid #2c3e50;padding-bottom:4px">ECOM</h2><h3>1. Totales ECOM</h3>')
    a(totales_tabla(tot["suma_1"], T2, tot["suma_costo"], R, tot["cantidad_lineas"], "Órdenes"))
    if extra:
        a(f'<p style="font-size:13px;background:#fff4e5;border-left:4px solid #e67e22;padding:8px 10px"><b>⚠ Los totales cuentan doble '
          f'{len(dup_ids)} órdenes duplicadas</b> ({", ".join(dup_ids)}). Sin los duplicados: facturación sin IVA {m(T2 - ex[1])}, '
          f'rentabilidad {m(R - ex[2])}. Diferencia: {m(ex[1])} de facturación sin IVA y {m(ex[2])} de rentabilidad.</p>')
    a("<h3>2. Desglose por canal</h3>")
    a(table(["Canal", "Fact. sin IVA", "% del total", "Rentab. $", "Rentab. %", "Órdenes"],
            [[x["dimension_valor"] or "(sin canal)", m(x["suma_2"]), pc(ratio(D(x["suma_2"]), T2)), red(m(x["suma_resultado"])),
              red(pc(x["pct"])), n(x["cantidad_lineas"])] for x in sorted(canal, key=lambda x: D(x["suma_2"]), reverse=True)],
            {1, 2, 3, 4, 5}))
    a(f'<p style="font-size:12px;color:#555">{len(canal)} canales, ninguno omitido.</p>')
    ms = [sum(D(x[k] or 0) for x in multi) for k in ("precio_sin_iva", "rentabilidad")]
    a("<h3>3. Ganadores por facturación (top 10, fact. sin IVA)</h3>")
    a('<h4 style="margin:12px 0 4px">Por SKU (solo órdenes de un único SKU)</h4>' + top(sku, 0, "SKU", "Órdenes"))
    a(f"<p>Órdenes multi-SKU, contadas aparte y fuera del ranking por SKU: <b>{n(len(multi))} órdenes</b>, "
      f"{m(ms[0])} de facturación sin IVA y {m(ms[1])} de rentabilidad ({pc(ratio(ms[1], ms[0]))}).</p>")
    a('<h4 style="margin:12px 0 4px">Por categoría</h4>' + top(cat, 0, "Categoría", "Órdenes"))
    a('<h4 style="margin:12px 0 4px">Por PM</h4>' + top(pm, 0, "PM", "Órdenes"))
    a("<h3>4. Ganadores por rentabilidad $ (top 10)</h3>")
    a('<h4 style="margin:12px 0 4px">Por SKU (solo órdenes de un único SKU)</h4>' + top(sku, 1, "SKU", "Órdenes"))
    a('<h4 style="margin:12px 0 4px">Por categoría</h4>' + top(cat, 1, "Categoría", "Órdenes"))
    a('<h4 style="margin:12px 0 4px">Por PM</h4>' + top(pm, 1, "PM", "Órdenes"))
    a("<h3>5. Alertas ECOM</h3>")
    if extra:
        a('<h4 style="margin:12px 0 4px">Órdenes duplicadas (se cuentan dos veces en los totales)</h4>')
        a(table(["Orden", "Fecha", "Canal", "SKU", "PM", "Fact. sin IVA (por fila)", "Rentab. $ (por fila)"],
                [[x["numero_orden"], x["fecha"], x["canal_de_venta"], x["skus_vendidos"], x["pm"], m(x["precio_sin_iva"] or 0),
                  red(m(x["rentabilidad"] or 0))] for x in extra], {5, 6}))
    can_d = desde_agregacion(canal, "(sin canal)")
    for titulo, d, et in (("Canales", can_d, "Canal"), ("PM", pm, "PM"), ("Categorías", cat, "Categoría"), ("Subcategorías", sub, "Subcategoría")):
        a(f'<h4 style="margin:12px 0 4px">{titulo} con rentabilidad negativa</h4>' + negativos(d, et, "Órdenes")[0])
    html, neg = negativos(sku, "SKU", "Órdenes", 20)
    a(f'<h4 style="margin:12px 0 4px">SKU con rentabilidad negativa (órdenes de un único SKU)</h4>'
      f"<p><b>{len(neg)} SKU</b> con rentabilidad negativa, que suman {m(sum(v[1] for _, v in neg))}. Los 20 que más pierden:</p>" + html)
    a(f'<h4 style="margin:12px 0 4px">Incidencias ECOM, resumen por tipo ({n(len(inc))} en total)</h4>' + resumen_incidencias(inc))
    # Mapa subcategoría -> categoría para Táctica, que no trae categoría propia.
    mapa = collections.Counter((x["subcategoria"], x["categoria"]) for x in filas if x["subcategoria"] and x["categoria"])
    sub_cat = {}
    for (s, c), _ in mapa.most_common():
        sub_cat.setdefault(s, c)
    return {"con_iva": D(tot["suma_1"]), "sin_iva": T2, "rent": R, "lineas": tot["cantidad_lineas"]}, sub_cat


def seccion_tactica(base, P, a, sub_cat):
    tot = get(base, f"/agregaciones/tactica?periodo={P}&dimension=periodo")[0]
    pm = desde_agregacion(get(base, f"/agregaciones/tactica?periodo={P}&dimension=pm"), "(sin PM)")
    resp = get(base, f"/agregaciones/tactica?periodo={P}&dimension=responsable")
    sub = desde_agregacion(get(base, f"/agregaciones/tactica?periodo={P}&dimension=subcategoria"), "(sin subcategoría)")
    filas = [x for x in get(base, "/historico/tactica") if x["periodo"] == P]
    inc = get(base, f"/incidencias?periodo={P}&entidad=tactica")

    sku = agrupar(filas, lambda x: x["codigo"], "precio_venta", "margen_real")
    cat = agrupar(filas, lambda x: sub_cat.get(x["subcategoria"]) or "(sin categoría)", "precio_venta", "margen_real")
    cli = agrupar(filas, lambda x: x["empresa"], "precio_venta", "margen_real")
    # Duplicados = misma línea (comprobante + SKU) más de una vez (control V-16).
    vistos, extra = set(), []
    for x in filas:
        k = (x["nro_factura"], x["codigo"])
        (extra.append(x) if k in vistos else vistos.add(k))
    ex = [sum(D(x[k] or 0) for x in extra) for k in ("precio_venta", "margen_real")]
    T2, R = D(tot["suma_2"]), D(tot["suma_resultado"])

    a('<h2 style="border-bottom:2px solid #2c3e50;padding-bottom:4px;margin-top:32px">TÁCTICA</h2><h3>1. Totales Táctica</h3>')
    a(totales_tabla(tot["suma_1"], T2, tot["suma_costo"], R, tot["cantidad_lineas"], "Líneas de factura"))
    if extra:
        a(f'<p style="font-size:13px;background:#fff4e5;border-left:4px solid #e67e22;padding:8px 10px"><b>⚠ Los totales cuentan doble '
          f'{len(extra)} líneas duplicadas</b> (mismo comprobante y SKU). Sin los duplicados: facturación sin IVA {m(T2 - ex[0])}, '
          f'rentabilidad {m(R - ex[1])}. Diferencia: {m(ex[0])} y {m(ex[1])}. Detalle en Alertas Táctica.</p>')
    a('<p style="font-size:12px;color:#555">Táctica tiene un único canal ("Canal Tactica"), así que el desglose es por vendedor responsable. '
      "Táctica no trae categoría: se toma la de ECOM para la misma subcategoría.</p>")
    a("<h3>2. Desglose por vendedor responsable</h3>")
    a(table(["Responsable", "Fact. sin IVA", "% del total", "Rentab. $", "Rentab. %", "Líneas"],
            [[x["dimension_valor"] or "(sin responsable)", m(x["suma_2"]), pc(ratio(D(x["suma_2"]), T2)), red(m(x["suma_resultado"])),
              red(pc(x["pct"])), n(x["cantidad_lineas"])] for x in sorted(resp, key=lambda x: D(x["suma_2"]), reverse=True)],
            {1, 2, 3, 4, 5}))
    a("<h3>3. Ganadores por facturación (top 10, fact. sin IVA)</h3>")
    for et, d in (("SKU", sku), ("Categoría", cat), ("PM", pm), ("Cliente", cli)):
        a(f'<h4 style="margin:12px 0 4px">Por {et if et == "SKU" else et.lower()}</h4>' + top(d, 0, et, "Líneas"))
    a("<h3>4. Ganadores por rentabilidad $ (top 10)</h3>")
    for et, d in (("SKU", sku), ("Categoría", cat), ("PM", pm), ("Cliente", cli)):
        a(f'<h4 style="margin:12px 0 4px">Por {et if et == "SKU" else et.lower()}</h4>' + top(d, 1, et, "Líneas"))
    a("<h3>5. Alertas Táctica</h3>")
    if extra:
        a('<h4 style="margin:12px 0 4px">Líneas duplicadas (se cuentan dos veces en los totales)</h4>')
        a(table(["Comprobante", "Fecha", "Cliente", "SKU", "Fact. sin IVA (por fila)", "Rentab. $ (por fila)"],
                [[x["nro_factura"], x["fecha"], x["empresa"], x["codigo"], m(x["precio_venta"] or 0), red(m(x["margen_real"] or 0))]
                 for x in extra], {4, 5}))
    resp_d = desde_agregacion(resp, "(sin responsable)")
    for titulo, d, et in (("Vendedores", resp_d, "Responsable"), ("PM", pm, "PM"), ("Categorías", cat, "Categoría"), ("Subcategorías", sub, "Subcategoría")):
        a(f'<h4 style="margin:12px 0 4px">{titulo} con rentabilidad negativa</h4>' + negativos(d, et, "Líneas")[0])
    html, neg = negativos(sku, "SKU", "Líneas", 20)
    a(f'<h4 style="margin:12px 0 4px">SKU con rentabilidad negativa</h4>'
      f"<p><b>{len(neg)} SKU</b> con rentabilidad negativa, que suman {m(sum(v[1] for _, v in neg))}. Los 20 que más pierden:</p>" + html)
    a(f'<h4 style="margin:12px 0 4px">Incidencias Táctica, resumen por tipo ({n(len(inc))} en total)</h4>' + resumen_incidencias(inc))
    if any(x["severidad"] == "BLOQUEANTE" for x in inc):
        a('<p style="font-size:13px;color:#c0392b">Hay incidencias BLOQUEANTES: esas líneas pueden tener la rentabilidad mal calculada.</p>')
    return {"con_iva": D(tot["suma_1"]), "sin_iva": T2, "rent": R, "lineas": tot["cantidad_lineas"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--periodo")
    ap.add_argument("--backend", default=BACKEND)
    ap.add_argument("--html", default="informe_rentabilidad.html")
    ap.add_argument("--txt", default="informe_rentabilidad.txt")
    ap.add_argument("--meta", default="informe_rentabilidad.json")
    args = ap.parse_args()
    base = args.backend.rstrip("/")

    cierres = get(base, "/cierres")
    if args.periodo:
        cierre = next(c for c in cierres if c["periodo"] == args.periodo)
    else:
        cierre = max((c for c in cierres if c["ecom_guardado"] and c["tactica_guardado"]), key=lambda c: c["desde"])
    P = cierre["periodo"]
    d1, d2 = date.fromisoformat(cierre["desde"]), date.fromisoformat(cierre["hasta"])
    rango = f"{d1:%d/%m} al {d2:%d/%m}"

    cuerpo = []
    ecom, sub_cat = seccion_ecom(base, P, cuerpo.append)
    tac = seccion_tactica(base, P, cuerpo.append, sub_cat)

    tot = {k: ecom[k] + tac[k] for k in ("con_iva", "sin_iva", "rent")}
    head = [f'<div style="font-family:Arial,Helvetica,sans-serif;color:#222;max-width:860px">'
            f'<h1 style="margin-bottom:4px;font-size:22px">Rentabilidad ECOM + Táctica — {rango}</h1>'
            f'<p style="color:#555;font-size:13px;margin-top:0">Período <code>{P}</code> · Cierre generado {cierre["generado_en"][:10]} '
            f'(origen ECOM: {cierre["ecom_origen"]}) · Consultado {date.today():%Y-%m-%d}. Excluye líneas marcadas como excluidas. '
            f"Rentabilidad % = rentabilidad $ / facturación sin IVA.</p>",
            "<h3>Resumen consolidado</h3>",
            table(["Negocio", "Fact. con IVA", "Fact. sin IVA", "Rentab. $", "Rentab. %"], [
                ["ECOM", m(ecom["con_iva"]), m(ecom["sin_iva"]), m(ecom["rent"]), pc(ratio(ecom["rent"], ecom["sin_iva"]))],
                ["Táctica", m(tac["con_iva"]), m(tac["sin_iva"]), m(tac["rent"]), pc(ratio(tac["rent"], tac["sin_iva"]))],
                ["<b>Total</b>", f'<b>{m(tot["con_iva"])}</b>', f'<b>{m(tot["sin_iva"])}</b>', f'<b>{m(tot["rent"])}</b>',
                 f'<b>{pc(ratio(tot["rent"], tot["sin_iva"]))}</b>']], {1, 2, 3, 4})]
    pie = ['<p style="font-size:11px;color:#888;margin-top:24px">Generado automáticamente con Claude Code a partir de los endpoints '
           f"/rentabilidad/* de {base.split('//')[-1]}.</p></div>"]
    with open(args.html, "w") as f:
        f.write("".join(head + cuerpo + pie))

    txt = (f"Rentabilidad ECOM + Táctica — {rango} (período {P})\n\n"
           f"ECOM: fact. sin IVA {m(ecom['sin_iva'])}, rentabilidad {m(ecom['rent'])} ({pc(ratio(ecom['rent'], ecom['sin_iva']))}).\n"
           f"Táctica: fact. sin IVA {m(tac['sin_iva'])}, rentabilidad {m(tac['rent'])} ({pc(ratio(tac['rent'], tac['sin_iva']))}).\n"
           f"Total: fact. sin IVA {m(tot['sin_iva'])}, rentabilidad {m(tot['rent'])} ({pc(ratio(tot['rent'], tot['sin_iva']))}).\n\n"
           "El informe completo, con tablas por canal, SKU, categoría, PM y alertas, está en la versión HTML de este mail.\n")
    with open(args.txt, "w") as f:
        f.write(txt)
    with open(args.meta, "w") as f:
        json.dump({"periodo": P, "asunto": f"Rentabilidad ECOM + Táctica — {rango}"}, f, ensure_ascii=False)
    print(txt)


if __name__ == "__main__":
    main()
