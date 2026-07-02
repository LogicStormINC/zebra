# Zebra Agent Operator Runbook

## Purpose

This runbook describes the current local operator flow for Zebra Agent
Phase 26.

Scope:

- local workspace bootstrap
- CLI session creation, execution, cancel, suspend, resume, inspection, and approval
- local HTTP API serving
- session diff, artifacts, delivery audit, and SSE replay
- local snapshot-backed suspend and resume behavior

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

Use an explicit local database path so CLI, API, and worker read the same state:

```bash
export ZEBRA_DATABASE_URL=.zebra-agent/operator-runbook.sqlite
mkdir -p .zebra-agent
```

Optional local API auth:

```bash
export ZEBRA_API_AUTH_TOKEN=local-demo-token
```

If this variable is unset, the current local API remains open.

## Control Model

Current local Phase 26 control semantics:

- `run` creates a ready session or executes it immediately
- `cancel` moves a non-terminal session to `cancelled`
- `resume --execute` runs a ready session through the worker-backed execution path
- `suspend` snapshots a workspace-backed session and moves the durable state to
  `suspended`
- resume execution from a suspended session restores onto a fresh
  runtime-managed workspace before harness execution continues

Important boundaries:

- this is a filesystem snapshot, not a process checkpoint
- open subprocess state, in-memory interpreter state, and live sockets are not restored
- suspend is only supported for sessions with a valid local `workspace_root`
- restore creates a new working directory, so operators must not assume the old
  workspace path remains the active execution root

For the runtime storage layout and retention model, also read
`docs/local_snapshot_runtime.md`.

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

Cancel a local session:

```bash
uv run zebra-agent cancel <session_id>
```

Expected result:

- JSON output with `command=cancel`
- `cancelled=true`
- `status=cancelled`
- `workspace_status=cancelled`

Read the current session projection without executing:

```bash
uv run zebra-agent resume <session_id>
```

Suspend a local session:

```bash
uv run zebra-agent suspend <session_id>
```

Expected result:

- JSON output with `command=suspend`
- `suspended=true`
- `status=suspended`
- `workspace_status=suspended`
- `snapshot_id`

Resume execution for a ready or suspended session:

```bash
uv run zebra-agent resume <session_id> --execute --worker-id local-worker
```

Expected result for a ready session:

- JSON output with `executed=true`
- terminal `status` such as `completed` or `failed`
- `assistant_message`
- compact `trace` data for any executed builtin tool calls

Expected result for a suspended session:

- the worker restores onto a fresh runtime-managed workspace before execution
- durable workspace state updates to the restored `workspace_root`
- previous snapshot metadata is cleared from the workspace projection once restore succeeds
- terminal `status` reflects the post-resume harness result

If a session reaches `waiting_approval`, record a decision with:

```bash
uv run zebra-agent approve <session_id> --decision approve --reason "operator approved"
```

Expected result:

- JSON output with `decision=approve` or `decision=reject`
- durable approval `event_type`
- new event `sequence`
- updated session `status`

Run one prompt directly through the configured model gateway:

```bash
uv run zebra-agent model "Summarize the current repository state"
```

Expected result:

- JSON output with `command=model`
- assistant `response`
- provider, model, and usage metadata when the upstream API returns them

If the configured API key environment variable is missing, the command fails before sending any HTTP request.

## HTTP API Workflow

Start the local API server:

```bash
make api-serve
```

This serves `create_http_app()` at `http://127.0.0.1:8000`.

Health check:

```bash
curl http://127.0.0.1:8000/health
```

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

Suspend a session through the API:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${ZEBRA_API_AUTH_TOKEN}" \
  -d '{}' \
  http://127.0.0.1:8000/sessions/<session_id>/suspend
```

Expected result:

- JSON output with `suspended=true`
- `status=suspended`
- `workspace_status=suspended`
- `snapshot_id`

Cancel a session through the API:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${ZEBRA_API_AUTH_TOKEN}" \
  -d '{}' \
  http://127.0.0.1:8000/sessions/<session_id>/cancel
```

Expected result:

- JSON output with `cancelled=true`
- `status=cancelled`
- `workspace_status=cancelled`

Resume execution through the API layer:

```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${ZEBRA_API_AUTH_TOKEN}" \
  -d '{"worker_id":"api-worker","lease_ttl_seconds":45}' \
  http://127.0.0.1:8000/sessions/<session_id>/resume
```

Expected result:

- JSON output with `executed=true`
- `worker_id` echoing the requested worker identity
- terminal `status` and `current_sequence`
- `assistant_message` and compact `trace`
- for suspended sessions, restore occurs before harness execution continues

When `ZEBRA_API_AUTH_TOKEN` is set, pass a bearer token for non-health routes:

```bash
curl -H "Authorization: Bearer $ZEBRA_API_AUTH_TOKEN" \
  http://127.0.0.1:8000/sessions/<session_id>
```

Read one session:

```bash
curl http://127.0.0.1:8000/sessions/<session_id>
```

Review the current Git diff for a session workspace:

```bash
curl http://127.0.0.1:8000/sessions/<session_id>/diff
```

Read the same session workspace diff directly from the local CLI without the
HTTP API:

```bash
uv run zebra-agent diff <session_id> \
  --database .zebra-agent/operator-runbook.sqlite
```

Expected result:

- JSON output with `clean=true` or `clean=false`
- `git_status` from `git status --short`
- unified `diff` from the session workspace
- deterministic `diff_unavailable` conflict when the workspace is missing or not a Git repository

List model and tool artifacts indexed for a session:

```bash
curl http://127.0.0.1:8000/sessions/<session_id>/artifacts
```

Read delivery audit records for one session:

```bash
curl http://127.0.0.1:8000/sessions/<session_id>/delivery-audit
```

Read the same delivery audit records directly from the local CLI without the
HTTP API:

```bash
uv run zebra-agent delivery-audit <session_id> \
  --database .zebra-agent/operator-runbook.sqlite
```

Inspect the waiting approval queue directly from the local CLI:

```bash
uv run zebra-agent approval queue \
  --database .zebra-agent/operator-runbook.sqlite
```

Inspect one approval detail directly from the local CLI:

```bash
uv run zebra-agent approval inspect <approval_id> \
  --database .zebra-agent/operator-runbook.sqlite
```

Append one more user message to an existing session:

```bash
curl -X POST http://127.0.0.1:8000/sessions/<session_id>/messages \
  -H "Content-Type: application/json" \
  -d '{"content":"Please continue from the latest checkpoint."}'
```

Append the same follow-up user message directly from the local CLI without the
HTTP API:

```bash
uv run zebra-agent message <session_id> \
  --content "Please continue from the latest checkpoint." \
  --database .zebra-agent/operator-runbook.sqlite
```

The local HTTP API exposes the same approval decision path. In the current
local MVP, the approval id is the waiting session id:

```bash
curl -X POST http://127.0.0.1:8000/approvals/<session_id>/approve \
  -H "Content-Type: application/json" \
  -d '{"operator":"api-operator","reason":"operator approved"}'
```

To reject instead:

```bash
curl -X POST http://127.0.0.1:8000/approvals/<session_id>/reject \
  -H "Content-Type: application/json" \
  -d '{"reason":"unsafe command scope"}'
```

## Worker Loop

Run the local worker loop against durable ready sessions:

```bash
uv run zebra-agent-worker \
  --database .zebra-agent/operator-runbook.sqlite \
  --worker-id local-worker \
  --batch-size 1 \
  --max-cycles 1 \
  --stop-when-idle
```

Expected result:

- JSON output with `command=loop`
- `cycles_completed` and `idle_cycles`
- `stop_reason` such as `idle`, `max_cycles`, or `blocked`
- `executed_session_ids` for any claimed ready sessions
- `skipped_session_ids` when a ready session is already leased elsewhere

For a long-running local worker, omit `--max-cycles` and keep
`--stop-when-idle` unset:

```bash
uv run zebra-agent-worker \
  --database .zebra-agent/operator-runbook.sqlite \
  --worker-id local-worker \
  --batch-size 1 \
  --idle-sleep-seconds 2
```

Expected behavior:

- the process keeps polling until interrupted by the operator or process manager
- idle cycles sleep between polls
- ready sessions are claimed and executed as they appear
- final JSON is emitted when the process exits through a bounded run path

## Git And Delivery Surfaces

Create a local Git commit for a reviewed session workspace:

```bash
curl -X POST http://127.0.0.1:8000/sessions/<session_id>/commit \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: commit-<unique-retry-key>" \
  -d '{"message":"Implement reviewed changes"}'
```

Create the same local Git commit directly from the CLI without the HTTP API:

```bash
uv run zebra-agent commit <session_id> \
  --message "Implement reviewed changes" \
  --idempotency-key commit-<unique-retry-key> \
  --database .zebra-agent/operator-runbook.sqlite
```

Plan a pull request for a committed session workspace:

```bash
curl -X POST http://127.0.0.1:8000/sessions/<session_id>/pull-request \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: pr-<unique-retry-key>" \
  -d '{"title":"Implement reviewed changes","body":"Summary and validation notes."}'
```

Open the same pull-request plan directly from the local CLI without the HTTP
API:

```bash
uv run zebra-agent pull-request <session_id> \
  --title "Implement reviewed changes" \
  --body "Summary and validation notes." \
  --idempotency-key pr-<unique-retry-key> \
  --database .zebra-agent/operator-runbook.sqlite
```

Expected result in the current local-only runtime:

- pull-request planning remains local-first by default
- guarded remote SCM execution still requires explicit provider, dry-run, token,
  credential, network-profile, and policy gates
- delivery audit records persist non-replayed commit and pull-request attempts

## Session Stream Replay

Replay the persisted session event stream over SSE:

```bash
curl -N http://127.0.0.1:8000/sessions/<session_id>/stream
```

Read the same persisted session event stream directly from the local CLI
without the HTTP API:

```bash
uv run zebra-agent stream <session_id> \
  --database .zebra-agent/operator-runbook.sqlite
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
- create-only sessions replay bootstrap events before any later worker or execute path continues

## Proxy Gateway Operations

Proxy-backed SCM and MCP execution is documented in:

- [Proxy Gateway Operator Runbook](./proxy_gateway_operator_runbook.md)

Use that runbook for:

- proxy-backed GitHub pull-request configuration and rollback
- MCP proxy gateway execution semantics
- route / target / transport metadata interpretation
- proxy incident response and safe-default restoration

## Failure Interpretation

Interpret common local control-plane failures this way:

- `not_suspendable` means the session state or workspace state does not support a local snapshot-backed suspend
- `cannot_resume_terminal_session` means the session already reached a terminal state and cannot execute again
- `session_already_leased` means another worker already holds the session lease
- `diff_unavailable`, `commit_unavailable`, or `pull_request_unavailable` still indicate workspace or policy issues, not snapshot corruption

If suspend succeeds but a later resume fails:

1. inspect the session and workspace projection state
2. inspect the session stream for `session_suspended` and `session_resumed`
3. verify whether the retained snapshot is missing or incompatible under the runtime-managed snapshot root described in `docs/local_snapshot_runtime.md`
4. if needed, re-run resume after clearing the lease conflict or operator mistake

Interpret retained snapshot outcomes this way:

- `valid` means the retained payload and manifest still match the requested
  local snapshot
- `missing` usually means retention pruning, manual deletion, or prior cleanup
  already removed the retained payload
- `incompatible` means the retained payload exists but the manifest no longer
  matches the expected runtime or snapshot identity

## Known Boundaries

- this is still a local filesystem snapshot model, not full sandbox checkpointing
- suspend does not preserve running subprocess memory or network state
- restore moves execution onto a fresh runtime-managed workspace path
- snapshot retention is deterministic but local; operators should not treat it as archival backup
- successful restore also cleans the consumed retained snapshot payload
- health remains public even when the local bearer token is enabled

## Validation Commands

Use the default repository validation before or after operator changes:

```bash
make test
make check
```
