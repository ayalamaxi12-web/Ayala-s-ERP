import socket
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "scripts"))
import ts_sql_bridge as br  # noqa: E402


def _socks_falso():
    """Servidor SOCKS5 mínimo que acepta cualquier CONNECT (para probar el saludo del puente)."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def atender():
        c, _ = srv.accept()
        c.recv(3)
        c.sendall(b"\x05\x00")
        c.recv(64)
        c.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
        threading.Event().wait(1)
        c.close()

    threading.Thread(target=atender, daemon=True).start()
    return srv


def test_despues_del_saludo_la_conexion_no_tiene_timeout():
    srv = _socks_falso()
    br.SOCKS = srv.getsockname()
    s = br._conectar_via_socks5(("100.100.21.94", 1433))
    try:
        assert s.gettimeout() is None          # con timeout=10 el relay cortaba las consultas lentas
    finally:
        s.close()
        srv.close()
