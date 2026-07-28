# Zebra Docker Compose

`docker/` separates three lifecycles. Only the first two exist today.

| Layer | File | Status |
|---|---|---|
| Database/object dependencies | `compose.dependencies.yml` | Implemented by `CLOUD-COMPOSE-INFRA-01` |
| Optional Mem0 auxiliary service | `compose.mem0.yml` | Boot-smoke only; no Zebra adapter yet |
| Zebra API/Worker/migrations | `compose.application.yml` | Intentionally absent; locked as `CLOUD-COMPOSE-APP-01` |

The application overlay stays absent until the PostgreSQL, object-storage and
live-Redis adapters exist. Starting API/Worker containers now would still use
SQLite and would misrepresent the cloud dependency stack as authoritative.

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

The final command must print `401`. Real write/search, duplicate delivery,
restart, deletion, namespace and embedding-dimension behavior remain acceptance
criteria of `MEM-MEM0-SPIKE-01`, which requires a disposable approved model key.

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
