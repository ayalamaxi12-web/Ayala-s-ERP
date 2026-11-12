import requests

from ml_ofertas import MLOfertasClient


def _http_error(status):
    r = requests.Response()
    r.status_code = status
    return requests.HTTPError(f"{status} Client Error", response=r)


def _cliente(malos, status=403, llamadas=None):
    """get_fn falso de `/items?ids=`: si el lote incluye alguna publicación «mala» responde con error HTTP; si no, devuelve las publicaciones."""
    def get(url, params, headers):
        ids = params["ids"].split(",")
        if llamadas is not None:
            llamadas.append(ids)
        if any(i in malos for i in ids):
            raise _http_error(status)
        return [{"code": 200, "body": {"id": i, "title": f"t{i}"}} for i in ids]
    return MLOfertasClient(get_fn=get, token_fn=lambda cuenta: "tok")


def test_un_lote_con_403_se_parte_y_solo_se_saltea_la_publicacion_prohibida():
    ids = [f"MLA{n}" for n in range(1, 21)]
    llamadas = []
    ml = _cliente({"MLA7"}, llamadas=llamadas)
    detalle = ml.detalle_items_ofertas(ids, "IT")
    assert sorted(d["id"] for d in detalle) == sorted(i for i in ids if i != "MLA7")        # se leyeron las otras 19
    assert ml.items_sin_acceso == [{"item_id": "MLA7", "cuenta": "IT", "motivo": "ML respondió 403 (sin acceso a esta publicación)"}]
    assert len(llamadas) < 20                                                                # se aisló por mitades, no una por una


def test_si_todo_va_bien_no_hay_llamadas_extra_ni_publicaciones_salteadas():
    llamadas = []
    ml = _cliente(set(), llamadas=llamadas)
    assert len(ml.detalle_items_ofertas([f"MLA{n}" for n in range(1, 26)], "MT")) == 25
    assert len(llamadas) == 2 and not getattr(ml, "items_sin_acceso", [])                    # 25 ids = 2 lotes


def test_otros_errores_siguen_propagandose():
    ml = _cliente({"MLA1"}, status=401)
    try:
        ml.detalle_items_ofertas(["MLA1", "MLA2"], "IT")
    except requests.HTTPError as e:
        assert e.response.status_code == 401
    else:
        raise AssertionError("un 401 no debe taparse")
