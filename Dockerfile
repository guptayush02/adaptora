# syntax=docker/dockerfile:1.7
# Multi-stage build for the Token Optimizer.
#   Stage 1 (frontend-builder): compile the React app with Vite.
#   Stage 2 (backend):          install Python deps, copy backend + the
#                               built frontend assets, run uvicorn.
#
# The final image runs ONE process that serves both the API and the SPA
# from the same port — no nginx, no extra reverse proxy. That matches
# the user's "one container for frontend + backend" requirement and
# keeps the deploy story dead simple.

# ────────────────────────────── Stage 1: frontend ──────────────────────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /build

# Install deps first so docker layer caching does the heavy lifting on
# rebuilds where only source files (not package.json) changed.
#
# IMPORTANT: the host's frontend/node_modules is excluded via .dockerignore,
# so npm does a clean Linux-native install here. Without that exclusion the
# host's macOS binaries (e.g. vite) get copied in and fail at build time.
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund

# Copy the rest of the frontend source and build.
COPY frontend/ ./
RUN npm run build


# ────────────────────────────── Stage 2: backend ──────────────────────────────
FROM python:3.11-slim AS backend

# System deps: build-essential for any wheels that need compilation;
# curl for healthchecks; libpq-dev for psycopg2 if/when DB switches to
# postgres. We strip the apt lists after install to keep the image lean.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        libpq-dev \
        openssl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps first (same layer-caching trick as the frontend stage).
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir 'psycopg2-binary>=2.9'

# Headless Chromium for rendering JavaScript-heavy doc sites (e.g. Microsoft
# Learn / LinkedIn docs) so the dynamic extractor can read content that isn't
# present in the static HTML. `--with-deps` installs the required system libs.
# Runs entirely server-side and invisible — no GUI, nothing the end user sees.
RUN playwright install --with-deps chromium

# Backend source.
COPY main.py ./
COPY mcp_server.py ./
COPY app/ ./app/

# Built frontend → backend serves these via FastAPI's StaticFiles +
# SPA-fallback (see main.py). Keeping it inside ./frontend/dist matches
# the path main.py probes for, so the same code works in dev and docker.
COPY --from=frontend-builder /build/dist ./frontend/dist
COPY start.sh ./
RUN chmod +x start.sh

# Environment defaults — overridable from docker-compose / .env.
ENV HOST=0.0.0.0 \
    PORT=8000 \
    OLLAMA_MODEL=qwen2.5-coder:3b \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

# Container healthcheck — hits /api/health which the existing API
# exposes. Docker uses this to mark the container healthy/unhealthy
# before starting dependents in docker-compose.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl --silent --fail -k https://localhost:${PORT}/api/health \
        || curl --silent --fail http://localhost:${PORT}/api/health \
        || exit 1

CMD ["./start.sh"]
