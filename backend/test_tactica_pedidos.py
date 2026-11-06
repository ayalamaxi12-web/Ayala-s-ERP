import pytest

import tactica_pedidos as tp


@pytest.mark.parametrize("sql", [
    "SELECT 1",
    "SELECT TOP 5 * FROM [dbo].[pedidos] WITH (NOLOCK)",
    "WITH x AS (SELECT 1 AS a) SELECT a FROM x",
    "SELECT [Update], 'delete me' FROM [dbo].[t] WITH (NOLOCK)",
])
def test_select_permitido(sql):
    tp.verificar_select(sql)


@pytest.mark.parametrize("sql", [
    "UPDATE pedidos SET x = 1", "DELETE FROM pedidos", "INSERT INTO t VALUES (1)", "SELECT * INTO copia FROM pedidos",
    "EXEC sp_who", "SELECT 1; DROP TABLE t", "DROP TABLE t", "TRUNCATE TABLE t", "SELECT 1; SELECT 2",
])
def test_escritura_bloqueada(sql):
    with pytest.raises(PermissionError):
        tp.verificar_select(sql)


def test_tabla_siempre_con_nolock_y_nombre_valido():
    assert tp.tabla("pedidos") == "[dbo].[pedidos] WITH (NOLOCK)"
    with pytest.raises(ValueError):
        tp.tabla("pedidos; DROP TABLE x")


class Cur:
    description = [("a",), ("b",), ("c",), ("d",)]

    def __init__(self):
        self.q = []

    def execute(self, sql, params=()):
        self.q.append(sql)
        self.last = sql

    def fetchall(self):
        s = self.last
        if "dm_db_partition_stats" in s:
            return [("dbo", "pedidos", 1500), ("dbo", "pedidositems", 4000), ("dbo", "pagos", 900)]
        if "INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA" in s:
            return [("RecID", "binary", 8, "NO"), ("Numero", "int", None, "NO"), ("Estado", "int", None, "NO"), ("FechaEmision", "datetime", None, "NO")]
        if "COUNT(DISTINCT" in s:
            return [(5,)]
        if "GROUP BY" in s:
            return [(1, 10, "a", "b", "c", "d", 99)]
        if "DISTINCT c.TABLE_NAME" in s:
            return [("pedidositems", "IDPedido")]
        if "foreign_keys" in s:
            return []
        return [("x", "y")]


def test_exploracion_completa_solo_lectura_y_con_nolock():
    c, inf = Cur(), tp.Informe()
    tp.explorar(c, inf, None)
    texto = "\n".join(inf.lineas)
    assert "Tabla de pedidos: dbo.pedidos" in texto and "`Estado`" in texto and "pedidositems" in texto
    for q in c.q:
        tp.verificar_select(q)
        assert "WITH (NOLOCK)" in q or "sys." in q or "INFORMATION_SCHEMA" in q
