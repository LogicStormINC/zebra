# Cloud progress failure-boundary audit and prevention

Task `PROGRESS-RISK-HARDENING-01`; owner Luke Ding, executor Codex.
Branch `codex/progress-risk-hardening-01`, base `879e2dd8`.
Scope: shared Cloud publication, progress recovery, draft and finalization paths;
local activation/integration only. No business-specific Trench implementation.

## Findings fixed together

| Risk | Before | Repair |
| --- | --- | --- |
| Advisory evidence before primary source | MODEL_REQUEST_STARTED first flushes pending display facts; a failed flush prevents the request anchor reaching canonical storage | Persist the request first, then observe/flush within the same cumulative budget; confirmed-source deferral applies |
| Read-only observation poisons execution | Membership reads raise a plain TimeoutError; timer saves it as a global error, aborting the next primary event and cleanup | Mark these exact reads as observation-stage timeouts; optional timer/Effect observation may omit that display attempt, never authorize a write |
| Pending evidence discarded before publication | Evidence refs are popped before membership query/append; an observation timeout loses the pending display batch | Keep refs until publication returns or the exact output is already known; confirmed postcommit gap uses existing identity dedup |
| Recovery setup mislabeled as model failure | Eager pending-commentary repair can raise an untyped TimeoutError before the event callback exists | Preserve the failure with prepare-stage classification and no canonical acknowledgement; do not silently continue |

The first three are reproduced on the previous source by the standalone check:
priority raises WorkerProgressTimeout, membership read raises untyped TimeoutError,
and evidence retention assertion fails. Positive dedup and unknown-primary-write
controls already pass. All six final checks pass, including recovery preparation.

Only four production files change; the existing Makefile gate gains two standalone checks. Existing evidence-publishing code moves into
its existing publication module before editing the495line sink, leaving the sink
below its hard limit. No new framework, queue, timer, schema, pool or dependency.

## Shared-path audit matrix

| Boundary | Required rule / final disposition | Evidence |
| --- | --- | --- |
| Primary event acknowledgement | Only a positively acknowledged source can be treated as committed | Standalone unknown-primary negative control and native lost acknowledgement |
| Advisory publication priority | Optional facts cannot prevent a primary request anchor | New priority check; native source ordering assertion |
| Derived checkpoint failure | Reconcile indexed canonical identities before another append; never resend original event | Prior postcommit check retained; native commentary suite |
| Membership reads | Observation timeout grants no authority and cannot poison background/Effect display | New read/timer check; real bounded PostgreSQL sleep |
| Pending evidence | Failed read retains bounded refs; exact output identity prevents duplicate display append | New retention/dedup checks; native lost advisory acknowledgement |
| Commentary identity/quota | Source digest, chunk order and separate eight-chunk quota remain enforced | Existing model-commentary/progress/native regressions |
| Frozen v2/private output | No Redis failure fallback into durable text; strict/private eligibility stays fresh | Inspected transient sink/gate; unchanged from retained accepted sources |
| Lease, STOP, cancellation | Fresh execution authority remains required; a lost fence cannot publish the next chunk | Existing native expired-fence and cancellation tests |
| Unknown write outcome | Primary unknown append still escapes; no automatic model/tool/canonical write retry | Standalone and native primary-write controls |
| Shutdown/resources | Timer cancellation/join must actually finish; unresponsive owner remains a cleanup error | Existing bounded shutdown/recorder-lock regressions |
| Turn terminal recovery | Existing pending Turn close reconciliation appends only its matching terminal, without model re-entry | Inspected execution_finalization pending-close/reconciliation path; no new behavior claimed |
| Database/performance bounds | Same2s cumulative I/O scopes, bounded native pages and source-first authority | Existing deadline checks, native elapsed bound, retained source/config receipts |

The inspection-only rows are explicitly distinct from newly tested behavior.
The audit is bounded to these shared paths, not a guarantee that every subsystem
or future infrastructure failure has been eliminated. A sustained database outage,
unknown primary COMMIT, revoked authority or live owner that cannot shut down still
stops safely. Suppressing these failures would risk duplicated effects or leakage.

## Validation

Run `uv run python scripts/check_progress_risk_boundaries.py` for six standalone
checks. The prior `scripts/check_progress_postcommit_repair.py` remains green.

- Existing public-output/commentary/Worker progress/composition checks:84passed.
- Existing non-native deadline/shutdown checks:7passed,2skipped,3deselected.
- Existing native commentary/unknown-commit/fence checks:4passed.
- Native fault injection on a disposable PostgreSQL server: `pg_sleep(3)` in an
  observation query is stopped after1826.2ms, pending evidence survives, the next
  primary request precedes its display output, and the timer has no global error.
- In the same native check, a committed advisory output whose acknowledgement is
  lost is indexed on the next source event, yielding exactly two unique outputs
  for two batches. Unknown primary append propagates after one attempt.
- Ruff, mypy1283, file-size3093 and deterministic eval30 pass. No old fixture,
  database account or unrelated source was repaired. No full-suite claim.

The two standalone checks are now part of the default `make check` target.
Direct workspace execution hit the existing private `.artifacts` diagnostic
scripts during Ruff's directory scan (5779 lint findings). No historical script
or lint configuration was repaired. The same complete `make check` passes on a
clean tracked-source export with the exact candidate files and existing runtime:
file-size, whole-source Ruff, mypy, eval and both fault checks all pass.

These checks perform no real model call or business tool action. They use real
canonical/derived storage paths where stated and deterministic in-process fault
injection elsewhere. They establish failure semantics, not a latency/SQL savings
percentage or a page/model availability SLA.

## Local rollout

Build immutable source-only API/Worker overlays from the prior accepted normal
images, retaining earlier v2, resolver, catalog, lock-fairness and task-contract
repairs. Require zero active Host intents before replacement. Verify all retained
and replaced source identities, original six Compose files/environment/commands,
and unchanged search composition. Keep original failed Runs and accepted results;
no manual status reset, model replay, database migration, push or remote deployment.

Final normal API `907fcc00` / Worker `26f1769d` are healthy with zero restarts.
Verified77 retained/replaced source identities and original composition settings;
all overlay hashes match the final source bytes. Prior SQL/performance source
changes remain present. No new SQL reduction or live model/page acceptance claim.

Private red/green, native fault logs, focused regressions, image/source receipts
and local integration receipts are under `.artifacts/progress-risk-20261016/`.
