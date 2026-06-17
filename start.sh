#!/bin/sh
# Entrypoint: optionally generate a self-signed TLS cert and start uvicorn.
# Set ENABLE_HTTPS=true in your environment to enable HTTPS on PORT (default 8000).

set -e

PORT="${PORT:-8000}"

if [ "${ENABLE_HTTPS:-false}" = "true" ]; then
    CERT_DIR="/app/certs"
    mkdir -p "$CERT_DIR"

    if [ ! -f "$CERT_DIR/cert.pem" ]; then
        echo "[start.sh] Generating self-signed TLS certificate..."
        openssl req -x509 -newkey rsa:2048 -nodes \
            -keyout "$CERT_DIR/key.pem" \
            -out "$CERT_DIR/cert.pem" \
            -days 3650 \
            -subj "/CN=localhost" \
            -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" \
            2>/dev/null
        echo "[start.sh] Certificate generated at $CERT_DIR/cert.pem"
    fi

    exec python -m uvicorn main:app \
        --host 0.0.0.0 \
        --port "$PORT" \
        --ssl-keyfile "$CERT_DIR/key.pem" \
        --ssl-certfile "$CERT_DIR/cert.pem"
else
    exec python -m uvicorn main:app \
        --host 0.0.0.0 \
        --port "$PORT"
fi
