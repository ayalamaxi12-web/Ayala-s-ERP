"""Tests de `erp_auth.py` (clave X-ERP-Key) — sin red real.

Los de integración usan la app real (`main.app`) con TestClient SIN context
manager, así no corre el startup (migraciones) y no hace falta base de datos.
"""
import pytest
from fastapi.testclient import TestClient

import main
from erp_auth import clave_valida, requiere_clave

CLAVE = "clave-de-prueba-123"


@pytest.fixture
def cliente():
    return TestClient(main.app, raise_server_exceptions=False)


@pytest.fixture
def con_clave(monkeypatch):
    monkeypatch.setenv("ERP_API_KEY", CLAVE)


@pytest.fixture
def sin_clave(monkeypatch):
    monkeypatch.delenv("ERP_API_KEY", raising=False)


# ── Qué rutas exigen clave ───────────────────────────────────────────

@pytest.mark.parametrize("metodo,path", [
    ("PUT", "/ml-proxy/MLA123"),
    ("POST", "/ml-proxy"),
    ("POST", "/ecom/update-price"),
    ("POST", "/ecom/set-price-rule"),
    ("POST", "/ml-ofertas/item/MLA1/activar"),
    ("POST", "/ml-ofertas/item/MLA1/sacar"),
    ("POST", "/ml-ofertas/item/MLA1/activar-campana"),
    ("POST", "/ayala-core/item/MLA1/aplicar-precio"),
    ("POST", "/ml/tracker/run"),
    ("POST", "/competidores/refresh"),
    ("POST", "/rentabilidad/cierres/ecom"),
    ("DELETE", "/intel-comercial/referencias/1"),
    ("GET", "/ml/token"),
    ("GET", "/ml/token/"),
    ("GET", "/ml-proxy"),
])
def test_rutas_protegidas(metodo, path):
    assert requiere_clave(metodo, path)


@pytest.mark.parametrize("metodo,path", [
    ("GET", "/"),
    ("GET", "/health"),
    ("GET", "/tc/bna"),
    ("GET", "/jobs"),
    ("GET", "/ml-ofertas/status/abc"),
    ("GET", "/ayala-core/skus"),
    ("GET", "/rentabilidad/reporte/ecom/diario"),
    ("GET", "/rentabilidad/reporte/pricing/ofertas"),
    ("OPTIONS", "/ml-proxy"),
    ("OPTIONS", "/ecom/update-price"),
])
def test_rutas_abiertas(metodo, path):
    assert not requiere_clave(metodo, path)


def test_clave_valida():
    assert clave_valida(CLAVE, CLAVE)
    assert not clave_valida(CLAVE, "otra")
    assert not clave_valida(CLAVE, "")
    assert not clave_valida(CLAVE, None)
    assert not clave_valida(CLAVE, "clave-de-prueba-12")  # prefijo
    assert not clave_valida(CLAVE, "ñandú")  # no-ASCII no revienta


# ── Modo activo (ERP_API_KEY definida) ───────────────────────────────

def test_escritura_sin_clave_da_401(cliente, con_clave):
    r = cliente.post("/ecom/update-price", json={})
    assert r.status_code == 401
    assert "X-ERP-Key" in r.json()["detail"]


def test_escritura_con_clave_incorrecta_da_401(cliente, con_clave):
    r = cliente.put("/ml-proxy/MLA1", json={}, headers={"X-ERP-Key": "mala"})
    assert r.status_code == 401


def test_ml_token_sin_clave_da_401_y_no_filtra_token(cliente, con_clave, monkeypatch):
    monkeypatch.setattr(main, "get_ml_token", lambda: "TOKEN-SECRETO")
    r = cliente.get("/ml/token", params={"account": "IT"})
    assert r.status_code == 401
    assert "TOKEN-SECRETO" not in r.text


def test_ml_token_con_clave_responde(cliente, con_clave, monkeypatch):
    monkeypatch.setattr(main, "get_ml_token", lambda: "TOKEN-SECRETO")
    r = cliente.get("/ml/token", params={"account": "IT"}, headers={"X-ERP-Key": CLAVE})
    assert r.status_code == 200
    assert r.json()["token"] == "TOKEN-SECRETO"


def test_escritura_con_clave_correcta_llega_al_handler(cliente, con_clave):
    # Body inválido: el handler falla (500), lo importante es que NO sea 401.
    r = cliente.post("/ml-proxy", content=b"no-es-json", headers={"X-ERP-Key": CLAVE})
    assert r.status_code != 401


def test_lecturas_abiertas_con_clave_activa(cliente, con_clave):
    assert cliente.get("/health").status_code == 200
    assert cliente.get("/").status_code == 200


def test_reportes_n8n_siguen_con_su_propio_token(cliente, con_clave, monkeypatch):
    """Los GET de reportes no pasan por X-ERP-Key: los rige RENT_REPORTE_TOKEN."""
    monkeypatch.setenv("RENT_REPORTE_TOKEN", "token-n8n")
    r = cliente.get("/rentabilidad/reporte/ecom/diario")  # sin ningún token
    assert r.status_code == 401
    assert "X-ERP-Key" not in r.json()["detail"]  # lo rechazó el reporte, no nuestra clave


# ── Modo permisivo (ERP_API_KEY sin definir) ─────────────────────────

def test_permisivo_no_bloquea(cliente, sin_clave, monkeypatch):
    monkeypatch.setattr(main, "get_ml_token", lambda: "TOKEN")
    assert cliente.get("/ml/token").status_code == 200
    r = cliente.post("/ml-proxy", content=b"no-es-json")
    assert r.status_code != 401


def test_permisivo_con_clave_en_blanco_tampoco_bloquea(cliente, monkeypatch):
    monkeypatch.setenv("ERP_API_KEY", "   ")
    assert cliente.post("/ml-proxy", content=b"x").status_code != 401


def test_permisivo_loguea_el_request_sin_clave(cliente, sin_clave, capsys, monkeypatch):
    import erp_auth
    monkeypatch.setattr(erp_auth, "_avisados", set())
    cliente.post("/ml-proxy", content=b"x", headers={"Origin": "https://ayalamaxi12-web.github.io"})
    salida = capsys.readouterr().out
    assert "[auth] PERMISIVO" in salida and "POST /ml-proxy" in salida


# ── CORS ─────────────────────────────────────────────────────────────

FRONT = "https://ayalamaxi12-web.github.io"


def test_cors_preflight_del_front_permite_x_erp_key(cliente):
    r = cliente.options("/ecom/update-price", headers={
        "Origin": FRONT, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-erp-key"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == FRONT
    assert "x-erp-key" in r.headers["access-control-allow-headers"].lower()


def test_cors_no_abre_a_otros_origenes(cliente):
    r = cliente.options("/ecom/update-price", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in r.headers
    r = cliente.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_el_401_lleva_headers_cors_para_que_el_front_lo_lea(cliente, con_clave):
    r = cliente.post("/ecom/update-price", json={}, headers={"Origin": FRONT})
    assert r.status_code == 401
    assert r.headers["access-control-allow-origin"] == FRONT


# ── /auth/check (el front lo usa para "Testear") ─────────────────────

def test_auth_check_con_clave_activa(cliente, con_clave):
    assert cliente.post("/auth/check").status_code == 401
    r = cliente.post("/auth/check", headers={"X-ERP-Key": CLAVE})
    assert r.status_code == 200 and r.json() == {"ok": True, "clave_activa": True}


def test_auth_check_permisivo(cliente, sin_clave):
    r = cliente.post("/auth/check")
    assert r.status_code == 200 and r.json() == {"ok": True, "clave_activa": False}
