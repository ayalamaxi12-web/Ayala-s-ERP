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
# comando en lugar del backend — lo usa el Cron de Railway de la corrida
# diaria de Rentabilidad ECOM (railway.cron.json):
#   ./entrypoint.sh python scripts/ecom_diario.py
#
# El túnel es OPCIONAL y NUNCA bloquea el arranque (2026-09-28: el Cron
# quedaba colgado): `tailscale up` tiene un tope de TS_UP_TIMEOUT segundos
# (default 20) y si no levanta se sigue sin túnel — lo que necesita Táctica
# queda vacío, el resto corre igual.
# En modo job (con argumentos) el túnel no se levanta salvo TS_EN_JOB=1: la
# corrida de ECOM no usa Táctica. Si se pide, el nodo se registra efímero
# (--state=mem:) para no dejar un dispositivo nuevo por corrida.
if [ "$#" -gt 0 ]; then
  TS_STATE="mem:"
  TS_HOSTNAME_DEFAULT="rentabilidad-cron"
  QUIERE_TUNEL="${TS_EN_JOB:-0}"
else
  TS_STATE="/tmp/tailscale/state"
  TS_HOSTNAME_DEFAULT="rentabilidad-backend"
  QUIERE_TUNEL=1
fi

if [ -z "$TS_AUTHKEY" ]; then
  echo "[entrypoint] TS_AUTHKEY no configurada -- sin túnel Tailscale (Táctica SQL no va a ser alcanzable)."
elif [ "$QUIERE_TUNEL" != "1" ]; then
  echo "[entrypoint] Modo job: sin túnel Tailscale (no hace falta; TS_EN_JOB=1 para levantarlo)."
else
  echo "[entrypoint] Levantando túnel Tailscale (máx. ${TS_UP_TIMEOUT:-20}s)..."
  mkdir -p /tmp/tailscale
  tailscaled --tun=userspace-networking --socks5-server=localhost:1055 --state="$TS_STATE" &

  for i in $(seq 1 10); do
    timeout 3 tailscale status >/dev/null 2>&1 && break
    sleep 1
  done

  if timeout "${TS_UP_TIMEOUT:-20}" tailscale up --authkey="${TS_AUTHKEY}" --accept-routes \
      --hostname="${TS_HOSTNAME:-$TS_HOSTNAME_DEFAULT}" --timeout="${TS_UP_TIMEOUT:-20}s"; then
    echo "[entrypoint] Túnel Tailscale arriba."
    python3 scripts/ts_sql_bridge.py &
  else
    echo "[entrypoint] AVISO: el túnel Tailscale no levantó en ${TS_UP_TIMEOUT:-20}s -- sigo sin túnel."
  fi
fi

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
