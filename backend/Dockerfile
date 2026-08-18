FROM tailscale/tailscale:stable AS tailscale

FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Tailscale (ver entrypoint.sh) -- puente hacia la SQL de Táctica, que vive
# en una red interna sin ruta pública desde Railway.
COPY --from=tailscale /usr/local/bin/tailscaled /usr/local/bin/tailscaled
COPY --from=tailscale /usr/local/bin/tailscale /usr/local/bin/tailscale

COPY . .
RUN chmod +x entrypoint.sh

CMD ["./entrypoint.sh"]
