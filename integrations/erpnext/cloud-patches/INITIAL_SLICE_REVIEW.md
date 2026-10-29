# Initial HTTP input slice: ready for independent code review

Status: initial source passed independent specification and quality reviews. **Not release-ready.** The followup slice is separately described in `FOLLOWUP_SLICE_REVIEW.md`; its current source has not inherited the initial slice’s real PostgreSQL acceptance. No production service activation or model call occurred.

This slice contains17 deployed105-derived overrides. It adds consumed native Host verification evidence, explicit HTTP input proof versus Worker fencing, verified immutable object staging, and input metadata admission inside the existing atomic Task transaction. The migration106 catalog is for a dedicated ERP database only. The old shared PostgreSQL database must stay105.

Initial sequential replay is already handled by the native `ZebraAgentApi.create_session` receipt lookup before attachment parsing, object staging or new UUID generation. The runnable check exercises that exact preflight and proves zero additional object puts. Concurrent losing staging can still leave unreachable immutable objects; these are never deleted on an unknown acknowledgement and remain reconciliation debt. Public response bodies contain native attachment refs only, not the consumed grant proof or bearer.

`artifact_payload_rows` adds small discriminator checks and reuses existing reservation/object/event reconstruction. Worker rows validate the actual existing LeaseFence. HTTP rows require null lease fields and a typed input proof. Worker reserve/finalize/compensate/prune entrypoints reject HTTP authority; the separate administrative retention path can retain its finalized/pruning/pruned lifecycle.

Initial admission rechecks accepted grant ledger/audit evidence, current registry snapshot under SHARE lock, DB expiry and frozen Task binding before committing canonical refs. Upstream JWKS key removal still follows the native300-second resolver cache; there is no invented SQL signature or per-token revocation promise.

Executed locally using the existing native workspace Python:

```sh
/Users/lukeding/Desktop/playground/2026/product/zebra-agent/.venv/bin/python cloud-patches/tests/test_initial_http_input.py
```

Both focused groups passed: four-file metadata/proof/read-lane/one-transaction/zero-put replay; and the real queued Task adapter's exact batch forwarding plus missing-proof/provider-failure rejection before admission. Existing native Core artifact contracts, Host grant contracts, JWT adapter and artifact reader/bounds regressions also passed:47 tests. Python compilation passed.

`tests/overlay_imports.py` selects exact override modules over installed native dependencies. The local dependency workspace is newer than deployed105, so these local results do not substitute for both pinned image builds or native105 end-to-end acceptance.

The root operator ran `tests/test_initial_http_input_postgres.py` in the pinned API review image against a fresh disposable database owned by a nonsuperuser role. All three check groups passed: real migration106, four input rows and strict read record, complete replay and retention states, and rollback of bootstrap/binding/metadata/idempotency on invalid final authority. The script refuses nonempty or non-`zebra_http_input_qa_*` databases; that completed QA database is now nonempty and must not be reused as a fresh test target.

The two Dockerfiles use explicit local base tags. `build_initial_images.py` verifies the captured Docker config image IDs before any mutation, tags exactly those IDs, rechecks each local tag, and builds with `--pull=false --network=none`. A config image ID is not a published manifest digest; `FROM sha256:<config ID>` is invalid packaging and has been removed. Only reviewed role-relevant overrides are copied. Root evidence `native-http-initial.json` records successful corrected initial image builds (API `2c2d95f…c380`, Worker `8073125…93f`), the PostgreSQL checks above, and Worker package import/catalog106 checks. The original shared database remains105. These results cover the initial slice only; they do not prove the current followup source, real S3 behavior, Worker task recovery, model execution, or production activation. Do not activate either image until the atomic followup slice, isolated ERP database transfer, remaining acceptance gates, and independent reviews pass.
