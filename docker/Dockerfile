# syntax=docker/dockerfile:1.7

ARG ZEBRA_PYTHON_BASE_IMAGE=python:3.12-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b
FROM ghcr.io/astral-sh/uv:0.11.12@sha256:3a59a3cdd5f7c217faa36e32dbc7fddbb0412889c2a0a5229f6d790e5a019dd7 AS uv
FROM ${ZEBRA_PYTHON_BASE_IMAGE} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH=/app/.venv/bin:$PATH

COPY --from=uv /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY configs ./configs
COPY apps ./apps
COPY packages ./packages
COPY docker/migrate.py ./docker/migrate.py

RUN uv sync --frozen --all-packages --no-dev \
    && useradd --system --create-home --uid 65532 --shell /usr/sbin/nologin zebra \
    && chown -R zebra:zebra /app

USER zebra

FROM runtime AS migrate
ENTRYPOINT ["python", "docker/migrate.py"]

FROM runtime AS api
ENTRYPOINT ["uvicorn", "zebra_agent_api.http:create_http_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS worker
ENTRYPOINT ["zebra-agent-worker"]

FROM runtime AS broker
ENTRYPOINT ["python", "-m", "zebra_host_grant_broker"]

FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/library/docker:27-cli AS docker-cli

FROM runtime AS worker-engine
USER root
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
USER zebra
