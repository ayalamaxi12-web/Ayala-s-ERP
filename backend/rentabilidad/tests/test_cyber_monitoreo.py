"""Monitoreo del Cyber: precio cobrado vs el del Cyber, margen, ritmo, stock, alertas en formato Maca y candidatas (datos sintéticos, sin red ni base)."""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import cyber_monitoreo as cm

INI, FIN, DIA = date(2026, 11, 2), date(2026, 11, 12), date(2026, 11, 3)


def v(sku="A", mla="MLA1", cuenta="IT", u=1, final=10000.0, sin_iva=8264.46, rent=1000.0, costo=4000.0, fecha=DIA, pm="Veronica"):
    return {"fecha": fecha, "sku": sku, "sku_orig": sku, "cuenta": cuenta, "mla": mla, "unidades": u, "precio_final": final, "precio_sin_iva": sin_iva, "rentabilidad": rent, "costo": costo, "pm": pm}


def fila(mla="MLA1", cuenta="IT", precio=10000, margen=12.0, grupo="medio", estado="ok"):
    return {"SKU": "A", "Cuenta": cuenta, "MLA": mla, "Grupo": grupo, "Precio_Cyber": precio, "Margen_3_cuotas_pct": margen, "Estado": estado}


def correr(lista, ventas, base=None, stock=None, previas_extra=None):
    return cm.analizar_dia(DIA, INI, FIN, lista, [x for x in ventas if x["fecha"] == DIA], ventas, base or {}, stock)


def test_coincide_el_precio_y_no_hay_alerta():
    r = correr([fila()], [v()])
    f = r["filas"][0]
    assert f["coincide"] and f["prioridad"] == 0 and not r["alertas"] and f["precio_cobrado"] == 10000.0


def test_precio_cobrado_distinto_al_del_cyber_es_prioridad_1_en_formato_maca():
    r = correr([fila(precio=10000)], [v(final=11000.0, u=1)])
    a = r["alertas"][0]
    assert a["Prioridad"] == 1 and a["Canal"] == "ML Cyber" and a["Se_Vende"] == 11000.0 and a["Deberia"] == 10000
    assert [k for k in a if not k.startswith("_")] == cm.COLS_ALERTA and a["Link"] == "https://articulo.mercadolibre.com.ar/MLA-1"


def test_el_precio_cobrado_es_por_unidad():
    r = correr([fila(precio=10000)], [v(u=3, final=30000.0)])
    assert r["filas"][0]["precio_cobrado"] == 10000.0 and r["filas"][0]["coincide"]


def test_margen_bajo_el_piso_del_grupo_es_prioridad_1_y_poco_menos_que_lo_proyectado_es_2():
    bajo = correr([fila(grupo="rey", margen=25.0)], [v(rent=500.0)])           # 500/8264 = 6 %
    assert bajo["alertas"][0]["Prioridad"] == 1 and "bajo el piso" in bajo["alertas"][0]["_motivo"]
    medio = correr([fila(grupo="liquidar", margen=20.0)], [v(rent=1400.0)])    # 16,9 % contra 20 %
    assert medio["alertas"][0]["Prioridad"] == 2
    assert not correr([fila(grupo="liquidar", margen=17.0)], [v(rent=1400.0)])["alertas"]


def test_stock_y_ritmo():
    r = correr([fila()], [v(u=5)], base={("MLA", "MLA1"): 20.0}, stock=lambda sku: (4, 0))
    f = r["filas"][0]
    assert f["ratio_vs_historico"] == 0.25 and f["dias_stock"] == round(4 / (5 / 2), 1) and f["prioridad"] == 1
    assert any("días de stock" in m for m in f["motivos"]) and any("ritmo histórico" in m for m in f["motivos"])


def test_ordenes_sin_costo_no_entran_al_margen_pero_suman_facturacion():
    r = correr([fila()], [v(rent=None, costo=0.0), v(rent=1000.0)])
    f = r["filas"][0]
    assert f["unidades"] == 2 and f["sin_costo"] == 1 and f["facturacion"] == 20000.0 and f["margen_real"] == round(1000 / 8264.46 * 100, 2)


def test_no_participa_no_esta_en_la_lista_y_las_que_venden_fuera_son_candidatas():
    r = correr([fila(mla="MLA1"), fila(mla="MLA9", estado="no_participa")], [v(mla="MLA9", u=3, sku="B"), v(mla="MLA7", u=1, sku="C")])
    assert [c["mla"] for c in r["candidatas"]] == ["MLA9"] and r["candidatas"][0]["unidades"] == 3        # MLA7 con 1 unidad no llega al mínimo
    assert r["totales"]["publicaciones_en_lista"] == 1


def test_acumulado_y_dia_del_cyber_y_texto_del_mail():
    ayer = date(2026, 11, 2)
    r = correr([fila()], [v(fecha=ayer, u=2, final=20000.0), v()])
    assert r["dia_del_cyber"] == 2 and r["dias_totales"] == 11 and r["totales"]["acumulado_facturacion"] == 30000.0 and r["totales"]["facturacion"] == 10000.0
    asunto, texto = cm.texto_mail(r)
    assert "día 2/11" in asunto and "Acumulado del Cyber" in texto


class WsFalsa:
    def __init__(self, filas):
        self.filas = [list(x) for x in filas]

    def row_values(self, n):
        return self.filas[n - 1]

    def get_all_values(self):
        return self.filas

    def append_rows(self, nuevas, value_input_option=None):
        self.filas += [list(x) for x in nuevas]


class SsFalso:
    def __init__(self, ws):
        self.ws = ws

    def worksheet(self, t):
        return self.ws


class GcFalso:
    def __init__(self, ws):
        self.ss = SsFalso(ws)

    def open_by_key(self, k):
        assert k == cm.HISTORIAL_AUTOMATIZACIONES_ID
        return self.ss


def test_publicar_en_maca_agrega_sin_duplicar_ni_tocar_lo_existente():
    previa = ["2026-10-02", "X", "Matias", "ML", 1, 2, 3, 4, 1, "https://l"]
    ws = WsFalsa([cm.COLS_ALERTA, previa])
    r = correr([fila(precio=10000)], [v(final=11000.0)])
    assert cm.publicar_alertas_maca(GcFalso(ws), r["alertas"]) == {"agregadas": 1, "recibidas": 1}
    assert cm.publicar_alertas_maca(GcFalso(ws), r["alertas"])["agregadas"] == 0        # repetir el día no duplica
    assert len(ws.filas) == 3 and ws.filas[1] == previa and ws.filas[2][3] == "ML Cyber"


def test_si_cambian_los_encabezados_de_maca_no_escribe():
    import pytest
    ws = WsFalsa([["Fecha", "Otra"], []])
    with pytest.raises(ValueError):
        cm.publicar_alertas_maca(GcFalso(ws), [{"x": 1}])
    assert len(ws.filas) == 2
