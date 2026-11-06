#!/usr/bin/env python3
"""Exploración de pedidos de Táctica -- SOLO LECTURA (paso 1 de la alerta de pedidos pendientes).

Qué hace: ubica las tablas de pedidos / ítems / pagos, lista los estados de pedido con la cantidad de pedidos en cada uno
y muestra qué fechas hay para calcular la antigüedad. Escribe todo en `tactica_exploracion_<fecha>.md` (nombres de tablas,
columnas y conteos; no guarda datos de clientes ni credenciales) para que lo puedas pasar tal cual.

Seguridad (no negociable):
  - Solo SELECT. Cada consulta pasa por `verificar_select()`: si tiene INSERT/UPDATE/DELETE/EXEC/INTO/etc. se aborta antes de enviarla.
  - Toda tabla de usuario se consulta con `WITH (NOLOCK)`, y la sesión corre en READ UNCOMMITTED: no traba a quien trabaja en Táctica.
  - Nunca se hace commit; la conexión no se expone a nada: el resultado queda en un archivo local.
  - Credenciales en un .env FUERA del repo (por defecto ~/.tactica/.env; ver .env.example). Nunca se imprimen.

Uso:   python tactica_explorar.py                      (autodetecta la tabla de pedidos)
       python tactica_explorar.py --tabla-pedidos pedidos      (si hay más de una candidata)
Requiere: pip install pymssql   y la VPN conectada.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path

_PROHIBIDAS = re.compile(r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|CREATE|TRUNCATE|EXEC|EXECUTE|GRANT|REVOKE|INTO|BACKUP|RESTORE|SHUTDOWN|OPENROWSET|OPENQUERY|XP_\w*|SP_\w*)\b", re.I)
_IDENT = re.compile(r"^[A-Za-z0-9_]+$")
PATRON_TABLAS = re.compile(r"pedido|orden|remito|cobr|pago|recibo|reserva|moviment|histor|estado", re.I)
PATRON_ESTADO = re.compile(r"estado|status|situac|etapa|anulad|cancel|cerrad|factur|entreg|pendient|tipo", re.I)
TIPOS_FECHA = {"datetime", "smalldatetime", "date", "datetime2", "datetimeoffset"}


def verificar_select(sql: str) -> None:
    """Aborta si la consulta no es un único SELECT (o WITH ... SELECT) sin nada que escriba."""
    s = re.sub(r"'(?:[^']|'')*'", "''", sql)          # literales
    s = re.sub(r"\[[^\]]*\]", "[x]", s)                # identificadores entre corchetes
    s = s.strip().rstrip(";")
    if ";" in s:
        raise PermissionError("Una sola sentencia por consulta.")
    if not re.match(r"(?is)^\s*(SELECT|WITH)\b", s):
        raise PermissionError("Solo se permite SELECT.")
    m = _PROHIBIDAS.search(s)
    if m:
        raise PermissionError(f"Palabra no permitida en una consulta de solo lectura: {m.group(0)}")


def ident(nombre: str) -> str:
    if not _IDENT.match(nombre or ""):
        raise ValueError(f"Nombre de objeto no válido: {nombre!r}")
    return f"[{nombre}]"


def tabla(nombre: str, esquema: str = "dbo") -> str:
    """Referencia a tabla de usuario SIEMPRE con NOLOCK."""
    return f"{ident(esquema)}.{ident(nombre)} WITH (NOLOCK)"


def cargar_env(ruta: Path) -> dict[str, str]:
    if not ruta.exists():
        sys.exit(f"No encuentro el archivo de credenciales: {ruta}\nCrealo a partir de .env.example (fuera del repo) o indicá otro con --env.")
    out = {}
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        k, v = linea.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("TACTICA_SQL_SERVER", "TACTICA_SQL_DATABASE", "TACTICA_SQL_USER", "TACTICA_SQL_PASSWORD"):
        if not out.get(k):
            sys.exit(f"Falta {k} en {ruta}")
    return out


def conectar(env: dict[str, str]):
    import pymssql
    servidor, puerto = env["TACTICA_SQL_SERVER"], 1433
    m = re.match(r"^(.*?)[:,](\d+)$", servidor)
    if m:
        servidor, puerto = m.group(1), int(m.group(2))
    con = pymssql.connect(server=servidor, port=puerto, user=env["TACTICA_SQL_USER"], password=env["TACTICA_SQL_PASSWORD"],
                          database=env["TACTICA_SQL_DATABASE"], login_timeout=15, timeout=90, autocommit=True)
    cur = con.cursor()
    cur.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")      # respaldo del NOLOCK
    return con, cur


def consulta(cur, sql: str, params=None):
    verificar_select(sql)
    cur.execute(sql, params or ())
    cols = [d[0] for d in (cur.description or [])]
    return cols, cur.fetchall()


class Informe:
    def __init__(self):
        self.lineas: list[str] = []

    def h(self, nivel: int, texto: str):
        self.lineas += ["", "#" * nivel + " " + texto, ""]
        print("\n" + "=" * 8, texto)

    def p(self, texto: str):
        self.lineas.append(texto)
        print(texto)

    def tabla(self, cols, filas, maximo=200):
        if not filas:
            self.p("_(sin filas)_")
            return
        self.lineas.append("| " + " | ".join(cols) + " |")
        self.lineas.append("|" + "---|" * len(cols))
        print(" | ".join(cols))
        for f in filas[:maximo]:
            celdas = [str(x).replace("|", "/").replace("\n", " ")[:80] if x is not None else "" for x in f]
            self.lineas.append("| " + " | ".join(celdas) + " |")
            print(" | ".join(celdas))
        if len(filas) > maximo:
            self.p(f"_(se muestran {maximo} de {len(filas)})_")


def explorar(cur, informe: Informe, tabla_pedidos: str | None):
    # 1. Tablas candidatas (nombre) con cantidad de filas, sin escanear las tablas (metadatos).
    _, filas = consulta(cur, """
        SELECT s.name AS esquema, t.name AS tabla, SUM(ps.row_count) AS filas
        FROM sys.tables t
        JOIN sys.schemas s ON s.schema_id = t.schema_id
        JOIN sys.dm_db_partition_stats ps ON ps.object_id = t.object_id AND ps.index_id IN (0, 1)
        GROUP BY s.name, t.name ORDER BY t.name""")
    todas = {(e, t): int(n or 0) for e, t, n in filas}
    candidatas = [(e, t, n) for (e, t), n in sorted(todas.items(), key=lambda x: x[0][1].lower()) if PATRON_TABLAS.search(t)]
    informe.h(2, "1. Tablas candidatas (pedido / orden / remito / pago / cobro / recibo / reserva / movimiento / historial / estado)")
    informe.tabla(["esquema", "tabla", "filas"], candidatas)

    # 2. Tabla de pedidos
    nombres_ped = [t for (_e, t, _n) in candidatas if re.search(r"pedido", t, re.I)]
    exacta = [t for t in nombres_ped if t.lower() in ("pedidos", "pedido")]
    elegida = tabla_pedidos or (exacta[0] if exacta else (nombres_ped[0] if len(nombres_ped) == 1 else None))
    if not elegida:
        informe.p("\nNo pude elegir sola la tabla de pedidos. Volvé a correr con `--tabla-pedidos <nombre>` (de la lista de arriba).")
        return
    esquema = next((e for (e, t) in todas if t.lower() == elegida.lower()), "dbo")
    informe.h(2, f"2. Tabla de pedidos: {esquema}.{elegida}")
    cols_info, cols = consulta(cur, """
        SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE
        FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s ORDER BY ORDINAL_POSITION""", (esquema, elegida))
    informe.tabla(["columna", "tipo", "largo", "acepta_null"], cols)
    nombres_cols = [c[0] for c in cols]
    fechas = [c[0] for c in cols if str(c[1]).lower() in TIPOS_FECHA]
    estados = [c[0] for c in cols if PATRON_ESTADO.search(c[0]) and not c[0].lower().startswith("recid")]
    numero = next((c for c in nombres_cols if c.lower() in ("numero", "nro", "nropedido", "numeropedido")), None)

    # 3. Estados: valor, cantidad de pedidos, rango de fechas y un número de ejemplo para buscarlo en Táctica.
    informe.h(2, "3. Estados de pedido (valor, cantidad de pedidos, fechas, ejemplo)")
    fechas_uso = fechas[:3]
    for col in estados:
        _, d = consulta(cur, f"SELECT COUNT(DISTINCT {ident(col)}) FROM {tabla(elegida, esquema)}")
        distintos = d[0][0]
        informe.h(3, f"`{col}` ({distintos} valores distintos)")
        if distintos > 60:
            informe.p("Demasiados valores distintos: no parece una columna de estado.")
            continue
        extra = "".join(f", MIN({ident(f)}) AS min_{f}, MAX({ident(f)}) AS max_{f}" for f in fechas_uso)
        ej = f", MAX({ident(numero)}) AS ejemplo_numero" if numero else ""
        cs, filas = consulta(cur, f"SELECT {ident(col)} AS valor, COUNT(*) AS pedidos{extra}{ej} FROM {tabla(elegida, esquema)} "
                                  f"GROUP BY {ident(col)} ORDER BY COUNT(*) DESC")
        informe.tabla(cs, filas)

    # 4. Antigüedad: qué fechas existen y cómo se llenan.
    informe.h(2, "4. Fechas del pedido (para la antigüedad: fecha del pedido o último movimiento)")
    for f in fechas:
        cs, filas = consulta(cur, f"SELECT MIN({ident(f)}) AS minimo, MAX({ident(f)}) AS maximo, SUM(CASE WHEN {ident(f)} IS NULL THEN 1 ELSE 0 END) AS nulos, "
                                  f"COUNT(*) AS total FROM {tabla(elegida, esquema)}")
        informe.p(f"**{f}**")
        informe.tabla(cs, filas)

    # 5. Tablas hijas: ítems (SKU), pagos, movimientos / historial. Se buscan por columnas tipo IDPedido* y por foreign keys.
    informe.h(2, "5. Tablas relacionadas con el pedido")
    _, hijas = consulta(cur, """
        SELECT DISTINCT c.TABLE_NAME, c.COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS c
        WHERE (c.COLUMN_NAME LIKE %s OR c.COLUMN_NAME LIKE %s) AND c.TABLE_NAME <> %s
        ORDER BY c.TABLE_NAME""", ("IDPedido%", "IDPed%", elegida))
    informe.p("Por nombre de columna (IDPedido*):")
    informe.tabla(["tabla", "columna"], hijas)
    _, fks = consulta(cur, """
        SELECT OBJECT_NAME(fk.parent_object_id) AS tabla_hija, OBJECT_NAME(fk.referenced_object_id) AS tabla_padre
        FROM sys.foreign_keys fk WHERE OBJECT_NAME(fk.referenced_object_id) = %s OR OBJECT_NAME(fk.parent_object_id) = %s""", (elegida, elegida))
    informe.p("Por foreign keys declaradas:")
    informe.tabla(["tabla_hija", "tabla_padre"], fks)
    revisar = sorted({t for t, _c in hijas} | {a for a, _b in fks if a != elegida} | {b for _a, b in fks if b != elegida})
    for t in revisar[:15]:
        if not _IDENT.match(t):
            continue
        informe.h(3, f"{t} ({todas.get(('dbo', t), '?')} filas)")
        _, c2 = consulta(cur, "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = %s ORDER BY ORDINAL_POSITION", (t,))
        informe.tabla(["columna", "tipo"], c2, maximo=80)

    # 6. Posibles tablas de decodificación de estados (la base a veces guarda el estado como número).
    informe.h(2, "6. Tablas que podrían decodificar estados / listas")
    informe.tabla(["esquema", "tabla", "filas"], [x for x in candidatas if re.search(r"estado|lista|tipo", x[1], re.I)])


def main():
    ap = argparse.ArgumentParser(description="Exploración de pedidos de Táctica (solo lectura).")
    ap.add_argument("--env", default=os.environ.get("TACTICA_ENV") or str(Path.home() / ".tactica" / ".env"), help="archivo .env con las credenciales (fuera del repo)")
    ap.add_argument("--tabla-pedidos", default=None, help="nombre de la tabla de pedidos, si no se autodetecta")
    ap.add_argument("--salida", default=None, help="archivo del informe (por defecto tactica_exploracion_<fecha>.md)")
    a = ap.parse_args()
    env = cargar_env(Path(a.env))
    con, cur = conectar(env)
    informe = Informe()
    informe.p(f"# Exploración de Táctica · pedidos · {datetime.now():%Y-%m-%d %H:%M}")
    try:
        explorar(cur, informe, a.tabla_pedidos)
    finally:
        con.close()
    salida = Path(a.salida or f"tactica_exploracion_{datetime.now():%Y%m%d_%H%M}.md")
    salida.write_text("\n".join(informe.lineas), encoding="utf-8")
    print(f"\nListo. Informe guardado en: {salida.resolve()}")


if __name__ == "__main__":
    main()
