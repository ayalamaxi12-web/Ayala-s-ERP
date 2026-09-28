FROM tailscale/tailscale:stable AS tailscale

FROM python:3.11-slim

WORKDIR /app
# Logs de Python sin buffer: sin esto, lo que imprime un proceso sin TTY
# (el Cron de Railway) no aparece en el log hasta que termina.
ENV PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Tailscale (ver entrypoint.sh) -- puente hacia la SQL de Táctica, que vive
# en una red interna sin ruta pública desde Railway.
COPY --from=tailscale /usr/local/bin/tailscaled /usr/local/bin/tailscaled
COPY --from=tailscale /usr/local/bin/tailscale /usr/local/bin/tailscale

COPY . .
RUN chmod +x entrypoint.sh

CMD ["./entrypoint.sh"]
