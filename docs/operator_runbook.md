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
- `stop_reason` such as `idle`, `max_cycles`, or `blocked`
- `executed_session_ids` for any claimed ready sessions
- `skipped_session_ids` when a ready session is already leased elsewhere

For a long-running local worker, omit `--max-cycles` and keep
`--stop-when-idle` unset:

```bash
uv run zebra-agent-worker \
  --database .zebra/sessions.sqlite \
  --worker-id local-worker \
  --batch-size 1 \
  --idle-sleep-seconds 2
```

Expected behavior:

- the process keeps polling until interrupted by the operator or process manager
- idle cycles sleep between polls
- ready sessions are claimed and executed as they appear
- final JSON is emitted when the process exits through a bounded run path

If a session reaches `waiting_approval`, record a decision with:

```bash
uv run zebra-agent approve <session_id> --decision approve --reason "operator approved"
```

The local HTTP API exposes the same approval decision path. In the current local MVP,
the approval id is the waiting session id:

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

Expected result:

- JSON output with `approval_id` and `session_id`
- `decision=approve` or `decision=reject`
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

Review the current Git diff for a session workspace:

```bash
curl http://127.0.0.1:8000/sessions/<session_id>/diff
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

Expected result:

- JSON output with an `artifacts` list
- stable `artifact_id`, `sequence`, `source`, `kind`, `label`, `uri`, and `preview`
- model-call artifacts for assistant messages and usage metadata
- tool-run artifacts for tool output and optional `artifact_uri`
- an explicit empty list when no artifacts have been indexed

Create a local Git commit for a reviewed session workspace:

```bash
curl -X POST http://127.0.0.1:8000/sessions/<session_id>/commit \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: commit-<unique-retry-key>" \
  -d '{"message":"Implement reviewed changes"}'
```

Expected result:

- JSON output with `committed=true`
- new `commit_sha`
- committed `message`
- session `workspace`
- deterministic `policy_blocked` conflict unless the session was created with `policy_profile=full_access`
- deterministic `commit_unavailable` conflict when the workspace is missing, clean, or not a Git repository
- repeated requests with the same `Idempotency-Key` and request body return the first response
- reusing the same `Idempotency-Key` with a different body returns `idempotency_conflict`
- each non-replayed commit attempt is persisted in the delivery audit store with policy and result metadata

Plan a pull request for a committed session workspace:

```bash
curl -X POST http://127.0.0.1:8000/sessions/<session_id>/pull-request \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: pr-<unique-retry-key>" \
  -d '{"title":"Implement reviewed changes","body":"Summary and validation notes."}'
```

Expected result in the current local-only runtime:

- JSON output with a `pull_request` object
- `provider=local-only`
- `status=dry_run`
- current `commit_sha`
- base and head branch names
- no network call and no remote PR URL
- deterministic `pull_request_unavailable` conflict when `dry_run=false`
- deterministic `policy_blocked` conflict unless the session was created with `policy_profile=full_access`
- repeated requests with the same `Idempotency-Key` and request body return the first response
- reusing the same `Idempotency-Key` with a different body returns `idempotency_conflict`
- each non-replayed pull-request attempt is persisted in the delivery audit store with policy and result metadata
- pull-request audit metadata normalizes `provider`, `status`, `commit_sha`, `dry_run`, `url`, and failure `reason` when available

Read delivery audit records for one session:

```bash
curl http://127.0.0.1:8000/sessions/<session_id>/delivery-audit
```

Expected result:

- JSON output with `delivery_audit`
- explicit empty list when no delivery attempts were recorded
- action, status, status code, policy profile, idempotency key, result metadata, and timestamp for each record
- pull-request result metadata distinguishes `dry_run`, `created`, `policy_blocked`, and `pull_request_unavailable` outcomes
- token values must not appear in delivery audit result metadata
- read-only behavior with no delivery side effect

Token redaction regression scope:

- PR plans expose only redacted authorization headers.
- API pull-request responses must not include raw token values.
- Delivery audit result metadata must not include raw token values.
- SCM settings snapshots must store token environment variable names only.

GitHub pull-request provider status:

- `LocalOnlyPullRequestGateway` remains the default API behavior.
- The GitHub skeleton can build a dry-run request payload for review without live GitHub access.
- A non-dry-run GitHub request without a token fails before any network call.
- A non-dry-run GitHub request with a token may create a remote PR only when the explicit provider, dry-run, token, and policy gates all pass.
- Transport failures are reported as deterministic `pull_request_unavailable` responses and audit records.
- Serialized request headers redact the token as `Bearer <redacted>`.

SCM provider configuration:

```bash
ZEBRA_SCM_PROVIDER=local-only
ZEBRA_GITHUB_OWNER=
ZEBRA_GITHUB_REPO=
ZEBRA_GITHUB_TOKEN_ENV=
ZEBRA_GITHUB_API_BASE_URL=https://api.github.com
ZEBRA_SCM_PULL_REQUEST_DRY_RUN=true
```

Rules:

- `local-only` is the default provider.
- `github` must be selected explicitly with `ZEBRA_SCM_PROVIDER=github`.
- GitHub config requires `ZEBRA_GITHUB_OWNER`, `ZEBRA_GITHUB_REPO`, and `ZEBRA_GITHUB_TOKEN_ENV`.
- `ZEBRA_GITHUB_TOKEN_ENV` is the name of the environment variable that will hold a token later; the token value itself must not be written to config files.
- `ZEBRA_SCM_PULL_REQUEST_DRY_RUN=true` keeps provider selection non-mutating until remote execution is explicitly implemented.
- SCM credential snapshots store token environment variable names only.
- Any token value handled by the credential boundary serializes as `<redacted>`.
- GitHub PR execution requires all of the following:
- `ZEBRA_SCM_PROVIDER=github`
- `ZEBRA_SCM_PULL_REQUEST_DRY_RUN=false`
- configured `ZEBRA_GITHUB_TOKEN_ENV` with a token available in the process environment
- a session created with `policy_profile=full_access`
- tests and runbook examples should prefer dry-run unless a real repository side effect is intentional.

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
