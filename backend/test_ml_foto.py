"""Foto guardada, alertas y caché de lotes (`ml_foto.py`) y Full ML con foto (`ml_full_foto.py`) -- datos SINTÉTICOS, sin red."""
from contextlib import contextmanager
from datetime import timedelta

import pytest
import requests
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import main
import ml_foto
import ml_full
import ml_full_foto as mff
from ml_full import FactorPack, MLFullClient, MLCuotaAgotada
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

    monkeypatch.setattr(mff._db, "sesion", sesion)
    mff._jobs.clear(); mff._activo.clear()
    return sesion


# ── Foto ──

def test_la_foto_nueva_reemplaza_a_la_anterior_y_hay_una_sola_por_clave(sesion_fn):
    with sesion_fn() as db:
        ml_foto.guardar_exito(db, "m", "todas", "", {"v": 1}, "completa", 0, 1.0, [])
    with sesion_fn() as db:
        ml_foto.guardar_exito(db, "m", "todas", "", {"v": 2}, "completa", 0, 1.0, [])
        assert db.query(MlFoto).count() == 1
        assert ml_foto.leer(db, "m", "todas", "").payload == {"v": 2}


def test_otro_parametro_es_otra_foto(sesion_fn):
    with sesion_fn() as db:
        ml_foto.guardar_exito(db, "m", "todas", ml_foto.clave_params(dias=30), {"v": 1}, "completa", 0, 1.0, [])
        ml_foto.guardar_exito(db, "m", "todas", ml_foto.clave_params(dias=15), {"v": 2}, "completa", 0, 1.0, [])
        assert db.query(MlFoto).count() == 2
        assert ml_foto.leer(db, "m", "todas").payload in ({"v": 1}, {"v": 2})   # sin params: la más reciente


def test_un_fallo_conserva_la_foto_anterior_y_anota_el_error(sesion_fn):
    with sesion_fn() as db:
        ml_foto.guardar_exito(db, "m", "todas", "", {"v": 1}, "completa", 0, 1.0, [])
        ml_foto.guardar_fallo(db, "m", "todas", "", "Mercado Libre respondió 429")
    with sesion_fn() as db:
        v = ml_foto.vista_foto(ml_foto.leer(db, "m", "todas", ""))
        assert v["payload"] == {"v": 1} and v["obtenido_en"] and v["error_msg"] == "Mercado Libre respondió 429" and v["error_en"]


def test_si_falla_al_guardar_la_nueva_queda_la_anterior_intacta(sesion_fn):
    with sesion_fn() as db:
        ml_foto.guardar_exito(db, "m", "todas", "", {"v": 1}, "completa", 0, 1.0, [{"tipo": "t", "clave": "A", "detalle": None}])
    with pytest.raises(RuntimeError):
        with sesion_fn() as db:
            ml_foto.guardar_exito(db, "m", "todas", "", {"v": 2}, "completa", 0, 1.0, [])
            raise RuntimeError("se cortó")
    with sesion_fn() as db:
        assert ml_foto.leer(db, "m", "todas", "").payload == {"v": 1}
        assert db.query(MlAlerta).one().estado == "activa"          # y las alertas tampoco se migraron


def test_el_mensaje_de_error_no_lleva_la_url():
    m = ml_foto.mensaje_para_usuario(RuntimeError("429 Client Error: Too Many Requests for url: https://api.mercadolibre.com/stock/fulfillment/operations/search?seller_id=1"))
    assert "http" not in m and "mercadolibre" not in m and "429" in m
    assert "429" in str(MLCuotaAgotada(429)) and "http" not in str(MLCuotaAgotada(429))


# ── Alertas ──

def _alerta(tipo, clave): return {"tipo": tipo, "clave": clave, "detalle": {"x": 1}}


def test_alertas_siguen_nuevas_y_ya_no_aparecen_sin_borrarse(sesion_fn):
    t0 = ml_foto.ahora()
    with sesion_fn() as db:
        ml_foto.sincronizar_alertas(db, "m", [_alerta("dif", "A"), _alerta("dif", "B")], t0)
    t1 = t0 + timedelta(hours=1)
    with sesion_fn() as db:
        r = ml_foto.sincronizar_alertas(db, "m", [_alerta("dif", "B"), _alerta("dif", "C")], t1)
        assert r == {"creadas": 1, "actualizadas": 1, "ya_no_aparecen": 1}
        por = {a["clave"]: a for a in ml_foto.listar_alertas(db, "m")}
    assert por["A"]["estado"] == "ya_no_aparece" and por["A"]["ultima_vez"].startswith(t0.isoformat()[:13])
    assert por["B"]["estado"] == "activa" and por["B"]["primera_vez"] < por["B"]["ultima_vez"]
    assert por["C"]["estado"] == "activa" and por["C"]["primera_vez"] == por["C"]["ultima_vez"]


def test_una_alerta_que_vuelve_a_aparecer_se_reactiva(sesion_fn):
    t0 = ml_foto.ahora()
    with sesion_fn() as db:
        ml_foto.sincronizar_alertas(db, "m", [_alerta("dif", "A")], t0)
        ml_foto.sincronizar_alertas(db, "m", [], t0)
        ml_foto.sincronizar_alertas(db, "m", [_alerta("dif", "A")], t0)
        assert db.query(MlAlerta).one().estado == "activa"


def test_foto_parcial_no_dice_que_ya_no_aparece_lo_que_no_pudo_leer(sesion_fn):
    t0 = ml_foto.ahora()
    with sesion_fn() as db:
        ml_foto.sincronizar_alertas(db, "m", [_alerta("dif", "A"), _alerta("dif", "B")], t0)
        ml_foto.sincronizar_alertas(db, "m", [], t0, no_tocar={"A"})
        por = {a.clave: a.estado for a in db.query(MlAlerta).all()}
    assert por == {"A": "activa", "B": "ya_no_aparece"}


def test_vistas_se_borran_a_los_90_dias_y_las_demas_nunca_solas(sesion_fn):
    t0 = ml_foto.ahora()
    with sesion_fn() as db:
        ml_foto.sincronizar_alertas(db, "m", [_alerta("dif", "A"), _alerta("dif", "B"), _alerta("dif", "C")], t0)
        ml_foto.sincronizar_alertas(db, "m", [_alerta("dif", "A"), _alerta("dif", "B")], t0)       # C: ya_no_aparece
        ids = {a["clave"]: a["id"] for a in ml_foto.listar_alertas(db, "m")}
        assert ml_foto.marcar_vista(db, ids["A"], t0)
        assert ml_foto.purgar_vistas(db, t0 + timedelta(days=89)) == 0
        assert ml_foto.purgar_vistas(db, t0 + timedelta(days=91)) == 1
        assert {a.clave for a in db.query(MlAlerta).all()} == {"B", "C"}
        assert ml_foto.marcar_vista(db, "no-existe") is False


# ── Lectura de ML: ritmo, reintentos, lotes y resultado parcial ──

class _Resp:
    def __init__(self, status, body=None, headers=None):
        self.status_code, self._b, self.headers = status, body, headers or {}
    def json(self): return self._b
    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error for url: https://x")


def test_get_real_reintenta_con_retry_after_y_despues_pasa(monkeypatch):
    respuestas = [_Resp(429, headers={"Retry-After": "3"}), _Resp(429), _Resp(200, {"ok": 1})]
    esperas = []
    monkeypatch.setattr(ml_full.requests, "get", lambda *a, **k: respuestas.pop(0))
    monkeypatch.setattr(ml_full.time, "sleep", lambda s: esperas.append(s))
    assert ml_full._get_real("https://api.mercadolibre.com/x", {}, {}) == {"ok": 1}
    assert esperas[:2] == [3.0, 4.0]                      # Retry-After manda; sin él, espera creciente (2, 4, ...)


def test_get_real_agota_los_reintentos_con_error_sin_url(monkeypatch):
    llamadas = []
    monkeypatch.setattr(ml_full.requests, "get", lambda *a, **k: llamadas.append(1) or _Resp(429))
    monkeypatch.setattr(ml_full.time, "sleep", lambda s: None)
    with pytest.raises(MLCuotaAgotada) as e:
        ml_full._get_real("https://api.mercadolibre.com/stock/fulfillment/operations/search", {}, {})
    assert len(llamadas) == ml_full.REINTENTOS and "http" not in str(e.value)


def test_espera_creciente_con_tope(monkeypatch):
    assert ml_full._espera_reintento(_Resp(429), 0) == 2.0 and ml_full._espera_reintento(_Resp(429), 4) == 32.0
    assert ml_full._espera_reintento(_Resp(429, headers={"Retry-After": "9999"}), 0) == ml_full.ESPERA_MAX_SEG


class _CacheMem:
    def __init__(self): self.d = {}
    def get(self, k): return self.d.get(k)
    def put(self, k, v): self.d[k] = v


def _op(inv, cant, fecha="2026-10-01T10:00:00Z"):
    return {"inventory_id": inv, "date_created": fecha, "detail": {"available_quantity": -cant}}


def test_un_lote_ya_leido_no_se_vuelve_a_pedir(monkeypatch):
    monkeypatch.setattr(ml_full, "SELLERS", {"IT": 1})
    pedidos = []
    def get(url, params, headers):
        pedidos.append(params["inventory_id"]); return {"results": [_op("I1", 2)]}
    ml = MLFullClient(get_fn=get, token_fn=lambda c: "t", cache=_CacheMem())
    a = ml.ventas_full_por_inventory("IT", ["I1"], "2026-09-01", "2026-10-01")
    b = ml.ventas_full_por_inventory("IT", ["I1"], "2026-09-01", "2026-10-01")
    assert a == b and a["I1"]["unidades"] == 2 and len(pedidos) == 1


def test_si_un_lote_falla_el_resto_sigue_y_queda_registrado(monkeypatch):
    monkeypatch.setattr(ml_full, "SELLERS", {"IT": 1})
    ids = [f"I{n:02d}" for n in range(25)]                 # 2 lotes: 20 + 5
    def get(url, params, headers):
        if "I00" in params["inventory_id"]:
            raise MLCuotaAgotada(429)
        return {"results": [_op("I24", 4)]}
    ml = MLFullClient(get_fn=get, token_fn=lambda c: "t")
    r = ml.ventas_full_por_inventory("IT", ids, "2026-09-01", "2026-10-01")
    assert r == {"I24": {"unidades": 4, "primera": "2026-10-01", "ultima": "2026-10-01"}}
    assert len(ml.lotes_fallidos) == 1 and ml.lotes_fallidos[0]["inventory_ids"][0] == "I00" and ml.lotes_fallidos[0]["tipo"] == "SALE_CONFIRMATION"


# ── Actualización completa con fakes ──

class _FakeML:
    def __init__(self, fallar_stock=(), lotes_fallidos=()):
        self.fallar_stock, self.lotes_fallidos, self.llamadas = set(fallar_stock), list(lotes_fallidos), 0
    def items_activos(self, c): return ["MLA1", "MLA2"] if c == "IT" else []
    def detalle_items(self, ids, c):
        return [{"id": i, "title": f"t{i}", "inventory_id": f"INV{i[-1]}", "seller_custom_field": f"SKU{i[-1]}", "shipping": {"logistic_type": "fulfillment"}} for i in ids]
    def stock_fulfillment(self, inv, c):
        self.llamadas += 1
        if inv in self.fallar_stock:
            raise MLCuotaAgotada(429)
        return {"available_quantity": 10}
    def ventas_full_por_inventory(self, c, ids, d, h): return {"INV1": {"unidades": 6, "primera": "2026-10-01", "ultima": "2026-10-20"}}
    def envios_pendientes_por_inventory(self, c, ids, d, h): return {}


class _FakeEcom:
    def factor_pack(self, item_id): return FactorPack(item_sku={f"SKU{item_id[-1]}": 1})
    def stock_full_por_sku(self, sku, parent=None): return 10 if sku == "SKU1" else 7
    def stock_disponible_por_sku(self, sku, parent=None): return 50


class _FakeTactica:
    def stock_por_sku(self, sku): return 5


def _correr(sesion_fn, modulo, ml, job="j1", **kw):
    mff._jobs[job] = {"status": "queued", "log": [], "progress": None}
    mff.actualizar(job, modulo, sesion_fn=sesion_fn, ml_fn=lambda cache: ml, ecom_fn=_FakeEcom, tactica_fn=_FakeTactica, **kw)
    return mff._jobs[job]


def test_actualizar_conciliacion_guarda_la_foto_y_las_alertas(sesion_fn, monkeypatch):
    monkeypatch.setattr(ml_full, "SELLERS", {"IT": 1, "MT": 2}); monkeypatch.setattr(mff, "SELLERS", {"IT": 1, "MT": 2}, raising=False)
    job = _correr(sesion_fn, "conciliacion", _FakeML())
    assert job["status"] == "done"
    with sesion_fn() as db:
        f = ml_foto.vista_foto(ml_foto.leer(db, mff.MOD_CONC, "todas", ""))
        al = ml_foto.listar_alertas(db, mff.MOD_CONC)
    assert f["estado"] == "completa" and {x["sku"] for x in f["payload"]["filas"]} == {"SKU1", "SKU2"}
    assert [(a["tipo"], a["clave"]) for a in al] == [("diferencia_stock", "SKU2")]           # SKU2: ML 10 vs Ecom 7


def test_conciliacion_parcial_muestra_lo_leido_y_completa_con_la_foto_anterior(sesion_fn, monkeypatch):
    monkeypatch.setattr(ml_full, "SELLERS", {"IT": 1, "MT": 2})
    _correr(sesion_fn, "conciliacion", _FakeML(), job="j1")
    job = _correr(sesion_fn, "conciliacion", _FakeML(fallar_stock={"INV2"}), job="j2")
    assert job["status"] == "done" and "incompletos para 1 SKU" in job["log"][-1]
    with sesion_fn() as db:
        f = ml_foto.vista_foto(ml_foto.leer(db, mff.MOD_CONC, "todas", ""))
        al = {a["clave"]: a["estado"] for a in ml_foto.listar_alertas(db, mff.MOD_CONC)}
    assert f["estado"] == "parcial" and f["incompletos"] == 1
    filas = {x["sku"]: x for x in f["payload"]["filas"]}
    assert filas["SKU2"].get("dato_anterior") is True and "dato_anterior" not in filas["SKU1"]
    assert al["SKU2"] == "activa"                                    # no se afirma que "ya no aparece" algo que no se pudo leer


def test_si_falla_todo_se_conserva_la_foto_anterior_y_el_job_termina_en_error(sesion_fn, monkeypatch):
    monkeypatch.setattr(ml_full, "SELLERS", {"IT": 1, "MT": 2})
    _correr(sesion_fn, "conciliacion", _FakeML(), job="j1")
    class Roto(_FakeML):
        def items_activos(self, c): raise MLCuotaAgotada(429)
    job = _correr(sesion_fn, "conciliacion", Roto(), job="j2")
    assert job["status"] == "error" and "429" in job["message"] and "http" not in job["message"]
    with sesion_fn() as db:
        f = ml_foto.vista_foto(ml_foto.leer(db, mff.MOD_CONC, "todas", ""))
    assert f["payload"] and f["error_msg"] and f["error_en"] and f["estado"] == "completa"
    assert mff._activo == {}                                         # nunca queda "corriendo"


def test_reposicion_comparte_la_conciliacion_y_marca_datos_incompletos(sesion_fn, monkeypatch):
    monkeypatch.setattr(ml_full, "SELLERS", {"IT": 1, "MT": 2})
    import ml_reposicion; monkeypatch.setattr(ml_reposicion, "SELLERS", {"IT": 1, "MT": 2})
    ml = _FakeML(lotes_fallidos=[{"cuenta": "IT", "tipo": "SALE_CONFIRMATION", "inventory_ids": ["INV2"]}])
    job = _correr(sesion_fn, "reposicion", ml, fecha_llegada=ml_foto.ahora().date() + timedelta(days=10))
    assert job["status"] == "done"
    with sesion_fn() as db:
        conc = ml_foto.leer(db, mff.MOD_CONC, "todas", "")
        rep = ml_foto.leer(db, mff.MOD_REPO, "todas", ml_foto.clave_params(dias_ventas=30, semanas_objetivo=3))
    assert conc is not None and conc.estado == "completa"           # la reposición dejó también la foto de conciliación
    assert rep.estado == "parcial" and rep.incompletos == 1
    inc = [f for f in rep.payload["filas"] if f.get("datos_incompletos")]
    assert [f["inventory_id"] for f in inc] == ["INV2"] and rep.payload["params"]["dias_ventas"] == 30
    llamadas = ml.llamadas
    job2 = _correr(sesion_fn, "reposicion", ml, job="j2", fecha_llegada=ml_foto.ahora().date() + timedelta(days=10))
    assert job2["status"] == "done" and ml.llamadas == llamadas     # reutilizó la conciliación guardada: no volvió a leer el stock


# ── Endpoints ──

@pytest.fixture
def cliente(sesion_fn):
    return TestClient(main.app)


def test_endpoints_foto_vacia_y_modulo_invalido(cliente):
    r = cliente.get("/ml-full/foto/conciliacion")
    assert r.status_code == 200 and r.json()["existe"] is False and r.json()["alertas"] == [] and r.json()["job_id"] is None
    assert cliente.get("/ml-full/foto/otro").status_code == 404
    assert cliente.post("/ml-full/foto/reposicion/actualizar").status_code == 422     # falta la fecha de llegada


def test_endpoint_estado_de_un_job_inexistente_es_not_found(cliente):
    assert cliente.get("/ml-full/foto/estado/nada").json() == {"status": "not_found"}


def test_endpoint_alerta_vista(cliente, sesion_fn):
    with sesion_fn() as db:
        ml_foto.sincronizar_alertas(db, mff.MOD_CONC, [_alerta("dif", "A")], ml_foto.ahora())
        aid = ml_foto.listar_alertas(db, mff.MOD_CONC)[0]["id"]
    assert cliente.post(f"/ml-full/foto/alertas/{aid}/vista").json() == {"ok": True}
    assert cliente.get("/ml-full/foto/conciliacion").json()["alertas"][0]["estado"] == "vista"
    assert cliente.post("/ml-full/foto/alertas/nada/vista").status_code == 404
