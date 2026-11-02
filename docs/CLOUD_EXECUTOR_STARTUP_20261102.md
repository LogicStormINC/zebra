# Known pre-model executor failures (2026-11-02)

Production ERP Session `8d6fcfb6-9e71-4302-9c8d-c9c68f87de7c` suspended as
`executor_process_interrupted` without starting a model or tool. The Worker
container remained alive, without restart/OOM. The child actually failed during
execution-input resolution: an unsigned allocator refusal was mislabeled as a
receipt-authentication failure, then its known failure category was lost over
private process IPC. The allocator had discarded the historical inner cause;
this repair does not claim to reconstruct that exact triggering exception.

## Generic Worker repair

Reuse the existing input-resolution exception boundary, process result files,
lease fence and completion recovery. Introduce only the typed
`WorkerInputPreparationUnavailable` failure and its bounded private receipt:

- Atomic failure file, max2048 bytes, version/type/session and exact fence only;
  no user input, raw error, token, authority or provider data.
- Only a successful child exit with valid known failure proof crosses this
  boundary. Invalid/extra/oversized/symlink/wrong-session/wrong-fence/conflicting
  success proof remains an uncertain interruption. Missing proof stays unknown.
- Python boolean/integer equality cannot weaken fence comparison.
- Known setup failure suspends as `execution_input_unavailable`, retryable=false;
  no model dispatch or automatic ready-queue replay.
- Existing confirmed-completion recovery handles this category too, retaining
  the original authoritative answer. Existing process ownership, kill, lease,
  cancellation and late-error behavior remains unchanged.

No ERP module or filesystem operator is imported into the generic runtime.
Consumer repair is in canonical ERP commit
`878ed20` (`codex/erp-allocator-refusal-20261102`); it signs authenticated refusals,
adds sanitized diagnostics, retains the original20s/5s cleanup budget and repairs
same-filesystem bind detection. That mount bug became visible during the first
operator restart and temporarily caused a restart loop; it was stopped and68
empty duplicate layers removed, preserving all eight physical filesystems.

## Evidence and boundary

- Local focused Worker/completion suite:40 passed,2 conditional skips; targeted
  Ruff and mypy passed. No full-suite claim.
- Frozen production117 overlay (six Worker files and consumer client only),
  isolated Linux with real disposable PostgreSQL:44 passed. Original OS signal,
  force-stop/no-other-session-kill and completion invariants included.
- Production Worker/cleanup overlay deployed; operator listener and actual Worker
  UDS refusal verified; all eight mounted filesystem identities/capacities match.
  Service stayed on the same recovered PID without additional restarts.
- Original Run unchanged, model count188, session count52, migration117 checksum
  ledger unchanged. API/Scheduler/ERP/Search/MCP unchanged; no model/search calls.
- Signed original verify-only request now rejects expired authority in4.035s,
  confirmed by safe `HostGrantExpiredError` diagnostics. No original-grant renewal
  or task retry was performed. This is refusal/authority and no-model recovery
  proof, not a successful fresh production model Run or production HA/SLO claim.

Private release and rollback evidence:
`/home/ubuntu/releases/20261102-executor-interrupted/` on192.168.101.7.
Existing earlier tests that missed a static contract file were rerun only after
restoring its exact frozen source; the original failed logs remain available.

Consumer parity is also carried in `integrations/erpnext/` using its existing split
modules, retaining frozen compatibility originals. Three standalone no-model
checks and targeted Ruff passed for the port. This is a focused semantic port
of canonical878ed20, not a whole-tree source replacement. The latest size gate
passed4107 files with zero violations. Owned temporary QA containers/network and
runner image were reclaimed; immutable production/rollback images and original
workspace data remain. Final live receipt confirms the same allocator PID,
zero restarts since recovery and restored admission.

Local cloud-agent merge289a2ce2 retained the concurrent cancellation/shutdown
repair without code conflicts; both task records and progress entries preserved.
Post-merge no-model Worker/completion/shutdown/subagent regression:53 passed,
2 conditional skips. `UV_NO_SYNC=1 make check` passed (4113 size checks, Ruff,
1530 mypy source files, deterministic30 evals and both progress-safety checks).
One Python3.12 union-type Ruff correction was made only in the consumer port.
No GitHub publication was performed in this repair.
