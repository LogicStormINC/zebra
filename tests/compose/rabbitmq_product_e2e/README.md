# Isolated native product acceptance fixture

This fixture does not alter or restart original application services. It uses
project/network `rabbitmq-product-e2e`, dedicated PostgreSQL databases `zebra_e2e`
and `trench_e2e`, its own Redis/MinIO, and loopback ports 28432, 28379, 29000/29001,
28080 and 28443. The parent runner owns native Trench on 28000 and frontend on 3300.
The RabbitMQ acceptance project on 25672/25673 is managed separately.

Import `fixture.py` and retain **one** `build_environment()` dictionary for the
entire run. Never print it, write an env file, run expanded Compose `config`, or
print captured errors. Only the existing worker's allowlisted model credential
and runtime image/UID/GID/quota settings are read. Storage passwords, API token,
workload HMAC and cursor keys are generated in memory. Existing CA/TLS/broker key
files are mounted individually read-only; the CA private key is never mounted.

After the operator approves starting the fixture:

1. Call `prepare_workspace()`. It accepts only the exact dedicated child
   `/Volumes/ZEBRATRENCH/rabbitmq-product-e2e`, rejects symlinks, and never removes
   any existing files. Root layout reset is destructive inside this child only.
2. Call `compose(env, "up", "-d")`. PostgreSQL migration uses existing
   `docker/migrate.py`; subsequent bootstrap verifies mounted imports and registers
   the isolated Host authority before API/Worker start.
3. Start native Trench with `E2E_TRENCH_HOST_DSN` and the generated shared workload
   secret. Host URLs are `E2E_TLS_URL`, `E2E_BROKER_URL`, pinned by `E2E_CA_FILE`.
   Grant issuer is `https://broker.zebra.local:28443`; namespace is
   `trench-rabbitmq-e2e`, policy `trench-native-v2`, workload identity
   `rabbitmq-product-e2e-worker`. Host tool callback is
   `https://trench.zebra.local:28443/api/trench-ai/agent`.
4. Record `source_digest()` plus import origins and focused acceptance results.
   Application image IDs supply only dependencies: `/app/apps`, `/app/packages`
   and `/app/configs` are mounted read-only from the current isolated source.
5. Stop this project with `compose(env, "stop")`. Destruction of its volumes must
   be explicitly authorized (`down --volumes`), and loses this fixture's data.
   Never regenerate credentials against retained initialized data volumes.

The Worker uses gVisor/runsc on `tcp://host.docker.internal:2375`, which is the
approved sandbox engine. Every outer Docker inspection/image/Compose command pins
`--context orbstack` and first checks that context targets exactly
`unix:///Users/lukeding/.orbstack/run/docker.sock`; switching the current Docker
context cannot redirect the fixture. The sandbox engine remains separate.
Storage-enforced quota and the child mount must
be proven on the real engine before claiming execution acceptance. No model,
HTTP, browser or Rabbit delivery result is implied by fixture unit tests.

Run guards without Docker/services:

```sh
.venv/bin/python -m pytest tests/compose/rabbitmq_product_e2e -q
```
