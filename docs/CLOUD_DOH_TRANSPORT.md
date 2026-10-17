# Cloud execution-scoped DoH transport reuse

CLOUD-DOH-TRANSPORT-01; generic Cloud Worker/runtime only. No Trench logic,
model setting, stream protocol, authorization-policy or website transport change.

## Implementation

Cloud `build_worker_tool_gateway` explicitly enables DoH reuse on its existing
`LocalToolGateway`. The default local/CLI path remains single-request children.
Without a live cancellation callback, reuse is not enabled. Non-POSIX and browser
operations retain the previous path.

A gateway owns at most two exclusively leased native subprocesses. They accept
bounded newline-framed requests and run the original operation handler. Additional
calls wait within the original deadline, checking live execution authority at most
50ms apart; successful authorization is never cached. The same callback runs before
admission, during network waits and before publication. Revocation remains sticky.

Only the existing literal1.1.1.1 DoH transport persists inside a child, with TLS
verification and no environment proxy or redirect. `public_addresses` still runs
native DNS and the existing fallback/parser/public-IP validation for every request.
No DNS answers, task authority, cookies, target sockets or HTTP response bodies are
cached. The downstream HTTPS adapter continues pinning the freshly admitted IP.

Idle children and DoH sockets expire lazily at15seconds before reuse. Gateway close
terminates/reaps all children. Cancellation, protocol/operation failures and output
bounds retire the affected child without request replay. The shared original
kill-group/pipe-close/reap routine is retained. Output is bounded per caller and
request framing is capped at64KiB. Browser subprocess cleanup remains unchanged.

This requires retaining native children: pooling a connection only inside the
previous one-request child would provide no reuse. It is execution-scoped, not a
new egress service or cross-task connection fleet. Therefore an entirely new
execution still pays resolver/child cold-start costs.

## No-model validation

- Focused runtime, original native cancellation, DNS/SSRF, search TLS, native HTTP,
  Cloud composition and client gateway tests:98passed.
- Covers fresh resolver calls on a reused DoH socket, rejection of a newly private
  answer, malformed question, original default opener, request output bounds,
  idle-child retirement, no replay after child failure, deadline, authorization
  revocation, canceled request with sibling survival/recovery, actual TLS read
  cancellation/peer EOF and child reap, explicit gateway opt-in/close, and busy
  lanes keeping their original deadline and live checks.
- File-size gate passes; Ruff passes; Mypy1289source files passes; deterministic
  eval30/30; existing postcommit/risk-boundary checks pass. No full-suite claim.
- Tests use the candidate runtime source through explicit PYTHONPATH, not the
  primary checkout's editable package accidentally. Existing primary Teredo DNS
  recovery remains an independent dirty patch and must survive local integration.

## Actual native dispatcher measurements

Executed in the existing worker network/CA environment with an isolated source
overlay, leaving its normal entrypoint/process unchanged. No model, accepted Task,
SQL benchmark or Trench request. A uses the original one-request child dispatcher;
B uses the Cloud scope and actual DoH transport. Both use live check callbacks.

Fixed four pairs ordered AB, BA, AB, BA. Each sample starts with two concurrent
cold hostname resolutions (PostgreSQL/Redis), followed by two concurrent distinct
host resolutions (Python/SQLite). No target website is downloaded in this probe.
All32resolutions succeed; results are original `resolve` operation receipts.

| Pair | Cold A(ms) | Cold B(ms) | Different hosts A(ms) | Different hosts B(ms) |
| --- | ---: | ---: | ---: | ---: |
|1|3326.132|3473.180|1255.414|2099.530|
|2|2034.527|2014.918|1022.324|397.225|
|3|1190.485|2300.930|1918.335|114.207|
|4|987.317|1929.369|1928.933|133.925|
|Median|1612.506|2157.924|1586.875|265.575|

Warm different-host batch median decreases83.3%, but only3of4pairs improve; the
adverse first pair is retained. Entirely cold median increases33.8%; no cold gain,
non-regression guarantee or stable first-body improvement is established. These
numbers include retained-process startup savings and network variation, so they
must not be attributed exclusively to DoH keep-alive.

An earlier fixed cohort preceded the final concurrency-queue addition and is
retained as `results-before-queue.json`. The complete final cohort above was run
again after that change, with no further runtime edits. Do not select the earlier
more favorable cohort instead. The prior isolated transport experiment separately
measured fresh DoH resolution453→98ms without changing DNS query counts.

Raw private evidence: `.artifacts/cloud-doh-transport/results.json` and
`native-cohort.log`, plus retained prior cohort and regression logs.

## Delivery boundary

Source is prepared for staged local integration into `cloud-agent-trench`, preserving
all unrelated dirty files and the existing Teredo repair. The runtime change needs
an updated worker image to become active; a source commit is not live activation.

No real-page model cohort is triggered by these results: the matching cold/overall
stability gate remains open. High thinking and transient_v2 remain configured by
the existing composition. Any subsequent local activation must retain the original
service environment, entrypoint, commands, API/Search images and current DNS repair.

Local source integration completed as `d1b366da` on `cloud-agent-trench`. All
previous tracked dirty bytes outside the owned DNS file were verified unchanged;
its original `public_addresses` AST (including Teredo recovery) was preserved.
Primary-checkout combined DNS/cancellation regression:85passed. This includes
the pre-existing dirty DNS tests; it is distinct from the98-test clean slice.
Running Worker/API/Search images and configuration have not been switched.
Temporary network overlay removed; no further model/page sample was run.
