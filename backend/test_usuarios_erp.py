"""Usuarios del ERP: login con usuario y contraseña, accesos por módulo, sesiones firmadas y administración solo para el admin."""
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import main
import usuarios_erp as UE
from rentabilidad import db as _db
from rentabilidad.db import Base
from rentabilidad.models import UsuarioErp


@pytest.fixture
def sesion_fn(monkeypatch):
    monkeypatch.setenv("ERP_SESSION_SECRET", "secreto-de-prueba")
    monkeypatch.delenv("ERP_ADMIN_USER", raising=False)
    monkeypatch.delenv("ERP_ADMIN_PASSWORD", raising=False)
    UE._FALLOS.clear()
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(eng, tables=[UsuarioErp.__table__])
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


def test_clave_hasheada_y_verificacion():
    h = UE.hashear("MiClave1234")
    assert h.startswith("scrypt$") and "MiClave1234" not in h and UE.hashear("MiClave1234") != h        # nunca en claro y con sal distinta
    assert UE.verificar_clave("MiClave1234", h) and not UE.verificar_clave("otra", h) and not UE.verificar_clave("x", "basura")


def test_sin_usuarios_el_erp_sigue_abierto_y_con_el_admin_de_las_variables_pide_login(sesion_fn, monkeypatch):
    assert UE.estado(sesion_fn) == {"login_requerido": False}
    monkeypatch.setenv("ERP_ADMIN_USER", "Maxi")
    monkeypatch.setenv("ERP_ADMIN_PASSWORD", "ClaveSegura99")
    assert UE.estado(sesion_fn) == {"login_requerido": True}                                              # se creó el admin con las variables
    r = UE.login(sesion_fn, "MAXI", "ClaveSegura99")
    assert r["usuario"]["rol"] == "admin" and set(r["usuario"]["modulos"]) == set(UE.IDS_MODULOS) and r["usuario"]["usuario"] == "maxi"


def test_variables_de_admin_flojas_no_crean_nada(sesion_fn, monkeypatch):
    monkeypatch.setenv("ERP_ADMIN_USER", "maxi")
    monkeypatch.setenv("ERP_ADMIN_PASSWORD", "corta")
    assert UE.estado(sesion_fn) == {"login_requerido": False}


def _admin(sesion_fn):
    UE.crear(sesion_fn, "admin", "Admin", "AdminClave1", [], rol="admin")
    return UE.login(sesion_fn, "admin", "AdminClave1")["token"]


def test_usuario_comun_ve_solo_los_modulos_tildados_y_en_orden_del_menu(sesion_fn):
    UE.crear(sesion_fn, "laura", "Laura", "ClaveLaura1", ["reglas", "dashboard", "dashboard", "fravega"])
    r = UE.login(sesion_fn, "Laura", "ClaveLaura1")
    assert r["usuario"]["modulos"] == ["dashboard", "fravega", "reglas"] and r["usuario"]["rol"] == "usuario"
    with pytest.raises(UE.UsuarioInvalido):
        UE.crear(sesion_fn, "pepe", "Pepe", "ClavePepe12", ["modulo-inventado"])


def test_login_incorrecto_inactivo_y_bloqueo_por_intentos(sesion_fn):
    UE.crear(sesion_fn, "laura", "Laura", "ClaveLaura1", ["dashboard"])
    for _ in range(UE.MAX_INTENTOS):
        with pytest.raises(UE.CredencialesInvalidas):
            UE.login(sesion_fn, "laura", "mala", "1.2.3.4", ahora=1000.0)
    with pytest.raises(UE.Bloqueado):
        UE.login(sesion_fn, "laura", "ClaveLaura1", "1.2.3.4", ahora=1001.0)                              # aun con la clave buena, bloqueada
    assert UE.login(sesion_fn, "laura", "ClaveLaura1", "1.2.3.4", ahora=1000.0 + UE.BLOQUEO_SEG + 1)["usuario"]["usuario"] == "laura"
    with pytest.raises(UE.CredencialesInvalidas):
        UE.login(sesion_fn, "no-existe", "x" * 10)
    UE.editar(sesion_fn, "laura", activo=False)
    with pytest.raises(UE.CredencialesInvalidas):
        UE.login(sesion_fn, "laura", "ClaveLaura1", "9.9.9.9")


def test_la_sesion_vence_se_invalida_al_cambiar_la_clave_o_desactivar_y_no_se_puede_falsificar(sesion_fn):
    UE.crear(sesion_fn, "laura", "Laura", "ClaveLaura1", ["dashboard"])
    tok = UE.login(sesion_fn, "laura", "ClaveLaura1")["token"]
    assert UE.usuario_de_token(sesion_fn, tok)["usuario"] == "laura"
    for malo in (tok[:-2] + "xx", "basura", "", tok.split(".")[0] + ".AAAA"):
        with pytest.raises(UE.CredencialesInvalidas):
            UE.usuario_de_token(sesion_fn, malo)
    with pytest.raises(UE.CredencialesInvalidas):
        UE.usuario_de_token(sesion_fn, tok, ahora=1e12)                                                    # vencida
    UE.editar(sesion_fn, "laura", clave="OtraClave1234")                                                  # el admin le resetea la clave
    with pytest.raises(UE.CredencialesInvalidas):
        UE.usuario_de_token(sesion_fn, tok)
    nuevo = UE.login(sesion_fn, "laura", "OtraClave1234")["token"]
    UE.editar(sesion_fn, "laura", activo=False)
    with pytest.raises(UE.CredencialesInvalidas):
        UE.usuario_de_token(sesion_fn, nuevo)


def test_sin_secreto_en_el_servidor_no_se_abren_sesiones(sesion_fn, monkeypatch):
    UE.crear(sesion_fn, "laura", "Laura", "ClaveLaura1", [])
    monkeypatch.delenv("ERP_SESSION_SECRET")
    monkeypatch.delenv("ERP_API_KEY", raising=False)
    with pytest.raises(UE.SesionNoConfigurada):
        UE.login(sesion_fn, "laura", "ClaveLaura1")


def test_validaciones_al_crear_y_siempre_queda_un_admin(sesion_fn):
    for args in (("ab", "x", "ClaveLarga1"), ("con espacio", "x", "ClaveLarga1"), ("ok-user", "x", "corta")):
        with pytest.raises(UE.UsuarioInvalido):
            UE.crear(sesion_fn, *args, [])
    UE.crear(sesion_fn, "admin", "A", "AdminClave1", [], rol="admin")
    with pytest.raises(UE.UsuarioInvalido):
        UE.crear(sesion_fn, "ADMIN", "A", "AdminClave1", [])                                               # mismo usuario con otras mayúsculas
    with pytest.raises(UE.UsuarioInvalido):
        UE.editar(sesion_fn, "admin", activo=False)                                                        # es el único admin
    with pytest.raises(UE.UsuarioInvalido):
        UE.editar(sesion_fn, "admin", rol="usuario")
    UE.crear(sesion_fn, "admin2", "B", "AdminClave2", [], rol="admin")
    assert UE.editar(sesion_fn, "admin", activo=False)["activo"] is False                                 # ahora sí: queda admin2


def test_cambiar_la_propia_clave(sesion_fn):
    UE.crear(sesion_fn, "laura", "Laura", "ClaveLaura1", ["dashboard"])
    with pytest.raises(UE.CredencialesInvalidas):
        UE.cambiar_clave(sesion_fn, "laura", "incorrecta", "NuevaClave123")
    r = UE.cambiar_clave(sesion_fn, "laura", "ClaveLaura1", "NuevaClave123")
    assert UE.usuario_de_token(sesion_fn, r["token"])["usuario"] == "laura"
    with pytest.raises(UE.CredencialesInvalidas):
        UE.login(sesion_fn, "laura", "ClaveLaura1")


def test_endpoints_login_yo_y_solo_el_admin_administra(sesion_fn):
    c = TestClient(main.app)
    UE.crear(sesion_fn, "admin", "Admin", "AdminClave1", [], rol="admin")
    assert c.get("/auth/estado").json() == {"login_requerido": True}
    assert c.post("/auth/login", json={"usuario": "admin", "clave": "mala"}).status_code == 401
    adm = c.post("/auth/login", json={"usuario": "admin", "clave": "AdminClave1"}).json()["token"]
    H = {"Authorization": f"Bearer {adm}"}
    r = c.post("/auth/usuarios", json={"usuario": "laura", "nombre": "Laura", "clave": "ClaveLaura1", "modulos": ["dashboard", "reglas"]}, headers=H)
    assert r.status_code == 200 and r.json()["usuario"]["modulos"] == ["dashboard", "reglas"]
    assert c.post("/auth/usuarios", json={"usuario": "x", "clave": "ClaveLaura1"}, headers=H).status_code == 422
    assert c.post("/auth/usuarios", json={"usuario": "otra", "clave": "ClaveLaura1"}).status_code == 401                          # sin sesión
    lau = c.post("/auth/login", json={"usuario": "laura", "clave": "ClaveLaura1"}).json()["token"]
    HL = {"Authorization": f"Bearer {lau}"}
    assert c.get("/auth/yo", headers=HL).json()["modulos"] == ["dashboard", "reglas"]
    assert c.get("/auth/usuarios", headers=HL).status_code == 403                                                                  # Laura no es admin
    assert c.put("/auth/usuarios/laura", json={"modulos": IDS}, headers=HL).status_code == 403                                      # ni puede darse más accesos
    assert c.put("/auth/usuarios/laura", json={"modulos": ["fravega"], "nombre": "Laura B"}, headers=H).json()["usuario"]["modulos"] == ["fravega"]
    assert c.get("/auth/yo", headers=HL).json()["modulos"] == ["fravega"]                                                          # el cambio se ve sin volver a ingresar
    assert [u["usuario"] for u in c.get("/auth/usuarios", headers=H).json()["usuarios"]] == ["admin", "laura"]
    assert "pass_hash" not in c.get("/auth/usuarios", headers=H).text and "ClaveLaura1" not in c.get("/auth/usuarios", headers=H).text
    assert len(c.get("/auth/modulos").json()["modulos"]) == len(UE.MODULOS)


IDS = list(UE.IDS_MODULOS)


def test_el_catalogo_de_modulos_coincide_con_el_menu_de_la_pagina():
    import re
    html = open(main.__file__.replace("backend/main.py", "docs/index.html"), encoding="utf-8").read()
    menu = re.findall(r'<a href="#" class="sidebar-item[^"]*" data-page="([^"]+)"', html)
    menu = [m for m in menu if m != "accesos"]                                                                                       # «accesos» es solo del admin y no está en el catálogo
    assert sorted(menu) == sorted(UE.IDS_MODULOS), set(menu) ^ set(UE.IDS_MODULOS)                                                # si se agrega o saca un módulo del menú, hay que actualizar la lista


def test_front_acceso_permitido():
    import subprocess, json
    from scripts.paridad_margenes import extraer_funcion
    src = open(main.__file__.replace("backend/main.py", "docs/index.html"), encoding="utf-8").read()
    fn = extraer_funcion(src, "accesoPermitido")
    js = "let SESION=null;" + fn + """
const a={usuario:{rol:'admin',modulos:[]}},u={usuario:{rol:'usuario',modulos:['dashboard']}};
console.log(JSON.stringify([accesoPermitido('config',null),accesoPermitido('accesos',null),accesoPermitido('accesos',a),accesoPermitido('config',a),accesoPermitido('dashboard',u),accesoPermitido('config',u),accesoPermitido('accesos',u)]));"""
    r = subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True)
    assert json.loads(r.stdout) == [True, False, True, True, True, False, False]
