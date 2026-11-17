import ml_respuestas as R
from ml_full import MLFullClient


def _q(i, f, resp=None, st="ANSWERED", item="MLA1"):
    return {"id": i, "date_created": f, "status": st, "item_id": item, "answer": {"text": "ok", "date_created": resp} if resp else None}


def test_preguntas_por_mes_tiempos_y_sin_responder():
    qs = [_q(1, "2026-10-05T10:00:00.000-03:00", "2026-10-05T11:00:00.000-03:00"), _q(2, "2026-10-06T10:00:00.000-03:00", "2026-10-08T10:00:00.000-03:00"),
          _q(3, "2026-11-02T10:00:00.000-03:00", None, "UNANSWERED", "MLA9"), _q(4, "2026-11-03T10:00:00.000-03:00", "2026-11-03T10:30:00.000-03:00")]
    m = R.por_mes_preguntas(qs)
    assert [x["mes"] for x in m] == ["2026-10", "2026-11"]
    o, n = m
    assert (o["preguntas"], o["respondidas"], o["sin_responder"], o["pct_respondidas"], o["mediana_h"], o["pct_1h"], o["pct_24h"]) == (2, 2, 0, 100.0, 24.5, 50.0, 50.0)
    assert (n["preguntas"], n["respondidas"], n["sin_responder"], n["pct_respondidas"]) == (2, 1, 1, 50.0) and n["mediana_h"] == 0.5
    assert R.top_sin_responder(qs) == [{"item_id": "MLA9", "sin_responder": 1}]


def _m(u, f):
    return {"from": {"user_id": u}, "message_date": {"created": f}}


def test_conversacion_primera_respuesta_del_vendedor():
    msgs = [_m(115764017, "2026-11-01T08:00:00.000-03:00"), _m(5, "2026-11-01T10:00:00.000-03:00"), _m(5, "2026-11-01T10:05:00.000-03:00"), _m(115764017, "2026-11-01T13:00:00.000-03:00")]
    c = R.conversacion(MLFullClient(get_fn=lambda u, p, h: {"messages": msgs}, token_fn=lambda x: "t"), "IT", "77")
    assert c["respuesta_h"] == 3.0 and c["mensajes_comprador"] == 2 and c["inicio"].startswith("2026-11-01T10:00")
    assert R.conversacion(MLFullClient(get_fn=lambda u, p, h: {"messages": [_m(115764017, "2026-11-01T08:00:00.000-03:00")]}, token_fn=lambda x: "t"), "IT", "77") is None


def test_mensajes_por_mes_y_metricas_punta_a_punta():
    def get(url, params, headers):
        if "questions/search" in url:
            return {"total": 1, "questions": [_q(1, "2026-11-02T10:00:00.000-03:00", "2026-11-02T12:00:00.000-03:00")]}
        if url.endswith("/orders/search"):
            return {"paging": {"total": 2}, "results": [{"id": 1, "pack_id": 900, "status": "paid"}, {"id": 2, "status": "paid"}]}
        if "/messages/packs/900/" in url:
            return {"messages": [_m(5, "2026-11-03T10:00:00.000-03:00"), _m(115764017, "2026-11-03T11:00:00.000-03:00")]}
        return {"messages": [_m(5, "2026-10-30T10:00:00.000-03:00")]}
    r = R.metricas_respuestas(MLFullClient(get_fn=get, token_fn=lambda c: "t"), "IT", "2026-10-01", "2026-11-17")
    assert r["preguntas_por_mes"][0]["mediana_h"] == 2.0
    mm = {x["mes"]: x for x in r["mensajes_por_mes"]}
    assert mm["2026-11"]["respondidas"] == 1 and mm["2026-11"]["mediana_h"] == 1.0 and mm["2026-10"]["sin_responder"] == 1


def test_endpoint_valida(monkeypatch):
    from fastapi.testclient import TestClient
    import main
    monkeypatch.setenv("ERP_API_KEY", "k")
    c = TestClient(main.app)
    assert c.post("/ml-respuestas/run?cuenta=IT&desde=2026-11-05&hasta=2026-11-02", headers={"X-ERP-Key": "k"}).status_code == 422


def test_periodo_anterior_misma_duracion_y_comparacion():
    assert R.periodo_anterior("2026-11-01", "2026-11-10") == ("2026-10-22", "2026-10-31")
    def get(url, params, headers):
        if "questions/search" in url:
            return {"total": 1, "questions": [_q(1, "2026-11-02T10:00:00.000-03:00", "2026-11-02T12:00:00.000-03:00")]}
        return {}
    r = R.metricas_respuestas(MLFullClient(get_fn=get, token_fn=lambda c: "t"), "IT", "2026-11-01", "2026-11-10", con_mensajes=False, comparar=True)
    assert r["anterior"]["desde"] == "2026-10-22" and r["anterior"]["preguntas_total"]["preguntas"] == 0 and r["preguntas_total"]["preguntas"] == 1
    assert r["preguntas_series"]["por_semana"][0]["fecha"] == "2026-11-02"


def test_categorias_de_chat_y_desglose():
    assert R.categoria_chat("Hola, ¿cuándo llega mi pedido?") == "¿Dónde está mi pedido? / envío"
    assert R.categoria_chat("Necesito la FACTURA A") == "Factura"
    assert R.categoria_chat("No funciona, vino roto") == "Producto con falla o garantía"
    assert R.categoria_chat("xyz") == "Otros"
    cs = [{"categoria": "Factura", "inicio": "2026-11-01T10:00:00", "respuesta_h": 2.0, "texto": "factura"}, {"categoria": "Factura", "inicio": "2026-10-01T10:00:00", "respuesta_h": None, "texto": "factura a"},
          {"categoria": "Otros", "inicio": "2026-11-02T10:00:00", "respuesta_h": 1.0, "texto": "xyz"}]
    d = R.desglose_chats(cs)
    assert d[0]["categoria"] == "Factura" and d[0]["cantidad"] == 2 and d[0]["sin_responder"] == 1 and d[0]["pct"] == 66.7 and d[0]["por_mes"] == {"2026-10": 1, "2026-11": 1}


def test_foto_guardada_se_lee_sin_volver_a_ml(sesion_sqlite=None):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from contextlib import contextmanager
    from rentabilidad.models import Base
    eng = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    S = sessionmaker(bind=eng)

    @contextmanager
    def ses():
        db = S()
        try:
            yield db
            db.commit()
        finally:
            db.close()
    assert R.leer_foto("IT", "2026-10-01", "2026-10-31", True, True, ses)["existe"] is False
    R.guardar_foto("IT", "2026-10-01", "2026-10-31", True, True, {"preguntas_total": {"preguntas": 5}}, 1.0, ses)
    v = R.leer_foto("IT", "2026-10-01", "2026-10-31", True, True, ses)
    assert v["existe"] and v["payload"]["preguntas_total"]["preguntas"] == 5 and v["periodo_cerrado"] is True
    assert R.leer_foto("IT", "2026-10-01", "2026-10-31", False, True, ses)["existe"] is False
    assert R.listar_fotos("IT", ses)[0]["desde"] == "2026-10-01"
