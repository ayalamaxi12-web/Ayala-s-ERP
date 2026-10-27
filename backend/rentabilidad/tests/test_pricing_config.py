from contextlib import contextmanager
from datetime import date

import pytest

from rentabilidad import api, motor_precios as m, pricing_config as pc
from .conftest import d

HOY = date(2026, 10, 12)


@pytest.fixture()
def par(db_session):
    return m.cargar_parametros(db_session, HOY, criterios=False)  # tabla de la base, sin el criterio de ML


def test_cuotas_ml_son_las_oficiales_ordenadas(par):
    c = pc.cuotas_ml(par)
    assert [(x["plan"], str(x["pct_texto"])) for x in c] == [("reducida", "5"), ("3", "8.9"), ("6", "13.4"), ("9", "17.8"), ("12", "21.6")]
    assert all(x["plan"] != "contado" for x in c)


def test_validar_rechaza_planes_y_valores_raros():
    for malo in ({}, {"18": 22}, {"3": "abc"}, {"3": -1}, {"3": 51}):
        with pytest.raises(pc.CuotasInvalidas):
            pc.validar_planes(malo)
    assert pc.validar_planes({"3": "8,9", "reducida": 5}) == {"3": d("0.089"), "reducida": d("0.05")}


def test_previsualizar_no_escribe_y_guardar_solo_lo_que_cambia(db_session, par):
    prev = {x["plan"]: x for x in pc.previsualizar(par, {"3": 8.9, "6": 14})}
    assert prev["3"]["cambia"] is False and prev["6"]["cambia"] is True and str(prev["6"]["actual_pct"]) == "13.4"
    assert pc.guardar(db_session, {"3": 8.9, "6": 14}, HOY, "maxx") == 1                   # el 3 no cambió: no se agrega fila
    nuevos = {x["plan"]: x["pct"] for x in pc.cuotas_ml(m.cargar_parametros(db_session, HOY, criterios=False))}
    assert nuevos["6"] == d("0.14") and nuevos["3"] == d("0.089")
    # el motor ya usa el valor nuevo, y a una fecha anterior sigue el viejo (historial)
    assert {x["plan"]: x["pct"] for x in pc.cuotas_ml(m.cargar_parametros(db_session, date(2026, 10, 1), criterios=False))}["6"] == d("0.134")


def test_endpoints_get_con_criterios_y_post_derivado_a_criterios(monkeypatch, db_session):
    @contextmanager
    def _ses():
        yield db_session
    monkeypatch.setattr(api, "sesion", _ses)
    g = api.pricing_ml_cuotas(HOY)
    assert [str(x["pct_texto"]) for x in g["planes"]] == ["5", "8.5", "12.9", "17.3", "20.8"]  # los de «Criterios de precio»
    with pytest.raises(api.HTTPException) as e:
        api.pricing_ml_cuotas_editar(api.CuotasMLIn(planes={"12": 22.5}, cargado_por="maxx", vigente_desde=HOY, confirmar=True))
    assert e.value.status_code == 409 and "Criterios de precio" in e.value.detail
    assert str(api.pricing_ml_cuotas(HOY)["planes"][-1]["pct_texto"]) == "20.8"  # no escribió nada
