"""Puente TCP -> SOCKS5 para llegar a la SQL de Táctica desde un contenedor
sin acceso a /dev/net/tun (Railway). Tailscale corre ahí en modo
userspace-networking (ver entrypoint.sh) y expone un proxy SOCKS5 local en
vez de una interfaz de red real -- pymssql no sabe hablar SOCKS5, así que
este script escucha en localhost y reenvía cada conexión a través de ese
proxy hacia el destino real, para que la conexión a la base le llegue como
si el SQL Server estuviera en localhost.

Config vía variables de entorno (default = caso de uso actual, SQL Server
de Táctica en 10.10.10.99:1433, alcanzado vía el subnet router que corre en
la PC de Maxx):
- TS_BRIDGE_LISTEN  (default "127.0.0.1:1433")
- TS_BRIDGE_TARGET  (default "10.10.10.99:1433")
- TS_BRIDGE_SOCKS   (default "127.0.0.1:1055")
"""
import os
import socket
import struct
import threading


def _env_hostport(nombre: str, default: str) -> tuple[str, int]:
    host, port = os.environ.get(nombre, default).rsplit(":", 1)
    return host, int(port)


LISTEN = _env_hostport("TS_BRIDGE_LISTEN", "127.0.0.1:1433")
TARGET = _env_hostport("TS_BRIDGE_TARGET", "10.10.10.99:1433")
SOCKS = _env_hostport("TS_BRIDGE_SOCKS", "127.0.0.1:1055")


def _conectar_via_socks5(destino: tuple[str, int]) -> socket.socket:
    s = socket.create_connection(SOCKS, timeout=10)
    s.sendall(b"\x05\x01\x00")  # versión 5, 1 método, sin autenticación
    version, metodo = s.recv(2)
    if version != 5 or metodo != 0:
        raise ConnectionError(f"SOCKS5 no aceptó conexión sin autenticación (método={metodo})")
    host, port = destino
    host_b = host.encode()
    s.sendall(b"\x05\x01\x00\x03" + bytes([len(host_b)]) + host_b + struct.pack(">H", port))
    resp = s.recv(10)
    if len(resp) < 2 or resp[1] != 0:
        codigo = resp[1] if len(resp) > 1 else "?"
        raise ConnectionError(f"SOCKS5 CONNECT rechazado (código={codigo})")
    return s


def _relay(origen: socket.socket, destino: socket.socket) -> None:
    try:
        while True:
            datos = origen.recv(4096)
            if not datos:
                break
            destino.sendall(datos)
    except OSError:
        pass
    finally:
        for s in (origen, destino):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def _atender(cliente: socket.socket) -> None:
    try:
        remoto = _conectar_via_socks5(TARGET)
    except Exception as e:
        print(f"[ts_sql_bridge] no se pudo conectar vía SOCKS5 a {TARGET}: {e}", flush=True)
        cliente.close()
        return
    threading.Thread(target=_relay, args=(cliente, remoto), daemon=True).start()
    threading.Thread(target=_relay, args=(remoto, cliente), daemon=True).start()


def main() -> None:
    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    servidor.bind(LISTEN)
    servidor.listen(20)
    print(f"[ts_sql_bridge] escuchando en {LISTEN}, reenviando a {TARGET} vía SOCKS5 {SOCKS}", flush=True)
    while True:
        cliente, _ = servidor.accept()
        threading.Thread(target=_atender, args=(cliente,), daemon=True).start()


if __name__ == "__main__":
    main()
