# syntax=docker/dockerfile:1

# --- build: resolve and install dependencies with uv -------------------------
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

# --- runtime ------------------------------------------------------------------
FROM python:3.13-slim-bookworm
# Runs as a non-root user. Match it to your host user (id -u) so the bind-mounted
# .env and .secrets stay readable/writable: --build-arg UID=$(id -u)
ARG UID=1000
RUN useradd --uid "${UID}" --home-dir /app --no-create-home app \
    && mkdir -p /app /data \
    && chown app:app /app /data
WORKDIR /app
COPY --from=build --chown=app:app /app /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/data/finance.db
USER app
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/login', timeout=3).status == 200 else 1)"
CMD ["uvicorn", "finance.main:app", "--host", "0.0.0.0", "--port", "8000"]
