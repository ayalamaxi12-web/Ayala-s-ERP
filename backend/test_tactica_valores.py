import pytest

import tactica_pedidos as tpd


class Cur:
    """Cursor de prueba: responde según la consulta y guarda todo lo que se le pide (para verificar que sea solo lectura)."""

    def __init__(self, columnas=("RecID", "Numero", "Estado", "Escenario"), distintos=3, otras=()):
        self.columnas, self.distintos, self.otras, self.q = columnas, distintos, otras, []

    def execute(self, sql, params=()):
        self.q.append(sql)
        self.sql = sql
        if "WHERE TABLE_SCHEMA" in sql:
            self.description = [("COLUMN_NAME",)]
        elif "WHERE COLUMN_NAME" in sql:
            self.description = [("TABLE_SCHEMA",), ("TABLE_NAME",)]
        elif "COUNT(DISTINCT" in sql:
            self.description = [("n",)]
        else:
            self.description = [("valor",), ("pedidos",), ("pendientes",), ("ejemplo_numero",)]

    def fetchall(self):
        if "WHERE TABLE_SCHEMA" in self.sql:
            return [(c,) for c in self.columnas]
        if "WHERE COLUMN_NAME" in self.sql:
            return list(self.otras)
        if "COUNT(DISTINCT" in self.sql:
            return [(self.distintos,)]
        return [("Pagado ", 150, 10, 27001), ("Sin pagar", 40, 30, 27002), (None, 5, 0, 999)]


def test_lista_valores_con_cantidades_y_ejemplo():
    c = Cur()
    r = tpd.valores_columna(c, "escenario")            # no distingue mayúsculas; usa el nombre real
    assert r["existe"] and r["columna"] == "Escenario" and r["distintos"] == 3
    assert r["valores"][0] == {"valor": "Pagado", "pedidos": 150, "pendientes": 10, "ejemplo_numero": 27001}
    assert r["valores"][2]["valor"] is None


def test_todas_las_consultas_son_solo_lectura_y_con_nolock():
    c = Cur()
    tpd.valores_columna(c, "Escenario")
    for q in c.q:
        tpd.verificar_select(q)
        if "FROM [dbo]" in q:
            assert "WITH (NOLOCK)" in q


def test_columna_inexistente_dice_donde_aparece_algo_parecido():
    c = Cur(columnas=("RecID", "Numero"), otras=(("dbo", "cobranzas"),))
    r = tpd.valores_columna(c, "Escenario")
    assert r["existe"] is False and r["aparece_en"] == ["dbo.cobranzas"] and "Numero" in r["columnas_de_la_tabla"]


def test_demasiados_valores_no_los_lista():
    r = tpd.valores_columna(Cur(distintos=500), "Escenario")
    assert r["existe"] and r["valores"] == [] and "no parece" in r["nota"]


def test_rechaza_nombres_raros():
    for malo in ("Escenario; DROP TABLE x", "a b", "x'--", ""):
        with pytest.raises(ValueError):
            tpd.valores_columna(Cur(), malo)
