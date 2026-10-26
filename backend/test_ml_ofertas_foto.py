"""Ofertas ML: foto guardada y lectura automática de la mañana (`ml_ofertas_foto`). Datos sintéticos, sin red."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import main
import ml_ofertas
import ml_ofertas_foto as mof
from rentabilidad import db as _db
from rentabilidad.db import Base
from rentabilidad.models import MlAlerta, MlFoto, MlLoteCache

AR = timezone(timedelta(hours=-3))


def _utc(y, mo, d, h, mi):           # hora ARGENTINA -> UTC
    return datetime(y, mo, d, h, mi, tzinfo=AR).astimezone(timezone.utc)


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
    mof._activo["job_id"] = None
    return sesion


def test_toca_actualizar_solo_despues_de_la_hora_y_sin_foto_de_hoy():
    asi = lambda *a: mof.toca_actualizar(_utc(2026, 10, 27, *a), *RESTO)
    RESTO = (None, None)
    assert not asi(6, 29) and asi(6, 30) and asi(11, 0)                         # antes de las 06:30 no; después sí
    ayer = _utc(2026, 10, 26, 6, 40).replace(tzinfo=None)
    RESTO = (ayer, None)
    assert asi(6, 30)                                                           # la foto es de ayer: toca
    hoy_temprano = _utc(2026, 10, 27, 6, 45).replace(tzinfo=None)
    RESTO = (hoy_temprano, None)
    assert not asi(9, 0)                                                        # ya hay una foto de hoy (también si alguien la pidió a mano)


def test_tras_un_fallo_espera_30_minutos_y_vuelve_a_intentar():
    fallo = _utc(2026, 10, 27, 7, 0).replace(tzinfo=None)
    assert not mof.toca_actualizar(_utc(2026, 10, 27, 7, 20), None, fallo)
    assert mof.toca_actualizar(_utc(2026, 10, 27, 7, 31), None, fallo)


def test_la_hora_y_el_apagado_se_configuran_por_entorno(monkeypatch):
    monkeypatch.setenv("OFERTAS_AUTO_HORA", "05:15")
    assert mof.hora_objetivo() == (5, 15)
    monkeypatch.setenv("OFERTAS_AUTO_HORA", "basura")
    assert mof.hora_objetivo() == (6, 30)
    monkeypatch.setenv("OFERTAS_AUTO", "0")
    assert mof.auto_activa() is False and mof.iniciar_programador(lambda: 1) is None


def _fake_job(resultado, status="done"):
    def iniciar_job(job_id, cuentas, propias, tc):
        ml_ofertas._jobs[job_id] = {"status": status, "log": ["listo" if status == "done" else "Error: ML 500"], "result": resultado, "progress": None}
    return iniciar_job


def test_la_lectura_se_guarda_y_cualquiera_la_ve_con_su_fecha(sesion_fn, monkeypatch):
    monkeypatch.setattr(ml_ofertas, "iniciar_job", _fake_job({"filas": [{"item_id": "MLA1"}], "incidencias": [], "tc": 1500.0}))
    mof.correr_y_guardar("job1", 1500.0, "automatica")
    v = TestClient(main.app).get("/ml-ofertas/foto").json()
    assert v["existe"] and v["payload"]["filas"][0]["item_id"] == "MLA1" and v["payload"]["origen"] == "automatica"
    assert v["obtenido_en"].endswith("Z") and v["auto"]["hora"] == "06:30" and v["job_id"] is None
    meta = TestClient(main.app).get("/ml-ofertas/foto", params={"meta": True}).json()
    assert meta["existe"] and "payload" not in meta


def test_si_la_lectura_falla_se_conserva_la_foto_anterior_y_se_avisa(sesion_fn, monkeypatch):
    monkeypatch.setattr(ml_ofertas, "iniciar_job", _fake_job({"filas": [{"item_id": "MLA1"}], "incidencias": [], "tc": 1500.0}))
    mof.correr_y_guardar("job1", 1500.0, "automatica")
    monkeypatch.setattr(ml_ofertas, "iniciar_job", _fake_job(None, status="error"))
    mof.correr_y_guardar("job2", 1500.0, "automatica")
    v = TestClient(main.app).get("/ml-ofertas/foto").json()
    assert v["existe"] and v["payload"]["filas"][0]["item_id"] == "MLA1" and v["error_msg"] and "https" not in v["error_msg"]


def test_una_sola_lectura_a_la_vez(sesion_fn):
    tareas = []
    ml_ofertas._jobs.pop("x", None)
    a = mof.lanzar(lambda fn, *args: tareas.append(args), 1500.0, "manual")
    b = mof.lanzar(lambda fn, *args: tareas.append(args), 1500.0, "manual")
    assert a["status"] == "started" and b == {"job_id": a["job_id"], "status": "ya_corriendo"} and len(tareas) == 1
    assert mof.vista()["job_id"] == a["job_id"]            # y la pantalla de otra persona se engancha a esa
