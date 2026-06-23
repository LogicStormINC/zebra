# Zebra Agent Operator Runbook

## Purpose

This runbook describes the current local operator flow for Zebra Agent Phase 8.

Scope:

- local workspace bootstrap
- CLI session creation, durable execution, inspection, and approval
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
- `status=ready`
- persisted bootstrap events for session creation, user input, and task preparation

Create and execute one durable harness attempt immediately:

```bash
uv run zebra-agent run "Inspect the current workspace" \
  --title "Operator execute demo" \
  --execute \
  --workspace "$(pwd)"
```

Expected result:

- JSON output with `executed=true`
- terminal `status` such as `completed` or `failed`
- `assistant_message`
- compact `trace` data for any executed builtin tool calls

Current default policy profile for `--execute` is `workspace_write`.
Override it explicitly when needed:

```bash
uv run zebra-agent run "Inspect git status" \
  --execute \
  --workspace "$(pwd)" \
  --policy-profile read_only
```

Inspect the same session:

```bash
uv run zebra-agent inspect <session_id>
```

Resume readback:

```bash
uv run zebra-agent resume <session_id>
```

Execute the queued ready session through the worker-backed resume path:

```bash
uv run zebra-agent resume <session_id> --execute --worker-id local-worker
```

Expected result:

- JSON output with `executed=true`
- terminal `status` such as `completed` or `failed`
- `assistant_message`
- compact `trace` data for any executed builtin tool calls

Execute the same queued ready session through the API layer:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${ZEBRA_AGENT_API_AUTH_TOKEN}" \
  -d '{"worker_id":"api-worker","lease_ttl_seconds":45}' \
  http://127.0.0.1:8000/sessions/<session_id>/resume
```

Expected result:

- JSON output with `executed=true`
- `worker_id` echoing the requested worker identity
- terminal `status` and `current_sequence`
- `assistant_message` and compact `trace`

Run the local worker loop against durable ready sessions:

```bash
uv run zebra-agent-worker \
  --database .zebra/sessions.sqlite \
  --worker-id local-worker \
  --batch-size 1 \
  --max-cycles 1 \
  --stop-when-idle
```

Expected result:

- JSON output with `command=loop`
- `cycles_completed` and `idle_cycles`
- `executed_session_ids` for any claimed ready sessions
- `skipped_session_ids` when a ready session is already leased elsewhere

If a session reaches `waiting_approval`, record a decision with:

```bash
uv run zebra-agent approve <session_id> --decision approve --reason "operator approved"
```

Run one prompt directly through the configured model gateway:

```bash
uv run zebra-agent model "Summarize the current repository state"
```

Expected result:

- JSON output with `command=model`
- assistant `response`
- provider, model, and usage metadata when the upstream API returns them

If the configured API key environment variable is missing, the command fails before sending any HTTP request.

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

Append one more user message to an existing session:

```bash
curl -X POST http://127.0.0.1:8000/sessions/<session_id>/messages \
  -H "Content-Type: application/json" \
  -d '{"content":"Please continue from the latest checkpoint."}'
```

Expected result:

- JSON output with `appended=true`
- appended `content`
- new `sequence` and `current_sequence`
- unchanged non-terminal session `status`

Create one session through the API without immediate execution:

```bash
curl -X POST http://127.0.0.1:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Inspect the current workspace","title":"API create demo"}'
```

Create and execute one durable local harness attempt through the API:

```bash
curl -X POST http://127.0.0.1:8000/sessions \
  -H "Content-Type: application/json" \
  -d "{\"prompt\":\"Inspect the current workspace\",\"title\":\"API execute demo\",\"workspace\":\"$(pwd)\",\"execute\":true}"
```

When `ZEBRA_API_AUTH_TOKEN` is set, pass a bearer token for non-health routes:

```bash
curl -H "Authorization: Bearer $ZEBRA_API_AUTH_TOKEN" \
  http://127.0.0.1:8000/sessions/<session_id>
```

Authenticated create or execute:

```bash
curl -X POST http://127.0.0.1:8000/sessions \
  -H "Authorization: Bearer $ZEBRA_API_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"prompt\":\"Inspect the current workspace\",\"workspace\":\"$(pwd)\",\"execute\":true}"
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
- create-only sessions now replay bootstrap events before any later worker or execute path continues

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
- The API now also exposes `POST /sessions` for local session creation and optional immediate execution.
- The stream endpoint is read-only and does not subscribe to future events.
- Local API auth is optional and uses one static bearer token from settings.
- Health remains public even when the local bearer token is enabled.
