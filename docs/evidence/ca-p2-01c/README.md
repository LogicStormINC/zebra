# CA-P2-01C validation evidence

- Base:92f494cb9a9da596e5c7418e7d7a57b6deaf82e7; branch codex/ca-p2-01c-bundle-validation.
- Independent managed worktree; original cloud-agent dirty files and P1/P2A/P2B
  worktrees retained. No main/cloud-agent integration by this task.
- Dependency audit: offline native P2A and actual assembly P2B lack a dedicated
  pure control-plane validator. Added this scoped C prerequisite before separate
  Go OD-P2-01A/paired OD-P2-01B, not a jump to script runner or deployment.
- Written design/plan, implementation spec and independent quality review approved;
  no unresolved findings. Reviewer independently ran20new tests including actual
  subprocess HTTP and retained-capacity/rotation checks.
- make sync exit0; old targeted baseline20passed in7.20s.
- [Focused final summary](focused-summary.txt):58passed/zero skip in18.58s, covering
  new endpoints/config/artifacts/process plus old target/assembly/materialization
  and Worker execution/title recovery. New acceptance modules contain20tests.
- Meaningful red→green: absentconfig/routes, insecurecatalogpermissions,
  declared Content-Length mismatch, extension-method fixederror bypass and mutable
  shared nested contract output; all now protected by runnable regressions.
- Actual independent loopback uvicorn subprocess verifies contract pin, raw input,
  scoped receipt/assembly/public approval digest, seven negative vectors, old
  credential refusal, action changes, Token rotation, unchanged native table counts
  and unchanged catalog/input. This is local HTTP evidence, not production HA,
  authenticated external provider, Worker/DB readiness or publication acceptance.
- Body8slots cover both routes; slow body, thread timeout/cancel retain actual work
  slots until completion; late errors consumed. Concurrent requests stay isolated.
  Final full approval comparison detects issuer/target/expiry/action changes even
  without changed Token/revision/headers. Private files reject FIFO/device/unsafe
  modes; catalog relative paths remain accepted.
- Baseline old golden is exactly
  sha256:c7748ed8d32a5c534d4c7c8290fd71f5d5d3c01d46c3d38c53665a5cce900fdc
  with test settings and key ab*32; new management setting unset/configured both
  preserve it, while changed old settings still change the digest.
- Published [producer hashes](producer-sha256.json) pin static document/OpenAPI and
  portable vectors. Existing runtime-bundle-v1 tree and historical core v1/v2
  sources have no diff against B; no historical data/Coverage proof rewrite.
- [Frozen Python hashes](python-source-sha256.json) cover11modified/new source/test
  files; source must remain unchanged throughout full gates.
- make check exit0: boundary,3308file-size checks/zero violations, Ruff,
  mypy1357sources, eval30/30 and postcommit/unknown-write/risk boundaries pass.
  [Full output](make-check.log).
- Full make test exit0:10705passed/3007skipped/zero failures in1059.97s
  (17:39). [Summary](make-test-summary.txt), [structured receipt](validation.json).
- All11frozen Python files and published producer artifacts remained unchanged
  throughout both full gates. No core or original Bundle v1 artifact changes.
- Existing skipped opt-in/external suites do not prove live service/production
  acceptance. This task has no new PostgreSQL migration or storage write path.
- Original cloud-agent working tree retained its dirty file list; concurrent
  operator documentation advanced its HEAD to8ee49ec1 independently. This task
  neither resets nor integrates that work. P1/P2A/P2B pins remain clean at
  6dbb2a8d/e56f8272/92f494cb respectively.
- This task performs no deployment, production migration, model/tool/script call,
  production data mutation or branch integration. The private-file authorization
  limitation across replicas and validation snapshot/publication boundary remain
  explicit in docs/BUNDLE_MANAGEMENT.md.
