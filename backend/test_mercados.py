"""Mercados del Motor de Precios (Bloque 2, PR 4): tarifas desde la pestaña «Mercados», fórmula de siempre con los números de cada mercado, avisos y foto guardada."""
from contextlib import contextmanager
from datetime import date
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import ayala_core
import main
import mercados as mk
from rentabilidad import costos_ecom
from rentabilidad.db import Base
from rentabilidad.models import MlAlerta, MlFoto, MlLoteCache

FILAS = mk.filas_iniciales_parseadas()
HOY = date(2026, 10, 25)
RENTA = {c: D("30") for c in ("contado", "reducida", "3", "6", "9", "12", "18", "24")}


def _sin(filas, mercado, concepto, cuotas=None):
    return [f for f in filas if not (f["mercado"] == mercado and f["concepto"] == concepto and (cuotas is None or f["cuotas"] == cuotas))]


def test_web_aplica_el_recargo_de_20_por_ciento_sobre_las_cuotas_y_es_editable():
    par = mk.parametros_mercado("web", FILAS, HOY)
    esperado = {"contado": "0", "3": "4.08", "6": "9.48", "9": "15.12", "12": "18.24", "18": "26.52", "24": "33.12"}   # las cifras de la planilla de Maxi
    assert {k: str(v.normalize()) for k, v in par["financiero"].items()} == {k: str(D(v).normalize()) for k, v in esperado.items()}
    assert par["comision_pct"] == D("6") and par["recargo_cuotas"] == D("20") and par["condiciones"] == ["contado", "3", "6", "9", "12", "18", "24"]
    sin_recargo = mk.parametros_mercado("web", FILAS, HOY, recargo_cuotas=D("0"))
    assert sin_recargo["financiero"]["24"] == D("27.60")
    # lo que Maxi ya decidió (base 6 % y recargo 20 %) no se marca «a confirmar»; solo las cuotas de Mercado Pago, en UN aviso
    assert [a["texto"] for a in par["avisos"]] == ["Cuotas de Web (Mercado Pago): a confirmar"]


def test_fravega_suma_base_y_cuotas_con_desglose_y_simple_es_solo_la_base():
    par = mk.parametros_mercado("fravega", FILAS, HOY)
    assert par["comision_pct"] == D("15.5") and "reducida" not in par["condiciones"] and par["etiqueta_contado"] == "Simple"
    assert par["financiero"] == {"contado": D("0"), "3": D("6.8"), "6": D("10.6"), "9": D("13.7"), "12": D("16.6")}
    assert par["desglose"]["3"]["total"] == D("22.3") and par["desglose"]["contado"]["total"] == D("15.5")
    assert par["avisos"] == []     # comisión base y cuotas ya decididas: nada «a confirmar»


def test_oncity_y_megatone_usan_los_mismos_numeros_pero_con_sus_propias_filas_y_marcados_copiados():
    f = mk.parametros_mercado("fravega", FILAS, HOY)
    for m in ("oncity", "megatone"):
        p = mk.parametros_mercado(m, FILAS, HOY)
        assert p["comision_pct"] == f["comision_pct"] and p["financiero"] == f["financiero"]
        assert p["avisos"] == [] and [n["texto"] for n in p["notas"]] == [f"Las cifras de {p['nombre']} están copiadas de Frávega."]   # nota gris, no aviso
        assert sum(1 for x in FILAS if x["mercado"] == m) == sum(1 for x in FILAS if x["mercado"] == "fravega")      # cada uno con sus filas
    chico = [dict(x, porcentaje="9.9") if (x["mercado"] == "oncity" and x["concepto"] == "comision_base") else x for x in FILAS]
    assert mk.parametros_mercado("megatone", chico, HOY)["comision_pct"] == D("15.5")                          # cambiar uno no toca a los otros


def test_ml_conserva_sus_parametros_de_siempre():
    par = mk.parametros_mercado("ml", FILAS, HOY)
    assert par["comision_pct"] == ayala_core.COMISION_ML_DEFAULT == D("15.5") and par["financiero"]["reducida"] == D("5.00") and par["financiero"]["12"] == D("20.80")
    assert par["condiciones"] == ["contado", "reducida", "3", "6", "9", "12"]


def test_si_falta_una_fila_no_se_inventa_la_tarifa_y_se_dice_cual():
    par = mk.parametros_mercado("fravega", _sin(FILAS, "fravega", "cuotas", "12"), HOY)
    precios, errores = mk.calcular_mercado(par, costo_sin_iva=D("100000"), iva_factor=D("1.21"), envio_real=D(0), renta_por_condicion=RENTA)
    assert "12" not in precios and errores["12"] == "falta dato: tarifa de 12 cuotas de Frávega" and set(precios) == {"contado", "3", "6", "9"}
    sin_base = mk.parametros_mercado("web", _sin(FILAS, "web", "comision_base"), HOY)
    assert all(v == "falta dato: comisión base de Web (Mercado Pago)" for v in sin_base["faltantes"].values()) and len(sin_base["faltantes"]) == 7


def test_vigencia_vencida_o_futura_avisa():
    vencida = [dict(x, hasta="31/05/2026") if (x["mercado"] == "fravega" and x["cuotas"] == "6") else x for x in FILAS]
    assert any(a["tipo"] == "vencida" and "Cuotas de Frávega" in a["texto"] for a in mk.parametros_mercado("fravega", vencida, HOY)["avisos"])
    futura = [dict(x, desde="01/01/2027") if (x["mercado"] == "fravega" and x["cuotas"] == "9") else x for x in FILAS]
    assert any(a["tipo"] == "no_vigente" for a in mk.parametros_mercado("fravega", futura, HOY)["avisos"])


def test_la_cuenta_es_la_de_siempre_con_los_numeros_del_mercado():
    """Con los parámetros de ML (comisión, financiero) `calcular_mercado` da EXACTAMENTE lo que `calcular_precios_todas_condiciones` (la fórmula de hoy)."""
    par = mk.parametros_mercado("ml", FILAS, HOY)
    renta = {"contado": D("32"), "reducida": D("32"), "3": D("30"), "6": D("28"), "9": D("26"), "12": D("24")}
    for costo, iva, envio, full in ((D("250000"), D("1.21"), D("8500"), False), (D("43210.55"), D("1.105"), D(0), True)):
        propio, err = mk.calcular_mercado(par, costo_sin_iva=costo, iva_factor=iva, envio_real=envio, renta_por_condicion=renta, envio_full=full, costo_orden=ayala_core.COSTO_ORDEN_ECOM_DEFAULT)
        base = ayala_core.calcular_precios_todas_condiciones(
            costo_sin_iva=costo, iva_factor=iva, envio_real=envio, envio_full=full,
            renta_por_condicion={"contado": D("32"), "reducida": D("32"), 3: D("30"), 6: D("28"), 9: D("26"), 12: D("24")})
        assert not err and propio == base


def test_costo_por_orden_suma_un_monto_fijo_y_con_cero_no_cambia_nada():
    kw = dict(costo_sin_iva=D("100000"), iva_factor=D("1.21"), financiero_pct=D("6.8"), renta_pct=D("30"), comision_pct=D("15.5"), envio_real=D("8500"))
    sin = ayala_core.calcular_precio_condicion(**kw)
    assert ayala_core.calcular_precio_condicion(**kw, costo_orden=D(0)) == sin
    con = ayala_core.calcular_precio_condicion(**kw, costo_orden=D("149.12"))
    assert con == ayala_core.calcular_precio_condicion(**{**kw, "costo_sin_iva": D("100149.12")}) and con > sin


# ── endpoints ──

COSTOS = {s: D("12.5") for s in ayala_core.SKUS_PILOTO[:3]}


class _Costo:
    def precargar(self): pass
    def obtener(self, sku): return COSTOS.get(sku)


class _Iva:
    tactica_caida = False
    def precargar(self): pass
    def factor(self, sku): return D("1.21")


@pytest.fixture
def sesion_fn(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(eng, tables=[MlFoto.__table__, MlAlerta.__table__, MlLoteCache.__table__])
    Sesion = sessionmaker(bind=eng, future=True, expire_on_commit=False)

    @contextmanager
    def sesion():
        db = Sesion()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    import rentabilidad.db as rdb
    monkeypatch.setattr(rdb, "sesion", sesion)
    main._TARIFAS_CACHE.update(en=0.0, payload=None, info=None)
    return sesion


@pytest.fixture
def cliente(monkeypatch, sesion_fn):
    monkeypatch.setenv("MERCADOS_SHEET_ID", "SHEET-DE-PRUEBA")
    main._SHEET_NOMBRE_CACHE.update(id=None, nombre=None, en=0.0)
    monkeypatch.setattr(main.costos_ecom, "proveedores_de_costo_e_iva", lambda: (_Costo(), _Iva()))
    monkeypatch.setattr(main, "tc_info_rapido", lambda: {"tc": D("1450"), "source": "cache", "fecha": None})
    return TestClient(main.app)


def test_lote_por_mercado_solo_trae_las_condiciones_de_ese_mercado(cliente):
    sku = ayala_core.SKUS_PILOTO[0]
    web = cliente.get("/ayala-core/motor-lote", params={"mercado": "web", "skus": sku}).json()["resultados"][0]
    assert list(web["precios"]) == ["contado", "3", "6", "9", "12", "18", "24"] and web["mercado"] == "web" and web["etiqueta_contado"] == "Simple"
    assert web["envio_estimado_como_ml"] is True and web["parametros"]["costo_orden"] == 149.12 and web["parametros"]["recargo_cuotas"] == 20
    fr = cliente.get("/ayala-core/motor-lote", params={"mercado": "fravega", "skus": sku, "envio_real": 8500}).json()["resultados"][0]
    assert "reducida" not in fr["precios"] and fr["envio_estimado_como_ml"] is False and fr["parametros"]["desglose"]["6"]["total"] == 26.1
    r = cliente.get("/ayala-core/motor-lote", params={"mercado": "oncity", "skus": sku}).json()
    assert r["calculado_con"]["avisos_mercado"] == [] and any("copiadas de Frávega" in n for n in r["calculado_con"]["notas_mercado"]) and r["calculado_con"]["tarifas"]["origen"] == "codigo"


def test_precio_de_otro_mercado_coincide_con_la_cuenta_hecha_a_mano(cliente):
    sku = ayala_core.SKUS_PILOTO[0]
    r = cliente.get("/ayala-core/motor-lote", params={"mercado": "fravega", "skus": sku, "envio_real": 8500, "renta_contado": 30, "renta_3": 30, "renta_6": 30, "renta_9": 30, "renta_12": 30}).json()["resultados"][0]
    esperado = ayala_core.calcular_precio_condicion(costo_sin_iva=D("12.5") * D("1450"), iva_factor=D("1.21"), envio_real=D("8500"), financiero_pct=D("6.8"), renta_pct=D("30"),
                                                    comision_pct=D("15.5"), costo_orden=D("149.12"))
    assert r["precios"]["3"] == float(esperado)


def test_ml_sin_cambios_lleva_el_costo_por_orden_y_apagarlo_baja_el_precio(cliente):
    sku = ayala_core.SKUS_PILOTO[0]
    a = cliente.get("/ayala-core/motor-lote", params={"skus": sku}).json()["resultados"][0]
    b = cliente.get("/ayala-core/motor-lote", params={"skus": sku, "mercado": "ml"}).json()["resultados"][0]
    assert a["precios"] == b["precios"] and a["mercado"] == "ml"
    c = cliente.get("/ayala-core/motor-lote", params={"skus": sku, "mercado": "ml", "usar_costo_orden": False}).json()["resultados"][0]
    assert all(c["precios"][k] < a["precios"][k] for k in a["precios"])      # decidido por Maxx (27/10): el costo por orden se descuenta en TODAS las ventas por Ecom, ML incluido


def test_mercado_desconocido_da_422(cliente):
    assert cliente.get("/ayala-core/motor-lote", params={"mercado": "otro"}).status_code == 422


def test_foto_de_tarifas_primero_valores_iniciales_y_despues_la_hoja(cliente, monkeypatch):
    e = cliente.get("/mercados/tarifas").json()
    assert e["tarifas"]["origen"] == "codigo" and e["avisos"] == [] and any("valores iniciales del código" in x for x in e["informacion"]) and e["comunes"]["costo_orden"] == 149.12
    hoja = [mk.HEADERS] + [list(f) for f in mk.FILAS_INICIALES]
    hoja = [([*f[:3], "16.5", *f[4:]] if (f[0] == "fravega" and f[1] == "comision_base") else f) for f in hoja]
    monkeypatch.setattr(main, "get_gs", lambda: object())
    monkeypatch.setattr(mk, "leer_hoja", lambda gs, sid, pest="Mercados": hoja)
    e2 = cliente.post("/mercados/tarifas/actualizar").json()
    assert e2["tarifas"]["origen"] == "hoja" and e2["tarifas"]["obtenido_en"]
    r = cliente.get("/ayala-core/motor-lote", params={"mercado": "fravega", "skus": ayala_core.SKUS_PILOTO[0]}).json()
    assert r["resultados"][0]["parametros"]["comision_pct"] == 16.5 and r["calculado_con"]["tarifas"]["origen"] == "hoja"


def test_si_falla_la_lectura_se_conserva_la_foto_y_el_mensaje_no_lleva_url(cliente, monkeypatch):
    hoja = [mk.HEADERS] + [list(f) for f in mk.FILAS_INICIALES]
    monkeypatch.setattr(main, "get_gs", lambda: object())
    monkeypatch.setattr(mk, "leer_hoja", lambda *a, **k: hoja)
    cliente.post("/mercados/tarifas/actualizar")
    def rota(*a, **k): raise RuntimeError("APIError 403 for url: https://sheets.googleapis.com/v4/spreadsheets/ABC/values/Mercados")
    monkeypatch.setattr(mk, "leer_hoja", rota)
    r = cliente.post("/mercados/tarifas/actualizar")
    assert r.status_code == 502 and "http" not in r.json()["detail"]
    e = cliente.get("/mercados/tarifas").json()
    assert e["tarifas"]["origen"] == "hoja" and e["tarifas"]["error_msg"] and any("Falló la última lectura" in a["texto"] for a in e["avisos"])


class _WS:
    def __init__(self, t): self.title, self.datos = t, None
    def update(self, values, range_name): self.datos = values


class _SS:
    def __init__(self, existentes=()): self.ws = [_WS(t) for t in existentes]
    def worksheets(self): return self.ws
    def add_worksheet(self, title, rows, cols):
        w = _WS(title); self.ws.append(w); return w


class _GS:
    def __init__(self, ss): self.ss = ss
    def open_by_key(self, _): return self.ss


def test_crear_pestanas_mercados_con_valores_iniciales_y_envios_vacia_sin_pisar_nada():
    ss = _SS()
    r = mk.crear_pestanas(_GS(ss), "ID")
    m = {w.title: w for w in ss.ws}
    assert m["Mercados"].datos[0] == mk.HEADERS and len(m["Mercados"].datos) == 1 + len(mk.FILAS_INICIALES) and "creada" in r["Mercados"]
    assert m["Envios"].datos == [mk.HEADERS_ENVIOS] and mk.HEADERS_ENVIOS[:3] == ["mercado", "peso desde", "peso hasta"]
    ss2 = _SS(["Mercados", "Envios"])
    r2 = mk.crear_pestanas(_GS(ss2), "ID")
    assert all(w.datos is None for w in ss2.ws) and "no se tocó" in r2["Mercados"] and "no se tocó" in r2["Envios"]


def test_el_desglose_cierra_con_la_renta_pedida(cliente):
    """La renta en pesos del desglose es la renta objetivo × el precio (a menos del redondeo del precio al peso)."""
    sku = ayala_core.SKUS_PILOTO[0]
    for mercado in ("fravega", "web"):
        r = cliente.get("/ayala-core/motor-lote", params={"mercado": mercado, "skus": sku, "envio_real": 8500, "renta_contado": 30, "renta_3": 30, "renta_6": 30, "renta_9": 30, "renta_12": 30, "renta_18": 30, "renta_24": 30}).json()["resultados"][0]
        for c, p in r["precios"].items():
            g = r["desglose_mercado"][c]
            assert abs(g["renta"] / p - 0.30) < 0.0005, (mercado, c, g["renta"] / p)
            assert g["costo_orden"] == 149.12


def test_ml_trae_su_comision_real_en_el_lote_sin_cambiar_precios(cliente):
    r = cliente.get("/ayala-core/motor-lote", params={"skus": ayala_core.SKUS_PILOTO[0]}).json()["resultados"][0]
    assert r["comision_pct"] == 15.5 and r["mercado"] == "ml"


def test_sin_la_variable_no_se_lee_ni_se_escribe_ningun_sheet_y_la_pantalla_lo_sabe(cliente, monkeypatch):
    monkeypatch.delenv("MERCADOS_SHEET_ID")
    abierto = []
    monkeypatch.setattr(main, "get_gs", lambda: abierto.append(1))
    e = cliente.get("/mercados/tarifas").json()
    assert e["sheet"] == {"configurado": False, "nombre": None, "variable": "MERCADOS_SHEET_ID"} and e["tarifas"]["origen"] == "codigo"
    for ruta in ("/mercados/init", "/mercados/tarifas/actualizar"):
        r = cliente.post(ruta)
        assert r.status_code == 409 and "MERCADOS_SHEET_ID" in r.json()["detail"]
    assert abierto == []                                                      # nunca se abrió un Sheet


def test_con_la_variable_escribe_y_lee_solo_ese_sheet_y_devuelve_su_nombre(cliente, monkeypatch):
    ss = _SS()
    ss.title = "ERP Global – Configuración"
    abiertos = []

    class GS(_GS):
        def open_by_key(self, k):
            abiertos.append(k)
            return super().open_by_key(k)
    monkeypatch.setattr(main, "get_gs", lambda: GS(ss))
    e = cliente.get("/mercados/tarifas").json()
    assert e["sheet"] == {"configurado": True, "nombre": "ERP Global – Configuración", "variable": "MERCADOS_SHEET_ID"}
    r = cliente.post("/mercados/init").json()
    assert r["sheet"]["nombre"] == "ERP Global – Configuración" and "creada" in r["pestanas"]["Mercados"]
    assert set(abiertos) == {"SHEET-DE-PRUEBA"}                               # y no el Sheet fijo del código
