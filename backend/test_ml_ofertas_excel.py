"""Carga de ofertas por Excel: lectura/validación, análisis (solo lectura) y aplicación con tachado y final exactos."""
import io
from decimal import Decimal

import pytest
from openpyxl import Workbook

import ml_ofertas_excel as mx
from ml_ofertas import MLOfertasClient, MLOfertasEscritura

TOKEN = lambda cuenta: "FAKE"


def _xlsx(filas, encabezado=("SKU", "MLA", "Precio tachado", "Precio final")):
    wb = Workbook()
    ws = wb.active
    ws.append(list(encabezado))
    for f in filas:
        ws.append(list(f))
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


# ── lectura ──

def test_lee_las_columnas_por_encabezado_aunque_vengan_en_otro_orden():
    r = mx.leer_excel(_xlsx([("MLA123456789", 15000, "A-1", 20000)], encabezado=("MLA", "Precio final", "SKU", "Precio tachado")))
    f = r["filas"][0]
    assert (f["sku"], f["mla"], f["tachado"], f["final"]) == ("A-1", "MLA123456789", 20000.0, 15000.0)


def test_lectura_mapea_por_encabezado_y_normaliza_mla_y_precios():
    r = mx.leer_excel(_xlsx([("A-1", "mla-123456789", "20.000,50", "$ 15.000")]))
    f = r["filas"][0]
    assert (f["sku"], f["mla"], f["tachado"], f["final"]) == ("A-1", "MLA123456789", 20000.5, 15000.0)
    assert f["bloqueos"] == [] and f["fila"] == 2


def test_falta_una_columna_es_un_error_de_formato():
    r = mx.leer_excel(_xlsx([("A", "MLA123456", 10)], encabezado=("SKU", "MLA", "Precio tachado")))
    assert r["filas"] == [] and "precio final" in r["errores"][0]


def test_bloqueos_de_formato_precio_y_descuento():
    r = mx.leer_excel(_xlsx([
        ("A", "XYZ", 100, 50),                       # MLA inválido
        ("B", "MLA111111111", 100, 100),             # sin oferta
        ("C", "MLA222222222", 100, 95),              # 5 % de descuento: menos del 10 %
        ("D", "MLA333333333", 100, 10),              # 90 %: más del 80 %
        ("E", "MLA444444444", 100, 70),              # ok
        ("F", "MLA444444444", 100, 70),              # repetido
        ("G", "MLA555555555", None, 70),             # falta tachado
    ]))
    b = [f["bloqueos"] for f in r["filas"]]
    assert "no es válido" in b[0][0]
    assert "menor al tachado" in b[1][0]
    assert "10" in b[2][0] and "80" in b[2][0]
    assert "90.0 %" in b[3][0]
    assert b[4] == []
    assert "repetido" in b[5][0] and "fila 6" in b[5][0]
    assert "tachado" in b[6][0]


def test_archivo_que_no_es_excel_y_excel_vacio():
    assert "No se pudo leer" in mx.leer_excel(b"hola")["errores"][0]
    assert "No hay filas" in mx.leer_excel(_xlsx([]))["errores"][0]


# ── análisis ──

class _MLFalso(MLOfertasClient):
    def __init__(self, detalles, promos, campanas):
        super().__init__(get_fn=None, token_fn=TOKEN)
        self._d, self._p, self._c = detalles, promos, campanas

    def detalle_items_ofertas(self, item_ids, cuenta, progreso_cb=None):
        return [self._d[i] for i in item_ids if i in self._d]

    def promociones_item(self, item_id, cuenta):
        if item_id == "MLA9":
            raise RuntimeError("503")
        return self._p.get(item_id, [])

    def promociones_seller(self, cuenta):
        return self._c


def _fila(n, sku, mla, t, f):
    return {"fila": n, "sku": sku, "mla": mla, "tachado": t, "final": f, "bloqueos": [], "avisos": []}


def _escenario():
    det = {
        "MLA1": {"id": "MLA1", "title": "Uno", "price": 20000, "seller_custom_field": "SKU-1", "status": "active", "available_quantity": 5},
        "MLA2": {"id": "MLA2", "title": "Dos", "price": 20000, "seller_custom_field": "OTRO", "status": "paused", "sub_status": ["x"], "available_quantity": 0},
        "MLA3": {"id": "MLA3", "title": "Tres", "price": 20000, "seller_custom_field": "SKU-3", "status": "active", "available_quantity": 5},
        "MLA9": {"id": "MLA9", "title": "Nueve", "price": 20000, "seller_custom_field": "SKU-9", "status": "active", "available_quantity": 5},
    }
    promos = {
        "MLA1": [{"id": "C1", "type": "SELLER_CAMPAIGN", "status": "candidate", "min_discounted_price": 12000, "max_discounted_price": 16000},
                 {"id": "C2", "type": "SELLER_CAMPAIGN", "status": "candidate"}],
        "MLA2": [{"id": "C1", "type": "SELLER_CAMPAIGN", "status": "candidate"}],
        "MLA3": [{"id": "C2", "type": "SELLER_CAMPAIGN", "status": "started"}, {"id": "L1", "type": "LIGHTNING", "status": "candidate"}],
    }
    camp = [{"id": "C1", "type": "SELLER_CAMPAIGN", "name": "Oferta Tradicional Oct", "status": "started"},
            {"id": "C2", "type": "SELLER_CAMPAIGN", "name": "Toners", "status": "pending"},
            {"id": "C3", "type": "SELLER_CAMPAIGN", "name": "Vacía", "status": "started"},
            {"id": "L1", "type": "LIGHTNING", "name": "Relámpago", "status": "started"}]
    return _MLFalso(det, promos, camp)


def test_analisis_cuenta_cuantos_pueden_participar_por_campana_y_da_las_alertas():
    filas = [_fila(2, "SKU-1", "MLA1", 20000, 15000), _fila(3, "SKU-2", "MLA2", 20000, 15000),
             _fila(4, "SKU-3", "MLA3", 20000, 15000), _fila(5, "X", "MLA77", 20000, 15000), _fila(6, "SKU-9", "MLA9", 20000, 15000)]
    r = mx.analizar(_escenario(), "IT", filas)
    por_id = {c["id"]: c for c in r["campanas"]}
    assert set(por_id) == {"C1", "C2", "C3"}                       # solo campañas propias
    assert por_id["C1"]["pueden"] == 2 and por_id["C1"]["mlas"] == ["MLA1", "MLA2"]
    assert por_id["C2"]["pueden"] == 2 and por_id["C3"]["pueden"] == 0
    assert r["campanas"][-1]["id"] == "C3"                         # las que más sirven, primero
    f = {x["mla"]: x for x in r["filas"]}
    assert "no existe en la cuenta IT" in f["MLA77"]["bloqueos"][0]
    assert any("no coincide" in a for a in f["MLA2"]["avisos"]) and any("paused" in a for a in f["MLA2"]["avisos"]) and any("stock" in a for a in f["MLA2"]["avisos"])
    assert any("No se pudieron leer sus promociones" in a for a in f["MLA9"]["avisos"])
    assert r["total"] == 5 and r["sin_bloqueo"] == 4


class _Costo:
    def obtener(self, sku): return Decimal("1") if sku == "SKU-1" else None


class _Iva:
    def factor(self, sku): return Decimal("1.21") if sku == "SKU-1" else None


def test_el_margen_solo_avisa_nunca_bloquea():
    filas = [_fila(2, "SKU-1", "MLA1", 20000, 15000), _fila(3, "SKU-3", "MLA3", 20000, 15000)]
    r = mx.analizar(_escenario(), "IT", filas, _Costo(), _Iva(), Decimal("1000"))   # costo 1 USD × 1000 = $1.000: gana
    f = {x["mla"]: x for x in r["filas"]}
    assert f["MLA1"]["margen_pct"] is not None and f["MLA1"]["bloqueos"] == []
    assert any("falta el costo" in a for a in f["MLA3"]["avisos"])
    caro = mx.analizar(_escenario(), "IT", [_fila(2, "SKU-1", "MLA1", 20000, 15000)], _Costo(), _Iva(), Decimal("20000"))  # costo 20.000: pierde
    x = caro["filas"][0]
    assert x["margen_pct"] < 0 and any("se pierde plata" in a for a in x["avisos"]) and x["bloqueos"] == []


# ── aplicación ──

def _put(url, headers, body):
    _put.calls.append(body)
    return {"id": "x", "price": body["price"]}


def _post(url, headers, body):
    _post.calls.append(body)
    if body.get("fallar"):
        pass
    return _post.responder(url, headers, body)


def _ml_escritura(responder):
    _put.calls, _post.calls = [], []
    _post.responder = responder

    def get(url, params, headers):
        if url.endswith("/seller-promotions/items/MLA1") or "/seller-promotions/items/" in url:
            return []
        if "/items/" in url:
            return {"id": "x", "price": 20000.0, "tags": ["installments_3x"]}     # tag de cuotas: el modo exacto NO debe ajustar
        raise AssertionError(url)

    return MLOfertasEscritura(get_fn=get, token_fn=TOKEN, put_fn=_put, post_fn=_post)


def _aptas(*mlas, promo="C1", **extra):
    out = []
    for i, m in enumerate(mlas, start=2):
        f = _fila(i, f"S{i}", m, 20000, 15000)
        f["candidatas"] = [{"id": promo, "status": "candidate", "min": None, "max": None}]
        f.update(extra)
        out.append(f)
    return out


def test_aplica_el_tachado_y_el_final_exactos_sin_ajustar_cuotas_ni_envio():
    ml = _ml_escritura(lambda u, h, b: {"price": b["deal_price"], "original_price": 20000.0})
    r = mx.aplicar(ml, "IT", "C1", _aptas("MLA1"))
    assert r["resultados"][0]["estado"] == "ok"
    assert _put.calls == [{"price": 20000.0}]                               # tachado tal cual
    assert _post.calls[0]["deal_price"] == 15000.0 and _post.calls[0]["promotion_id"] == "C1"   # final tal cual


def test_las_que_no_pueden_quedan_pendientes_y_el_resto_sigue():
    ml = _ml_escritura(lambda u, h, b: {"price": b["deal_price"], "original_price": 20000.0})
    filas = _aptas("MLA1", "MLA2", "MLA3")
    filas[1]["candidatas"] = []                                              # MLA2 no puede en C1
    filas[2]["candidatas"] = [{"id": "C1", "status": "candidate", "min": 16000, "max": None}]   # final 15.000 < mínimo 16.000
    r = mx.aplicar(ml, "IT", "C1", filas)["resultados"]
    assert [x["estado"] for x in r] == ["ok", "pendiente", "pendiente"]
    assert "no puede participar" in r[1]["mensaje"] and "mínimo" in r[2]["mensaje"]
    assert len(_post.calls) == 1


def test_un_rechazo_de_ml_se_informa_por_fila_y_no_corta_el_lote():
    respuestas = iter([{"message": "rechazado por X"}, {"price": 15000.0, "original_price": 20000.0}])
    ml = _ml_escritura(lambda u, h, b: next(respuestas))
    r = mx.aplicar(ml, "IT", "C1", _aptas("MLA1", "MLA2"))["resultados"]
    assert r[0]["estado"] == "error" and "rechazado por X" in r[0]["mensaje"]
    assert r[1]["estado"] == "ok"


def test_verificacion_de_seguridad_corta_el_lote():
    ml = _ml_escritura(lambda u, h, b: {"message": "security challenge: facial verification required"})
    r = mx.aplicar(ml, "IT", "C1", _aptas("MLA1", "MLA2"))
    assert r["resultados"][0]["estado"] == "error" and r["resultados"][1]["estado"] == "pendiente"
    assert r["cortado_por_verificacion"] is True and len(_post.calls) == 1


def test_el_historial_se_anota_una_vez_con_las_aplicadas_y_origen_excel():
    ml = _ml_escritura(lambda u, h, b: {"price": 15000.0, "original_price": 20000.0})
    anotado = []
    r = mx.aplicar(ml, "IT", "C1", _aptas("MLA1", "MLA2"), operador="Natalia", historial_cb=anotado.append)
    assert len(anotado) == 1 and len(anotado[0]) == 2
    assert anotado[0][0]["Origen"] == "Excel (lote)" and anotado[0][0]["Operador"] == "Natalia" and anotado[0][0]["Item ID"] == "MLA1"
    assert "aviso_historial" not in r


def test_si_falla_el_historial_el_resultado_real_igual_se_devuelve():
    ml = _ml_escritura(lambda u, h, b: {"price": 15000.0, "original_price": 20000.0})

    def mal(_):
        raise RuntimeError("cuota de Sheets")
    r = mx.aplicar(ml, "IT", "C1", _aptas("MLA1"), historial_cb=mal)
    assert r["resultados"][0]["estado"] == "ok" and "cuota de Sheets" in r["aviso_historial"]


def test_filas_con_bloqueo_o_precio_roto_nunca_se_mandan_a_ml():
    ml = _ml_escritura(lambda u, h, b: pytest.fail("no debía llamar a ML"))
    a, b = _aptas("MLA1", "MLA2")
    a["bloqueos"] = ["no existe"]
    b["final"] = 30000                                                       # final mayor al tachado (cliente manipulado)
    r = mx.aplicar(ml, "IT", "C1", [a, b])["resultados"]
    assert [x["estado"] for x in r] == ["pendiente", "pendiente"] and not _put.calls


def test_el_modo_normal_de_la_campana_tradicional_no_cambia():
    """Sin `tachado_exacto` sigue siendo tachado = final / (1 − 25 %)."""
    from ml_ofertas import activar_en_campana_tradicional

    def get(url, params, headers):
        if "seller-promotions/users" in url:
            return {"results": [{"id": "C1", "type": "SELLER_CAMPAIGN", "status": "started", "name": "Oferta Tradicional Oct"}]}
        if "/seller-promotions/items/" in url:
            return []
        return {"id": "MLA1", "price": 13333.0}
    _put.calls, _post.calls = [], []
    _post.responder = lambda u, h, b: {"price": 10000.0, "original_price": 13333.0}
    ml = MLOfertasEscritura(get_fn=get, token_fn=TOKEN, put_fn=_put, post_fn=_post)
    assert activar_en_campana_tradicional(ml, "IT", "MLA1", Decimal(10000))["precio_tachado_pedido"] == 13333.0
