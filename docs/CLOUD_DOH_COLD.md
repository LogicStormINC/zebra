# Fully cold DNS batch: measured startup and network waiting

CLOUD-DOH-COLD-01, basea1affb0a, branch `codex/cloud-doh-cold-01`.
Generic runtime only; no model calls, Trench product edits, service restart,
authorization/DNS cache, retry, resolver change or artificial free prewarming.

## Investigation

An isolated source overlay in the existing worker network/CA environment executes
the actual scoped native dispatcher. A private child profiler records monotonic
parent Popen/child-entry, standard-library/runtime imports, operation entry, fresh
DNS entry, CA-context creation, TCP, verified TLS, response headers and body.
No tool arguments, tokens or response text are recorded. Nested timings are
identified as nested, not added twice. Both concurrent lanes retain their own
trace; the batch critical path is the slowest lane, not the sum of both lanes.
The profiler moves standard-library imports into its initial phase, so the exact
split between stdlib/runtime imports is observer-specific; combined phase cost
and the identical-observer A/B boundary are the useful comparisons.

Initial four fully cold batches/eight children:

| Per-child phase | Observed range |
| --- | ---: |
| Popen call |0.2–2.9ms|
| Parent start to first child Python statement |9.4–21.0ms|
| Profile launcher stdlib imports |107.7–123.4ms|
| Remaining runtime imports |209.9–309.7ms|
| First SSRF import before public DNS entry |147.5–197.0ms|
| CA context |15.9–24.0ms|
| TCP connect, including literal-IP lookup |0.9–2.6ms|
| DoH TLS handshake |322.8–1320.7ms|
| DoH response headers |84.3–420.6ms|
| DoH body read |less than1ms|

The OS process launcher is not the dominant fixed cost. The interpreters import
Pydantic/tool contracts, then the `resolve` operation imports `agent_security.ssrf`.
That submodule first executes the entire security package initializer, which
imports unrelated policy, JWT and grant components. Its cost is measurable and
avoidable. TLS and server-header waits account for the large variable spikes;
this experiment cannot split TLS wall time further into packet loss, network RTT,
proxy scheduling or remote handshake CPU without additional transport evidence.

## Minimal repair

Change only `packages/agent-security/src/agent_security/__init__.py` in production:
reuse the existing `agent_tools` per-name lazy export pattern. Named public aliases
load their original module/object on first access. Direct SSRF submodule imports
no longer initialize unrelated policy/JWT modules. Existing explicit type-only
aliases retain static exports; `__dir__` includes named aliases. The historical
final13-name `__all__` is preserved exactly, including the existing distinction
between star imports and the larger named public API. This task does not fix or
reinterpret that historical contract.

All original exported aliases are frozen in a compatibility test and compared
against their original source objects. A fresh-interpreter regression verifies
that importing and executing `resolve_and_validate` does not import policy, grant
or JWT components. It failed before the repair and passes afterward.

No policy, JWT verification, SSRF implementation, resolved-address validation,
network transport, cancellation loop or authority callback is changed. The
repaired initializer remains270lines, below the target300line limit.

## Fixed actual no-model A/B

Four pairs in AB, BA, AB, BA order. A/B differ only in the security initializer;
identical observers, source, network, CA and two cold children otherwise. Each
sample resolves PostgreSQL and Redis concurrently with a fresh scope. All16
resolutions succeed; no model, accepted Task or SQL workload is involved.
All adverse samples are retained; no favorable extra acceptance sample is added.

| Pair | A cold batch(ms) | B cold batch(ms) |
| --- | ---: | ---: |
|1|859.7|1882.9|
|2|3691.1|1940.4|
|3|872.6|2329.9|
|4|875.8|787.1|
|Median|874.2|1911.7|

First SSRF initialization before DNS: A median133.324ms → B1.744ms, a reduction
of131.580ms (98.7%). All eight candidate child traces remove the fixed cost.
But only two of four whole batches improve. Overall batch latency is not proven
better: the candidate median is worse, and must be reported as such.

Network explains the apparent reversal: A2 TLS reaches2767.9ms; B1 TLS1453.3ms
and another lane's headers588.9ms; B3 TLS1868.9ms. Other A batches have roughly
263–293ms TLS. These independent network waits exceed the removed131.6ms. They
are not evidence that lazy exports remove or cause TLS packet latency.

## Check against the actual website-fetch path

A separate bounded diagnostic pair performs the two real official-page fetches,
with all four outcomes retained. This is path diagnosis, not a second acceptance
cohort or a causal performance claim.

- `web.fetch` does not import the security aggregate in its child before DNS. It
  uses the existing connection-time public resolver/pinning guard. Consequently,
  this initializer repair does not provide the same131.6ms benefit on the current
  legacy HTTP fetch path.
- A fetch batch1928.1ms, B1819.7ms: one pair and different network timings do not
  establish an optimization gain.
- A DoH TLS279/283ms, headers97/100ms; target PostgreSQL TLS676ms/headers288ms,
  Redis TLS386ms/headers179ms.
- B DoH TLS273/268ms, headers88/81ms; target PostgreSQL TLS661ms/headers257ms,
  Redis TLS319ms/headers127ms.
- Thus actual fetch latency contains two independently established TLS connections
  plus upstream response waits. Current transient_v2 is distinct from web pipeline
  v2; this task does not enable the latter or force a different tool path.

## Validation and delivery boundary

-370tests pass: complete agent-security package, Cloud composition, scoped DoH and
  original native cancellation paths. Separate SSRF/network-profile46tests pass.
- Mypy1289source files, repository-source Ruff, file-size gate, eval30/30 and
  existing progress/risk guards pass. Private captured source snapshots are
  diagnostic artifacts, not new production source lint targets.
- Named aliases/type-only imports are preserved; only type-only grouping was
  reformatted after the network cohort, without runtime behavior changes.
- No fresh-authority bypass, DNS-answer cache, additional upstream query per
  request, lower thinking, stream-v2 change, Trench change or automatic retry.
- No whole-page/SQL improvement claim; stable whole-cold gain remains unproven.
  The page/model gate remains open, so no real-page model cohort is run.
- Local source integration may reuse the authorized `cloud-agent-trench` boundary;
  preserve all unrelated dirty paths, especially existing policy and Teredo repairs.
  Running services remain unchanged; a source commit is not live activation.

## Evidence and commands

Private `.artifacts/cloud-doh-cold/`: initial `diagnostic.json`, all A1…B4 raw
traces/logs, `pairs-summary.json`, actual `fetch-A/B.json` diagnostics and test logs.

```sh
python -m pytest -q tests/agent_security/test_lazy_exports.py
DOH_COLD_TRACE=/tmp/doh-profile python scripts/check_cloud_doh_cold.py
```

The network runner requires the worker's DNS/CA environment. It deliberately
instruments only private child processes and must not become a normal Worker
entrypoint. OS launch/import/DoH/server-header intervals are separately observable;
further network-routing explanations require new evidence, not another test repair.
