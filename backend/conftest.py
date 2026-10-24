"""Los tests no esperan el ritmo real de lectura de ML (ver `ml_full.PAUSA_OPS_SEG`) ni las esperas de reintento."""
import pytest


@pytest.fixture(autouse=True)
def _sin_pausas_de_ml(monkeypatch):
    import ml_full
    monkeypatch.setattr(ml_full, "PAUSA_OPS_SEG", 0)
    monkeypatch.setattr(ml_full, "PAUSA_GENERAL_SEG", 0)
