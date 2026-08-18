"""Puente TCP simple para correr en la PC de Maxx (no en Railway).

En vez de depender de "subnet routing" de Tailscale (que en Windows requiere
IP forwarding + NAT a nivel de sistema operativo, frágil de configurar bien),
esta PC escucha en su propia IP de Tailscale y reenvía cada conexión a la
SQL de Táctica usando una conexión saliente normal -- exactamente la misma
ruta (VPN "Global") que ya usa cualquier programa de esta PC para llegar a
10.10.10.99, sin necesitar reenvío de paquetes a nivel de red.

Config vía variables de entorno:
- TS_RELAY_LISTEN  (default "0.0.0.0:1433")
- TS_RELAY_TARGET  (default "10.10.10.99:1433")
"""
import os
import socket
import threading


def _env_hostport(nombre: str, default: str) -> tuple[str, int]:
    host, port = os.environ.get(nombre, default).rsplit(":", 1)
    return host, int(port)


LISTEN = _env_hostport("TS_RELAY_LISTEN", "0.0.0.0:1433")
TARGET = _env_hostport("TS_RELAY_TARGET", "10.10.10.99:1433")


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
        remoto = socket.create_connection(TARGET, timeout=10)
    except OSError as e:
        print(f"[ts_pc_relay] no se pudo conectar a {TARGET}: {e}", flush=True)
        cliente.close()
        return
    threading.Thread(target=_relay, args=(cliente, remoto), daemon=True).start()
    threading.Thread(target=_relay, args=(remoto, cliente), daemon=True).start()


def main() -> None:
    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    servidor.bind(LISTEN)
    servidor.listen(20)
    print(f"[ts_pc_relay] escuchando en {LISTEN}, reenviando a {TARGET}", flush=True)
    while True:
        cliente, direccion = servidor.accept()
        print(f"[ts_pc_relay] conexión desde {direccion}", flush=True)
        threading.Thread(target=_atender, args=(cliente,), daemon=True).start()


if __name__ == "__main__":
    main()
