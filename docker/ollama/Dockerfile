# Ollama image with the model pre-pulled at startup. The official
# `ollama/ollama` image doesn't ship any models — they have to be
# pulled via `ollama pull <model>` after the daemon is running. We
# wrap the daemon with a small entrypoint that pulls the configured
# model in the background once Ollama is responsive.
FROM ollama/ollama:latest

# Drop in the entrypoint script that starts the daemon and pulls the
# model. The default model matches the user's local setup
# (qwen2.5-coder:3b — small, fast, code-aware) and is overridable
# via the OLLAMA_MODEL env var.
COPY docker/ollama/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENV OLLAMA_HOST=0.0.0.0:11434 \
    OLLAMA_MODEL=qwen2.5-coder:3b

EXPOSE 11434

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
