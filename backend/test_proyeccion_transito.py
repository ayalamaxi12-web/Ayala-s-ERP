"""Tests de GET /proyeccion-2027/transito con una conexión FALSA a Táctica: sin red y con datos sintéticos (nada real)."""
import re
import sys
from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

import main
import proyeccion_transito as pt

CLAVE = "clave-de-prueba-123"
H = {"X-ERP-Key": CLAVE}
URL = "/proyeccion-2027/transito"
HOY = date(2026, 10, 19)


class FakeCursor:
    def __init__(self, resultados, log):
        self.resultados, self.log, self.i = resultados, log, -1

    def execute(self, sql, params=None):
        self.i += 1
        self.log["execute"].append((sql, params))

    def fetchmany(self, n):
        self.log["fetchmany"].append(n)
        return self.resultados[self.i][:n]


class FakeConn:
    def __init__(self, resultados, log):
        self.resultados, self.log = resultados, log

    def cursor(self):
        return FakeCursor(self.resultados, self.log)

    def close(self):
        self.log["cerrada"] = True


def fila(**k):
    base = dict(req_recid=1, req_id=100, req_numero=900, estado=1, proveedor="Proveedor Demo SA ", item_recid=1, codigo_item="SKU-A    ", en_maestro="SKU-A",
                codigo_respaldo=None, pedido=Decimal("10"), recibido=Decimal("4"), comprometido=Decimal("2"),
                fecha_item=datetime(2026, 11, 20), fecha_cab=datetime(2026, 9, 1))
    base.update(k)
    return base


@pytest.fixture
def cliente(monkeypatch):
    log = {"execute": [], "fetchmany": [], "cerrada": False, "conexiones": 0}
    est = {"resultados": [[fila()]]}

    def conectar():
        log["conexiones"] += 1
        return FakeConn(est["resultados"], log)

    monkeypatch.setattr(pt, "_conectar", conectar)
    monkeypatch.setenv("ERP_API_KEY", CLAVE)
    c = TestClient(main.app, raise_server_exceptions=False)
    c.log, c.est = log, est
    return c


# ── Acceso ───────────────────────────────────────────────────────────────

def test_sin_clave_401_y_no_se_conecta(cliente):
    assert cliente.get(URL).status_code == 401 and cliente.get(URL + "?diagnostico=1", headers={"X-ERP-Key": "x"}).status_code == 401
    assert cliente.log["conexiones"] == 0


def test_sin_clave_en_el_servidor_falla_cerrado(cliente, monkeypatch):
    monkeypatch.delenv("ERP_API_KEY")
    assert cliente.get(URL, headers=H).status_code == 503 and cliente.log["conexiones"] == 0


# ── Fechas ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("item,cab,esperado", [
    (datetime(2026, 12, 1), datetime(2026, 9, 1), (date(2026, 12, 1), None)),            # manda la del ítem
    (None, datetime(2026, 9, 1), (date(2026, 9, 1), None)),                              # si el ítem no tiene, la de cabecera
    (None, None, (None, "nula")),
    (datetime(2001, 1, 1), datetime(2026, 9, 1), (date(2001, 1, 1), "placeholder_2001")),
    (date(2019, 12, 31), None, (date(2019, 12, 31), "anterior_2020")),
    (date(2020, 1, 1), None, (date(2020, 1, 1), None)),                                  # 2020-01-01 ya es válida
])
def test_clasificar_fecha(item, cab, esperado):
    assert pt.clasificar_fecha(item, cab) == esperado


# ── Modo normal ──────────────────────────────────────────────────────────

def test_modo_normal_una_consulta_fija_y_pendiente_calculado(cliente):
    r = cliente.get(URL, headers=H)
    assert r.status_code == 200
    (sql, params), = cliente.log["execute"]
    assert sql == pt._SQL_ITEMS and params is None and cliente.log["cerrada"] and cliente.log["fetchmany"] == [pt.TOPE_FILAS + 1]
    j = r.json()
    it, = j["items"]
    assert (it["pedido"], it["recibido"], it["comprometido"], it["pendiente"]) == (10, 4, 2, 6)
    assert it["sku"] == "SKU-A" and it["proveedor"] == "Proveedor Demo SA" and it["fecha_estimada"] == "2026-11-20" and it["fecha_invalida"] is None
    assert j["por_sku"] == [{"sku": "SKU-A", "pendiente": 6, "proxima_fecha": "2026-11-20", "requerimientos": ["900"], "proveedores": ["Proveedor Demo SA"]}]


def test_pendiente_nunca_negativo_y_respaldo_de_sku():
    items, resumen, _ = pt.armar_respuesta([fila(pedido=3, recibido=5, codigo_item="  ", codigo_respaldo="SKU-RESP  ", en_maestro=None)], HOY)
    assert items[0]["pendiente"] == 0 and items[0]["sku"] == "SKU-RESP" and resumen[0]["pendiente"] == 0


def test_antiguedad_y_fecha_de_cabecera_como_respaldo():
    items, _, _ = pt.armar_respuesta([fila(fecha_item=None, fecha_cab=datetime(2026, 7, 1))], HOY)
    assert items[0]["fecha_estimada"] == "2026-07-01" and items[0]["antiguedad_dias"] == (HOY - date(2026, 7, 1)).days


def test_informe_de_calidad():
    filas = [
        fila(req_id=1, req_numero=11, item_recid=1, fecha_cab=datetime(2026, 1, 1)),                                    # viejo (> 90 días)
        fila(req_id=2, req_numero=12, item_recid=2, fecha_item=datetime(2001, 1, 1), fecha_cab=datetime(2026, 10, 1)),  # placeholder
        fila(req_id=3, req_numero=13, item_recid=3, fecha_item=None, fecha_cab=None),                                   # nula
        fila(req_id=4, req_numero=14, item_recid=4, fecha_item=datetime(2018, 5, 5), fecha_cab=datetime(2026, 10, 1)),  # anterior a 2020
        fila(req_id=5, req_numero=15, item_recid=5, codigo_item="SKU-X", en_maestro=None, fecha_cab=datetime(2026, 10, 1)),   # fuera del maestro
        fila(req_id=5, req_numero=15, item_recid=6, codigo_item="SKU-X", en_maestro=None, fecha_cab=datetime(2026, 10, 1)),   # duplicado
        fila(req_id=6, req_numero=16, item_recid=7, codigo_item=None, codigo_respaldo=None, en_maestro=None, fecha_cab=datetime(2026, 10, 1)),  # sin SKU
    ]
    items, resumen, q = pt.armar_respuesta(filas, HOY)
    assert q["viejos_pendientes"] == {"items": 1, "requerimientos": ["11"]}
    assert q["fechas_invalidas"] == {"total": 3, "nula": 1, "placeholder_2001": 1, "anterior_2020": 1}
    assert q["duplicados"]["total"] == 1 and q["duplicados"]["muestra"] == [{"req_numero": 15, "sku": "SKU-X", "veces": 2}]
    assert q["sku_fuera_del_maestro"] == {"total": 1, "muestra": ["SKU-X"]}
    assert q["items_sin_sku"] == 1 and all(s["sku"] for s in resumen)
    assert items[1]["fecha_estimada"] is None and items[1]["fecha_invalida"] == "placeholder_2001"


def test_resumen_por_sku_suma_y_toma_la_fecha_valida_mas_cercana():
    filas = [fila(req_numero=1, item_recid=1, pedido=10, recibido=0, fecha_item=datetime(2026, 12, 1)),
             fila(req_numero=2, item_recid=2, pedido=5, recibido=0, fecha_item=datetime(2026, 11, 5), proveedor="Otro"),
             fila(req_numero=3, item_recid=3, pedido=7, recibido=0, fecha_item=datetime(2001, 1, 1))]
    _, resumen, _ = pt.armar_respuesta(filas, HOY)
    assert resumen == [{"sku": "SKU-A", "pendiente": 22, "proxima_fecha": "2026-11-05", "requerimientos": ["1", "2", "3"], "proveedores": ["Otro", "Proveedor Demo SA"]}]


def test_tope_de_filas_marca_truncado(cliente, monkeypatch):
    monkeypatch.setattr(pt, "TOPE_FILAS", 3)
    cliente.est["resultados"] = [[fila(item_recid=i) for i in range(10)]]
    j = cliente.get(URL, headers=H).json()
    assert j["truncado"] is True and j["total_items"] == 3 and cliente.log["fetchmany"] == [4]


# ── Modo diagnóstico ─────────────────────────────────────────────────────

def _res_diag(con_reqs):
    r = [[{"estado": 1, "requerimientos": 5, "items": 12, "items_fecha_invalida": 2}, {"estado": 3, "requerimientos": 1, "items": 1, "items_fecha_invalida": 0}],
         [{"estado": 1, "requerimientos": 3, "con_fecha_despacho": 2, "con_fecha_despacho_invalida": Decimal("1")}]]
    if con_reqs:
        r.append([{"req_recid": 7, "req_id": 1001, "req_numero": 11, "estado": 1, "coincide_id": 1, "coincide_numero": 0, "items": 2, "pedido": Decimal("10"), "recibido": Decimal("4"), "pendiente": Decimal("6"), "comprometido": Decimal("1")},
                  {"req_recid": 8, "req_id": 200, "req_numero": 1002, "estado": 3, "coincide_id": 0, "coincide_numero": 1, "items": 1, "pedido": 5, "recibido": 5, "pendiente": 0, "comprometido": 0}])
    return r


def test_diagnostico_sin_reqs_dos_consultas_sin_proveedores(cliente):
    cliente.est["resultados"] = _res_diag(False)
    r = cliente.get(URL + "?diagnostico=1", headers=H)
    assert r.status_code == 200 and [s for s, _ in cliente.log["execute"]] == [pt._SQL_DIAG_ESTADOS, pt._SQL_DIAG_DESPACHO]
    j = r.json()
    assert j["modo"] == "diagnostico" and "pedidos" not in j and j["por_estado"][0] == {"estado": 1, "requerimientos": 5, "items": 12, "items_fecha_invalida": 2}
    assert j["despacho_por_estado"][0]["con_fecha_despacho_invalida"] == 1
    assert '"proveedor"' not in r.text and "Proveedor Demo" not in r.text and "costo" not in r.text.lower().replace("proveedores ni costos", "")


def test_diagnostico_con_reqs_los_manda_como_parametro_y_resume_coincidencias(cliente):
    cliente.est["resultados"] = _res_diag(True)
    r = cliente.get(URL + "?diagnostico=1&reqs=1001,1002, 9999,1001", headers=H)
    assert r.status_code == 200
    sql, params = cliente.log["execute"][2]
    assert sql == pt._SQL_DIAG_REQS and params == {"reqs": ("1001", "1002", "9999")}  # sin repetidos, como texto y como parámetro
    j = r.json()
    assert j["pedidos"] == {"recibidos": 3, "coinciden_por_id": 1, "coinciden_por_numero": 1, "sin_coincidencia": ["9999"]}
    a, b = j["por_requerimiento"]
    assert (a["estado"], a["items"], a["pedido"], a["recibido"], a["comprometido"], a["coincide_id"]) == (1, 2, 10, 4, 1, 1) and b["coincide_numero"] == 1
    assert '"proveedor"' not in r.text and "Proveedor Demo" not in r.text


@pytest.mark.parametrize("q", ["reqs=abc", "reqs=1;DROP", "reqs=", "reqs=1,,x", "reqs=" + ",".join(str(i) for i in range(pt.MAX_REQS + 1)), "reqs=-5", "reqs=1.5"])
def test_reqs_invalidos_422_y_no_se_conecta(cliente, q):
    assert cliente.get(URL + "?diagnostico=1&" + q, headers=H).status_code == 422 and cliente.log["conexiones"] == 0


def test_reqs_sin_diagnostico_422_y_diagnostico_invalido(cliente):
    assert cliente.get(URL + "?reqs=1", headers=H).status_code == 422
    assert cliente.get(URL + "?diagnostico=5", headers=H).status_code == 422 and cliente.log["conexiones"] == 0


# ── Errores ──────────────────────────────────────────────────────────────

def test_error_de_conexion_no_filtra_el_mensaje(cliente, monkeypatch):
    def falla():
        raise OSError("fallo contra servidor-secreto-123 con usuario-secreto")

    monkeypatch.setattr(pt, "_conectar", falla)
    r = cliente.get(URL, headers=H)
    assert r.status_code == 502 and "OSError" in r.json()["detail"] and "secreto" not in r.text


def test_error_de_columna_inexistente_si_se_informa_pero_sin_el_resto(cliente, monkeypatch):
    class ProgrammingError(Exception):
        pass

    def falla():
        raise ProgrammingError(207, b"Invalid column name 'FechaEntrega'.DB-Lib error message 20018, severity 16:\nGeneral SQL Server error en servidor-secreto")

    monkeypatch.setattr(pt, "_conectar", falla)
    d = cliente.get(URL, headers=H).json()["detail"]
    assert "Invalid column name 'FechaEntrega'" in d and "secreto" not in d and "DB-Lib" not in d


def test_programming_error_que_no_es_de_esquema_solo_da_la_clase(monkeypatch):
    class ProgrammingError(Exception):
        pass

    assert pt._detalle_error(ProgrammingError(1, b"Login failed for user 'usuario-secreto'")) == "ProgrammingError"


# ── Solo lectura / construcción de las consultas ─────────────────────────

TODAS = [pt._SQL_ITEMS, pt._SQL_DIAG_ESTADOS, pt._SQL_DIAG_REQS, pt._SQL_DIAG_DESPACHO]


@pytest.mark.parametrize("sql", TODAS)
def test_cada_consulta_es_un_unico_select_de_solo_lectura(sql):
    s = " ".join(sql.split())
    assert s.upper().startswith("SELECT ") and ";" not in s and "--" not in s and "/*" not in s
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|EXEC|EXECUTE|MERGE|GRANT|INTO)\b", s, re.I)
    assert "{" not in s and "}" not in s                       # no quedó ningún hueco sin rellenar
    assert re.search(r"TOP \(\d+\)", s)                         # con tope


@pytest.mark.parametrize("sql", TODAS)
def test_toda_tabla_se_lee_sin_bloqueos(sql):
    s = " ".join(sql.split())
    for tabla in re.findall(r"\b(?:FROM|JOIN)\s+(requerimientos\w*|comprasitems|compras|fiscal|productos)\s+\w+", s):
        assert re.search(rf"\b{tabla}\s+\w+\s+WITH \(NOLOCK\)", s), tabla


def test_el_diagnostico_no_toca_proveedores_ni_costos():
    for sql in (pt._SQL_DIAG_ESTADOS, pt._SQL_DIAG_REQS, pt._SQL_DIAG_DESPACHO):
        assert not re.search(r"fiscal|RazonSocial|proveedor|costo|precio|importe", sql, re.I)


def test_identificadores_de_columna_son_solo_palabras():
    for v in (pt.C_PEDIDO, pt.C_FECHA_ITEM, pt.C_FECHA_CAB, pt.C_PRODUCTO):
        assert re.fullmatch(r"\w+", v)


def test_el_modulo_temporal_ya_no_existe():
    with pytest.raises(ImportError):
        __import__("proyeccion_descubrir_esquema")
    assert "descubrir-esquema" not in str([r.path for r in main.app.routes])


def test_timeouts_configurados_en_la_conexion(monkeypatch):
    visto = {}

    class Pym:
        @staticmethod
        def connect(**kw):
            visto.update(kw)
            return FakeConn([], {})

    monkeypatch.setitem(sys.modules, "pymssql", Pym)
    for v in ("SERVER", "USER", "PASSWORD", "DATABASE"):
        monkeypatch.setenv("RENT_TACTICA_SQL_" + v, "dato-de-prueba")
    pt._conectar()
    assert visto["login_timeout"] == pt.LOGIN_TIMEOUT_SEG and visto["timeout"] == pt.QUERY_TIMEOUT_SEG and visto["as_dict"] is True
