import pytest

import tactica_explorar as te


@pytest.mark.parametrize("sql", [
    "SELECT 1",
    "SELECT TOP 5 * FROM [dbo].[pedidos] WITH (NOLOCK)",
    "WITH x AS (SELECT 1 AS a) SELECT a FROM x",
    "SELECT [Update], 'delete me' FROM [dbo].[t] WITH (NOLOCK)",       # palabras dentro de identificadores/literales no cuentan
])
def test_select_permitido(sql):
    te.verificar_select(sql)


@pytest.mark.parametrize("sql", [
    "UPDATE pedidos SET x = 1", "DELETE FROM pedidos", "INSERT INTO t VALUES (1)", "SELECT * INTO copia FROM pedidos",
    "EXEC sp_who", "SELECT 1; DROP TABLE t", "DROP TABLE t", "TRUNCATE TABLE t", "SELECT 1; SELECT 2",
])
def test_escritura_bloqueada(sql):
    with pytest.raises(PermissionError):
        te.verificar_select(sql)


def test_tabla_siempre_con_nolock_y_nombre_valido():
    assert te.tabla("pedidos") == "[dbo].[pedidos] WITH (NOLOCK)"
    with pytest.raises(ValueError):
        te.tabla("pedidos; DROP TABLE x")
