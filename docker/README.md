# Zebra Docker Compose

`docker/` separates three lifecycles. The application overlay now exists as a
separate main-container lifecycle; it never owns the dependency containers.

| Layer | File | Status |
|---|---|---|
| Database/object dependencies | `compose.dependencies.yml` | Implemented by `CLOUD-COMPOSE-INFRA-01` |
| Optional Mem0 auxiliary service | `compose.mem0.yml` | Boot-smoke only; no Zebra adapter yet |
| Zebra API/Worker/migrations | `compose.application.yml` | `CLOUD-COMPOSE-APP-01`; joins the external dependency network |

The application overlay requires the PostgreSQL, object-storage and live-state
contracts already recorded by the cloud mainline. It uses the explicit cloud
profile and fails closed on missing configuration; Redis is not yet selected by
API/Worker startup.

## Service and authority boundaries

| Service | Role | Durable authority |
|---|---|---|
| `postgres` | Future Zebra Task/Event/Projection/Lease truth | Yes, after `CLOUD-PG-01` |
| `redis-live` | Erasable fan-out, notifications and bounded cache | No |
| `minio` / `minio-init` | Future Artifact bytes and bucket bootstrap | Bytes only; metadata stays in Zebra PostgreSQL |
| `mem0-postgres` | Mem0 vector/application data | Derived index only |
| `mem0-migrate` / `mem0-api` | Optional self-hosted Mem0 service | Derived, replaceable and degraded-safe |
| `mem0-history-data` | Mem0 server history SQLite file | Operational history, not Zebra truth |

Mem0 never replaces Zebra's governed `MemoryStorePort`. A later
`AgentMemoryGateway` may publish only confirmed memories with `infer=false` and
must revalidate every search hit against Zebra's authoritative lifecycle before
prompt admission.

## Start base dependencies

```bash
cp docker/.env.example docker/.env
docker compose \
  --env-file docker/.env \
  -f docker/compose.dependencies.yml \
  config --quiet
docker compose \
  --env-file docker/.env \
  -f docker/compose.dependencies.yml \
  up -d --wait postgres redis-live minio minio-init
```

Host ports bind to `127.0.0.1` and default to `15432`, `16379`, `19000`
and `19001`. The services join the explicitly named `zebra-dependencies`
network so a future application project can join without owning their lifecycle.

`minio-init` also enables bucket versioning. Artifact deletion is bound to the exact
opaque object version returned by the S3-compatible provider; ETag is never treated
as Zebra's SHA-256 authority.

## Start the application containers

The application overlay is intentionally a separate Compose project. Start the
base dependency stack first, then copy the application example and align its
PostgreSQL and MinIO credentials with `docker/.env`:

```bash
cp docker/.env.application.example docker/.env.application
docker compose \
  --env-file docker/.env.application \
  -f docker/compose.application.yml \
  config --quiet
docker compose \
  --env-file docker/.env.application \
  -f docker/compose.application.yml \
  up -d --build --wait zebra-migrate zebra-api zebra-worker
curl --fail http://127.0.0.1:18080/health
```

`zebra-migrate` is the one-shot migration container; API and Worker start only
after it exits successfully. The overlay joins the external
`zebra-dependencies` network and does not create PostgreSQL, Redis, MinIO or
Mem0 containers. Stop only the application project with:

```bash
docker compose \
  --env-file docker/.env.application \
  -f docker/compose.application.yml \
  down --remove-orphans
```

The dependency stack and its volumes remain intact.

The application image uses the explicit `cloud` profile and requires the full
PostgreSQL, namespace, signing-key and S3 configuration. Redis live fan-out is
not selected by API/Worker startup in this slice. Application Compose defaults
the Python runtime base to the API-confirmed `linux/amd64` mirror
`swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/library/python:3.12-slim-bookworm`
for local/CI pulls; set `ZEBRA_APPLICATION_PYTHON_BASE_IMAGE` to the pinned
Docker Hub digest when the upstream registry is reachable. The Dockerfile keeps
that official digest as its standalone-build default.

## Start the optional Mem0 boot smoke

Mem0's official Compose file is a development example. This repository instead
builds the REST server from the pinned Mem0 release commit
`ca2abca2b884e038d3e525070e79d3057ef2012c`, pins `mem0ai==2.0.13`, enables
the complete Python graph with package hashes, enables authentication, disables
telemetry, runs non-root/read-only and excludes the Dashboard, Graph and MCP
services. The image build also rejects drift between the reviewed input and the
pinned upstream server requirements, verifies all locked direct dependencies and
runs `pip check`. Mem0's generated client identity config is redirected to tmpfs;
the separate history volume is the only writable persistent API path. Its health
probe combines an audit-skipped HTTP route with `SELECT 1`, so monitoring does
not grow Mem0's persistent request log. See the official
[OSS setup](https://docs.mem0.ai/open-source/setup),
[REST API](https://docs.mem0.ai/open-source/features/rest-api) and
[Compose source](https://github.com/mem0ai/mem0/blob/main/server/docker-compose.yaml).

The committed `mem0-healthcheck-only` model-key sentinel can only prove boot and
authentication behavior. It must not be used for memory writes or searches.

```bash
docker compose \
  --env-file docker/.env \
  -f docker/compose.dependencies.yml \
  -f docker/compose.mem0.yml \
  --profile mem0 config --quiet
docker compose \
  --env-file docker/.env \
  -f docker/compose.dependencies.yml \
  -f docker/compose.mem0.yml \
  --profile mem0 build mem0-api
docker compose \
  --env-file docker/.env \
  -f docker/compose.dependencies.yml \
  -f docker/compose.mem0.yml \
  --profile mem0 up -d --wait mem0-api
```

Inspect all containers and prove that the protected API rejects an anonymous
memory request:

```bash
docker compose \
  --env-file docker/.env \
  -f docker/compose.dependencies.yml \
  -f docker/compose.mem0.yml \
  --profile mem0 ps -a
curl --fail http://127.0.0.1:18088/auth/setup-status
curl -sS -o /dev/null -w '%{http_code}\n' \
  'http://127.0.0.1:18088/memories?user_id=anonymous-probe'
```

The final command must print `401`. The deterministic Spike below covers the
remaining OSS write/search and failure contracts without an external key; only
real-provider compatibility remains credential-gated.

## Run the isolated deterministic Mem0 contract spike

The test-only `compose.mem0.test.yml` redirects Mem0's OpenAI-compatible
embedding calls to a deterministic local stub. Chat completions deliberately
fail, so a successful write proves that `infer=false` did not call the LLM. The
Spike uses a separate Compose project, network, ports and volumes; it does not
touch the long-running dependency data.

```bash
ZEBRA_RUN_MEM0_SPIKE=1 uv run pytest -q \
  tests/spikes/mem0/test_mem0_oss_contract.py
```

This validates Mem0 OSS/REST/pgvector behavior without an external credential.
It does not validate a real model provider; that remains a separate release
gate. See `docs/Mem0 OSS协议兼容性验证记录.md` for the observed limitations.

## Stop and cleanup

Stop only the optional Mem0 layer while preserving all volumes and base services:

```bash
docker compose \
  --env-file docker/.env \
  -f docker/compose.dependencies.yml \
  -f docker/compose.mem0.yml \
  --profile mem0 stop mem0-api mem0-postgres
```

Do not add `down --volumes` casually: it deletes Zebra PostgreSQL, MinIO, Mem0
PostgreSQL and Mem0 history data for the whole `zebra-dependencies` project.
