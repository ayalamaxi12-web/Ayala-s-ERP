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
#
# Sin argumentos arranca el backend (uvicorn). Con argumentos corre ese
# comando en lugar del backend, con el mismo túnel — lo usa el Cron de
# Railway de la corrida diaria de Rentabilidad ECOM (railway.cron.json):
#   ./entrypoint.sh python scripts/ecom_diario.py
# En ese modo el nodo de Tailscale se registra efímero (--state=mem:), para
# que cada corrida no deje un dispositivo nuevo en el panel.
if [ "$#" -gt 0 ]; then
  TS_STATE="mem:"
  TS_HOSTNAME_DEFAULT="rentabilidad-cron"
else
  TS_STATE="/tmp/tailscale/state"
  TS_HOSTNAME_DEFAULT="rentabilidad-backend"
fi

if [ -n "$TS_AUTHKEY" ]; then
  mkdir -p /tmp/tailscale
  tailscaled --tun=userspace-networking --socks5-server=localhost:1055 --state="$TS_STATE" &

  for i in $(seq 1 10); do
    tailscale status >/dev/null 2>&1 && break
    sleep 1
  done

  tailscale up --authkey="${TS_AUTHKEY}" --accept-routes --hostname="${TS_HOSTNAME:-$TS_HOSTNAME_DEFAULT}"

  python3 scripts/ts_sql_bridge.py &
else
  echo "TS_AUTHKEY no configurada -- arrancando sin túnel Tailscale (Táctica SQL no va a ser alcanzable)."
fi

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
