"""«Poner precio» (Precios y ofertas ML): el operador es obligatorio TAMBIÉN en el backend, solo precio de lista, y se registra (con hora) solo si ML lo aceptó."""
import os

import pytest
from fastapi.testclient import TestClient

import main

URL = "/ayala-core/item/MLA1/aplicar-precio"
BODY = {"cuenta": "IT", "sku": "PLANCHA-SUB-GORRA", "precio": 25999, "precio_anterior": 27999, "margen_pct": "18.40", "bajo_umbral": False,
        "operador": "Natalia", "origen": "Precios y ofertas ML"}


@pytest.fixture()
def cl(monkeypatch):
    escritos, registros = [], []
    resultado = {"ok": True}

    def fijar(item_id, cuenta, precio, tachado):
        escritos.append((item_id, cuenta, precio, tachado))
        return dict(resultado)

    monkeypatch.setattr(main, "_ayala_core_aplicar_precio_sync", fijar)
    monkeypatch.setattr(main, "_registrar_historial_oferta", lambda fila: registros.append(fila))
    c = TestClient(main.app)
    c.escritos, c.registros, c.resultado = escritos, registros, resultado
    return c


def _post(cl, **cambios):
    b = {**BODY, **cambios}
    h = {"X-ERP-Key": os.environ["ERP_API_KEY"]} if os.environ.get("ERP_API_KEY") else {}
    return cl.post(URL, json=b, headers=h)


def test_sin_operador_no_escribe_nada_en_ml(cl):
    r = _post(cl, operador="  ")
    assert r.status_code == 422 and cl.escritos == [] and cl.registros == []


def test_solo_precio_de_lista_positivo_y_sin_tachado(cl):
    assert _post(cl, precio_tachado=39999).status_code == 422
    assert _post(cl, precio=0).status_code == 422
    assert cl.escritos == []


def test_ok_escribe_una_vez_y_registra_con_operador_margen_origen_y_hora(cl):
    r = _post(cl)
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert len(cl.escritos) == 1 and cl.escritos[0][0] == "MLA1" and cl.escritos[0][3] is None
    f = cl.registros[0]
    assert f["Accion"] == "Poner precio" and f["Operador"] == "Natalia" and f["Margen % Resultante"] == "18.40" and f["Bajo Umbral"] == "No"
    assert f["Origen"] == "Precios y ofertas ML" and f["Precio Anterior"] == 27999


def test_bajo_umbral_se_registra_como_si(cl):
    _post(cl, bajo_umbral=True)
    assert cl.registros[0]["Bajo Umbral"] == "Sí"


def test_si_ml_rechaza_no_se_registra_y_se_devuelve_el_motivo(cl):
    cl.resultado.clear()
    cl.resultado.update({"ok": False, "error": "has_bids: la publicación tiene ofertas"})
    r = _post(cl)
    assert r.json()["ok"] is False and "has_bids" in r.json()["error"] and cl.registros == []


def test_el_flujo_del_motor_de_precios_sigue_igual(cl):
    b = {k: v for k, v in BODY.items() if k not in ("origen", "margen_pct", "bajo_umbral")}
    h = {"X-ERP-Key": os.environ["ERP_API_KEY"]} if os.environ.get("ERP_API_KEY") else {}
    r = cl.post(URL, json={**b, "operador": ""}, headers=h)          # el Motor nunca exigió operador acá
    assert r.status_code == 200 and cl.registros[0]["Accion"] == "Ayala Core -- aplicar precio" and cl.registros[0]["Margen % Resultante"] == ""


def test_el_historial_lleva_hora_y_origen_al_final():
    assert main.HIST_OFERTAS_HEADERS[-2:] == ["Hora", "Origen"]
    assert len(main._hora_argentina()) == 8
