"""Picking de envíos de ML con el celular (página aparte: `docs/picking/index.html`).

La etiqueta de ML trae un QR con `{"id":"<ID de envío>","sender_id":<vendedor>,...}`. Con eso:
  - la cuenta (IT = Group, MT = Arg) sale del `sender_id` (`ml_auth.SELLERS`);
  - el ID de venta sale de `GET /shipments/{id}` de ML con el token de esa cuenta;
  - se agrega una fila a la pestaña «Picking» del Sheet de picking. Si ese envío ya está, NO se agrega y se devuelve cuándo se pickeó (anti-duplicado).
Solo agrega filas: nunca borra ni pisa. La clave de esta ruta es `PICKING_KEY` (distinta de `X-ERP-Key`): solo sirve para registrar pickeos."""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timedelta, timezone

SHEET_ID = "1ad1AUKagoATjUpj8VdOc4xIPODeNOWzjfYJjPXAZ5Is"
TAB = "Picking"
COLS = ["ID_Envio", "ID_Venta", "Cuenta", "Fecha", "Hora", "Operador"]
ART = timezone(timedelta(hours=-3))
_LOCK = threading.Lock()
URL_ENVIO = "https://api.mercadolibre.com/shipments/{}"


class PickingError(ValueError):
    """Error que se le muestra a quien escanea (mensaje en castellano)."""


def parsear_qr(texto: str) -> tuple[str, str | None]:
    """(id de envío, sender_id|None) a partir del texto del QR. Acepta el JSON de ML o un número suelto."""
    t = (texto or "").strip()
    if not t:
        raise PickingError("No se leyó ningún código.")
    try:
        d = json.loads(t)
    except ValueError:
        d = None
    if isinstance(d, dict) and d.get("id") is not None:
        envio = re.sub(r"\D", "", str(d["id"]))
        sender = re.sub(r"\D", "", str(d.get("sender_id") or "")) or None
    else:
        envio, sender = re.sub(r"\D", "", t), None
    if not 8 <= len(envio) <= 15:
        raise PickingError("Ese código no es una etiqueta de envío de ML.")
    return envio, sender


def cuenta_de_vendedor(sender_id: str | None, sellers: dict[str, str]) -> str | None:
    if not sender_id:
        return None
    for cuenta, sid in sellers.items():
        if str(sid) == str(sender_id):
            return cuenta
    raise PickingError(f"El vendedor {sender_id} de la etiqueta no es ninguna de las cuentas (Group/Arg).")


def consultar_venta(envio: str, cuenta: str | None, headers_fn, get_fn) -> tuple[str, str | None]:
    """(ID de venta, cuenta). Si la cuenta no vino en el QR prueba con las dos. Devuelve ("", cuenta) si ML no responde (el pickeo igual se registra)."""
    for c in ([cuenta] if cuenta else ["IT", "MT"]):
        try:
            r = get_fn(URL_ENVIO.format(envio), headers_fn(c))
            if r.status_code == 200:
                d = r.json()
                return str(d.get("order_id") or ""), c
        except Exception:  # noqa: BLE001
            continue
    return "", cuenta


def _hoja(ss):
    try:
        ws = ss.worksheet(TAB)
    except Exception:  # noqa: BLE001
        ws = ss.add_worksheet(title=TAB, rows=1000, cols=len(COLS))
        ws.append_row(COLS)
        return ws
    cab = [str(c).strip() for c in (ws.row_values(1) or [])][: len(COLS)]
    if not cab:
        ws.append_row(COLS)
    elif cab != COLS:
        raise PickingError(f"Los encabezados de la pestaña «{TAB}» cambiaron: no se escribió nada.")
    return ws


def registrar(ss, envio: str, venta: str, cuenta: str | None, operador: str = "", ahora: datetime | None = None) -> dict:
    """Agrega la fila si el envío no estaba. Con el candado, dos celulares escaneando a la vez no duplican."""
    ahora = ahora or datetime.now(ART)
    with _LOCK:
        ws = _hoja(ss)
        for fila in ws.get_all_values()[1:]:
            if fila and str(fila[0]).strip() == envio:
                f = (list(fila) + [""] * len(COLS))[: len(COLS)]
                return {"estado": "duplicada", "envio": envio, "venta": f[1], "cuenta": f[2], "fecha": f[3], "hora": f[4], "operador": f[5]}
        fecha, hora = ahora.strftime("%Y-%m-%d"), ahora.strftime("%H:%M:%S")
        ws.append_row([envio, venta, cuenta or "", fecha, hora, operador], value_input_option="RAW")
    return {"estado": "ok", "envio": envio, "venta": venta, "cuenta": cuenta or "", "fecha": fecha, "hora": hora, "operador": operador}


def escanear(ss, codigo: str, operador: str, sellers: dict[str, str], headers_fn, get_fn, ahora: datetime | None = None) -> dict:
    envio, sender = parsear_qr(codigo)
    cuenta = cuenta_de_vendedor(sender, sellers)
    # Primero se mira si ya estaba: no hace falta molestar a ML para un duplicado.
    with _LOCK:
        for fila in _hoja(ss).get_all_values()[1:]:
            if fila and str(fila[0]).strip() == envio:
                f = (list(fila) + [""] * len(COLS))[: len(COLS)]
                return {"estado": "duplicada", "envio": envio, "venta": f[1], "cuenta": f[2], "fecha": f[3], "hora": f[4], "operador": f[5]}
    venta, cuenta = consultar_venta(envio, cuenta, headers_fn, get_fn)
    r = registrar(ss, envio, venta, cuenta, (operador or "").strip()[:40], ahora)
    if r["estado"] == "ok" and not venta:
        r["aviso"] = "Se registró el pickeo, pero ML no devolvió el ID de venta."
    return r
