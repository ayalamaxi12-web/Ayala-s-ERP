"""get_client() — sin credenciales, debe fallar como ConfiguracionFaltante,
no con el error crudo de la librería (bug real encontrado en vivo el
2026-08-11: con RENT_SHEET_GLOBAL_ID configurado pero sin credenciales de
Google, esto tiraba FileNotFoundError sin capturar en ningún lado —
persistencia.py._opcional solo atrapaba ConfiguracionFaltante)."""
import pytest

from rentabilidad.config import ConfiguracionFaltante
from rentabilidad.gsheets import get_client


def test_sin_credenciales_levanta_configuracion_faltante(monkeypatch, tmp_path):
    monkeypatch.delenv("GOOGLE_CREDENTIALS_JSON", raising=False)
    monkeypatch.chdir(tmp_path)  # sin credentials.json en este directorio
    with pytest.raises(ConfiguracionFaltante):
        get_client()


def test_credenciales_json_invalido_levanta_configuracion_faltante(monkeypatch):
    monkeypatch.setenv("GOOGLE_CREDENTIALS_JSON", "no es json valido")
    with pytest.raises(ConfiguracionFaltante):
        get_client()
