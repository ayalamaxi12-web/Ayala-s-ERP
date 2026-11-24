"""Rechequeo de ventas Ecom contra el ERP y el Sheet «Historial Automatizaciones» (pedido de Maxx, 2026-11-24).

La corrida diaria solo agrega al Sheet las órdenes CREADAS AYER y solo las ya cobradas: una orden que se cobra después, o que quedó afuera ese día, nunca llega. Por eso el ERP
muestra menos que la plataforma de Mercado Libre. Este módulo vuelve a pedirle a Ecom TODAS las órdenes de un rango y agrega **solo las que faltan**:

- **ERP (`venta_ecom`)**: las órdenes que no están. Además, una orden que estaba guardada como EXCLUIDA (no cobrada en ese momento) y ahora figura cobrada se reemplaza por la versión
  actual. Nada más se toca: las órdenes que ya están no se recalculan.
- **Sheet**: las órdenes cobradas (las que exporta `/reporte/ecom/ventas`) cuyo «Numero Orden» no está en la hoja, con las MISMAS columnas, ubicadas por el título del encabezado.

Dos pasos: primero se revisa (no escribe nada) y la persona confirma; recién ahí se agrega.
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from .cierre_ecom_diario import ayer_en_argentina, ciclo_de
from .export_ventas_ecom import COLUMNAS, _fila
from .models import ParametroTasa, VentaEcom
from .regimen import periodo_de_rango

HISTORIAL_AUTOMATIZACIONES_ID = os.getenv("RENT_HISTORIAL_SHEET_ID", "1Ps4vx3dhsNZTMYCYXxXnTyLo0XOw65SpAn7QerCltx4")      # «Historial Automatizaciones»
COL_CLAVE = "Numero Orden"
MUESTRA = 60          # órdenes que se listan en pantalla (el resto solo se cuenta)


def ultimo_ciclo_cerrado(hoy: date | None = None) -> tuple[date, date]:
    """El ciclo 23 → 22 más reciente que ya terminó."""
    ayer = ayer_en_argentina() if hoy is None else hoy - timedelta(days=1)
    inicio_actual, _ = ciclo_de(ayer + timedelta(days=1)) if ayer.day == 22 else ciclo_de(ayer)
    return ciclo_de(inicio_actual - timedelta(days=1))


def norm_orden(v) -> str:
    t = str(v if v is not None else "").strip()
    return re.sub(r"\.0+$", "", t)


class HojaSheet:
    """La pestaña de ventas del Historial: se detecta por sus encabezados («Numero Orden» y «Comision Venta»), así no hay que saber cómo se llama."""

    def __init__(self, ws):
        self.ws = ws
        self.encabezados = [str(c).strip() for c in (ws.row_values(1) or [])]
        idx = self.encabezados.index(COL_CLAVE)
        self.numeros = {norm_orden(x) for x in ws.col_values(idx + 1)[1:] if str(x).strip()}

    @property
    def titulo(self) -> str:
        return self.ws.title

    def agregar(self, filas: list[dict]) -> int:
        valores = [[f.get(t, "") if f.get(t) is not None else "" for t in self.encabezados] for f in filas]
        if valores:
            self.ws.append_rows(valores, value_input_option="USER_ENTERED")
        return len(valores)

    @classmethod
    def detectar(cls, gc, sheet_id: str = HISTORIAL_AUTOMATIZACIONES_ID, pestana: str | None = None) -> "HojaSheet":
        ss = gc.open_by_key(sheet_id)
        if pestana:
            return cls(ss.worksheet(pestana))
        candidatas = []
        for ws in ss.worksheets():
            cab = [str(c).strip() for c in (ws.row_values(1) or [])]
            if COL_CLAVE in cab and "Comision Venta" in cab:
                candidatas.append(ws)
        if len(candidatas) == 1:
            return cls(candidatas[0])
        con_ecom = [w for w in candidatas if "ecom" in w.title.lower()]
        if len(con_ecom) == 1:
            return cls(con_ecom[0])
        if not candidatas:
            raise ValueError("No encontré en el Historial Automatizaciones una pestaña de ventas (con las columnas «Numero Orden» y «Comision Venta»).")
        raise ValueError("Hay más de una pestaña de ventas en el Historial: " + ", ".join(w.title for w in candidatas) + ". Indicá cuál usar.")


def _etiqueta_periodo(fecha: date | None) -> str | None:
    return periodo_de_rango(*ciclo_de(fecha)) if fecha else None


def comparar_y_aplicar(db: Session, frescas: list[VentaEcom], hoja, desde: date, hasta: date, ejecutar: bool, costo_operacion: Decimal | None = None) -> dict:
    """`frescas`: las ventas que devolvió Ecom para el rango, ya calculadas (en memoria). Con `ejecutar=False` solo cuenta; con `ejecutar=True` agrega a `venta_ecom` y a la hoja."""
    en_db = {norm_orden(v.numero_orden): v for v in db.query(VentaEcom).filter(VentaEcom.fecha_creacion_venta >= desde, VentaEcom.fecha_creacion_venta <= hasta).all()}
    nuevas_db, reactivadas = [], []
    for f in frescas:
        k = norm_orden(f.numero_orden)
        viejo = en_db.get(k)
        if viejo is None:
            nuevas_db.append(f)
        elif viejo.excluido and not f.excluido:
            reactivadas.append((viejo, f))
    cobradas = [f for f in frescas if not f.excluido and f.neto is not None]
    faltan_sheet = [f for f in cobradas if norm_orden(f.numero_orden) not in hoja.numeros]

    def _item(f: VentaEcom, motivo: str) -> dict:
        return {"orden": f.numero_orden, "fecha": f.fecha_creacion_venta.isoformat() if f.fecha_creacion_venta else None, "canal": f.canal_de_venta, "estado_pago": f.estado_pago,
                "facturacion": float(f.precio_final or 0), "rentabilidad": float(f.rentabilidad) if f.rentabilidad is not None else None, "motivo": motivo}
    detalle = ([_item(f, "falta en el ERP") for f in nuevas_db] + [_item(n, "estaba sin cobrar y ahora está cobrada") for _, n in reactivadas]
               + [_item(f, "falta en el Sheet") for f in faltan_sheet if norm_orden(f.numero_orden) not in {norm_orden(x.numero_orden) for x in nuevas_db}])
    excluidas = [f for f in frescas if f.excluido]
    res = {
        "desde": desde.isoformat(), "hasta": hasta.isoformat(), "pestana": hoja.titulo, "ejecutado": bool(ejecutar),
        "en_ecom": len(frescas), "cobradas": len(cobradas), "sin_cobrar_excluidas": len(excluidas),
        "facturacion_sin_cobrar": float(sum((f.precio_final or 0) for f in excluidas)),
        "ya_en_erp": len(frescas) - len(nuevas_db), "faltan_en_erp": len(nuevas_db), "reactivadas_en_erp": len(reactivadas),
        "ya_en_sheet": len(cobradas) - len(faltan_sheet), "faltan_en_sheet": len(faltan_sheet),
        "facturacion_faltante_sheet": float(sum((f.precio_final or 0) for f in faltan_sheet)),
        "rentabilidad_faltante_sheet": float(sum((f.rentabilidad or 0) for f in faltan_sheet)),
        "detalle": detalle[:MUESTRA], "detalle_total": len(detalle),
    }
    if ejecutar:
        for f in nuevas_db:
            f.periodo = _etiqueta_periodo(f.fecha_creacion_venta) or f.periodo
            db.add(f)
        for viejo, nuevo in reactivadas:
            nuevo.periodo = viejo.periodo
            db.delete(viejo)
            db.add(nuevo)
        db.flush()
        res["agregadas_a_erp"] = len(nuevas_db) + len(reactivadas)
        res["agregadas_al_sheet"] = hoja.agregar([_fila(f, costo_operacion) for f in faltan_sheet])
    return res


def costo_operacion_vigente(db: Session) -> Decimal | None:
    t = db.get(ParametroTasa, "costo_operacion_ecom")
    return t.valor if t else None
