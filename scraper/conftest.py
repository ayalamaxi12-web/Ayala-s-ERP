import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest


@pytest.fixture(autouse=True)
def _sin_pausas(monkeypatch):
    import corrida
    import sheets_io
    import prueba
    for m in (corrida, sheets_io, prueba):
        monkeypatch.setattr(m.time, 'sleep', lambda s: None)
