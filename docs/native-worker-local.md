# Native Apple Silicon Worker acceptance

## Why

The local Apple Silicon host was running an amd64 Worker and Docker CLI.
Ten alternating read-only Docker info calls in the same diagnostic container
measured medians of 149.86 ms (amd64 CLI) and 18.34 ms (arm64 CLI). These are
CLI timings, not whole-turn latency. No daemon, authority, or sandbox check
was disabled for the comparison.

## Reproduce the opt-in build

This is a local development option, not a change to production defaults.
The API and broker images are unaffected by the Worker-specific variables.

Docker provides static binaries for testing:
[official binary installation guidance](https://docs.docker.com/engine/install/binaries/).
The local CLI stage pins the existing 27.5.1 version and archive SHA-256;
it does not install a daemon or alter host Docker credentials. Static binaries
need explicit security updates and are not an automatic-update production path.

```sh
docker build --platform linux/arm64 -f docker/Dockerfile.arm64-cli \
  -t zebra-docker-cli:27.5.1-arm64 .
```

Set these two entries in the ignored local `docker/.env`:

```dotenv
ZEBRA_WORKER_PYTHON_BASE_IMAGE=python:3.12-slim-bookworm@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2
ZEBRA_WORKER_DOCKER_CLI_IMAGE=zebra-docker-cli:27.5.1-arm64
```

Then use the normal acceptance Compose inputs:

```sh
docker compose --env-file docker/.env --env-file docker/trench-acceptance.env \
  -f docker/compose.dependencies.yml -f docker/compose.application.yml \
  -f docker/compose.trench-acceptance.yml -p zebra-trench-acceptance build zebra-worker
docker compose --env-file docker/.env --env-file docker/trench-acceptance.env \
  -f docker/compose.dependencies.yml -f docker/compose.application.yml \
  -f docker/compose.trench-acceptance.yml -p zebra-trench-acceptance up -d --no-deps zebra-worker
```

## Runnable architecture check

This checks both Python's machine architecture and the actual CLI ELF header,
not merely the image metadata. It makes no network or daemon calls.

```sh
docker run --rm --network none --read-only --cap-drop ALL \
  --entrypoint python zebra-trench-acceptance-zebra-worker:latest -c '
import platform, struct
from pathlib import Path
assert platform.machine() == "aarch64", platform.machine()
header = Path("/usr/local/bin/docker").read_bytes()[:20]
assert header[:4] == b"\x7fELF"
assert struct.unpack("<H" if header[5] == 1 else ">H", header[18:20])[0] == 183
print("native Python and Docker CLI: OK")'
```

Follow with Worker health and real signed Trench requests, including a second
turn on the same Task. Architecture correctness alone is not E2E acceptance.

## Rollback

Remove only the two Worker-specific overrides from `docker/.env`, rebuild and
recreate just `zebra-worker` with the commands above. No schema migration or
data deletion is involved. Existing runtime identity checks, fenced leases,
namespace isolation, and disposable sandbox lifecycle are unchanged.

## Local result (2026-09-05)

Worker image `fcf4474fc30e` is arm64, deployed healthy. Python and CLI ELF checks
passed. Runtime/Worker regression: 527 passed, 23 environment-gated skips;
`make check` passed. Compose resolved the native overrides for Worker only.

Real signed Trench requests reused Task `c96a2359-313b-4900-9095-ffea2cce7a3f`:

| Request | First text | Finished |
| --- | ---: | ---: |
| New Task, short reply | 2.395s | 2.732s |
| Same Task, short reply | 2.021s | 2.446s |
| Same Task, subscription listing | 1.935s | 3.184s |

Durable events confirm `sources.list` status `executed`, not merely a successful
transport. Follow-up command-to-model fell from 2.622s to 0.860s; model-to-first
delta was 0.822s. Previous short follow-up first text was 3.374s and finish
4.358s. The native Python base also moves 3.12.12 to 3.12.13; the isolated CLI
comparison above controls for that by running both CLIs in the same container.

These are small-sample cross-service measurements, not browser first-paint or
p95. Complex report generation, concurrent load, and browser rendering remain
separate acceptance boundaries. No branch merge or remote push was performed.
