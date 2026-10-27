"""Criterios de precio por canal: ningún precio cambia hasta editar, cada cambio pide operador y queda registrado, y Mercado Libre usa lo que se edita."""
import copy
from contextlib import contextmanager
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import ayala_core as ac
import criterios as C
import main
import mercados as M
from rentabilidad import db as _db
from rentabilidad.db import Base
from rentabilidad.models import MlAlerta, MlFoto, MlLoteCache


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

    monkeypatch.setattr(_db, "sesion", sesion)
    main._TARIFAS_CACHE.update(en=0.0, payload=None)
    antes = copy.deepcopy({k: (dict(v) if isinstance(v, dict) else v) for k, v in ac.PARAMS_ML.items()})
    yield sesion
    for k, v in antes.items():                      # los tests no dejan a Mercado Libre con valores editados
        if k == "cuotas":
            ac.PARAMS_ML["cuotas"].clear(); ac.PARAMS_ML["cuotas"].update(v)
        else:
            ac.PARAMS_ML[k] = v
    main._TARIFAS_CACHE.update(en=0.0, payload=None)


def _precios(**kw):
    return ac.calcular_precios_todas_condiciones(costo_sin_iva=D("42025"), iva_factor=D("1.21"), envio_real=D(0), **kw)


def test_con_los_valores_iniciales_los_precios_de_ml_son_los_de_siempre(sesion_fn):
    antes = _precios()
    main._criterios_cambiaron()                                      # carga los criterios (valores iniciales) y los aplica a ML
    assert _precios() == antes
    assert ac.PARAMS_ML["comision"] == D("15.5") and ac.PARAMS_ML["orden"] == D("149.12") and ac.PARAMS_ML["reducida"] == D("5.00")
    assert ac.PARAMS_ML["tramos"] == ac.COSTO_FIJO_ML_TRAMOS


def test_cambiar_la_comision_de_ml_cambia_su_precio_y_queda_en_el_historial(sesion_fn):
    antes = _precios()["contado"]
    e = C.editar(sesion_fn, "ml", "comision_base", "", "16", "Natalia")
    main._criterios_cambiaron()
    assert D(_precios()["contado"]) > D(antes) and ac.PARAMS_ML["comision"] == D("16")
    assert e["antes"] == "15.5" and e["despues"] == "16" and e["operador"] == "Natalia"
    assert C.leer(sesion_fn)[1][-1]["operador"] == "Natalia"


def test_sin_operador_o_con_un_valor_malo_no_se_cambia_nada(sesion_fn):
    for args in (("ml", "comision_base", "", "16", " "), ("ml", "comision_base", "", "abc", "Maxi"), ("ml", "comision_base", "", "150", "Maxi"), ("ml", "comision_base", "", "-1", "Maxi"),
                 ("ml", "costo_orden_inexistente", "", "1", "Maxi"), ("xx", "iibb", "", "5", "Maxi")):
        with pytest.raises(C.CriterioInvalido):
            C.editar(sesion_fn, *args)
    assert C.leer(sesion_fn)[1] == [] and ac.PARAMS_ML["comision"] == D("15.5")


def test_el_costo_fijo_y_las_cuotas_de_ml_se_editan_y_se_usan(sesion_fn):
    C.editar(sesion_fn, "ml", "costo_fijo", "15000", "2000", "Maxi")
    C.editar(sesion_fn, "ml", "cuotas", "3", "10", "Maxi")
    main._criterios_cambiaron()
    assert ac.PARAMS_ML["tramos"][0] == (D(15000), D(2000)) and ac.PARAMS_ML["cuotas"][3] == D(10)
    assert ac.CUOTAS_PCT_DEFAULT[3] == D(10)            # es el mismo dict que lee Ofertas ML


def test_un_canal_puede_tener_su_propio_iibb_y_volver_al_comun(sesion_fn):
    C.editar(sesion_fn, "fravega", "iibb", "", "3", "Maxi")
    filas = C.leer(sesion_fn)[0]
    assert M.valores_canal(filas, "fravega")["iibb_pct"] == (D("3"), "propio") and M.valores_canal(filas, "web")["iibb_pct"] == (D("5"), "todos")
    C.volver_al_comun(sesion_fn, "fravega", "iibb", "Maxi")
    assert M.valores_canal(C.leer(sesion_fn)[0], "fravega")["iibb_pct"] == (D("5"), "todos")
    with pytest.raises(C.CriterioInvalido):
        C.volver_al_comun(sesion_fn, "fravega", "iibb", "Maxi")          # ya usa el común


def test_el_valor_comun_cambia_a_todos_los_canales_sin_valor_propio(sesion_fn):
    C.editar(sesion_fn, "todos", "costo_orden", "", "200", "Maxi")
    filas = C.leer(sesion_fn)[0]
    assert all(M.valores_canal(filas, m)["costo_orden"][0] == D(200) for m in M.MERCADOS)


def test_endpoints_vista_valor_y_volver(sesion_fn):
    import os
    cl = TestClient(main.app)
    h = {"X-ERP-Key": os.environ["ERP_API_KEY"]} if os.environ.get("ERP_API_KEY") else {}
    v = cl.get("/criterios").json()
    assert [c["clave"] for c in v["canales"]] == ["todos", "ml", "fravega", "oncity", "megatone", "web"]
    ml = {a["id"]: a for a in next(c for c in v["canales"] if c["clave"] == "ml")["apartados"]}
    assert set(ml) == {"comision", "impuestos", "costo_fijo", "cuotas"} and [f["valor"] for f in ml["costo_fijo"]["filas"]] == ["1330", "2740", "3320", "0"]
    assert [f["etiqueta"] for f in ml["cuotas"]["filas"]] == ["Reducida", "3 cuotas", "6 cuotas", "9 cuotas", "12 cuotas"]
    assert cl.put("/criterios/valor", json={"mercado": "ml", "concepto": "comision_base", "valor": "15.8", "operador": ""}, headers=h).status_code == 422
    assert cl.put("/criterios/valor", json={"mercado": "ml", "concepto": "comision_base", "valor": "15.8", "operador": "Natalia"}, headers=h).json()["ok"] is True
    assert cl.get("/criterios").json()["historial"][0]["despues"] == "15.8" and ac.PARAMS_ML["comision"] == D("15.8")
    web = {a["id"]: a for a in next(c for c in cl.get("/criterios").json()["canales"] if c["clave"] == "web")["apartados"]}
    assert [f["etiqueta"] for f in web["cuotas"]["filas"]][:3] == ["Simple", "3 cuotas", "6 cuotas"] and web["cuotas"]["filas"][-1]["etiqueta"] == "Recargo sobre las cuotas"


def test_el_iibb_propio_de_un_canal_se_usa_en_su_cuenta(sesion_fn):
    C.editar(sesion_fn, "fravega", "iibb", "", "3", "Maxi")
    main._criterios_cambiaron()
    m = main._preparar_mercado("fravega")
    assert m["usados"]["iibb_pct"] == D(3) and main._preparar_mercado("web")["usados"]["iibb_pct"] == D(5)


def test_ofertas_ml_y_el_motor_comparten_los_criterios_y_el_endpoint_los_entrega(sesion_fn):
    import ml_ofertas as mo
    C.editar(sesion_fn, "ml", "comision_base", "", "16", "Maxi")
    C.editar(sesion_fn, "ml", "costo_fijo", "15000", "2000", "Maxi")
    C.editar(sesion_fn, "todos", "costo_orden", "", "200", "Maxi")
    main._criterios_cambiaron()
    p = mo.ParametrosMargen()                                     # lo que usa Ofertas ML al calcular
    assert p.comision_general == D(16) and p.costo_fijo_tramos[0] == (D(15000), D(2000)) and p.costo_orden == D(200)
    d = TestClient(main.app).get("/criterios/ml").json()
    assert d["comision"] == 16 and d["orden"] == 200 and d["tramos"][0] == [15000, 2000] and d["tramos"][-1] == [None, 0] and d["cuotas"]["3"] == 8.5 and d["reducida"] == 5
    assert ac.PARAMS_ML is mo.PARAMS_ML
