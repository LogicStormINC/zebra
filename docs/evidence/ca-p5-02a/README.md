# CA-P5-02A validation evidence

Final make test/check exited0:11203 passed/3067 conditional skips,1443 typed sources/30Eval.25 focused and6 HTTP export checks passed; full cloud termination-only composition passed. [Exact sources](source-manifest.json), [log hashes/gates](validation.json), [actual HTTP vectors](http-vectors.json). Tests use newly owned disposable PostgreSQL only; no production access.
Actual machine HTTP, missing/committed originals, duplicates, delayed old repeatable-read snapshot,
current revoke/read-only permission, immutable rows, capacity and maximum-size original bytes are tested.
Native gate v1 Task/admission/Worker and historical baseline checks remain intact. One candidate concurrent
gate test returned503; independent diagnostic15 rounds passed with expected CAS/serialization failures,
without broadening its assertion. Final full gate results must independently pass before delivery.
Go handoff pins exact published producer/schema/source bytes and actual synthetic-scope response vectors;
no Go runtime/identity/frontend changes or proof-consumer implementation are part of this slice.
Proof covers original gate command only, not execution/process/fleet stop or production HA.

Initial full Native run had11201 pass/3067 conditional skips plus a catalog expectation still ending115
and one local Worker lease-loss failure. Migration expectation now explicitly checks116 without relaxing
uniqueness/order; isolated old Worker and the8-case migration/Worker file passed with original lease checks.
Go initial unchanged script-publication test timed out during new owned PG bootstrap; exact isolated case
passed11.8s. Only its verified orphan owner791e75ac-7f55-4610-af3f-21250b662c3a container/volume removed.
Final full results replace neither history nor these diagnostic boundaries. No business retries were added.
