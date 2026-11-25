"""Verificar Ecom BR (etapa 1, solo lectura): base de stock, lectura y simulación del Excel."""
import io

import pytest
from openpyxl import Workbook, load_workbook

import ecom_br_stock as eb

DEP = "Good Storage Jaguaré"


def _prod(pid, sku, variantes, title="Prod"):
    return {"id": pid, "sku": sku, "title": title, "active": True, "variants": variantes}


def _var(vid, sku, deps, commited=0, qty=0):
    return {"id": vid, "sku": sku, "qty": qty, "cost": 10, "availableQty": 0, "commited": commited, "variantPrices": [],
            "variantWarehouses": [{"warehouse_title": t, "warehouse_qty": q} for t, q in deps.items()]}


PRODUCTOS = [
    _prod("P1", "PADRE1", [_var("V1", "SKU-A", {DEP: 50, "Full": 7}, commited=10), _var("V2", "SKU-B", {DEP: 0}, commited=0)], "Padre uno"),
    _prod("P2", "PADRE2", [_var("V3", "sku-c", {"Full": 3}, commited=5), _var("V4", "DUP", {"Full": 1}), _var("V5", "DUP", {"Full": 2})]),
]
CAT = {**eb.normalizar(PRODUCTOS), "obtenido_en": 0.0}


class _Cliente:
    def __init__(self, paginas):
        self.paginas, self.llamadas = paginas, []

    def graphql(self, query, variables=None):
        assert "mutation" not in query.lower()              # la etapa 1 NO escribe nada
        self.llamadas.append(variables["page"])
        return {"products": {"find": {"pageInfo": {}, "data": self.paginas.get(variables["page"], [])}}}


def test_el_catalogo_pagina_hasta_que_una_pagina_no_trae_ids_nuevos():
    c = _Cliente({1: [PRODUCTOS[0]], 2: [PRODUCTOS[1]], 3: [PRODUCTOS[1]]})       # la 3 repite: se corta ahí
    r = eb.bajar_productos(c)
    assert [p["id"] for p in r] == ["P1", "P2"] and c.llamadas == [1, 2, 3]
    with pytest.raises(eb.EcomBRError, match="vacío"):
        eb.bajar_productos(_Cliente({}))


def test_la_consulta_pide_el_filtro_de_activos_y_los_campos_acordados():
    for t in ('filters: [{filter: "status", values: ["1"]}]', "commited", "availableQty", "variantWarehouses { warehouse_title warehouse_qty }", "variantPrices { title price }"):
        assert t in eb.QUERY_CATALOGO


def test_reintenta_una_pagina_que_falla_y_dice_cual():
    n = {"i": 0}

    class _Roto:
        def graphql(self, q, v=None):
            n["i"] += 1
            raise RuntimeError("500")
    with pytest.raises(eb.EcomBRError, match="página 1"):
        eb.bajar_productos(_Roto(), dormir=lambda s: None)
    assert n["i"] == eb.REINTENTOS_PAGINA


def test_la_base_es_un_excel_prolijo_con_una_fila_por_variante_y_deposito():
    wb = load_workbook(io.BytesIO(eb.base_xlsx(CAT, DEP)))
    assert wb.sheetnames == ["Base Stock", "Instrucciones"]                # pestañas con espacios en el nombre
    ws = wb["Base Stock"]
    assert [c.value for c in ws[1]] == ["SKU variante", "SKU producto", "Título", "Depósito", "Stock depósito", "Reservado", "Disponible", "Cantidad nueva"]
    assert ws.sheet_view.showGridLines is False and ws.freeze_panes == "A2"
    filas = [[c.value for c in r] for r in ws.iter_rows(min_row=2)]
    assert len(filas) == 6
    f_a = next(f for f in filas if f[0] == "SKU-A" and f[3] == DEP)
    assert f_a[4:] == [50, 10, 40, None]                                     # Jaguaré: disponible = stock − reservado
    f_a_full = next(f for f in filas if f[0] == "SKU-A" and f[3] == "Full")
    assert f_a_full[4:] == [7, 10, 7, None]                                  # otros depósitos: el valor tal cual


@pytest.mark.parametrize("v,esperado", [
    (None, ("vacia", None)), ("", ("vacia", None)), ("  ", ("vacia", None)), (0, ("ok", 0)), ("0", ("ok", 0)), (12, ("ok", 12)), (12.0, ("ok", 12)), ("12", ("ok", 12)), ("12.0", ("ok", 12)),
    (12.5, ("invalida", None)), ("12,5", ("invalida", None)), ("abc", ("invalida", None)), (-3, ("invalida", None)), ("-3", ("invalida", None)), (True, ("invalida", None)),
    ("1.000", ("ambigua", None)), ("1,000", ("ambigua", None)), ("12.345.678", ("ambigua", None)),
])
def test_cantidades(v, esperado):
    estado, valor, _ = eb.parsear_cantidad(v)
    assert (estado, valor) == esperado


def test_el_sku_se_lee_como_texto_sin_el_punto_cero_de_excel():
    assert eb._sku_texto(123456.0) == "123456" and eb._sku_texto("123456.0") == "123456" and eb._sku_texto(" ab​c ") == "abc" and eb._sku_texto("1.5") == "1.5" and eb._sku_texto(None) == ""


def _xlsx(filas, cab=("SKU variante", "Depósito", "Cantidad nueva"), hoja="Base Stock"):
    wb = Workbook()
    ws = wb.active
    ws.title = hoja
    ws.append(list(cab))
    for f in filas:
        ws.append(list(f))
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def test_lee_el_excel_por_encabezado_y_salta_filas_vacias():
    r = eb.leer_excel(_xlsx([("SKU-A", DEP, 5), (None, None, None), (123.0, "Full", "7")]))
    assert [(f["fila"], f["sku"], f["cantidad"]) for f in r["filas"]] == [(2, "SKU-A", 5), (4, "123", 7)]
    assert "Faltan columnas" in eb.leer_excel(_xlsx([("a", 1)], cab=("SKU variante", "Otra")))["errores"][0]
    assert "No se pudo leer" in eb.leer_excel(b"no es un excel")["errores"][0]


def _sim(filas):
    return eb.simular([{"fila": i + 2, "sku": s, "deposito": d, **dict(zip(("cantidad_estado", "cantidad", "motivo"), eb.parsear_cantidad(q)))} for i, (s, d, q) in enumerate(filas)], CAT, DEP)


def test_en_el_deposito_con_disponible_se_escribe_cantidad_mas_reservado_y_en_los_otros_tal_cual():
    r = _sim([("SKU-A", DEP, 30), ("SKU-A", "Full", 20)])
    a, b = r["filas"]
    assert a["estado"] == "cambia" and a["stock_actual"] == 50 and a["reservado"] == 10 and a["disponible_actual"] == 40 and a["disponible_pedido"] == 30 and a["diferencia"] == -10
    assert a["stock_a_escribir"] == 40                                      # 30 disponibles + 10 reservados
    assert b["stock_actual"] == 7 and b["disponible_actual"] == 7 and b["disponible_pedido"] == 20 and b["diferencia"] == 13 and b["stock_a_escribir"] == 20


def test_cantidad_vacia_no_se_toca_y_cero_pone_en_cero():
    r = _sim([("SKU-A", DEP, None), ("SKU-A", "Full", 0), ("SKU-B", DEP, 0)])
    assert r["resumen"]["omitidas_sin_cantidad"] == 1 and len(r["filas"]) == 2
    assert r["filas"][0]["stock_a_escribir"] == 0 and r["filas"][0]["estado"] == "cambia"
    assert r["filas"][1]["estado"] == "sin_cambio"                          # SKU-B ya tiene 0 y 0 reservado


def test_validaciones_de_sku_deposito_y_cantidad():
    r = _sim([("SKU-X", DEP, 1), ("SKU-C", "Full", 1), ("SKU-C".lower(), "Full", 1), ("DUP", "Full", 1), ("SKU-A", "Depósito Fantasma", 1), ("SKU-A", DEP, "1.000"), ("SKU-A", DEP, "-2"), ("", DEP, 1)])
    por = {x["fila"]: x for x in r["filas"]}
    assert por[2]["codigo"] == "sku_inexistente" and por[2]["sugerencia"] is None
    assert por[3]["codigo"] == "sku_inexistente" and por[3]["sugerencia"] == "sku-c" and "mayúsculas" in por[3]["mensaje"]       # 'SKU-C' ≠ 'sku-c'
    assert por[4]["estado"] == "cambia"                                      # 'sku-c' escrito igual que el catálogo
    assert por[5]["codigo"] == "sku_ambiguo"
    assert por[6]["codigo"] == "deposito_inexistente"
    assert por[7]["codigo"] == "cantidad_ambigua" and por[8]["codigo"] == "cantidad_invalida" and por[9]["codigo"] == "sin_sku"
    assert r["resumen"]["con_error"] == 7


def test_duplicados_con_cantidades_distintas_se_rechazan_y_con_igual_cantidad_se_cuentan_una_vez():
    r = _sim([("SKU-A", DEP, 5), ("SKU-A", DEP, 6), ("SKU-A", "Full", 9), ("SKU-A", "Full", 9)])
    por = {x["fila"]: x for x in r["filas"]}
    assert por[2]["codigo"] == "duplicado" and por[3]["codigo"] == "duplicado"
    assert por[4]["estado"] == "cambia" and 5 not in por and r["resumen"]["omitidas_sin_cantidad"] == 1


def test_avisa_si_el_stock_nuevo_queda_menor_al_reservado_y_si_el_deposito_difiere_en_mayusculas():
    r = _sim([("sku-c", "full", 2)])                      # Full no es el depósito con disponible: se escribe 2, reservado 5
    x = r["filas"][0]
    assert x["estado"] == "cambia" and x["deposito"] == "Full" and any("menor al reservado" in a for a in x["avisos"]) and any("se toma «Full»" in a for a in x["avisos"])
    assert r["resumen"]["con_aviso"] == 1


def test_el_deposito_con_disponible_es_configuracion_no_esta_fijo():
    r = eb.simular([{"fila": 2, "sku": "SKU-A", "deposito": "Full", "cantidad_estado": "ok", "cantidad": 3, "motivo": None}], CAT, "Full")        # ahora «Full» es el depósito con disponible
    assert r["filas"][0]["stock_a_escribir"] == 3 + 10 and r["filas"][0]["disponible_actual"] == 7 - 10


def test_el_job_de_simulacion_no_escribe_y_deja_el_resultado(monkeypatch):
    eb._catalogo = None
    c = _Cliente({1: PRODUCTOS})
    monkeypatch.setattr(eb, "deposito_disponible", lambda sesion_fn=None: DEP)
    eb.iniciar_simulacion("sim1", _xlsx([("SKU-A", DEP, 30), ("SKU-A", "Full", None)]), cliente=c)
    j = eb.estado_job("sim1")
    assert j["status"] == "done" and j["result"]["resumen"]["a_cambiar"] == 1 and j["result"]["resumen"]["omitidas_sin_cantidad"] == 1 and "No se escribió nada" in j["log"][-1]


def test_el_job_de_base_deja_el_excel_para_descargar(monkeypatch):
    eb._catalogo = None
    monkeypatch.setattr(eb, "deposito_disponible", lambda sesion_fn=None: DEP)
    eb.iniciar_base("base1", cliente=_Cliente({1: PRODUCTOS}))
    assert eb.estado_job("base1")["status"] == "done" and eb.estado_job("base1")["result"]["filas"] == 6
    assert load_workbook(io.BytesIO(eb.archivo_base("base1")))["Base Stock"].max_row == 7 and eb.archivo_base("nada") is None


def test_endpoints(monkeypatch):
    from fastapi.testclient import TestClient
    import main
    monkeypatch.setenv("ERP_API_KEY", "k")
    monkeypatch.delenv("ECOM_BR_EMAIL", raising=False)
    monkeypatch.delenv("ECOM_BR_PASSWORD", raising=False)
    monkeypatch.setattr(eb, "deposito_disponible", lambda sesion_fn=None: DEP)
    c, h = TestClient(main.app), {"X-ERP-Key": "k"}
    e = c.get("/ecom-br/estado").json()
    assert e["configurado"] is False and e["escritura_habilitada"] is False and e["etapa"] == 1 and e["deposito_disponible"] == DEP
    assert c.post("/ecom-br/base/run", headers=h).status_code == 409                          # sin credenciales de Brasil
    assert c.post("/ecom-br/excel/simular", headers=h, files={"archivo": ("a.xlsx", _xlsx([("SKU-A", DEP, 1)]))}).status_code == 409
    assert c.post("/ecom-br/base/run").status_code == 401                                      # escribe en memoria / gasta recursos: pide la clave
    assert c.post("/ecom-br/base/descargar", headers=h, json={"job_id": "no"}).status_code == 404
    assert c.get("/ecom-br/status/x").json() == {"status": "not_found"}
    assert not any(r.path.startswith("/ecom-br") and "aplicar" in r.path for r in main.app.routes)        # no existe ningún endpoint de escritura
