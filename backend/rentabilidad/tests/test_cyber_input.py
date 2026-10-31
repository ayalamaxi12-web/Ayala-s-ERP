"""Insumo del Cyber 2026: cuentas, clasificación, una fila por SKU, stock de Ecom (propio vs Full), orden, resumen y CSV."""
import csv
import io
from datetime import date
from decimal import Decimal

import cyber_input as ci
from rentabilidad import motor_precios as m
from rentabilidad.models import VentaEcom
from rentabilidad.pricing_pm import DatosSku

from .conftest import d

HOY = date(2026, 10, 31)


def test_la_cuenta_sale_del_usuario_de_integracion():
    assert ci.cuenta_de_usuario("GLOBALELECTRONICSGROUP") == "IT" and ci.cuenta_de_usuario("GLOBALELECTRONICSARG") == "MT"
    assert ci.cuenta_de_usuario("Global WEB") is None and ci.cuenta_de_usuario(None) is None
    assert ci.CUENTA_NOMBRE == {"IT": "GROUP", "MT": "ARG"}


def test_clasificar_liquidar_manda_el_rey_es_la_clase_y_el_precio_no_lo_define():
    assert ci.clasificar(True, True) == "liquidar" and ci.clasificar(False, True) == "rey" and ci.clasificar(False, False) == "medio"


def test_una_fila_por_sku_la_publicacion_que_mas_vendio_y_si_empatan_las_dos():
    c = lambda sku, cuenta, mla, v: {"sku_norm": sku, "cuenta": cuenta, "mla_id": mla, "ventas_ult_90d_unid": v}
    r = ci.elegir_publicaciones([c("A", "IT", "MLA1", 5), c("A", "MT", "MLA2", 9), c("B", "IT", "MLA3", 0), c("B", "MT", "MLA4", 0), c("C", "IT", "MLA5", 1)])
    assert sorted(x["mla_id"] for x in r) == ["MLA2", "MLA3", "MLA4", "MLA5"]


def _fila(sku, grupo, costo, stock, origen="ecom"):
    return {"sku": sku, "titulo": "t", "cuenta": "GROUP", "mla_id": "MLA", "grupo": grupo, "costo": costo, "precio_actual": 1.0, "margen_actual_pct": 10.0,
            "stock_disponible": stock, "ventas_ytd_unid": 0, "ventas_ult_90d_unid": 0, "ticket_alto": "no", "link_rey": "", "link_media": "", "link_barato": "", "stock_origen": origen}


def test_orden_por_grupo_y_plata_en_stock_resumen_y_csv():
    filas = ci.ordenar([_fila("M1", "medio", 10, 5), _fila("R1", "rey", 100, 1), _fila("L1", "liquidar", 1, 3, "full"), _fila("M2", "medio", 10, 50), _fila("L2", "liquidar", 20, 20)])
    assert [f["sku"] for f in filas] == ["L2", "L1", "R1", "M2", "M1"]
    r = ci.resumen(filas)
    assert r["liquidar"] == {"skus": 2, "plata_en_stock": 403.0, "stock_solo_full": 1} and r["medio"]["plata_en_stock"] == 550.0 and r["total"]["skus"] == 5
    filas_csv = list(csv.reader(io.StringIO(ci.a_csv(filas))))
    assert filas_csv[0][:15] == ["sku", "titulo", "cuenta", "mla_id", "grupo", "costo", "precio_actual", "margen_actual_pct", "stock_disponible", "ventas_ytd_unid",
                                 "ventas_ult_90d_unid", "ticket_alto", "link_rey", "link_media", "link_barato"]
    assert filas_csv[1][0] == "L2" and len(filas_csv) == 6


class _Ecom:
    def __init__(self, productos):
        self.p = productos

    def warehouse_full_id(self):
        return "FULL"

    def _producto_por_sku(self, sku):
        return self.p.get(sku)


def _prod(**depositos):
    return {"variants": [{"sku": "x", "variantWarehouses": [{"warehouse_id": k, "warehouse_qty": v} for k, v in depositos.items()]}]}


def test_stock_propio_es_el_deposito_no_full_que_mas_tiene_y_full_aparte():
    e = _Ecom({"A": _prod(PITEC=40, GAONA=10, FULL=300), "B": _prod(PITEC=0, FULL=25), "C": _prod(PITEC=3, OUTLET=9)})
    assert ci.stock_de_ecom(e, "A") == (40, 300)                       # no suma depósitos: el que más tiene
    assert ci.stock_de_ecom(e, "B") == (0, 25)                         # solo en Full → el insumo lo marca stock_origen = full
    assert ci.stock_de_ecom(e, "C") == (9, 0)
    assert ci.stock_de_ecom(e, "NO-ESTA") == (None, None)


def test_stock_de_un_pack_o_combo_sale_de_sus_componentes():
    e = _Ecom({"A": _prod(PITEC=10), "B": _prod(PITEC=7)})
    assert ci.stock_de_ecom(e, "X2 A") == (5, 0)                       # 10 // 2
    assert ci.stock_de_ecom(e, "A B") == (7, 0)                        # el componente más escaso


def test_links_de_competidores_por_rol_solo_activos_y_competencia():
    filas = [["Referencia_ID", "SKU", "Tipo", "Link_Publicacion", "Activo", "Rol_Competidor"],
             ["1", "PLANCHA-SUB-GORRA", "Competencia", "https://a", "SI", "Rey"], ["2", "PLANCHA-SUB-GORRA", "Competencia", "https://b", "SI", "Media"],
             ["3", "PLANCHA-SUB-GORRA", "Competencia", "https://c", "NO", "Barato"], ["4", "PLANCHA-SUB-GORRA", "Propia", "https://d", "SI", "Barato"]]
    assert ci.links_de_competidores(filas) == {"PLANCHA-SUB-GORRA": {"Rey": "https://a", "Media": "https://b"}}


def test_ventas_por_sku_y_cuenta_ytd_90_dias_solo_ml_y_un_sku(db_session):
    def v(orden, dia, skus, usuario, unidades):
        return VentaEcom(periodo="2026-10-01_2026-10-31", numero_orden=orden, skus_vendidos=skus, fecha_creacion_venta=dia, costo_sin_iva=Decimal(1), comision_venta=Decimal(0),
                         costo_envio=Decimal(0), precio_final=Decimal(1), precio_sin_iva=Decimal(1), tc=Decimal(1500), usuario_integracion=usuario, unidades=unidades)
    db_session.add_all([v("1", date(2026, 10, 20), "SKU-A", "GLOBALELECTRONICSGROUP", 3), v("2", date(2026, 3, 1), "SKU-A", "GLOBALELECTRONICSGROUP", 5),
                        v("3", date(2026, 10, 20), "SKU-A", "GLOBALELECTRONICSARG", 2), v("4", date(2026, 10, 20), "SKU-A", "Global WEB", 9),
                        v("5", date(2026, 10, 20), "SKU-A,SKU-B", "GLOBALELECTRONICSGROUP", 7), v("6", date(2025, 12, 31), "SKU-A", "GLOBALELECTRONICSGROUP", 4)])
    db_session.flush()
    r = ci.ventas_por_sku_y_cuenta(db_session, HOY)
    assert r[("SKU-A", "IT")] == {"ytd": 8, "d90": 3} and r[("SKU-A", "MT")] == {"ytd": 2, "d90": 2} and len(r) == 2


class _ML:
    def items_activos(self, cuenta):
        return {"IT": ["MLA1", "MLA2"], "MT": ["MLA3"]}[cuenta]

    def _token(self, cuenta):
        return "t"

    def _get(self, url, params, headers):
        todos = {"MLA1": ("PLANCHA-SUB-5EN1", 200000), "MLA2": ("SKU-LIQ", 5000), "MLA3": ("SKU-LIQ", 5000)}
        return [{"body": {"id": i, "title": f"T {todos[i][0]}", "price": todos[i][1], "seller_custom_field": todos[i][0], "status": "active", "category_id": "C", "listing_type_id": "gold_special"}}
                for i in params["ids"].split(",")]


def test_generar_arma_filas_grupos_y_stock_origen(db_session, monkeypatch):
    import campanas_ml_comision
    monkeypatch.setattr(campanas_ml_comision, "comisiones", lambda items, **k: ({}, []))
    par = m.cargar_parametros(db_session, HOY)
    datos = lambda sku: DatosSku(d("10"), d("1.21"), None, None, None)
    ecom = _Ecom({"PLANCHA-SUB-5EN1": _prod(PITEC=0, FULL=80), "SKU-LIQ": _prod(PITEC=30, FULL=0)})
    alertas = {"PLANCHA-SUB-5EN1": {"clase": "REY", "alerta": "OK"}, "SKU-LIQ": {"clase": "REVENTAR", "alerta": "LIQUIDAR"}}
    r = ci.generar(_ML(), ecom, db_session, datos, d("1500"), par, HOY, alertas, {"PLANCHA-SUB-5EN1": {"Rey": "https://rival"}})
    por = {(f["sku"], f["cuenta"]): f for f in r["filas"]}
    rey = por[("PLANCHA-SUB-5EN1", "GROUP")]
    assert rey["grupo"] == "rey" and rey["stock_origen"] == "full" and rey["stock_disponible"] == 80 and rey["ticket_alto"] == "si" and rey["link_rey"] == "https://rival"
    liq = [f for f in r["filas"] if f["sku"] == "SKU-LIQ"]
    assert len(liq) == 2 and {f["cuenta"] for f in liq} == {"GROUP", "ARG"} and all(f["grupo"] == "liquidar" and f["ticket_alto"] == "no" for f in liq)   # empate: las dos cuentas
    assert [f["grupo"] for f in r["filas"]] == ["liquidar", "liquidar", "rey"] and r["resumen"]["rey"]["stock_solo_full"] == 1
    assert rey["costo"] == 15000.0 and rey["margen_actual_pct"] is not None and r["reglas"]["grupos"]["rey"]["piso_margen_pct"] == 20


def test_los_ids_salen_del_excel_de_la_campana_y_la_cuenta_de_cada_publicacion():
    leidos = {b"x1": {"campana": "Cyber GROUP", "filas": [{"ITEM_ID": "MLA1"}, {"ITEM_ID": "MLA2"}, {"ITEM_ID": ""}]},
              b"x2": {"campana": "Cyber ARG", "filas": [{"ITEM_ID": "MLA2"}, {"ITEM_ID": "MLA3"}, {"ITEM_ID": "MLA9"}]}}
    cuentas = {"MLA1": {"cuenta": "IT"}, "MLA2": {"cuenta": "IT"}, "MLA3": {"cuenta": "MT"}}
    por_cuenta, info = ci.ids_desde_excels([b"x1", b"x2"], leer_fn=lambda c: leidos[c], detectar_fn=lambda ids: (cuentas, []))
    assert por_cuenta == {"IT": ["MLA1", "MLA2"], "MT": ["MLA3"]}
    assert info["publicaciones_en_excel"] == 4 and info["sin_cuenta"] == 1 and info["campanas"] == ["Cyber GROUP", "Cyber ARG"]


def test_con_excel_solo_se_miran_las_publicaciones_de_la_campana(db_session, monkeypatch):
    import campanas_ml_comision
    monkeypatch.setattr(campanas_ml_comision, "comisiones", lambda items, **k: ({}, []))
    pedidas = []

    class ML(_ML):
        def items_activos(self, cuenta):
            raise AssertionError("con Excel no se barren todas las publicaciones activas")

        def _get(self, url, params, headers):
            pedidas.extend(params["ids"].split(","))
            return super()._get(url, params, headers)
    par = m.cargar_parametros(db_session, HOY)
    r = ci.generar(ML(), _Ecom({"PLANCHA-SUB-5EN1": _prod(PITEC=5)}), db_session, lambda sku: DatosSku(d("10"), d("1.21"), None, None, None), d("1500"), par, HOY, {}, {},
                   ids_por_cuenta={"IT": ["MLA1"], "MT": []})
    assert pedidas == ["MLA1"] and [f["mla_id"] for f in r["filas"]] == ["MLA1"] and r["conteos"]["origen"] == "Excel de la campaña"


def test_un_sku_con_muchas_publicaciones_de_una_cuenta_queda_en_una_sola_fila_la_que_mas_vendio():
    c = lambda mla, cuenta, v90, vm90, vmytd=0, sku="A": {"sku_norm": sku, "cuenta": cuenta, "mla_id": mla, "ventas_ult_90d_unid": v90, "ventas_mla_90d": vm90, "ventas_mla_ytd": vmytd}
    # 4 publicaciones del mismo SKU en la misma cuenta: queda la que más vendió ella misma (no las 4 por empatar a nivel SKU)
    r = ci.elegir_publicaciones([c("MLA10", "IT", 9, 1), c("MLA11", "IT", 9, 6), c("MLA12", "IT", 9, 6, 20), c("MLA13", "IT", 9, 0)])
    assert [x["mla_id"] for x in r] == ["MLA12"] and r[0]["publicaciones_del_sku"] == 4
    # sin ventas por publicación: desempata la de menor MLA (estable)
    r = ci.elegir_publicaciones([c("MLA9", "IT", 0, 0), c("MLA3", "IT", 0, 0)])
    assert [x["mla_id"] for x in r] == ["MLA3"]
    # entre cuentas: gana la que más vendió el SKU; si empatan, una por cuenta
    r = ci.elegir_publicaciones([c("MLA1", "IT", 5, 5), c("MLA2", "MT", 8, 8), c("MLA3", "IT", 5, 1)])
    assert [x["mla_id"] for x in r] == ["MLA2"]
    r = ci.elegir_publicaciones([c("MLA1", "IT", 4, 4), c("MLA2", "MT", 4, 4), c("MLA3", "IT", 4, 0)])
    assert sorted(x["mla_id"] for x in r) == ["MLA1", "MLA2"]


def test_las_ventas_tambien_se_cuentan_por_publicacion_mla(db_session):
    def v(orden, mla, unidades):
        return VentaEcom(periodo="2026-10-01_2026-10-31", numero_orden=orden, skus_vendidos="SKU-A", fecha_creacion_venta=date(2026, 10, 20), costo_sin_iva=Decimal(1),
                         comision_venta=Decimal(0), costo_envio=Decimal(0), precio_final=Decimal(1), precio_sin_iva=Decimal(1), tc=Decimal(1500),
                         usuario_integracion="GLOBALELECTRONICSGROUP", unidades=unidades, item_ml=mla)
    db_session.add_all([v("1", "MLA1", 3), v("2", "MLA2", 5), v("3", "MLA1", 1)])
    db_session.flush()
    r = ci.ventas_por_sku_y_cuenta(db_session, HOY)
    assert r[("MLA", "MLA1")] == {"ytd": 4, "d90": 4} and r[("MLA", "MLA2")]["d90"] == 5 and r[("SKU-A", "IT")]["d90"] == 9


def test_las_descartadas_dicen_por_que_quedaron_afuera(db_session, monkeypatch):
    import campanas_ml_comision
    monkeypatch.setattr(campanas_ml_comision, "comisiones", lambda items, **k: ({}, []))
    class ML2(_ML):
        def items_activos(self, cuenta):
            return {"IT": ["MLA1", "MLA2", "MLA4"], "MT": []}[cuenta]

        def _get(self, url, params, headers):
            datos = {"MLA1": ("A-OK", 100), "MLA2": ("SIN-ECOM", 100), "MLA4": ("SIN-STOCK", 100)}
            return [{"body": {"id": i, "title": f"T {i}", "price": datos[i][1], "seller_custom_field": datos[i][0], "status": "active", "category_id": "C", "listing_type_id": "g"}}
                    for i in params["ids"].split(",")]
    par = m.cargar_parametros(db_session, HOY)
    ecom = _Ecom({"A-OK": _prod(PITEC=5), "SIN-STOCK": _prod(PITEC=0, FULL=0)})
    datos = lambda sku: DatosSku(None if sku == "A-OK" else d("10"), d("1.21"), None, None, None)
    r = ci.generar(ML2(), ecom, db_session, datos, d("1500"), par, HOY, {}, {})
    motivos = {(x["sku"], x["motivo"][:12]) for x in r["descartadas"]}
    assert ("SIN-ECOM", "el SKU no se") in motivos and ("SIN-STOCK", "sin stock di") in motivos and ("A-OK", "SIN COSTO en") in motivos
    csv_txt = ci.descartadas_a_csv(r["descartadas"])
    assert csv_txt.startswith("sku,mla_id,cuenta,titulo,motivo") and "SIN-ECOM" in csv_txt
