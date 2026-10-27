"""Criterios de precio por canal: el lugar único de las comisiones, impuestos y costos que usan los módulos.

Se guardan como las tarifas de «Mercados» (mismo formato de filas y misma foto `ml_foto`, módulo `mercados_tarifas`), editables desde la página «Criterios de precio»:
cada cambio pide operador y queda en un historial (quién, cuándo, valor anterior y nuevo) dentro de la misma foto. Sin foto se usan los valores iniciales del código, así que
**ningún precio cambia hasta que alguien edita un valor**. Un canal puede tener su propio IIBB / cheque / costo por orden (fila propia); si no, usa el común («todos»).
Sin FastAPI ni red: recibe una sesión de SQLAlchemy.
"""
from __future__ import annotations

import copy
import threading
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import ml_foto
import mercados as M

_LOCK = threading.Lock()
MAX_HISTORIAL = 1000
CONCEPTOS_PCT = {"comision_base", "cuotas", "reducida", "impuesto_cheque", "iibb", "recargo_cuotas"}
CONCEPTOS_MONTO = {"costo_orden", "costo_fijo"}
CONCEPTOS_OVERRIDE = {"costo_orden", "impuesto_cheque", "iibb"}        # los que un canal puede tener propios
ETIQUETA = {"comision_base": "Comisión por venta", "iibb": "IIBB", "impuesto_cheque": "Impuesto al cheque", "costo_orden": "Costo por orden de Ecom",
            "costo_fijo": "Costo fijo por unidad", "reducida": "Reducida", "cuotas": "Cuotas", "recargo_cuotas": "Recargo sobre las cuotas"}


class CriterioInvalido(ValueError):
    pass


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clave(f: dict) -> tuple:
    return (f["mercado"], f["concepto"], f["cuotas"])


def completar(filas: list[dict]) -> list[dict]:
    """Suma las filas iniciales que falten (un criterio nuevo del código aparece sin pisar lo ya editado)."""
    tengo = {_clave(f) for f in filas}
    return filas + [copy.deepcopy(f) for f in M.filas_iniciales_parseadas() if _clave(f) not in tengo]


def leer(sesion_fn) -> tuple[list[dict], list[dict], dict]:
    """(filas, historial, info). Sin foto guardada: valores iniciales, historial vacío, info.origen == 'codigo'."""
    payload, info = M.foto_o_iniciales(sesion_fn)
    return completar(payload["filas"]), list(payload.get("historial", [])), info


def _guardar(sesion_fn, filas: list[dict], historial: list[dict]) -> None:
    payload = {"filas": filas, "origen": "criterios", "historial": historial[-MAX_HISTORIAL:]}
    with sesion_fn() as db:
        ml_foto.guardar_exito(db, M.MODULO_FOTO, M.CUENTA_FOTO, "", payload, "completa", 0, 0, [])


def validar_valor(concepto: str, valor) -> Decimal:
    try:
        v = Decimal(str(valor).strip().replace(",", ".").replace("%", "").replace("$", ""))
    except (InvalidOperation, AttributeError):
        raise CriterioInvalido("El valor tiene que ser un número.")
    if v < 0:
        raise CriterioInvalido("El valor no puede ser negativo.")
    if concepto in CONCEPTOS_PCT and v > 100:
        raise CriterioInvalido("Un porcentaje no puede pasar de 100.")
    if concepto in CONCEPTOS_MONTO and v > 1_000_000:
        raise CriterioInvalido("Ese monto es demasiado alto: revisalo.")
    return v.normalize() if v != v.to_integral() else v.quantize(Decimal(1))


def _formato(v: Decimal) -> str:
    return format(v, "f")


def _hist(operador, accion, f, antes, despues) -> dict:
    return {"cuando": _ahora(), "operador": operador, "accion": accion, "mercado": f["mercado"], "concepto": f["concepto"], "cuotas": f["cuotas"], "antes": antes, "despues": despues}


def editar(sesion_fn, mercado: str, concepto: str, cuotas: str, valor, operador: str) -> dict:
    """Cambia un valor. Si es IIBB / cheque / costo por orden de un canal que todavía usa el común, le crea su fila propia. Devuelve la entrada del historial."""
    operador = (operador or "").strip()
    if not operador:
        raise CriterioInvalido("Falta el operador: sin operador no se cambia ningún criterio.")
    if mercado not in M.MERCADOS and mercado != "todos":
        raise CriterioInvalido("Canal desconocido.")
    v = validar_valor(concepto, valor)
    with _LOCK:
        filas, hist, _ = leer(sesion_fn)
        f = next((x for x in filas if _clave(x) == (mercado, concepto, cuotas)), None)
        accion = "cambio"
        if f is None:
            base = next((x for x in filas if _clave(x) == ("todos", concepto, cuotas)), None) if (concepto in CONCEPTOS_OVERRIDE and mercado != "todos") else None
            if base is None:
                raise CriterioInvalido("Ese criterio no existe.")
            f = {**copy.deepcopy(base), "mercado": mercado, "fuente": "propio de este canal", "nota": ""}
            filas.append(f)
            accion = "propio_alta"
        antes = f["porcentaje"]
        f["porcentaje"] = _formato(v)
        entrada = _hist(operador, accion, f, antes, f["porcentaje"])
        _guardar(sesion_fn, filas, hist + [entrada])
        return entrada


def volver_al_comun(sesion_fn, mercado: str, concepto: str, operador: str) -> dict:
    operador = (operador or "").strip()
    if not operador:
        raise CriterioInvalido("Falta el operador: sin operador no se cambia ningún criterio.")
    if concepto not in CONCEPTOS_OVERRIDE or mercado == "todos":
        raise CriterioInvalido("Ese criterio no tiene un valor propio por canal.")
    with _LOCK:
        filas, hist, _ = leer(sesion_fn)
        f = next((x for x in filas if _clave(x) == (mercado, concepto, "")), None)
        if f is None:
            raise CriterioInvalido("Este canal ya usa el valor común.")
        filas.remove(f)
        entrada = _hist(operador, "propio_baja", f, f["porcentaje"], "común")
        _guardar(sesion_fn, filas, hist + [entrada])
        return entrada


# ── lo que muestra la página ──

def _fila_vista(f: dict, etiqueta: str, unidad: str, origen: str | None = None, puede_volver: bool = False) -> dict:
    return {"mercado": f["mercado"], "concepto": f["concepto"], "cuotas": f["cuotas"], "etiqueta": etiqueta, "valor": f["porcentaje"], "unidad": unidad,
            "origen": origen, "puede_volver": puede_volver, "nota": f.get("nota", ""), "fuente": f.get("fuente", ""), "a_confirmar": f.get("incluye_iva") == M.A_CONFIRMAR}


def vista(sesion_fn) -> dict:
    filas, hist, info = leer(sesion_fn)
    por_clave = {_clave(f): f for f in filas}
    canales = []
    comunes = []
    for concepto, unidad in (("iibb", "%"), ("impuesto_cheque", "%"), ("costo_orden", "$")):
        f = por_clave.get(("todos", concepto, ""))
        if f:
            comunes.append(_fila_vista(f, ETIQUETA[concepto], unidad))
    canales.append({"clave": "todos", "nombre": "Todos los canales (valor común)", "apartados": [{"id": "comunes", "titulo": "Valores comunes: los usa cada canal que no tenga uno propio", "filas": comunes}]})
    for clave, meta in M.MERCADOS.items():
        ap = []
        f = por_clave.get((clave, "comision_base", ""))
        ap.append({"id": "comision", "titulo": "Simple = comisión por venta", "filas": [_fila_vista(f, "Comisión por venta", "%")] if f else []})
        vc = M.valores_canal(filas, clave)
        filas_c = []
        for concepto, k, unidad in (("iibb", "iibb_pct", "%"), ("impuesto_cheque", "cheque_pct", "%"), ("costo_orden", "costo_orden", "$")):
            valor, origen = vc[k]
            propio = por_clave.get((clave, concepto, ""))
            filas_c.append({"mercado": clave, "concepto": concepto, "cuotas": "", "etiqueta": ETIQUETA[concepto], "valor": _formato(valor), "unidad": unidad,
                            "origen": origen, "puede_volver": propio is not None, "nota": "", "fuente": "", "a_confirmar": False})
        ap.append({"id": "impuestos", "titulo": "IIBB, impuesto al cheque y costo por orden de Ecom", "filas": filas_c})
        if clave == "ml":
            fijos = [f for f in filas if f["mercado"] == "ml" and f["concepto"] == "costo_fijo"]
            fijos.sort(key=lambda f: (f["cuotas"] == "sin_tope", Decimal(f["cuotas"]) if f["cuotas"] != "sin_tope" else 0))
            ap.append({"id": "costo_fijo", "titulo": "Costos fijos por unidad (solo Mercado Libre)",
                       "filas": [{**_fila_vista(f, f["nota"] or f["cuotas"], "$"), "nota": ""} for f in fijos]})
            red = por_clave.get(("ml", "reducida", ""))
            cuo = sorted([f for f in filas if f["mercado"] == "ml" and f["concepto"] == "cuotas"], key=lambda f: int(f["cuotas"]))
            ap.append({"id": "cuotas", "titulo": "3 a 12 (solo Mercado Libre): Reducida y cuotas sin interés",
                       "filas": ([_fila_vista(red, "Reducida", "%")] if red else []) + [_fila_vista(f, f"{f['cuotas']} cuotas", "%") for f in cuo]})
        else:
            cuo = [f for f in filas if f["mercado"] == clave and f["concepto"] == "cuotas"]
            cuo.sort(key=lambda f: (f["cuotas"] != "simple", int(f["cuotas"]) if f["cuotas"].isdigit() else 0))
            fv = [_fila_vista(f, "Simple" if f["cuotas"] == "simple" else f"{f['cuotas']} cuotas", "%") for f in cuo]
            rec = por_clave.get((clave, "recargo_cuotas", ""))
            if rec:
                fv.append(_fila_vista(rec, ETIQUETA["recargo_cuotas"], "%"))
            ap.append({"id": "cuotas", "titulo": "Cuotas" + (" (18 y 24 solo Web)" if clave == "web" else ""), "filas": fv})
        canales.append({"clave": clave, "nombre": meta["nombre"], "apartados": ap})
    return {"canales": canales, "historial": hist[-50:][::-1], "info": info}
