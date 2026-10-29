# Host-only cleanup budget candidate; no live execution

Baseline source operator SHA256 `14b556b63a0cc627875e7ccaee4323d5d5f8b9a2e2796b486a3bd7a412752ff6`, product baseline at root repository `e048934`; parent reports current `6c854e7` adds evidence docs only. Original source and earlier QA sources remain untouched. `SOURCE_SHA256.json` pins the original files/evidence; `SHA256.json` pins this candidate. No commit, staging, server action, Worker/API image change or product integration was performed.

## Evidence and limit

Attempt `498e894a6960` completed all 17 confined native HTTPS checks, then the first real NativeProof + UDS ensure refused in 6.415s and parent require_clean found its orphan. The root result reports helper-cleanup failure and no passed joint checks. Parent independently verified volume_records0/ext4images0/logbytes0 and all own processes/helpers gone; original sources/state retained. The sanitized Docker events for exact last owned helper `erp-private-proof-6b43f87f-157b-4644-a05e-804a7a0b2214` show create0, start0.149496100s, die5.607572229s, destroy9.405494489s. Die→destroy was 3.797922260s, exceeding the former 1s cleanup budget. Docker die→destroy is a lifecycle interval, not a measured rm RPC duration; the event stream cannot identify whether the delayed final destruction was initiated by the timed-out cleanup or later root cleanup. It is enough to reject the assumption that a stopped helper reliably disappears inside1s. Five seconds covers this observed interval with about1.2s margin, within the existing20s request deadline. It is not a guarantee under all Docker load.

The original helper process exit code/primary launch outcome is unknown because NativeProof's finally cleanup failure replaced it. This candidate fixes the cleanup-budget mismatch; it does not establish that the original proof itself succeeded or remove the requirement for fresh QA. Earlier546f0c0172a8 has insufficient evidence to assert the same cause.

## Smallest shared repair

`Allocator.ensure` calls its injected proof before reading/creating volume state; the real injected implementation is NativeProof configured at main startup. Every ensure/verify request therefore uses this one repair. `NativeProof.require_clean` is an independent startup/orphan guard and is unchanged. Request handler keeps the same absolute ContextVar deadline and20s alarm, including response. No deadline reset or aggregate widening.

Three budget expressions change: reject before launch when available<=5s; launch timeout=min(7,available−5); finally cleanup timeout=min(5,remaining()). The ponytail comment records measured rationale. Unique per-call UUID helper removal, fixed image/network/env/confinement, bounded packets and responses, fresh proof checks and sticky failed_cleanup remain unchanged. Failure/expiration while cleaning still latches review and prevents another helper launch.

Hardening test changes only the obsolete1s assertion, expired-finally fixture2→6 (so it still reaches finally), and one deterministic fake-clock replay block. It covers3.797s cleanup success, short available6/5.5s launch reservation, exact<=5s no-launch boundary, cleanup timeout sticky refusal/no relaunch, exact owned-name removal and the original20s bound. Existing handler tests continue to prove response budget exhaustion and no post-deadline spawn.

Native-related tests inspected: check_private_workspace_native.py exercises native authority/resolver flow, and check_private_preparation_native.py/check_private_message_fixture_native.py cover native preparation/message fixtures; none directly owns this host-only NativeProof timing. No dependency or native image execution is necessary for this timing-only offline test.

## QA-only copies

`qa/check_confined_helper.py` differs from original diagnostic candidate only cleanup timeout1→5; launch remains fixed7s. The two QA drivers differ only in checker hash. Every original assertion, confinement check, strict diagnostic schema and lifecycle remains. `qa/check_diagnostics.py` uses the exact extracted lifecycle to preserve primary and cleanup classifications for launch timeout + successful cleanup, launch timeout + cleanup timeout, and launch OSError + nonzero cleanup. It requires exact7/5 arguments, validates driver diagnostics, and byte-compares wrappers/checker to pinned original diagnostic sources. This is preparation, no native QA execution.

The approved actual root runner `2f9d51444d39a65496e26b227d179cfd2ef2565beb704605b5bc5ef8d1af2c82` is copied to `qa/run_joint_allocator.py` with only OPERATOR_SHA256 updated to the candidate operator digest. The offline diagnostic check byte-compares that exact single substitution; original runner remains unchanged. Parent has separately prepared a safe die-event exit_code observer for the next attempt, outside this candidate. The parent coordinates integration and fresh QA after separate SPEC/QUALITY review.

## Runnable offline check

From workspace: `python3 work/native-cleanup-budget/run_checks.py`. It checks original source provenance, runs the copied hardening suite against the copied operator, reads the unchanged original Worker fixture only, then runs QA diagnostic checks. Docker and privileged filesystem calls are mocked; the existing deadline check also runs one bounded local Python child with a 0.04s timeout. No services are called. All checks passed locally. The copied hardening test can also run directly at its normal cloud-patches location after integration.

No full Agent, commandgateway/runsc, model, browser, artifact, two-principal, physical-volume or end-to-end acceptance is claimed.
