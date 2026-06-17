#!/bin/sh
# Entrypoint: optionally generate a self-signed TLS cert and start uvicorn.
# Set ENABLE_HTTPS=true to run HTTPS on PORT (default 8000).
# When ENABLE_HTTPS=true, also starts a plain HTTP server on HTTP_PORT (default 8080)
# so OAuth2 providers that block https://localhost can redirect to http://localhost:8080.

set -e

PORT="${PORT:-8000}"
HTTP_PORT="${HTTP_PORT:-8080}"

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

    # Start plain HTTP on HTTP_PORT in the background (for OAuth callbacks)
    echo "[start.sh] Starting HTTP server on port $HTTP_PORT (OAuth callback)"
    python -m uvicorn main:app \
        --host 0.0.0.0 \
        --port "$HTTP_PORT" \
        --log-level warning &

    # Start HTTPS on PORT (main app)
    echo "[start.sh] Starting HTTPS server on port $PORT"
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
