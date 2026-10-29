"""Endpoints del módulo Frávega (`/fravega/*`): catálogo con margen/stock/ventas, simulador y cambio de precio / plan (apagado por defecto)."""
from __future__ import annotations

import time
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

import fravega_catalogo as fc
from rentabilidad.fravega_seller import FravegaNoConfigurado, SesionFravegaVencida

router = APIRouter(prefix="/fravega", tags=["fravega"])
_CACHE = {"t": 0.0, "items": []}
TTL = 120


def _items(forzar: bool = False) -> list[dict]:
    if forzar or not _CACHE["items"] or time.time() - _CACHE["t"] > TTL:
        try:
            _CACHE.update(t=time.time(), items=fc.traer_items())
        except FravegaNoConfigurado as e:
            raise HTTPException(status_code=409, detail=str(e))
        except SesionFravegaVencida as e:
            raise HTTPException(status_code=409, detail=str(e))
    return _CACHE["items"]


def _contexto():
    import main
    from rentabilidad.db import sesion
    motor, datos_sku_fn, resolver_tc, fecha = main._campanas_contexto(None)
    avisos: list = []
    return main, motor, main._campanas_datos(datos_sku_fn, avisos), resolver_tc(None), fecha, avisos, sesion


def _catalogo_sync(forzar: bool) -> dict:
    from rentabilidad.fravega_vista import construir_vista, stock_general_por_sku
    items = _items(forzar)
    main, motor, datos, tc, fecha, avisos, sesion = _contexto()
    with sesion() as db:
        par = motor.cargar_parametros(db, fecha)
        try:
            stock_gral = stock_general_por_sku()
        except Exception as e:  # noqa: BLE001
            stock_gral = None
            avisos.append(f"No se pudo leer el stock general ({type(e).__name__}: {e}): se muestra solo el publicado en Frávega.")
        filas = construir_vista(db, items, datos, tc, par, date.today(), stock_gral)
    planes = [{"id": p["_id"], "nombre": p.get("name"), "cuotas": fc.cuotas_de_plan(p.get("name")), "comision": p.get("commission")}
              for p in fc.planes_en_uso(items)]
    return {"filas": filas, "planes": planes, "escritura": fc.escritura_habilitada(), "tc": float(tc), "avisos": avisos}


@router.get("/catalogo")
async def catalogo(refrescar: bool = False):
    return await run_in_threadpool(_catalogo_sync, refrescar)


class _SimIn(BaseModel):
    ref_id: str
    venta: float
    cuotas: str


@router.post("/simular")
async def simular(b: _SimIn):
    """Margen a un precio y plan cualquiera (solo lectura)."""
    def _hacer():
        from rentabilidad.fravega_vista import margen_fravega
        from rentabilidad.pricing_pm import fee_historico_fravega, norm_sku
        main, motor, datos, tc, fecha, avisos, sesion = _contexto()
        sku = norm_sku(b.ref_id)
        with sesion() as db:
            par = motor.cargar_parametros(db, fecha)
            m, av = margen_fravega(Decimal(str(b.venta)), datos(sku), tc, par, b.cuotas, fee_historico_fravega(db).get(sku))
        return {"margen": m and m["margen"], "rentabilidad": m and m["rentabilidad"], "avisos": av}
    return await run_in_threadpool(_hacer)


class _PrecioIn(BaseModel):
    id: str
    ref_id: str
    lista: float
    venta: float
    operador: str


def _historial(main, fila: dict) -> str | None:
    try:
        main._registrar_historial_oferta_lote([{"Fecha": date.today().isoformat(), "Cuenta": "Frávega", "Origen": "Módulo Frávega", **fila}])
        return None
    except Exception as e:  # noqa: BLE001
        return f"El cambio se hizo pero no se pudo anotar en el historial ({type(e).__name__})."


def _exigir(operador: str):
    if not (operador or "").strip():
        raise HTTPException(status_code=422, detail="Elegí el operador primero.")
    if not fc.escritura_habilitada():
        raise HTTPException(status_code=403, detail="La escritura en Frávega está apagada: poné FRAVEGA_ESCRITURA=1 en Railway.")


def _errores(e: Exception):
    if isinstance(e, fc.FravegaRechazo):
        raise HTTPException(status_code=422, detail=str(e))
    if isinstance(e, (ValueError, FravegaNoConfigurado, SesionFravegaVencida)):
        raise HTTPException(status_code=409 if not isinstance(e, ValueError) else 422, detail=str(e))
    raise e


@router.post("/precio")
async def poner_precio(b: _PrecioIn):
    """Cambia lista (tachado) y venta de UNA publicación y la vuelve a leer para verificar. Escribe en Frávega."""
    _exigir(b.operador)

    def _hacer():
        import main
        actual = next((i for i in _items(True) if i["id"] == b.id), None)
        if not actual:
            raise HTTPException(status_code=404, detail="Esa publicación no está en el listado de Frávega.")
        lista, venta = Decimal(str(b.lista)), Decimal(str(b.venta))
        ratio = (actual["neto"] / actual["venta"]) if actual.get("neto") and actual.get("venta") else Decimal(1) / Decimal("1.21")
        neto = (venta * ratio).quantize(Decimal("0.01"))
        try:
            fc.poner_precio(b.id, lista, venta, neto)
        except Exception as e:  # noqa: BLE001
            _errores(e)
        despues = fc.releer_item(b.id)
        ok = bool(despues and despues["venta"] == venta and despues["lista"] == lista)
        _CACHE["t"] = 0
        aviso = _historial(main, {"Item ID": b.id, "SKU": b.ref_id, "Accion": "Precio Frávega", "Tipo/Promocion": f"lista {lista} / venta {venta}",
                                  "Precio Anterior": float(actual["venta"] or 0), "Precio Nuevo": float(venta), "Operador": b.operador})
        return {"ok": ok, "verificado": ok, "despues": despues and {"lista": float(despues["lista"] or 0), "venta": float(despues["venta"] or 0),
                                                                   "estado": despues["estado"], "estado_msg": despues["estado_msg"]}, "aviso": aviso}
    return await run_in_threadpool(_hacer)


class _PlanIn(BaseModel):
    id: str
    ref_id: str
    plan_id: str
    operador: str


@router.post("/plan")
async def poner_plan(b: _PlanIn):
    """Asigna un plan de cuotas a UNA publicación. Frávega lo puede demorar: se relee y se informa. Escribe en Frávega."""
    _exigir(b.operador)

    def _hacer():
        import main
        items = _items(True)
        actual = next((i for i in items if i["id"] == b.id), None)
        plan = next((p for p in fc.planes_en_uso(items) if p["_id"] == b.plan_id), None)
        if not actual or not plan:
            raise HTTPException(status_code=404, detail="No encuentro esa publicación o ese plan en el listado de Frávega.")
        try:
            fc.poner_plan(b.id, plan)
        except Exception as e:  # noqa: BLE001
            _errores(e)
        despues = fc.releer_item(b.id)
        aplicado = bool(despues and (despues.get("plan") or {}).get("id") == b.plan_id)
        _CACHE["t"] = 0
        aviso = _historial(main, {"Item ID": b.id, "SKU": b.ref_id, "Accion": "Plan Frávega", "Tipo/Promocion": plan.get("name"),
                                  "Precio Anterior": (actual.get("plan") or {}).get("nombre") or "", "Operador": b.operador})
        return {"ok": True, "aplicado": aplicado, "aviso": aviso or (None if aplicado else "Frávega recibió el cambio pero todavía figura el plan anterior: puede demorar en impactar.")}
    return await run_in_threadpool(_hacer)
