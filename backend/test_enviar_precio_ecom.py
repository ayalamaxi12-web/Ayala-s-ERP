"""«Enviar a Ecom» (Jugar mi precio): operador obligatorio, no toca SKU con varias variantes, se da por bueno solo con lectura de verificación y se registra."""
import pytest
from fastapi.testclient import TestClient

import main

BODY = {"cookie": "CAKEPHP=x", "sku": "PLANCHA-SUB-GORRA", "precio": 26000, "margen_pct": "18.20", "bajo_umbral": False, "operador": "Natalia"}


def _variantes(precio, n=1, lista="Mercado Libre"):
    return [{"variantId": str(i), "position": i + 1, "prices": [{"name": lista, "priceId": "9", "currentPrice": float(precio), "variantPriceId": "5"}]} for i in range(n)]


@pytest.fixture()
def cl(monkeypatch):
    estado = {"precio": 27999.0, "n": 1, "escrituras": [], "registros": [], "aplica": True, "lista": "Mercado Libre"}

    async def fetch(cookie, sku):
        return "<html>"

    monkeypatch.setattr(main, "ecom_fetch_price_html", fetch)
    monkeypatch.setattr(main, "ecom_parse_variants", lambda html: _variantes(estado["precio"], estado["n"], estado["lista"]) if estado.get("hay", True) else [])

    async def actualizar(cookie, sku, madre, pos, price, nombre):
        estado["escrituras"].append((sku, madre, price, nombre))
        if estado["aplica"]:
            estado["precio"] = price
        return {"success": True}

    monkeypatch.setattr(main, "ecom_update_price", actualizar)
    monkeypatch.setattr(main, "_registrar_historial_oferta", lambda fila: estado["registros"].append(fila))
    c = TestClient(main.app)
    c.estado = estado
    return c


def _post(cl, **cambios):
    import os
    h = {"X-ERP-Key": os.environ["ERP_API_KEY"]} if os.environ.get("ERP_API_KEY") else {}
    return cl.post("/competencia/enviar-precio-ecom", json={**BODY, **cambios}, headers=h)


def test_sin_operador_no_se_toca_nada(cl):
    assert _post(cl, operador=" ").status_code == 422 and cl.estado["escrituras"] == []
    assert _post(cl, precio=0).status_code == 422 and _post(cl, cookie="").status_code == 422


def test_ok_cambia_la_lista_mercado_libre_verifica_y_registra(cl):
    r = _post(cl).json()
    assert r == {"ok": True, "precio_anterior": 27999.0, "precio_nuevo": 26000.0}
    assert cl.estado["escrituras"] == [("PLANCHA-SUB-GORRA", "PLANCHA-SUB-GORRA", 26000.0, "Mercado Libre")]
    f = cl.estado["registros"][0]
    assert f["Accion"] == "Enviar precio a Ecom" and f["Operador"] == "Natalia" and f["Precio Anterior"] == 27999.0 and f["Precio Nuevo"] == 26000.0 and f["Origen"] == "Análisis de Competencia"


def test_un_sku_con_varias_variantes_no_se_toca(cl):
    cl.estado["n"] = 3
    r = _post(cl).json()
    assert r["ok"] is False and "3 variantes" in r["error"] and "Verificar Ecom" in r["error"] and cl.estado["escrituras"] == [] and cl.estado["registros"] == []


def test_si_la_lectura_de_verificacion_no_confirma_no_se_da_por_bueno_ni_se_registra(cl):
    cl.estado["aplica"] = False
    r = _post(cl).json()
    assert r["ok"] is False and "no confirma" in r["error"] and cl.estado["registros"] == []


def test_sku_inexistente_o_sin_la_lista(cl):
    cl.estado["hay"] = False
    assert "No se encontró" in _post(cl).json()["error"]
    cl.estado["hay"] = True
    cl.estado["lista"] = "Precio Web"
    assert "no tiene la lista" in _post(cl).json()["error"] and cl.estado["escrituras"] == []
