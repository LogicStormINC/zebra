# Real search latency and projection repair fairness

Task `E2E-SEARCH-LATENCY-01`; owner Luke Ding, executor Codex.
Branch `codex/e2e-search-latency-01`, base `e7eec6a7`; local activation/integration only.

## Workload and evidence boundary

Two fresh page searches use Flash/high, exploration capabilities, and v2:
“请联网搜索并核对 PostgreSQL 18、Redis 8 的正式发布日期和各两项主要新特性，
只采用官方来源并附链接，简明回答。” All outcomes are retained. No old Run is replayed.

| Observation | A1 | B1 |
| --- | --- | --- |
| Conversation | conv_1792123707104_a7ddbd | conv_1792125201503_1c62f9 |
| Run | dfde31bc-ca15-4450-a991-6b319cc24866 | 3da34a0e-3a5b-4908-954f-bda3d6c0ed29 |
| Outcome | failed, LockNotAvailable | awaiting_input, task_contract_verification |
| Models / tools executed | 1 / 0 | 6 / 9, zero tool failures |
| Click → first Cloud HTTP | 240202 ms | 755 ms |
| Cloud HTTP → command response | 1884 ms | 1004 ms |
| Command response → Worker entry | 324 ms | 181 ms |
| Worker entry → actual Provider HTTP | 3143 ms | 1172 ms |
| Provider HTTP → first public delta | 1168 ms | 912 ms |
| Delta → Redis first draft | 4.7 ms | 1.9 ms |
| Delta → API first draft tail | 6.2 ms | 3.0 ms |
| Startup explicit SQL / TaskIO connections | 398 / 53 | 398 / 53 |

A1 stayed queued/attempt0 despite an eligible pending Outbox, no database lock,
and zero Cloud requests. An unchanged-source mtime triggered the existing Trench
Uvicorn reload; its new dispatcher then executed that intent for the first time.
This is an operational recovery, not a Cloud speedup or a replay. Historical
process state could not distinguish a stopped dispatcher from a suspended one.

A1 then failed during canonical COMMIT; PostgreSQL logs identify a lock timeout
while updating `task_projection_work`. The derived repair transaction can replay
up to 256 headers while holding that row close to its two-second I/O deadline,
contending with execution commits that must update the same derived queue.

## Minimal repair and native proof

Only `PostgresTaskProjectionWorkStore.repair_projection_work` changes: cap the
header-processing sub-budget at 100 ms, within its existing parent deadline and
200 ms cleanup reserve. Each completed header remains atomic; commit the partial
frontier and continue next tick. This bounds header processing, not an absolute
100 ms wall-time guarantee for connect, lock acquisition or transaction exit.
No source authority, CAS, lease, nonce, STOP, polling, schema or dependency changes.

`scripts/check_projection_repair_fairness.py` is a standalone assert-based native
check, without a new framework/fixture. It creates/drops a unique database on a
configured local disposable PostgreSQL server, injects slow derived headers,
and overlaps an actual Event Store append/COMMIT with repair. Credentials remain
in memory. A fresh dedicated test container avoids the older scratch role's
stale authentication; no existing scratch role or fixture was repaired.

- Original function negative control: canonical writer fails LockNotAvailable
  after 234.45 ms with its 200 ms lock limit.
- Candidate: writer commits in 79.63 ms; the partial prefix is durable, the
  remaining repair converges, source sequence is exact and the new event occurs
  once; derived requested frontier equals the final source frontier (34).
- Existing projection consumer regression: 19 passed, 5 skipped; source Ruff,
  mypy1283, file-size3090 and deterministic eval30 pass. Full suite not claimed.

Smaller repair batches may add maintenance transaction overhead on a backlog.
The canonical per-event path and v2 frame persistence cost are unchanged.
Startup SQL is 398 in both real samples: no additional SQL reduction is claimed.
The two real samples have different terminal outcomes and Host/cold conditions;
their wall-time difference is not a causal latency improvement percentage.

## Page and quality result

B1 negotiated `transient_v2`; all six model receipts retain enabled/high/retry0.
The first visible text at 4623 ms says it will search and is a process update.
The first substantive answer block appears at 33572 ms; dated facts at 34126 ms,
official links at 34710 ms. These remain provisional until final acceptance.
The observer's broad `answer` field also sees process text; the cited substantive
boundary is classified from its captured visible text, not that field alone.

All nine tools execute, but the contract is classified `operate` because the
fallback matches 发布 inside 发布日期. It requires `operation_completed` and
`result_verified`; after extra verification rounds the Run suspends with
`task_contract_verification`. This is not successful full generation acceptance.
A separate focused contract correction will preserve the lock fix and use one
fresh confirmation Run; B1 is retained and not resumed.

Safe traces, native red/green, page timing and screenshots are private under
`.artifacts/e2e-search-latency-20261016/`. Temporary trace launchers remain active
for the immediate acceptance follow-up and must be replaced with the prepared
normal images afterwards, preserving the original six Compose files and gains.
