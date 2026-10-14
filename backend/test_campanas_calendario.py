"""Aviso diario de campañas de ML: calendario de las dos cuentas, secciones, días y marca de "a 5 días" (ML simulado)."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

import campanas_calendario as cc

HOY = date(2026, 10, 14)


class FakeML:
    def __init__(self, promos, candidatos=None, aceptados=None, caidas=()):
        self.promos, self.cand, self.ok, self.caidas, self.llamadas = promos, candidatos or {}, aceptados or {}, caidas, []

    def promociones_seller(self, cuenta):
        if cuenta in self.caidas:
            raise RuntimeError("403 Client Error: Forbidden")
        return self.promos.get(cuenta, [])

    def contar_items_promocion(self, pid, tipo, cuenta, status):
        self.llamadas.append((pid, tipo, cuenta, status))
        return (self.cand if status == "candidate" else self.ok).get((cuenta, pid))


def _p(id, tipo, nombre, estado="pending", inicio=None, fin=None, limite=None):
    d = {"id": id, "type": tipo, "name": nombre, "status": estado}
    if inicio:
        d["start_date"] = inicio + "T00:00:00"
    if fin:
        d["finish_date"] = fin + "T23:59:59"
    if limite:
        d["deadline_date"] = limite + "T23:59:59"
    return d


def _por_nombre(res):
    return {f["nombre"]: f for f in res["especiales"] + res["cupones_operativas"]}


def test_separa_especiales_de_cupones_y_operativas():
    ml = FakeML({"IT": [_p("1", "DEAL", "Black Friday", inicio="2026-11-20", fin="2026-11-27"),
                        _p("2", "SMART", "Smart", inicio="2026-11-01", fin="2026-11-10"),
                        _p("3", "SELLER_CAMPAIGN", "Oferta tradicional Nov", inicio="2026-11-01", fin="2026-11-30"),
                        _p("4", "SELLER_COUPON_CAMPAIGN", "Cupón 10%", inicio="2026-10-20", fin="2026-10-31"),
                        _p("5", "UNHEALTHY_STOCK", "Stock no saludable", inicio="2026-10-18", fin="2026-11-18"),
                        _p("6", "EVENTO_RARO", "Algo nuevo", inicio="2026-10-30", fin="2026-11-02")]})
    r = cc.calendario(ml, HOY, con_elegibles=False, cuentas=["IT"])
    assert {f["nombre"] for f in r["especiales"]} == {"Black Friday", "Smart", "Oferta tradicional Nov", "Algo nuevo"}
    assert {f["nombre"] for f in r["cupones_operativas"]} == {"Cupón 10%", "Stock no saludable"}
    assert _por_nombre(r)["Algo nuevo"]["tipo_desconocido"] is True and any("EVENTO_RARO" in a for a in r["avisos"])
    assert r["resumen"] == {"campanas": 6, "especiales": 4, "cupones_operativas": 2, "a_dias_aviso": 0, "en_las_dos_cuentas": 0}


def test_dias_al_limite_si_tiene_y_si_no_al_inicio_y_marca_exactamente_5():
    ml = FakeML({"IT": [
        _p("a", "DEAL", "Con límite a 5", inicio="2026-10-30", fin="2026-11-05", limite="2026-10-19"),          # límite en 5 días → aviso
        _p("b", "DEAL", "Sin límite, inicio a 5", inicio="2026-10-19", fin="2026-10-25"),                       # inicio en 5 días → aviso
        _p("c", "DEAL", "Con límite a 9 e inicio a 5", inicio="2026-10-19", fin="2026-10-25", limite="2026-10-23"),  # la referencia es el límite (9)
        _p("d", "DEAL", "A 4 días", inicio="2026-10-18", fin="2026-10-25"),
        _p("e", "DEAL", "A 6 días", inicio="2026-10-20", fin="2026-10-25"),
        _p("f", "DEAL", "Límite ya pasado", inicio="2026-10-25", fin="2026-10-30", limite="2026-10-10"),
    ]})
    r = cc.calendario(ml, HOY, con_elegibles=False, cuentas=["IT"])
    f = _por_nombre(r)
    assert (f["Con límite a 5"]["dias_faltan"], f["Con límite a 5"]["referencia_dias"]) == (5, "limite_adhesion")
    assert (f["Sin límite, inicio a 5"]["dias_faltan"], f["Sin límite, inicio a 5"]["referencia_dias"]) == (5, "inicio")
    assert f["Con límite a 9 e inicio a 5"]["dias_faltan"] == 9 and f["Con límite a 9 e inicio a 5"]["dias_al_inicio"] == 5
    assert f["Límite ya pasado"]["dias_faltan"] == -4
    assert [x["nombre"] for x in r["a_5_dias"]] == ["Con límite a 5", "Sin límite, inicio a 5"]            # EXACTAMENTE 5 (ni 4 ni 6)
    assert r["hay_aviso_destacado"] is True and "2 campaña(s)" in r["asunto"]
    assert [x["dias_faltan"] for x in r["especiales"]] == sorted(x["dias_faltan"] for x in r["especiales"])   # ordenadas por urgencia


def test_la_misma_campana_en_it_y_mt_sale_una_vez_con_las_dos_cuentas():
    comun = dict(inicio="2026-11-01", fin="2026-11-10", limite="2026-10-19")
    ml = FakeML({"IT": [_p("P-1", "DEAL", "Hot Sale", **comun), _p("S-IT", "SELLER_CAMPAIGN", "Oferta tradicional Nov", inicio="2026-11-01", fin="2026-11-30")],
                 "MT": [_p("P-1", "DEAL", "Hot Sale", **comun), _p("S-MT", "SELLER_CAMPAIGN", "Oferta Tradicional  Nov", inicio="2026-11-01", fin="2026-11-30"),
                        _p("P-9", "DEAL", "Solo MT", inicio="2026-12-01", fin="2026-12-05")]},
                candidatos={("IT", "P-1"): 42, ("MT", "P-1"): 7}, aceptados={("IT", "P-1"): 3, ("MT", "P-1"): 0})
    r = cc.calendario(ml, HOY)
    f = _por_nombre(r)
    assert len(r["especiales"]) == 3 and r["resumen"]["en_las_dos_cuentas"] == 2
    assert f["Hot Sale"]["cuentas"] == ["IT", "MT"] and f["Hot Sale"]["ids_por_cuenta"] == {"IT": "P-1", "MT": "P-1"}
    assert f["Hot Sale"]["elegibles"] == {"IT": 42, "MT": 7} and f["Hot Sale"]["items_elegibles"] == 49 and f["Hot Sale"]["aceptados"] == {"IT": 3, "MT": 0}
    assert f["Oferta tradicional Nov"]["cuentas"] == ["IT", "MT"]                                         # mismo nombre/fechas con ids distintos
    assert f["Oferta tradicional Nov"]["ids_por_cuenta"] == {"IT": "S-IT", "MT": "S-MT"}
    assert f["Solo MT"]["cuentas"] == ["MT"]
    assert "IT+MT" in f["Hot Sale"]["texto"] and "elegible en 42 ítems (IT) + 7 ítems (MT)" in f["Hot Sale"]["texto"] and "límite de adhesión 19/10" in f["Hot Sale"]["texto"]
    assert ("P-1", "DEAL", "IT", "candidate") in ml.llamadas and ("P-1", "DEAL", "MT", "started") in ml.llamadas


def test_una_cuenta_caida_no_tira_la_otra_y_se_informa():
    ml = FakeML({"IT": [_p("1", "DEAL", "Solo IT", inicio="2026-11-01", fin="2026-11-10")]}, caidas=("MT",))
    r = cc.calendario(ml, HOY, con_elegibles=False)
    assert r["cuentas_consultadas"]["IT"] == {"ok": True, "campanas": 1, "error": None}
    assert r["cuentas_consultadas"]["MT"]["ok"] is False and "403" in r["cuentas_consultadas"]["MT"]["error"]
    assert len(r["especiales"]) == 1 and any("cuenta MT" in a for a in r["avisos"])


def test_finalizadas_afuera_y_sin_fecha_se_informa_sin_inventar():
    ml = FakeML({"IT": [_p("1", "DEAL", "Vieja", estado="finished", inicio="2026-09-01", fin="2026-09-10"),
                        _p("2", "DEAL", "Terminó ayer", estado="started", inicio="2026-10-01", fin="2026-10-13"),
                        _p("3", "DEAL", "Sin fechas")]})
    r = cc.calendario(ml, HOY, con_elegibles=False, cuentas=["IT"])
    assert [f["nombre"] for f in r["especiales"]] == ["Sin fechas"]
    f = r["especiales"][0]
    assert f["sin_fecha"] is True and f["dias_faltan"] is None and f["a_dias_aviso"] is False
    assert r["diagnostico"]["campanas_sin_fecha"][0]["id"] == "3" and any("sin fecha" in a for a in r["avisos"])
    assert len(cc.calendario(ml, HOY, con_elegibles=False, cuentas=["IT"], incluir_finalizadas=True)["especiales"]) == 3


@pytest.mark.parametrize("v,esperado", [("2026-10-19T00:00:00", date(2026, 10, 19)), ("2026-10-19", date(2026, 10, 19)), ("2026-10-19T23:59:59.000-03:00", date(2026, 10, 19)),
                                        ("2026-10-19T02:00:00Z", date(2026, 10, 19)), (1792368000, date(2026, 10, 19)), (1792368000000, date(2026, 10, 19)),
                                        (None, None), ("", None), ("mañana", None), ("2026-13-45", None)])
def test_fechas_de_ml(v, esperado):
    assert cc.fecha(v) == esperado


def test_acepta_las_variantes_de_nombre_de_los_campos_de_fecha():
    ml = FakeML({"IT": [{"id": "x", "type": "DEAL", "name": "Variante", "status": "pending", "date_from": "2026-10-19", "date_to": "2026-10-25", "deadline": "2026-10-19"}]})
    f = cc.calendario(ml, HOY, con_elegibles=False, cuentas=["IT"])["especiales"][0]
    assert (f["inicio"], f["fin"], f["limite_adhesion"], f["dias_faltan"]) == ("2026-10-19", "2026-10-25", "2026-10-19", 5)


# ── el endpoint ──
@pytest.fixture()
def cli(monkeypatch):
    import ml_ofertas
    import main
    fake = FakeML({"IT": [_p("1", "DEAL", "Black Friday", inicio="2026-10-19", fin="2026-10-25")]}, candidatos={("IT", "1"): 12})
    monkeypatch.setattr(ml_ofertas, "MLOfertasClient", lambda: fake)
    return TestClient(main.app)


def test_endpoint_protegido_con_la_clave_y_devuelve_el_json_del_mail(cli, monkeypatch):
    monkeypatch.setenv("ERP_API_KEY", "secreta")
    assert cli.get("/campanas/calendario").status_code == 401
    assert cli.get("/campanas/calendario", headers={"X-ERP-Key": "mala"}).status_code == 401
    r = cli.get("/campanas/calendario?hoy=2026-10-14", headers={"X-ERP-Key": "secreta"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["fecha"] == "2026-10-14" and j["hay_aviso_destacado"] is True and [f["nombre"] for f in j["a_5_dias"]] == ["Black Friday"]
    assert j["especiales"][0]["items_elegibles"] == 12 and set(j) >= {"asunto", "especiales", "cupones_operativas", "a_5_dias", "avisos", "cuentas_consultadas", "resumen"}


def test_endpoint_valida_parametros(cli, monkeypatch):
    monkeypatch.delenv("ERP_API_KEY", raising=False)
    assert cli.get("/campanas/calendario?hoy=ayer").status_code == 422
    assert cli.get("/campanas/calendario?dias_aviso=99").status_code == 422
    assert cli.get("/campanas/calendario?hoy=2026-10-14&con_elegibles=false").status_code == 200
