#!/bin/sh
# Start the Ollama daemon, wait for it to become responsive, then pull
# the configured model in the background. Without this, the first
# request from the app would fail because no model is loaded; the
# alternative is requiring the user to run `docker exec ... ollama
# pull qwen2.5-coder:3b` manually, which is hostile UX for a quick
# "docker compose up" experience.

set -e

MODEL="${OLLAMA_MODEL:-qwen2.5-coder:3b}"

# Run the daemon in the background. We use `ollama serve` directly so
# we can keep this script as PID 1 — that way docker stop sends SIGTERM
# to us, we forward it to the daemon, and the container exits cleanly.
ollama serve &
DAEMON_PID=$!

# Forward SIGTERM/SIGINT to the daemon so `docker stop` doesn't have
# to wait the 10s grace period before SIGKILL.
trap 'kill -TERM "$DAEMON_PID" 2>/dev/null; wait "$DAEMON_PID"' TERM INT

# Wait for the daemon to start listening. We poll the local HTTP
# endpoint rather than just `sleep N` because cold starts (first run
# on a fresh volume) take longer than warm starts and we don't want
# to either over- or under-wait.
echo "[ollama-init] waiting for daemon to become responsive..."
for i in $(seq 1 60); do
    if ollama list > /dev/null 2>&1; then
        echo "[ollama-init] daemon ready after ${i}s"
        break
    fi
    sleep 1
done

# Pull the model. This is idempotent — if the model is already on the
# mounted volume from a previous run, `ollama pull` is a no-op.
# Running in the background means container readiness isn't gated on
# the (potentially multi-GB) download — the app's startup-period
# healthcheck handles the "ollama not ready yet" window separately.
{
    echo "[ollama-init] ensuring model '${MODEL}' is available..."
    if ollama pull "${MODEL}"; then
        echo "[ollama-init] model '${MODEL}' is ready"
    else
        echo "[ollama-init] WARNING: failed to pull '${MODEL}'; check network / model name"
    fi
} &

# Keep the daemon in the foreground so the container stays alive.
wait "$DAEMON_PID"
