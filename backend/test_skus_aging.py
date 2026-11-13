"""Listado de SKUs de aging (Criterios de precio): cada PM carga los suyos, pide operador, no duplica y deja historial."""
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import main
import skus_aging as SA
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
    return sesion


def test_sin_nada_guardado_el_listado_esta_vacio(sesion_fn):
    assert SA.leer(sesion_fn) == {"skus": [], "historial": []}


def test_agrega_varios_skus_de_un_pm_y_quedan_en_el_historial(sesion_fn):
    r = SA.agregar(sesion_fn, "TN1060COMP\nCF283ACOMP, W1105ACOMP ;  \n", "Laura", "stock viejo", "Natalia")
    assert r == {"agregados": ["TN1060COMP", "CF283ACOMP", "W1105ACOMP"], "ya_estaban": []}
    d = SA.leer(sesion_fn)
    assert [(x["sku"], x["pm"], x["motivo"], x["operador"]) for x in d["skus"]] == [("TN1060COMP", "Laura", "stock viejo", "Natalia"), ("CF283ACOMP", "Laura", "stock viejo", "Natalia"),
                                                                               ("W1105ACOMP", "Laura", "stock viejo", "Natalia")]
    assert [h["accion"] for h in d["historial"]] == ["agregar"] * 3


def test_no_duplica_aunque_cambien_mayusculas_o_espacios_y_dice_de_quien_es(sesion_fn):
    SA.agregar(sesion_fn, "TN1060COMP", "Laura", "", "Natalia")
    r = SA.agregar(sesion_fn, ["tn1060comp", "CHOPP BLUE -16OZ"], "Matias", "", "Macarena")
    assert r["agregados"] == ["CHOPP BLUE -16OZ"] and r["ya_estaban"] == [{"sku": "TN1060COMP", "pm": "Laura"}]
    assert len(SA.leer(sesion_fn)["skus"]) == 2
    assert SA.agregar(sesion_fn, "chopp blue-16oz", "Matias", "", "Macarena")["ya_estaban"][0]["sku"] == "CHOPP BLUE -16OZ"       # el espacio interno no cuenta


def test_pide_operador_pm_y_skus(sesion_fn):
    for args in (("A1", "Laura", "", ""), ("A1", "", "", "Natalia"), ("  \n ,; ", "Laura", "", "Natalia"), ("X" * 81, "Laura", "", "Natalia")):
        with pytest.raises(SA.SkuAgingInvalido):
            SA.agregar(sesion_fn, *args)
    assert SA.leer(sesion_fn)["skus"] == []                                                       # no se guardó nada


def test_quitar_pide_operador_deja_historial_y_falla_si_no_esta(sesion_fn):
    SA.agregar(sesion_fn, "A1,B2", "Laura", "m", "Natalia")
    with pytest.raises(SA.SkuAgingInvalido):
        SA.quitar(sesion_fn, "A1", "")
    with pytest.raises(SA.SkuAgingInvalido):
        SA.quitar(sesion_fn, "ZZZ", "Natalia")
    assert SA.quitar(sesion_fn, " a1 ", "Maxi A.") == {"quitado": "A1", "pm": "Laura"}
    d = SA.leer(sesion_fn)
    assert [x["sku"] for x in d["skus"]] == ["B2"]
    assert d["historial"][-1]["accion"] == "quitar" and d["historial"][-1]["operador"] == "Maxi A."


def test_endpoints_agregar_listar_y_quitar(sesion_fn, monkeypatch):
    monkeypatch.setenv("ERP_API_KEY", "k-test")
    c = TestClient(main.app)
    h = {"X-ERP-Key": "k-test"}
    r = c.post("/criterios/skus-aging", json={"skus": "A1\nB2", "pm": "Laura", "motivo": "x", "operador": "Natalia"}, headers=h)
    assert r.status_code == 200 and r.json()["agregados"] == ["A1", "B2"]
    assert c.get("/criterios/skus-aging").json()["skus"][0]["sku"] == "A1"                        # leer no necesita clave
    assert c.post("/criterios/skus-aging", json={"skus": "C3", "pm": "Laura", "operador": ""}, headers=h).status_code == 422
    assert c.post("/criterios/skus-aging/quitar", json={"sku": "A1", "operador": "Natalia"}, headers=h).json()["quitado"] == "A1"
    assert c.post("/criterios/skus-aging", json={"skus": "C3", "pm": "Laura", "operador": "Natalia"}).status_code in (401, 403)   # escribir sí necesita la clave
