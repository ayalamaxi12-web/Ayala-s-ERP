"""Tests del endpoint TEMPORAL /proyeccion-2027/descubrir-esquema con una conexión FALSA a Táctica: no hay red ni cifras reales."""
import re

import pytest
from fastapi.testclient import TestClient

import main
import proyeccion_descubrir_esquema as de

CLAVE = "clave-de-prueba-123"
H = {"X-ERP-Key": CLAVE}
URL = "/proyeccion-2027/descubrir-esquema"


class FakeCursor:
    def __init__(self, filas, log):
        self.filas, self.log = filas, log

    def execute(self, *args, **kwargs):
        self.log["execute"].append((args, kwargs))

    def fetchmany(self, n):
        self.log["fetchmany"].append(n)
        return self.filas[:n]


class FakeConn:
    def __init__(self, filas, log):
        self.filas, self.log = filas, log

    def cursor(self):
        return FakeCursor(self.filas, self.log)

    def close(self):
        self.log["cerrada"] = True


def _filas(n):
    return [{"TABLE_NAME": f"tabla_demo_{i // 3}", "COLUMN_NAME": f"col{i}", "DATA_TYPE": "int", "EXTRA": "no debe salir"} for i in range(n)]


@pytest.fixture
def cliente(monkeypatch):
    log = {"execute": [], "fetchmany": [], "cerrada": False, "conexiones": 0}
    estado = {"filas": _filas(7)}

    def conectar():
        log["conexiones"] += 1
        return FakeConn(estado["filas"], log)

    monkeypatch.setattr(de, "_conectar", conectar)
    monkeypatch.setenv("ERP_API_KEY", CLAVE)
    c = TestClient(main.app, raise_server_exceptions=False)
    c.log, c.estado = log, estado
    return c


def test_sin_clave_o_clave_mala_401_y_no_se_conecta(cliente):
    assert cliente.get(URL).status_code == 401
    assert cliente.get(URL, headers={"X-ERP-Key": "otra"}).status_code == 401
    assert cliente.log["conexiones"] == 0


def test_sin_clave_en_el_servidor_falla_cerrado(cliente, monkeypatch):
    monkeypatch.delenv("ERP_API_KEY")
    assert cliente.get(URL, headers=H).status_code == 503 and cliente.log["conexiones"] == 0


def test_ejecuta_una_sola_sentencia_fija_y_sin_parametros(cliente):
    r = cliente.get(URL, headers=H)
    assert r.status_code == 200
    (args, kwargs), = cliente.log["execute"]
    assert args == (de._SQL,) and kwargs == {}  # sin segundo argumento: nada del request llega a la consulta
    assert cliente.log["cerrada"] is True and cliente.log["conexiones"] == 1


def test_devuelve_solo_las_tres_columnas(cliente):
    j = cliente.get(URL, headers=H).json()
    assert j["total"] == 7 and j["truncado"] is False and j["tope"] == de.TOPE_FILAS
    assert all(set(f) == {"TABLE_NAME", "COLUMN_NAME", "DATA_TYPE"} for f in j["filas"])


def test_parametros_del_usuario_se_ignoran(cliente):
    r = cliente.get(URL + "?tabla=usuarios&sql=DROP%20TABLE%20x&x=1", headers=H)
    assert r.status_code == 200 and cliente.log["execute"][0][0] == (de._SQL,)


def test_tope_de_filas_y_truncado(cliente, monkeypatch):
    monkeypatch.setattr(de, "TOPE_FILAS", 5)
    cliente.estado["filas"] = _filas(50)
    j = cliente.get(URL, headers=H).json()
    assert cliente.log["fetchmany"] == [6] and j["total"] == 5 and j["truncado"] is True and len(j["filas"]) == 5
    cliente.estado["filas"] = _filas(5)
    assert cliente.get(URL, headers=H).json()["truncado"] is False


def test_timeouts_configurados_en_la_conexion(monkeypatch):
    visto = {}

    class Pym:
        @staticmethod
        def connect(**kw):
            visto.update(kw)
            return FakeConn([], {"execute": [], "fetchmany": []})

    import sys
    monkeypatch.setitem(sys.modules, "pymssql", Pym)
    for v in ("SERVER", "USER", "PASSWORD", "DATABASE"):
        monkeypatch.setenv("RENT_TACTICA_SQL_" + v, "dato-de-prueba")
    de._conectar()
    assert visto["login_timeout"] == de.LOGIN_TIMEOUT_SEG and visto["timeout"] == de.QUERY_TIMEOUT_SEG and visto["as_dict"] is True


def test_error_de_conexion_no_filtra_el_mensaje(cliente, monkeypatch):
    def falla():
        raise OSError("fallo contra servidor-secreto-123 con usuario-secreto")

    monkeypatch.setattr(de, "_conectar", falla)
    r = cliente.get(URL, headers=H)
    assert r.status_code == 502 and "OSError" in r.json()["detail"]
    assert "secreto" not in r.text


def test_config_faltante_da_503_con_el_nombre_de_la_variable_y_no_el_valor(monkeypatch):
    monkeypatch.setenv("ERP_API_KEY", CLAVE)
    for v in ("SERVER", "USER", "PASSWORD", "DATABASE"):
        monkeypatch.delenv("RENT_TACTICA_SQL_" + v, raising=False)
    monkeypatch.setattr(de.config, "_env", lambda nombre, *a, **k: "")
    r = TestClient(main.app, raise_server_exceptions=False).get(URL, headers=H)
    assert r.status_code == 503 and "RENT_TACTICA_SQL_SERVER" in r.json()["detail"]


def test_el_sql_es_un_unico_select_de_solo_lectura():
    sql = " ".join(de._SQL.split())
    assert sql.upper().startswith("SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE ")
    assert ";" not in sql and "--" not in sql and "/*" not in sql
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|EXEC|EXECUTE|MERGE|GRANT|INTO)\b", sql, re.I)
    assert "%(" not in sql and "%s" not in sql  # los únicos % son los comodines de los LIKE
    assert re.findall(r"LIKE '%(\w+)%'", sql) == ["requer", "pedido", "compra", "import", "transit", "embarque"]
