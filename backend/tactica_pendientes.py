"""Alerta diaria de pedidos PENDIENTES de Táctica (solo lectura sobre la base de Táctica).

Reglas confirmadas por Maxx (2026-11-06): en `pedidos.Estado`, 0 = Pendiente, 1 = Completado, 2 = Anulado. «Días parado» = días corridos desde
`pedidos.FechaModificacion` (último movimiento). Entran los pendientes con 3 días o más: de 3 a 6 → «activar»; desde 7 → «cerrar o anular».

Seguridad: solo SELECT con `WITH (NOLOCK)` (mismo guard que `tactica_pedidos`); la conexión sale solo de este backend y hacia afuera va el resultado ya armado.
Cada corrida se guarda en la base propia (Postgres) con historial por pedido; el mail se arma desde lo guardado (`armar_mail`).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from tactica_pedidos import consulta, tabla

ART = timezone(timedelta(hours=-3))
ESTADO_PENDIENTE = 0
DIAS_ACTIVAR = 3          # desde acá entra en la alerta
DIAS_CERRAR = 7           # desde acá: «cerrar o anular»
MONEDAS = {1: "ARS", 2: "USD", 3: "EUR", 4: "CNY"}
LOTE = 400
MAX_FILAS_GRUPO = 40      # tope de líneas de detalle POR GRUPO en el mail (el detalle completo va al Sheet por n8n)
DIAS_VIEJO = 30           # más de esto: «atraso viejo», aparte, solo resumido
# Vendedores cuyos pedidos NO son el foco del mail (pedido de Maxx, 2026-11-11): se avisan solo con su cantidad y van a su propia pestaña del Sheet.
# Clave: nombre en minúsculas y sin espacios de más. «notas_credito»: se cargan como pedido pero son notas de crédito (probable).
VENDEDORES_APARTE = {"maximiliano ayala": "propios", "jacqueline romero": "notas_credito", "mariannys rodriguez": "notas_credito"}
GRUPO_PRINCIPAL = "pendientes"

SQL_PEDIDOS = (
    "SELECT p.Numero AS nro, p.FechaCreacion AS creado, p.FechaModificacion AS ultimo, p.Total AS total, p.NroMoneda AS moneda, p.RecID AS recid, "
    "f.RazonSocial AS cliente, u.Usuario AS vendedor "
    f"FROM {tabla('pedidos', alias='p')} "
    f"LEFT JOIN {tabla('fiscal', alias='f')} ON f.RecID = p.IDFiscal "
    f"LEFT JOIN {tabla('usuarios', alias='u')} ON u.RecID = p.IDUsuarioVendedor "
    "WHERE p.Estado = %s AND p.FechaModificacion < %s "
    "ORDER BY p.FechaModificacion"
)
SQL_CONTEO = f"SELECT COUNT(*) FROM {tabla('pedidos')} WHERE Estado = %s"


def hoy_art() -> date:
    return datetime.now(ART).date()


def nivel_de(dias: int) -> str:
    return "cerrar_o_anular" if dias >= DIAS_CERRAR else "activar"


def consultar_pendientes(cur, hoy: date) -> tuple[list[dict], int]:
    """(pedidos pendientes con 3 días o más sin movimiento, total de pendientes). Solo lectura."""
    _, tot = consulta(cur, SQL_CONTEO, (ESTADO_PENDIENTE,))
    total = int(tot[0][0])
    # 3 días corridos o más <=> último movimiento antes de las 00:00 de (hoy - 2 días)
    corte = datetime.combine(hoy - timedelta(days=DIAS_ACTIVAR - 1), time.min)
    cols, filas = consulta(cur, SQL_PEDIDOS, (ESTADO_PENDIENTE, corte))
    pedidos = []
    for f in filas:
        r = dict(zip(cols, f))
        ultimo = r["ultimo"]
        dias = (hoy - ultimo.date()).days if ultimo else 0
        if dias < DIAS_ACTIVAR:
            continue
        pedidos.append({"recid": str(r["recid"]).strip(), "nro": int(r["nro"]), "cliente": str(r["cliente"] or "").strip(), "vendedor": str(r["vendedor"] or "").strip(),
                        "monto": Decimal(str(round(float(r["total"] or 0), 2))), "moneda": MONEDAS.get(int(r["moneda"] or 1), str(r["moneda"])),
                        "ultimo": ultimo, "creado": r["creado"], "dias": dias, "nivel": nivel_de(dias), "skus": ""})
    # SKU de cada pedido, por lotes (solo lectura)
    for i in range(0, len(pedidos), LOTE):
        lote = pedidos[i:i + LOTE]
        marcas = ",".join(["%s"] * len(lote))
        _, items = consulta(cur, f"SELECT i.IDPedido, i.Codigo FROM {tabla('pedidositems', alias='i')} WHERE i.IDPedido IN ({marcas}) ORDER BY i.NroFila",
                            tuple(p["recid"] for p in lote))
        por_pedido: dict[str, list[str]] = {}
        for idp, cod in items:
            c = str(cod or "").strip()
            lst = por_pedido.setdefault(str(idp).strip(), [])
            if c and c not in lst:
                lst.append(c)
        for p in lote:
            p["skus"] = ", ".join(por_pedido.get(p["recid"], []))
    pedidos.sort(key=lambda p: -p["dias"])
    return pedidos, total


def guardar_corrida(db, fecha: date, pedidos: list[dict], total_pendientes: int, ahora: datetime | None = None) -> dict:
    """Guarda (o reemplaza la del mismo día) la corrida y sus pedidos. El historial de otros días no se toca."""
    from rentabilidad.models import TacticaPendiente, TacticaPendienteCorrida

    ahora = ahora or datetime.now(ART).replace(tzinfo=None)
    db.query(TacticaPendiente).filter(TacticaPendiente.fecha == fecha).delete(synchronize_session=False)
    corrida = db.query(TacticaPendienteCorrida).filter(TacticaPendienteCorrida.fecha == fecha).first()
    if corrida is None:
        corrida = TacticaPendienteCorrida(fecha=fecha)
        db.add(corrida)
    corrida.ejecutada_en, corrida.estado, corrida.error_msg = ahora, "ok", None
    corrida.total_pendientes, corrida.parados = total_pendientes, len(pedidos)
    for p in pedidos:
        db.add(TacticaPendiente(fecha=fecha, nro_pedido=p["nro"], cliente=p["cliente"][:255], vendedor=p["vendedor"][:120], monto=p["monto"], moneda=p["moneda"],
                                skus=p["skus"], dias_parado=p["dias"], ultimo_movimiento=p["ultimo"], creado=p["creado"], nivel=p["nivel"]))
    db.flush()
    return resumen(len(pedidos), total_pendientes, pedidos)


def registrar_error(db, fecha: date, mensaje: str, ahora: datetime | None = None) -> None:
    """Anota que la corrida falló, SIN pisar una corrida buena del mismo día."""
    from rentabilidad.models import TacticaPendienteCorrida

    ahora = ahora or datetime.now(ART).replace(tzinfo=None)
    corrida = db.query(TacticaPendienteCorrida).filter(TacticaPendienteCorrida.fecha == fecha).first()
    if corrida is not None and corrida.estado == "ok":
        return
    if corrida is None:
        corrida = TacticaPendienteCorrida(fecha=fecha, total_pendientes=0, parados=0)
        db.add(corrida)
    corrida.ejecutada_en, corrida.estado, corrida.error_msg = ahora, "error", mensaje[:500]
    db.flush()


def resumen(parados: int, total: int, pedidos: list[dict]) -> dict:
    return {"estado": "ok", "total_pendientes": total, "parados": parados,
            "cerrar_o_anular": sum(1 for p in pedidos if p["nivel"] == "cerrar_o_anular"), "activar": sum(1 for p in pedidos if p["nivel"] == "activar")}


def correr(db, cur, hoy: date | None = None) -> dict:
    hoy = hoy or hoy_art()
    pedidos, total = consultar_pendientes(cur, hoy)
    return guardar_corrida(db, hoy, pedidos, total)


def _monto(p) -> str:
    return f"{p.moneda} {p.monto:,.0f}".replace(",", ".")


def _linea(p) -> str:
    ult = p.ultimo_movimiento.strftime("%Y-%m-%d") if p.ultimo_movimiento else "?"
    skus = p.skus if len(p.skus) <= 90 else p.skus[:87] + "..."
    return f"  #{p.nro_pedido} · {p.dias_parado} d · {p.cliente or '(sin cliente)'} · {p.vendedor or '(sin vendedor)'} · {_monto(p)} · {skus or '(sin ítems)'} · último mov. {ult}"


def grupo_de(vendedor: str) -> str:
    return VENDEDORES_APARTE.get(" ".join((vendedor or "").lower().split()), GRUPO_PRINCIPAL)


def _es_preventa(p) -> bool:
    return any(c.strip().upper().startswith("PV-") for c in (p.skus or "").split(",") if c.strip())


def _por_vendedor(filas) -> list[str]:
    cuenta: dict[str, list[int]] = {}
    for p in filas:
        c = cuenta.setdefault(p.vendedor or "(sin vendedor)", [0, 0])
        c[0 if p.nivel == "cerrar_o_anular" else 1] += 1
    orden = sorted(cuenta.items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0]))
    return [f"  {v}: {c[0] + c[1]} (cerrar {c[0]} · activar {c[1]})" for v, c in orden]


def _filas_out(filas) -> list[dict]:
    """TODAS las filas (también las apartadas) con su `grupo`: n8n las reparte en pestañas según ese campo."""
    return [{"nro_pedido": p.nro_pedido, "cliente": p.cliente, "vendedor": p.vendedor, "monto": float(p.monto), "moneda": p.moneda, "skus": p.skus,
             "dias_parado": p.dias_parado, "ultimo_movimiento": p.ultimo_movimiento.isoformat() if p.ultimo_movimiento else None, "nivel": p.nivel,
             "atraso_viejo": p.dias_parado > DIAS_VIEJO, "grupo": grupo_de(p.vendedor)} for p in filas]


def armar_mail(db, fecha: date | None = None) -> dict:
    """Asunto y texto del mail de las 8:00, desde lo guardado. Si no hay corrida buena del día, avisa que no llegaron datos.

    El mail es un resumen: por vendedor, avisos (monto 0 / preventas), detalle de los pedidos de hasta DIAS_VIEJO días (con tope por grupo)
    y el atraso viejo solo contado por vendedor. El detalle completo de TODOS los pedidos va en `filas` (n8n lo vuelca al Sheet)."""
    from rentabilidad.models import TacticaPendiente, TacticaPendienteCorrida

    fecha = fecha or hoy_art()
    corrida = db.query(TacticaPendienteCorrida).filter(TacticaPendienteCorrida.fecha == fecha).first()
    if corrida is None or corrida.estado != "ok":
        texto = "No se recibieron datos de Táctica hoy: revisar la PC o la VPN."
        if corrida is not None and corrida.error_msg:
            texto += f"\n\nÚltimo intento ({corrida.ejecutada_en:%H:%M}): {corrida.error_msg}"
        return {"hay_datos": False, "fecha": fecha.isoformat(), "asunto": "Táctica · SIN DATOS hoy (revisar la PC o la VPN)", "texto": texto, "filas": []}
    filas = (db.query(TacticaPendiente).filter(TacticaPendiente.fecha == fecha).order_by(TacticaPendiente.dias_parado.desc(), TacticaPendiente.nro_pedido).all())
    aparte = [p for p in filas if grupo_de(p.vendedor) != GRUPO_PRINCIPAL]
    todas = filas
    filas = [p for p in todas if grupo_de(p.vendedor) == GRUPO_PRINCIPAL]
    cerrar = [p for p in filas if p.nivel == "cerrar_o_anular"]
    activar = [p for p in filas if p.nivel == "activar"]
    cab = (f"Pedidos pendientes de Táctica · {fecha:%Y-%m-%d}\n"
           f"Pendientes en total: {corrida.total_pendientes} · parados {DIAS_ACTIVAR} días o más: {len(filas)} "
           f"(cerrar o anular: {len(cerrar)} · activar: {len(activar)})")
    if aparte:
        cuenta: dict[str, int] = {}
        for p in aparte:
            nombre = " ".join((p.vendedor or "(sin vendedor)").split())      # mismo nombre aunque venga con espacios de más
            cuenta[nombre] = cuenta.get(nombre, 0) + 1
        cab += "\nAparte, no cuentan arriba: " + " · ".join(f"{v} {n}" for v, n in sorted(cuenta.items())) + " (están en sus pestañas del Sheet)."
    if not filas:
        texto = cab + "\n\nNo hay pedidos pendientes parados."
        return {"hay_datos": True, "fecha": fecha.isoformat(), "asunto": "Táctica · sin pedidos pendientes parados", "texto": texto, "filas": _filas_out(todas)}
    cerrar_reciente = [p for p in cerrar if p.dias_parado <= DIAS_VIEJO]
    viejos = [p for p in cerrar if p.dias_parado > DIAS_VIEJO]
    partes = [cab, "", "POR VENDEDOR", *_por_vendedor(filas)]
    sin_monto = sum(1 for p in filas if not p.monto)
    preventas = sum(1 for p in filas if _es_preventa(p))
    avisos = [t for t in ((f"{sin_monto} con monto 0" if sin_monto else ""), (f"{preventas} con SKU de preventa (PV-)" if preventas else "")) if t]
    if avisos:
        partes += ["", "Para revisar aparte: " + " · ".join(avisos) + " (siguen contados arriba)."]
    for titulo, grupo in ((f"CERRAR O ANULAR ({DIAS_CERRAR} a {DIAS_VIEJO} días)", cerrar_reciente), (f"ACTIVAR ({DIAS_ACTIVAR} a {DIAS_CERRAR - 1} días)", activar)):
        if not grupo:
            continue
        partes += ["", f"{titulo} · {len(grupo)}"]
        partes += [_linea(p) for p in grupo[:MAX_FILAS_GRUPO]]
        if len(grupo) > MAX_FILAS_GRUPO:
            partes.append(f"  … y {len(grupo) - MAX_FILAS_GRUPO} más (están en el Sheet).")
    if viejos:
        partes += ["", f"ATRASO VIEJO (más de {DIAS_VIEJO} días) · {len(viejos)}", *_por_vendedor(viejos), "  El detalle está en el Sheet."]
    partes += ["", "El detalle completo de todos los pedidos está en el Sheet."]
    asunto = f"Táctica · {len(filas)} pedidos pendientes parados ({len(cerrar)} para cerrar o anular)"
    return {"hay_datos": True, "fecha": fecha.isoformat(), "asunto": asunto, "texto": "\n".join(partes), "filas": _filas_out(todas)}


def historial_pedido(db, nro: int) -> list[dict]:
    from rentabilidad.models import TacticaPendiente

    filas = db.query(TacticaPendiente).filter(TacticaPendiente.nro_pedido == nro).order_by(TacticaPendiente.fecha).all()
    return [{"fecha": p.fecha.isoformat(), "dias_parado": p.dias_parado, "nivel": p.nivel, "cliente": p.cliente, "vendedor": p.vendedor, "monto": float(p.monto),
             "moneda": p.moneda, "skus": p.skus, "ultimo_movimiento": p.ultimo_movimiento.isoformat() if p.ultimo_movimiento else None} for p in filas]
