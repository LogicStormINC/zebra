# syntax=docker/dockerfile:1.7

FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de

ARG MEM0_PYTHON_VERSION

WORKDIR /app

COPY requirements.in requirements.runtime.in requirements.lock /tmp/
COPY --from=mem0-source /server/requirements.txt /tmp/upstream-requirements.txt

RUN test -n "${MEM0_PYTHON_VERSION}" \
    && sed -i "s/^mem0ai.*/mem0ai==${MEM0_PYTHON_VERSION}/" /tmp/upstream-requirements.txt \
    && python -c "from pathlib import Path; assert Path('/tmp/upstream-requirements.txt').read_bytes() == Path('/tmp/requirements.in').read_bytes(), 'requirements.in drifted from pinned Mem0 source'" \
    && pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock \
    && pip install --no-index --no-deps -r /tmp/requirements.in -r /tmp/requirements.runtime.in \
    && pip check \
    && rm /tmp/requirements.in /tmp/requirements.runtime.in /tmp/requirements.lock /tmp/upstream-requirements.txt

COPY --from=mem0-source /server/ /app/

RUN groupadd --gid 10001 mem0 \
    && useradd --uid 10001 --gid mem0 --no-create-home --shell /usr/sbin/nologin mem0 \
    && mkdir -p /app/history \
    && chown mem0:mem0 /app/history

USER mem0

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
