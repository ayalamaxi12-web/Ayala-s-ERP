"""Los tests no esperan el ritmo real de lectura de ML (ver `ml_full.PAUSA_OPS_SEG`) ni las esperas de reintento."""
import pytest


@pytest.fixture(autouse=True)
def _sin_pausas_de_ml(monkeypatch):
    import ml_full
    monkeypatch.setattr(ml_full, "PAUSA_OPS_SEG", 0)
    monkeypatch.setattr(ml_full, "PAUSA_GENERAL_SEG", 0)


@pytest.fixture(autouse=True)
def _sin_reintentos_de_lotes(monkeypatch):
    """Los tests existentes fijan `lotes_fallidos` a mano: los reintentos del simulador se prueban aparte, con su propio test."""
    import ml_reposicion
    monkeypatch.setattr(ml_reposicion, "REINTENTOS_LOTES", 0)
    monkeypatch.setattr(ml_reposicion, "ESPERA_REINTENTO_SEG", 0)


@pytest.fixture(autouse=True)
def _sin_refresco_de_faltantes(monkeypatch):
    """Un SKU que falta no dispara una bajada real de Ecom en los tests (la lógica del refresco se prueba aparte)."""
    from rentabilidad import costos_ecom
    monkeypatch.setattr(costos_ecom, "refrescar_por_faltante", lambda *a, **k: False)
