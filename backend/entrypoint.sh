#!/bin/sh
set -e

# Túnel Tailscale hacia la SQL de Táctica (10.10.10.99), alcanzada vía el
# subnet router que corre en la PC de Maxx (aprobado como 10.10.10.99/32 en
# el panel de Tailscale -- no se expone el resto de la red de oficina).
# Modo userspace-networking: este contenedor no tiene acceso a /dev/net/tun,
# así que Tailscale expone un proxy SOCKS5 local en vez de una interfaz de
# red real; scripts/ts_sql_bridge.py traduce eso a una conexión TCP normal
# en 127.0.0.1:1433 para que pymssql (que no sabe hablar SOCKS5) no necesite
# ningún cambio.
if [ -n "$TS_AUTHKEY" ]; then
  mkdir -p /tmp/tailscale
  tailscaled --tun=userspace-networking --socks5-server=localhost:1055 --state=/tmp/tailscale/state &

  for i in $(seq 1 10); do
    tailscale status >/dev/null 2>&1 && break
    sleep 1
  done

  tailscale up --authkey="${TS_AUTHKEY}" --accept-routes --hostname=rentabilidad-backend

  python3 scripts/ts_sql_bridge.py &
else
  echo "TS_AUTHKEY no configurada -- arrancando sin túnel Tailscale (Táctica SQL no va a ser alcanzable)."
fi

exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
