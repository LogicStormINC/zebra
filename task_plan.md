# CA-HA-03 / 03A — Cloud polling and resource-boundary audit

Owner Luke Ding / executor Codex; branch codex/ca-ha-03-budgets; base56ae352a5.

1. Trace both Worker compositions, storage pools and independent control lanes.
2. Claim exact paths and reproduce no-progress polling before code.
3. Reuse bounded lanes; introduce bounded jittered scheduling delay only.
4. Verify both real run paths, cancellation and existing admission/fairness behavior.
5. Record per-process vs aggregate limits, remaining03B requirements and evidence.

No production deployment/migration, model calls, old-environment restart or unknown operation replay.

03A steps1–5 completed: Worker1326/759skip, PG33, make check pass. Candidate Review; no production rollout.

Next: claim03B exact files from docs/CA-HA-03_resource_budgets.md; freeze fleet connection inventory and reserve-control design before implementation. Do not unlock04 or label03Done.
