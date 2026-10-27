# CA-P2-01B validation evidence

- Base: e56f827295cd8e704afe2c8ea071e88e7b599ee4.
- Branch: codex/ca-p2-01b-bundle-assembly.
- Worktree: /Users/lukeding/.codex/worktrees/ca-p2-01b-bundle-assembly/zebra-agent.
- Original cloud-agent checkout and earlier pinned worktrees preserved.
- Independent design/plan, core spec/quality and final integration spec/quality reviews approved; no outstanding findings.
- Review fixes: preserve creation-time retry idempotency; defer incompatible v2 Coverage/setup checks until durable-close healing; defer Workspace effects until compatibility; use frozen optional title model; refuse unversioned local Skills/MCP despite a matching path-only baseline.
- Baseline:162passed/1legacy PostgreSQL skip. New storage tests use owned disposable postgres17 containers, including v109→110 historical preservation, sidecar atomic rollback/corruption/conflict/concurrent retry.
- Actual Worker uses local SQLite and httpx MockTransport provider; verifies persisted/recovered v2 content and outgoing model/limits/temperature/instructions, current profile/default changes, concurrent isolation, retryable mismatch/missing credential, strict Coverage refusal with/without strict composition, pending-close ordering and optional title recovery. These are not authenticated production provider/gVisor acceptance.
- Final focused command: `uv run pytest -q tests/test_bundle_assembly.py tests/api/test_bundle_materialization.py tests/worker/test_bundle_execution.py tests/worker/test_bundle_title_recovery.py tests/agent_integrations/test_bundle_model.py tests/agent_core/test_bundle_definition.py tests/agent_storage/test_bundle_definition_postgres.py`:65passed/zero skip in17.20s, including11actual disposable PostgreSQL tests.
- Final make check: exit0, Runtime product boundary pass, source size3300checked/zero violations, Ruff pass, mypy1353sources pass, eval30/30 and progress/risk/unknown-commit checks pass.
- [Frozen modified Python source/test hashes](python-source-sha256.json) cover41files; all remain unchanged during the full gate. Published P2A artifact tree and v1 domain/golden source diff against base is empty.
- First full make test:3failed/10682passed/3007skipped in1080.19s. All3shared an old SimpleNamespace entry-task substitute missing the existing nullable definition_snapshot field. Added explicit None in that substitute; all cancellation/progress assertions preserved, focused9pass. Production source unchanged. Independent quality review approved the fixture correction (affected-file4passed); final r2 full rerun passed.
- No production migration, deployment, online Bundle management, native scripts or main/cloud-agent integration.

## Final result

- `make test`: exit0,10685passed/3007skipped in1043.90s (17:23), zero failures.
- `make check`: exit0; boundary/size/Ruff/mypy1353sources/eval30/30/progress-risk gates pass.
- All41frozen Python source/test files unchanged during r2; the only change after the first full run was the legacy test-substitute field correction.
- [Structured receipt](validation.json), [test summary](make-test-summary.txt), [check output](make-check.log).
- Skipped external/opt-in suites do not constitute live PostgreSQL/S3/Redis/provider/gVisor acceptance. The11new disposable PostgreSQL tests actually ran; existing business/production databases were untouched.
- Original cloud-agent HEAD703c3c03 and its dirty files retained; P1pin6dbb2a8d/P2Apine56f8272 worktrees remain clean. Scoped branch delivery only; no merge/deployment/production migration.
