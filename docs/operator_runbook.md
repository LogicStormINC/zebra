# Zebra Agent Operator Runbook

## Purpose

This runbook describes the current local operator flow for Zebra Agent Phase 8.

Scope:

- local workspace bootstrap
- CLI session creation, inspection, and approval
- local HTTP API serving
- SSE session stream replay

This runbook only documents behavior that exists in the repository today.

## Prerequisites

- Python `3.12`
- `uv`
- repository root as current working directory

Bootstrap once:

```bash
make sync
```

## Local Database

Use an explicit local database path so CLI and API read the same state:

```bash
export ZEBRA_DATABASE_URL=.zebra-agent/operator-runbook.sqlite
mkdir -p .zebra-agent
```

The CLI can still override this path with `--database`, but the runbook uses one shared default.

Optional local API auth:

```bash
export ZEBRA_API_AUTH_TOKEN=local-demo-token
```

If this variable is unset, the current local API remains open.

## CLI Workflow

Create one session:

```bash
uv run zebra-agent run "Inspect the current workspace" --title "Operator demo"
```

Expected result:

- JSON output with `command=run`
- a `session_id`
- `status=created`

Inspect the same session:

```bash
uv run zebra-agent inspect <session_id>
```

Resume readback:

```bash
uv run zebra-agent resume <session_id>
```

If a session reaches `waiting_approval`, record a decision with:

```bash
uv run zebra-agent approve <session_id> --decision approve --reason "operator approved"
```

## API Serve

Start the local API server:

```bash
make api-serve
```

This serves `create_http_app()` at `http://127.0.0.1:8000`.

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Read one session:

```bash
curl http://127.0.0.1:8000/sessions/<session_id>
```

When `ZEBRA_API_AUTH_TOKEN` is set, pass a bearer token for non-health routes:

```bash
curl -H "Authorization: Bearer $ZEBRA_API_AUTH_TOKEN" \
  http://127.0.0.1:8000/sessions/<session_id>
```

## Session Stream Replay

Replay the persisted session event stream over SSE:

```bash
curl -N http://127.0.0.1:8000/sessions/<session_id>/stream
```

When auth is enabled:

```bash
curl -N -H "Authorization: Bearer $ZEBRA_API_AUTH_TOKEN" \
  http://127.0.0.1:8000/sessions/<session_id>/stream
```

Current behavior:

- returns `text/event-stream`
- replays persisted events in ascending `sequence`
- closes after the current stored events are sent

Current limitation:

- this is replay, not a live tail
- reconnect cursor and incremental delivery are not implemented yet

## Validation Commands

Use the default repository validation before or after operator changes:

```bash
make test
make check
```

## Known Boundaries

- The API currently exposes health, session read, and session stream replay only.
- The stream endpoint is read-only and does not subscribe to future events.
- Local API auth is optional and uses one static bearer token from settings.
- Health remains public even when the local bearer token is enabled.
