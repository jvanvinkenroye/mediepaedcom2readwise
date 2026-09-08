# syntax=docker/dockerfile:1.7
# Stage 1: Abhaengigkeiten und docling-Modelle bauen
FROM python:3.12.11-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    # CPU-only torch spart mehrere GB gegenueber dem CUDA-Default
    UV_INDEX_URL=https://pypi.org/simple \
    UV_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu \
    UV_INDEX_STRATEGY=unsafe-best-match

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

# Layout- und TableFormer-Modelle einmal laden, damit der Container offline laeuft.
RUN /app/.venv/bin/docling-tools models download layout tableformer -o /models

# Stage 2: schlankes Laufzeit-Image
FROM python:3.12.11-slim-bookworm AS runtime

RUN groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --home /app --shell /usr/sbin/nologin app \
    && mkdir -p /data && chown app:app /data

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /models /models

ENV PATH="/app/.venv/bin:$PATH" \
    DATA_DIR=/data \
    DOCLING_ARTIFACTS_PATH=/models \
    HF_HUB_OFFLINE=1 \
    OMP_NUM_THREADS=4 \
    PYTHONUNBUFFERED=1

USER app
WORKDIR /app
VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3).status == 200 else 1)"]

CMD ["medienpaed-reader", "serve"]
