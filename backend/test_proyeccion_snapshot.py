"""Tests de `proyeccion_snapshot.py` (tablero Proyección 2027, solo lectura) con datos SINTÉTICOS: nada de cifras reales."""
import copy
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import main
import proyeccion_snapshot as ps
from rentabilidad.db import Base
from rentabilidad.models import ProyeccionSnapshot

CLAVE = "clave-de-prueba-123"
H = {"X-ERP-Key": CLAVE}


def payload_sintetico(marca=1):
    return {
        "meta": {"schema_version": "1.0", "generado": "2000-01-01", "fuente": "sintetico", "moneda": "USD", "escenario": "base", "corte_ventas": "2000-01",
                 "corte_stock": "2000-01-02", "meses_capital": ["2000-02", "2000-03"], "advertencias": ["dato de prueba"]},
        "kpis": {"reyes": marca, "medios": 2, "reventar": 3},
        "parametros": [], "clases": [{"clase": "REY", "skus": marca}], "categorias": [], "plata_liberada": {}, "canales": [], "tactica": None,
        "capital": {"meses": ["2000-02", "2000-03"], "series": {"compras_usd": [1, 2]}, "kpis": {}},
        "alertas": {"conteos": [], "listas": {}}, "demanda_historica": [], "estacionalidad": [], "tc_bna": [],
        "skus": {"cols": ["sku", "clase"], "rows": [["SKU-A", "REY"], ["SKU-B", "MEDIO"]]}, "compras_sku": [], "pendientes": [],
    }


def payload_con_transito():
    """Extensión v1.1 (misma schema_version '1.0'): bloque `transito` inventado, requerimientos 9001, 9002..."""
    d = payload_sintetico()
    d["transito"] = {"meses": ["2000-02", "2000-03"], "unidades_por_mes": [10, 20], "resumen": {"NO_ESTA_EN_MARCELO": {"requerimientos": 1, "unidades": 5}},
                     "requerimientos": [{"requerimiento": 9001, "clasificacion": "FIRME", "unidades": 10, "fob": 100, "saldo": 50, "eta_marcelo": "2000-02-15"},
                                        {"requerimiento": 9002, "clasificacion": "NO_ESTA_EN_MARCELO", "unidades": 5, "fob": 0, "saldo": 0, "eta_marcelo": None}],
                     "pagos": []}
    return d


@pytest.fixture
def cliente(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(eng, tables=[ProyeccionSnapshot.__table__])
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

    monkeypatch.setattr(ps._db, "sesion", sesion)
    monkeypatch.setenv("ERP_API_KEY", CLAVE)
    return TestClient(main.app, raise_server_exceptions=False)


def test_sin_clave_401_en_las_tres_rutas(cliente):
    assert cliente.get("/proyeccion-2027/dashboard").status_code == 401
    assert cliente.get("/proyeccion-2027/versiones").status_code == 401
    assert cliente.post("/proyeccion-2027/snapshot", json=payload_sintetico()).status_code == 401
    assert cliente.get("/proyeccion-2027/dashboard", headers={"X-ERP-Key": "otra"}).status_code == 401


def test_sin_clave_en_el_servidor_falla_cerrado(cliente, monkeypatch):
    monkeypatch.delenv("ERP_API_KEY")
    assert cliente.get("/proyeccion-2027/dashboard").status_code == 503
    assert cliente.get("/proyeccion-2027/dashboard", headers=H).status_code == 503
    assert cliente.post("/proyeccion-2027/snapshot", json=payload_sintetico(), headers=H).status_code == 503


def test_sin_snapshot_404(cliente):
    assert cliente.get("/proyeccion-2027/dashboard", headers=H).status_code == 404


def test_subir_y_leer_ultimo(cliente):
    r = cliente.post("/proyeccion-2027/snapshot", json=payload_sintetico(1), headers=H)
    assert r.status_code == 200 and r.json()["version"] == 1
    g = cliente.get("/proyeccion-2027/dashboard", headers=H)
    assert g.status_code == 200 and g.json() == payload_sintetico(1)
    assert g.headers["cache-control"] == "no-store" and g.headers["x-proyeccion-version"] == "1"


def test_versionado_y_volver_atras(cliente):
    for m in (1, 2, 3):
        cliente.post("/proyeccion-2027/snapshot", json=payload_sintetico(m), headers=H)
    assert cliente.get("/proyeccion-2027/dashboard", headers=H).json()["kpis"]["reyes"] == 3
    assert cliente.get("/proyeccion-2027/dashboard?version=1", headers=H).json()["kpis"]["reyes"] == 1
    assert cliente.get("/proyeccion-2027/dashboard?version=99", headers=H).status_code == 404
    v = cliente.get("/proyeccion-2027/versiones", headers=H).json()
    assert [x["version"] for x in v["versiones"]] == [3, 2, 1] and "payload" not in v["versiones"][0]


def test_conserva_las_ultimas_20(cliente):
    for m in range(25):
        assert cliente.post("/proyeccion-2027/snapshot", json=payload_sintetico(m), headers=H).status_code == 200
    vs = [x["version"] for x in cliente.get("/proyeccion-2027/versiones", headers=H).json()["versiones"]]
    assert vs == list(range(25, 5, -1)) and len(vs) == ps.CONSERVAR
    assert cliente.get("/proyeccion-2027/dashboard?version=5", headers=H).status_code == 404


def _sin(clave):
    d = payload_sintetico(); d.pop(clave); return d


def _mut(fn):
    d = payload_sintetico(); fn(d); return d


@pytest.mark.parametrize("cuerpo", [
    _sin("skus"), _sin("capital"), _sin("meta"),
    _mut(lambda d: d["meta"].update(schema_version="2.0")),
    _mut(lambda d: d["meta"].pop("generado")),
    _mut(lambda d: d["skus"]["rows"].append(["solo-una-columna"])),
    _mut(lambda d: d["capital"].update(series=[])),
])
def test_contrato_invalido_422_y_no_guarda(cliente, cuerpo):
    r = cliente.post("/proyeccion-2027/snapshot", json=cuerpo, headers=H)
    assert r.status_code == 422
    assert cliente.get("/proyeccion-2027/versiones", headers=H).json()["versiones"] == []


def test_cuerpo_no_json_o_no_objeto_422(cliente):
    assert cliente.post("/proyeccion-2027/snapshot", content=b"no es json", headers=H).status_code == 422
    assert cliente.post("/proyeccion-2027/snapshot", json=[1, 2], headers=H).status_code == 422


def test_cuerpo_demasiado_grande_413(cliente, monkeypatch):
    monkeypatch.setattr(ps, "MAX_BYTES", 100)
    assert cliente.post("/proyeccion-2027/snapshot", json=payload_sintetico(), headers=H).status_code == 413


def test_validar_payload_ok():
    assert ps.validar_payload(copy.deepcopy(payload_sintetico())) == []


def test_cors_expone_la_version_al_front(cliente):
    r = cliente.get("/proyeccion-2027/versiones", headers={**H, "Origin": "https://ayalamaxi12-web.github.io"})
    assert r.headers["access-control-allow-origin"] == "https://ayalamaxi12-web.github.io"
    cliente.post("/proyeccion-2027/snapshot", json=payload_sintetico(), headers=H)
    g = cliente.get("/proyeccion-2027/dashboard", headers={**H, "Origin": "https://ayalamaxi12-web.github.io"})
    assert "x-proyeccion-version" in g.headers["access-control-expose-headers"].lower()


def test_transito_es_extension_aceptada_y_se_devuelve_intacta(cliente):
    d = payload_con_transito()
    assert ps.validar_payload(copy.deepcopy(d)) == []
    assert cliente.post("/proyeccion-2027/snapshot", json=d, headers=H).status_code == 200
    assert cliente.get("/proyeccion-2027/dashboard", headers=H).json() == d


def test_transito_no_exime_las_claves_obligatorias(cliente):
    d = payload_con_transito()
    del d["skus"]
    assert "falta la clave 'skus'" in ps.validar_payload(d)
    assert cliente.post("/proyeccion-2027/snapshot", json=d, headers=H).status_code == 422
    assert cliente.get("/proyeccion-2027/dashboard", headers=H).status_code == 404


def test_snapshot_sin_transito_sigue_valido():
    assert "transito" not in payload_sintetico() and ps.validar_payload(payload_sintetico()) == []
