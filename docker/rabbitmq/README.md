# Opt-in local RabbitMQ transport infrastructure

Stage 1 only. PostgreSQL remains authoritative; existing API/Worker/Redis/SSE
entrypoints do not import this adapter or include this Compose file. Starting
this broker does not fix or enable business task execution by itself.

## Reproduce

Run from the isolated Zebra repository root:

```bash
uv sync --all-packages --extra rabbitmq --frozen
.venv/bin/python scripts/provision_rabbitmq.py prepare --env-file docker/rabbitmq/.env
docker compose --env-file docker/rabbitmq/.env -p rabbitmq-infra-acceptance \
  -f docker/compose.rabbitmq.yml up -d --wait
.venv/bin/python scripts/provision_rabbitmq.py apply --env-file docker/rabbitmq/.env
ZEBRA_RABBITMQ_LIVE=1 .venv/bin/python -m pytest -q tests/integrations/test_rabbitmq_live.py
```

`prepare` exclusively creates a mode-0600 ignored file with five independent
random credentials. Re-running it fails rather than silently rotating secrets.
Use the same file on later starts; `apply` is repeatable. Never paste this file,
`docker compose config` output, connection URLs or raw messages into logs/chat.
Changing the bootstrap password in the file does not rotate a persisted broker's
provisioner password: perform explicit controlled rotation instead.

The live test is DESTRUCTIVE to this specific acceptance project's four queues:
it purges them and restarts its broker. Do not attach application consumers to
the `rabbitmq-infra-acceptance` project. The test checks the container's exact
project label; it is not a production smoke command.

Ports bind only loopback: AMQP 25672, management 25673, metrics 25692. This
single-node development fixture uses plaintext AMQP/HTTP on the local host.
Production needs TLS with validated server identity, three quorum members,
private networking, managed credentials, encryption/backup policy and HA tests.
No production TLS/HA acceptance is claimed here.

## Topology and ACL

| Vhost | Exchange | Queue | Exact routing key |
|---|---|---|---|
| `/trench` | `trench.command.x` | `trench.ai.turn.ready.q` | `ai.turn.ready.v1` |
| `/zebra` | `zebra.command.x` | `zebra.session.command.ready.q` | `session.command.ready.v1` |
| `/trench` | `trench.command.diagnostic.x` | `trench.command.diagnostic.q` | `delivery.rejected.v1` |
| `/zebra` | `zebra.command.diagnostic.x` | `zebra.command.diagnostic.q` | `delivery.rejected.v1` |

All queues are durable quorum queues. Each ready queue has its own same-vhost
`{system}.command.dlx` and corresponding `.dlq`. Reliability policy uses
at-least-once dead lettering, reject-publish overflow, delivery limit 5 and
4 MiB ready capacity. Capacity is a development budget, not a production SLO.
The broker rejects message bodies above 16 KiB.

Relay users can write only their command/diagnostic exchanges and exact topic keys;
consumer users read only their ready queue. Neither can configure topology,
cross vhosts or read DLQs. Only the provisioner has administrative access.
Runtime users are limited to 8 connections/16 channels; vhosts to 32 connections
and 8 queues. Vhosts do not isolate node disk/memory failure.

Native DLX can retain arbitrary original input and is restricted emergency
quarantine, not an ordinary operator queue. It is bounded to 1 MiB/24 hours in
this local fixture. Application validation failures must later persist a
sanitized rejection and confirm its separate diagnostic publication before transport ACK;
the adapter deliberately provides no
raw reject-to-DLQ method. Production retention must be tied to the approved
privacy/replay window, not copied from these local limits.

Diagnostic queues are separate from raw DLQs and bounded to 4 MiB/7 days with
reject-publish overflow. Runtime relay/consumer roles cannot read either queue.
Only generated rejection UUID, configured namespace/consumer role, SHA-256 body
digest, byte count, enum error code and DB creation time enter diagnostics.
Never copy raw payload, attacker-provided IDs or exception text into them.
`publish_diagnostic` validates this strict, bounded model before network I/O.
The Trench rejection row doubles as the diagnostic Outbox: concurrent identical
input shares one receipt; retries retain the same bytes/UUID. Its independently
scheduled `publish_once` sweep recovers pending/expired publication even if raw
redelivery reaches the emergency DLX. Positive broker confirm AND fenced DB
published commit are required before rejection callback return/consumer ACK.
Cancellation or ambiguous commit stays recoverable; do not replay raw DLQs
through this safe diagnostic route. Composition remains explicitly opt-in.

## Adapter contract

Optional extra `rabbitmq` installs aio-pika 10.0.1. The two repositories use the
same small implementation with their existing envelope imports. No dependency
or AMQP implementation is introduced into Zebra agent-core.

`RabbitMQTransport` explicitly starts one robust connection/channel, uses
persistent mandatory publications with confirms/return handling, and bounds
operations by timeout. Timeout is an unknown outcome: a future Outbox relay
must retry the SAME message ID, never invent a new business operation.
Passive queue declarations retain consumer registration across reconnects.
No automatic business retry, deduplication or authority inference occurs.

`Delivery.parse()` validates shape; DB identity/namespace/lease checks are still
mandatory. `ack()` is legal only after durable DB handoff or durable sanitized
rejection. Returning/raising from a callback never ACKs it. Original-channel
settlement prevents an old delivery from acknowledging a reused tag after
reconnect. Caller must recover/requeue or close on failed handoff.

Prefetch bounds unacknowledged delivery only. Stage 2/3 consumers must separately
bound handoff/execution slots and preserve DB recovery after early ACK.
Use separate relay and consumer instances/credentials; no shared business channel.
Runtime logging must redact/suppress third-party AMQP diagnostic logs before
activation; adapter exceptions alone are sanitized, not global library logs.

## Monitoring and stop

`prometheus.yml` and `alerts.yml` are optional host-local scrape/rule fragments,
not edits to your running monitoring stack. `/metrics` provides node totals;
`/metrics/detailed` requests only queue depths/consumer counts for the two vhosts.
No user/session/message identifiers become metric labels. These samples cover
broker availability, memory/disk pressure, DLQ depth and consumerless backlog.
Outbox age, handoff/fence, fallback, model and SSE timings belong to later
business instrumentation; broker metrics do not measure business completion.

Stop without deleting data:

```bash
docker compose --env-file docker/rabbitmq/.env -p rabbitmq-infra-acceptance \
  -f docker/compose.rabbitmq.yml stop
```

Remove only the throwaway acceptance resources after confirming no application
was connected (`--volumes` irreversibly removes its test queues/data):

```bash
docker compose --env-file docker/rabbitmq/.env -p rabbitmq-infra-acceptance \
  -f docker/compose.rabbitmq.yml down --volumes
```

Semantics: [RabbitMQ confirms](https://www.rabbitmq.com/docs/confirms),
[quorum queues](https://www.rabbitmq.com/docs/quorum-queues),
[aio-pika confirms](https://docs.aio-pika.com/rabbitmq-tutorial/7-publisher-confirms.html),
[bounded metric families](https://www.rabbitmq.com/docs/prometheus).
