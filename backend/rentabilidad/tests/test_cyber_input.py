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
