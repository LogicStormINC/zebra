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
profile and fails closed on missing configuration; API and Worker use the
explicit `ZEBRA_LIVE_REDIS_URL` to publish committed Events after durable append.

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
PostgreSQL, namespace, signing-key, S3 and live Redis configuration. Application Compose defaults
the Python runtime base to the API-confirmed `linux/amd64` mirror
`swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/library/python:3.12-slim-bookworm`
for local/CI pulls; set `ZEBRA_APPLICATION_PYTHON_BASE_IMAGE` to the pinned
Docker Hub digest when the upstream registry is reachable. The Dockerfile keeps
that official digest as its standalone-build default.

## Optional Scheduler and product compatibility

Base application Compose starts API, Worker and migrations without a business
product, private CA files or Scheduler authority configuration. The Scheduler is
available with `--profile scheduler`. Configure its grant exchange URL, workload
identity/secret, issuer, audience, JWKS URI and allowed origins before starting it.
Compose rendering permits blanks; the existing Scheduler configuration loader
rejects missing or invalid authority at process startup before any schedule work.

Historical Trench deployments must explicitly add `compose.trench-compat.yml`.
It restores `zebra-api-legacy` with the existing image identity and `trench-prod`
namespace, API dependency, private CA mounts and always-on Scheduler with the
historical `trench-scheduler` defaults. Keep the existing deployment environment
and CA files; the neutral example intentionally supplies neither. This overlay
does not rewrite credentials, registries, events or databases.

With a local gVisor engine, set `ZEBRA_LOCAL_GVISOR_CLIENT_CERT_DIR` to the verified
client certificate directory and retain the verified workspace root, VM address
and certificate group. **Overlay order matters**: gVisor replaces Worker mounts
to remove the local Docker socket; apply compatibility after it to restore Host
and Broker TLS trust alongside the engine client certificates:

```bash
docker compose --env-file /absolute/path/to/existing-deployment.env \
  -f docker/compose.application.yml \
  -f docker/compose.local-gvisor.yml \
  -f docker/compose.trench-compat.yml config --quiet
```

`compose.coverage-pro-test.yml` contains historical legacy API overrides and
requires the compatibility overlay as well. For an independent deployment using
private issuers, supply an explicit mount overlay and set the per-service
`ZEBRA_API_SSL_CERT_FILE` / `ZEBRA_WORKER_SSL_CERT_FILE`; the public system bundle
remains the base default.

The user-operated activation script requires an environment file argument:
`docker/local-gvisor/recreate-application.sh /absolute/path/to/deployment.env`.
Append `--trench-compat` for the historical product; the script enforces the
ordered overlays and runs runtime isolation preflight before replacing services.
Run it only as an explicitly authorized activation step.

`make test-runtime-independence` validates rendered composition and release
contracts. The default rollout candidate is `zebra.cloud-rollout-candidate.v2`:
it freezes only Runtime coordinates while retaining common evidence, protocol,
rollback and capability checks. Its attestation and rehearsal use v2, with the
`host-browser-client-action` scenario. The preserved
`configs/cloud_rollout_candidate.trench-joint.example.json` uses strict v1 joint
coordinates and the `trench-browser-client-action` rehearsal. Examples contain
placeholders and cannot attest a release until populated with real evidence.
Joint release evidence must use the explicit compatibility capabilities:

```bash
make release-evidence CAPABILITIES=configs/cloud_release_capabilities.trench-joint.example.json
make validate-rollout-candidate \
  ROLLOUT_CANDIDATE=/absolute/path/to/populated-joint-candidate.json
```

v1 requires a `trench-e2e` PASS gate for capability `trench`, including its
nonplaceholder evidence digest. The evidence builder still rejects missing,
stale, dirty or failed gate results. v2 allows omitted product gates; any Trench
gate present must explicitly report `NOT_ENABLED`. v2 also requires every core,
composition, integration and fault gate to pass; the integration gate binds all
five dependency/recovery member digests. Runtime and memory capabilities must
be explicit and their gate statuses must agree. Enabled gates require evidence
digests; an empty gate inventory cannot attest an independent release.
The default release capabilities mark Trench `not_enabled`; core, dependencies,
recovery and security gates remain required.

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


## Generic Host authority and binding policy (batch02)

New live Host discovery defaults to `ZEBRA_HOST_MANIFEST_BINDING_POLICY=declared`:
every tool must contain `resourceBindings`, including an empty array. Published
connector profiles pin this policy in a new immutable revision. Apply the additive
v106 migration through the usual deployment process before running the new code;
existing profile rows remain NULL and keep their old digest/compatibility behavior.

The Scheduler defaults to `ZEBRA_SCHEDULER_GRANT_EXCHANGE_PROTOCOL=generic`.
The Broker process defaults to `ZEBRA_GRANT_BROKER_AUTHORITY_MODE=generic` and
requires a fixed HTTPS `ZEBRA_GRANT_BROKER_AUTHORITY_URL` plus explicit Host and
namespace. That business endpoint verifies credentials and current entitlements;
a scheduler HMAC alone is insufficient in generic mode. See
[the developer contract](../docs/CLOUD_AGENT_DECOUPLING_BATCH2.md).

Existing Trench deployments use `compose.trench-compat.yml` and the explicit
`trench_legacy` Broker mode in their product overlay. Legacy mode preserves the
historical entitlement trust model until the business authority is upgraded.
No live services or existing databases are changed by editing these files.


## Product integration ownership

The default RabbitMQ provisioner prepares Runtime-only credentials/topology.
Historical joint acceptance must explicitly pass `--trench-compat`; see
[rabbitmq/README.md](rabbitmq/README.md). Existing vhosts/queues/credentials are
not removed or rotated. Product-owned joint CI stays manual; product-neutral
contract/storage conformance has separate Make targets and CI without business
credentials. Compatibility retirement is an offline materials check described in
[the fourth-batch plan](../docs/CLOUD_AGENT_DECOUPLING_BATCH4.md), not an automatic
live cleanup, database migration or deployment instruction.
