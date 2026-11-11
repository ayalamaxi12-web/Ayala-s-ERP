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
DIAS_VIEJO = 30           # más de esto: «atraso viejo», aparte, solo resumido
# Vendedores cuyos pedidos NO son el foco del mail (pedido de Maxx, 2026-11-11): se avisan solo con su cantidad y van a su propia pestaña del Sheet.
# Clave: nombre en minúsculas y sin espacios de más. «notas_credito»: se cargan como pedido pero son notas de crédito (probable).
VENDEDORES_APARTE = {"maximiliano ayala": "propios", "jacqueline romero": "notas_credito", "mariannys rodriguez": "notas_credito"}
GRUPO_PRINCIPAL = "pendientes"
# «Estado de pago» según el Escenario del pedido (versión PROVISORIA, a validar con Cobranzas/Ventas: pedido de Maxx 2026-11-11). El Escenario es la etapa del circuito
# (quién tiene el pedido), no un estado de pago puro: solo algunas etapas dicen algo del pago. Orden = prioridad; se busca el texto (en minúsculas) dentro del Escenario.
REGLAS_PAGO = (("pago total", "Pagado"), ("pago parcial", "Pago parcial"), ("esperando pago", "Esperando pago"), ("pago enviado", "Pago a confirmar"),
               ("pago recibido", "Pago a confirmar"), ("cobra autorizado", "Pagado"))
PAGO_SIN_DATO = "Sin dato en Escenario"

SQL_PEDIDOS = (
    "SELECT p.Numero AS nro, p.FechaCreacion AS creado, p.FechaModificacion AS ultimo, p.Total AS total, p.NroMoneda AS moneda, p.RecID AS recid, "
    "f.RazonSocial AS cliente, u.Usuario AS vendedor, p.Escenario AS escenario "
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
        pedidos.append({"recid": str(r["recid"]).strip(), "nro": int(r["nro"]), "cliente": str(r["cliente"] or "").strip(), "vendedor": str(r["vendedor"] or "").strip(), "escenario": str(r["escenario"] or "").strip(),
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
                                skus=p["skus"], dias_parado=p["dias"], ultimo_movimiento=p["ultimo"], creado=p["creado"], nivel=p["nivel"], escenario=p["escenario"][:120]))
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


def estado_pago_de(escenario: str) -> str:
    e = (escenario or "").strip().lower()
    for texto, estado in REGLAS_PAGO:
        if texto in e:
            return estado
    return PAGO_SIN_DATO


def es_preventa(skus: str) -> bool:
    """Pedido con algún SKU de preventa (prefijo PV-): espera la llegada de la mercadería, por eso no es «parado» en el sentido de los demás."""
    return any(c.strip().upper().startswith("PV-") for c in (skus or "").split(",") if c.strip())


def grupo_de(vendedor: str, skus: str = "") -> str:
    """propios / notas_credito (por vendedor, tienen prioridad), después preventas (por SKU PV-), el resto = pendientes."""
    g = VENDEDORES_APARTE.get(" ".join((vendedor or "").lower().split()))
    if g:
        return g
    return "preventas" if es_preventa(skus) else GRUPO_PRINCIPAL


def _fmt(n) -> str:
    return f"{n:,.0f}".replace(",", ".")


def _montos(filas) -> str:
    """Monto total por moneda (no se suman monedas distintas): «ARS 1.234.567 · USD 890»."""
    tot: dict[str, Decimal] = {}
    for p in filas:
        tot[p.moneda or "?"] = tot.get(p.moneda or "?", Decimal(0)) + (p.monto or 0)
    orden = sorted(tot.items(), key=lambda kv: (kv[0] != "ARS", kv[0]))
    return " · ".join(f"{m} {_fmt(v)}" for m, v in orden if v) or "sin monto"


def _resumen_por(filas, clave) -> list[str]:
    """Una línea por grupo: pedidos (cuántos para cerrar o anular y cuántos para activar) y monto. Primero quien más tiene para cerrar."""
    g: dict[str, list] = {}
    for p in filas:
        g.setdefault(clave(p), []).append(p)
    def orden(kv):
        c = sum(1 for p in kv[1] if p.nivel == "cerrar_o_anular")
        return (-c, -(len(kv[1]) - c), kv[0].lower())
    out = []
    for nombre, ps in sorted(g.items(), key=orden):
        c = sum(1 for p in ps if p.nivel == "cerrar_o_anular")
        out.append(f"  {nombre}: {len(ps)} (cerrar {c} · activar {len(ps) - c}) · {_montos(ps)}")
    return out


def pm_de_skus(skus: str, pm_fn) -> str:
    """PM del pedido = el PM con más ítems entre sus SKU (sin los de envío); si empatan, el primero por nombre; sin ninguno: «Sin PM».
    Es una atribución simple: el monto del pedido va entero a ese PM (los pedidos con SKU de varios PM no se reparten)."""
    cuenta: dict[str, int] = {}
    for sku in (c.strip() for c in (skus or "").split(",")):
        if not sku or sku.upper().startswith("ENVIOS-"):
            continue
        pm = (pm_fn(sku) or "").strip()
        if not pm or pm.upper() == "SIN PM":
            continue
        cuenta[pm] = cuenta.get(pm, 0) + 1
    if not cuenta:
        return "Sin PM"
    return sorted(cuenta.items(), key=lambda kv: (-kv[1], kv[0].lower()))[0][0]


def _filas_out(filas, pm_de=None) -> list[dict]:
    """TODAS las filas (también las apartadas) con su `grupo`, `escenario`, `estado_pago` y `pm`: n8n las reparte/filtra en el Sheet."""
    return [{"nro_pedido": p.nro_pedido, "cliente": p.cliente, "vendedor": p.vendedor, "monto": float(p.monto), "moneda": p.moneda, "skus": p.skus,
             "dias_parado": p.dias_parado, "ultimo_movimiento": p.ultimo_movimiento.isoformat() if p.ultimo_movimiento else None, "nivel": p.nivel,
             "atraso_viejo": p.dias_parado > DIAS_VIEJO, "grupo": grupo_de(p.vendedor, p.skus), "escenario": p.escenario or "", "estado_pago": estado_pago_de(p.escenario),
             "pm": (pm_de(p) if pm_de else "")} for p in filas]


def armar_mail(db, fecha: date | None = None, pm_fn=None) -> dict:
    """Asunto y texto del mail de la corrida del día, desde lo guardado. Si no hay corrida buena del día, avisa que no llegaron datos.

    El mail es solo un resumen (el desglose de cada pedido va al Sheet): cantidad de pedidos y monto por vendedor y por PM, para ver quién tiene que
    activar o cerrar. `pm_fn(sku) -> PM|None` (opcional) resuelve el PM de cada SKU; si no se pasa o falla, el mail sale sin la sección de PM."""
    from rentabilidad.models import TacticaPendiente, TacticaPendienteCorrida

    fecha = fecha or hoy_art()
    corrida = db.query(TacticaPendienteCorrida).filter(TacticaPendienteCorrida.fecha == fecha).first()
    if corrida is None or corrida.estado != "ok":
        texto = "No se recibieron datos de Táctica hoy: revisar la PC o la VPN."
        if corrida is not None and corrida.error_msg:
            texto += f"\n\nÚltimo intento ({corrida.ejecutada_en:%H:%M}): {corrida.error_msg}"
        return {"hay_datos": False, "fecha": fecha.isoformat(), "asunto": "Táctica · SIN DATOS hoy (revisar la PC o la VPN)", "texto": texto, "filas": []}
    todas = (db.query(TacticaPendiente).filter(TacticaPendiente.fecha == fecha).order_by(TacticaPendiente.dias_parado.desc(), TacticaPendiente.nro_pedido).all())

    # PM de cada pedido (una consulta por SKU distinto; si la planilla falla, el mail sale sin PM)
    pm_ok, memo_sku, memo_ped = pm_fn is not None, {}, {}

    def pm_sku(sku):
        if sku not in memo_sku:
            memo_sku[sku] = pm_fn(sku)
        return memo_sku[sku]

    def pm_de(p):
        nonlocal pm_ok
        if not pm_ok:
            return ""
        if p.nro_pedido not in memo_ped:
            try:
                memo_ped[p.nro_pedido] = pm_de_skus(p.skus, pm_sku)
            except Exception:  # noqa: BLE001
                pm_ok = False
                return ""
        return memo_ped[p.nro_pedido]

    aparte = [p for p in todas if grupo_de(p.vendedor, p.skus) != GRUPO_PRINCIPAL]
    filas = [p for p in todas if grupo_de(p.vendedor, p.skus) == GRUPO_PRINCIPAL]
    cerrar = [p for p in filas if p.nivel == "cerrar_o_anular"]
    activar = [p for p in filas if p.nivel == "activar"]
    cab = (f"Pedidos pendientes de Táctica · {fecha:%Y-%m-%d}\n"
           f"Parados {DIAS_ACTIVAR} días o más: {len(filas)} (cerrar o anular: {len(cerrar)} · activar: {len(activar)}) · {_montos(filas)}\n"
           f"Pendientes en total: {corrida.total_pendientes}")
    viejos = sum(1 for p in cerrar if p.dias_parado > DIAS_VIEJO)
    if viejos:
        cab += f" · de los parados, con más de {DIAS_VIEJO} días: {viejos}"
    if aparte:
        cuenta: dict[str, list] = {}
        for p in aparte:
            nombre = "preventas (PV-)" if grupo_de(p.vendedor, p.skus) == "preventas" else " ".join((p.vendedor or "(sin vendedor)").split())
            c = cuenta.setdefault(nombre.lower(), [nombre, 0])
            c[1] += 1
        cab += "\nAparte, no cuentan arriba: " + " · ".join(f"{v} {n}" for _, (v, n) in sorted(cuenta.items()))
    if not filas:
        texto = cab + "\n\nNo hay pedidos pendientes parados."
        return {"hay_datos": True, "fecha": fecha.isoformat(), "asunto": "Táctica · sin pedidos pendientes parados", "texto": texto, "filas": _filas_out(todas, pm_de)}
    partes = [cab, "", "POR VENDEDOR (pedidos · monto)", *_resumen_por(filas, lambda p: " ".join((p.vendedor or "(sin vendedor)").split()))]
    if pm_fn is not None:
        pms = {p.nro_pedido: pm_de(p) for p in filas}
        if pm_ok:
            partes += ["", "POR PM (pedidos · monto; PM con más ítems del pedido)", *_resumen_por(filas, lambda p: pms[p.nro_pedido])]
        else:
            partes += ["", "POR PM: no disponible hoy (no se pudo leer la planilla de categorías)."]
    partes += ["", "El desglose de cada pedido está en el Sheet."]
    asunto = f"Táctica · {len(filas)} pedidos pendientes parados ({len(cerrar)} para cerrar o anular)"
    return {"hay_datos": True, "fecha": fecha.isoformat(), "asunto": asunto, "texto": "\n".join(partes), "filas": _filas_out(todas, pm_de)}


def historial_pedido(db, nro: int) -> list[dict]:
    from rentabilidad.models import TacticaPendiente

    filas = db.query(TacticaPendiente).filter(TacticaPendiente.nro_pedido == nro).order_by(TacticaPendiente.fecha).all()
    return [{"fecha": p.fecha.isoformat(), "dias_parado": p.dias_parado, "nivel": p.nivel, "cliente": p.cliente, "vendedor": p.vendedor, "monto": float(p.monto),
             "moneda": p.moneda, "skus": p.skus, "ultimo_movimiento": p.ultimo_movimiento.isoformat() if p.ultimo_movimiento else None} for p in filas]
