# Zebra Development Version: Runtime Model Catalog Selection

## Identity and ancestry

- Repository: `/Users/vinson/Projects/github/hellolukeding/zebra`
- Owner / task: `Vinson` / `ZEBRA-MODEL-CATALOG-01`
- Source thread: `019f9d5b-6811-78f3-a774-cd03bd38dfa4`
- Base branch: `codex/agent-definition-completion-contract-20260802`
- Exact base commit: `8580bb7f2861b242f76ac044d0939ddd230f77d4`
- Development branch: `codex/runtime-model-catalog-selection-20260802`
- Worktree: `/Users/vinson/.codex/worktrees/zebra-runtime-model-catalog-selection-20260802`
- Fixed deployment / merge target: fork `vinson1101/zebra` branch
  `codex/finos-runtime-alignment`; this candidate does not update that line
- Model request: Luna Max
- Deployment state: local candidate only; no push, merge, or deploy permitted

## Contract slice

- Add an explicit JSON model catalog configuration with a backward-compatible
  single-model fallback from the existing `ModelSettings`.
- Expose only `schema`, safe model `id`/`label`/`available`, and `default_id`
  from `GET /capabilities/models`.
- Accept optional `model` on new session/task creation, reject unknown or
  unavailable entries, and persist the selected catalog id in the existing
  `TASK_PREPARED` event.
- Build API and worker gateways from the selected `ModelSettings`; recovery,
  handoff, and restart reuse the persisted id.
- Native image capability remains explicit profile data resolved by
  `resolve_model_profile`; model names do not grant capabilities.

## Owned paths

- `apps/config/src/zebra_agent_config/__init__.py`
- `apps/config/src/zebra_agent_config/model_catalog.py`
- `apps/config/src/zebra_agent_config/settings.py`
- `apps/api/src/zebra_agent_api/api_status_mixin.py`
- `apps/api/src/zebra_agent_api/app.py`
- `apps/api/src/zebra_agent_api/routes.py`
- `apps/api/src/zebra_agent_api/session_payloads.py`
- `apps/worker/src/zebra_agent_worker/execution.py`
- `apps/worker/src/zebra_agent_worker/task_recovery.py`
- `packages/agent-core/src/agent_core/application/session_bootstrap.py`
- `packages/agent-core/src/agent_core/contracts/events.py`
- `packages/agent-core/src/agent_core/harness/loop.py`
- `packages/agent-core/src/agent_core/harness/models.py`
- `packages/agent-runtime/src/agent_runtime/harness.py`
- `configs/default.env` (example catalog comment only)
- `tests/agent_core/test_session_bootstrap.py`
- `tests/api/test_api_model_catalog.py`
- `tests/config/test_model_catalog.py`
- `tests/worker/test_model_selection.py`
- this development record

## Non-goals

- No FinOS changes, provider/router registry, database table, MCP contract,
  model-name capability inference, secret exposure, or deployment change.
- MiniMax child environment declarations, including `MINIMAX_API_KEY` and
  `MINIMAX_API_HOST`, remain unchanged.
- Existing continuation message payloads do not accept a new model selector;
  selection applies only at new Task/session creation.

## Validation log

### Red-first

- `make sync`: passed with CPython 3.12.13.
- The first focused run collected 14 tests and produced `12 failed, 2 passed`.
  Failures were the expected contract gaps: no catalog setting, no catalog
  endpoint, `model` rejected by create-session, no TaskPrepared selection, and
  no worker recovery selection.

### Green and inherited baseline

- Focused catalog/API/bootstrap/recovery set: `15 passed`.
- Related config, API, HTTP, agent-core, worker, runtime, and integration set:
  `165 passed, 3 failed`; the three failures are inherited health, OpenAI
  response, and durable cancellation cases.
- Exact-base full run: `1983 passed, 12 failed, 9 skipped`. Two host-process
  timeout tests failed transiently with `PermissionError` during process-tree
  cleanup; rerunning those two exact tests passed. The stable inherited set is
  the same 10 failures seen on this candidate.
- Final candidate full run: `1998 passed, 10 failed, 9 skipped` across 2017
  collected tests. The 10 failures are exactly the stable inherited provider
  (2), health (1), pull-request credential/transport (5), file-size (1), and
  cancellation (1) cases; no catalog-selection test failed.
- Owned Ruff: passed. Python 3.12 compileall: passed. `git diff --check`:
  passed. `apps/api/src/zebra_agent_api/session_payloads.py` remains at the
  500-line repository limit; new catalog/test files remain below their limits.

## Unverified items

- No live provider request or staging deployment is part of this candidate.
- Full-suite inherited failures are environment/provider/HTTP/credential,
  file-size, and cancellation concerns outside this slice; no production fix
  for them is included here.
