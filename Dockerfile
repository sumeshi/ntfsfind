# syntax=docker/dockerfile:1
FROM python:3.13.16-slim-trixie AS builder
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
# Optional CA secret supports managed HTTPS proxies without weakening TLS.
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    python -m pip install --no-cache-dir uv==0.12.23
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export SSL_CERT_FILE=/run/secrets/proxy_ca; fi; \
    uv sync --frozen --no-dev --no-editable

FROM python:3.13.16-slim-trixie
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
WORKDIR /data
# docker run --rm -v "$(pwd):/data" ntfsfind:latest /data/sample.raw '.*\.evtx'
ENTRYPOINT ["ntfsfind"]
CMD ["--help"]
