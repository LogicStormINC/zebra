# CLOUD-STREAM-CLIENT-01 implementation and evidence

Date: 2026-10-13. Branch: `codex/cloud-stream-client-01`; base: `ffe8f38b`.
Human owner: Luke Ding. Status: independent SPEC and QUALITY GO; accepted bounded
component for staged local integration. No push or deployment.

## Delivered boundary

Session, Task and AG-UI HTTP adapters compose an instance-owned v2 multiplexer
when the accepted Run envelope freezes mode 2. Missing accepted metadata retains
legacy behavior. A configured reader also permits a genuinely unstarted raw
Task/Session: bounded complete source with no accepted command proves no
admission. Indexed Run/source uncertainty remains an error, never legacy fallback.
Operator admission defaults OFF. New admission enabled without
a shared cursor key or Redis URL fails factory composition. Previously accepted
v2 Runs require the compatible reader even when new admission is disabled;
removing its configuration returns explicit 503 rather than silently changing
recovery semantics. Configured Redis failure retains bounded canonical recovery.

The signed cursor uses a distinct HMAC domain and endpoint-specific scope digest.
It separates original durable coordinates, generation, Redis position and wire
chunk ordinals. Session preserves Session sequence/event IDs; Task preserves Task
sequence. Canonical history retains existing signed access and privacy checks,
including prior committed messages and effect receipts. Exact current Run and
active Segment singleton qualification applies to temporary output, not a new
history truncation rule. Cursor fields and Redis descriptors are never authority.

Worker publishes its trusted source request coordinate and full fence atomically
with generation activation. Discovery returns a bounded locator and revision;
a separate body-free control stream signals generation/closure changes. Fresh
canonical qualification checks accepted mode, namespace, Host/Task/Run/Segment,
Turn, call, Attempt, ordinary purpose, complete fence, lease, source window,
coverage and superseding or completed facts. Request-local qualification expires
within 30 seconds and fresh Grant/lease deadlines; canonical/checkpoint hints
force renewal before further draft delivery. Qualification does not query SQL
for each frame. Read TTLs are not renewed. Descriptor/revision is repeated after
proof before reading temporary bodies.

All startup Redis metadata operations share a 250 ms budget. XINFO captures
canonical, checkpoint, control and initial live coordinates before replay;
metadata capture grants no temporary body-read authority. Canonical catch-up
precedes fresh qualification and retained-prefix draft delivery. Redis blackholes
cannot consume the complete request Grant. API short Redis socket reads use
250 ms ceilings; Worker defaults remain unchanged. Long notification waits use
installed `redis.asyncio`, not blocking default-executor XREAD calls.

## Wire and product behavior

Durable AG-UI projection, state, frame counts, version and checkpoint keys remain
unchanged. Only transport output is transformed. A complete canonical response
replaces the stable `message:model_call_id` draft, including no-text tool-call
placeholder reset. Late provisional fragments cannot append after that response.
Commits without a model call use their canonical event ID (decoded source cursor
for AG-UI), preserving multiple historical answers across cold refresh.
Only ANSWER_COMMITTED clears the localized Draft badge; text end or Run closure
does not commit an answer. Private/coverage/public_expression candidate bodies
never enter the temporary display path. Existing canonical privacy flow and rich
content/Artifact facts retain their established semantics.

Final signed SSE records are bounded to 16 KiB, including cursor and headers.
Deterministic replacement/canonical chunks reserve the 4096-character cursor
ceiling and acknowledge individual wire ordinals only after awaited callbacks.
Large assessments, tool bodies and raw Unicode facts retain full canonical data
through bounded chunks. Existing canonical source page and checkpoint frame
limits still apply; this slice does not promise that arbitrarily large AG-UI
frames rejected by the existing checkpoint producer become admissible.

SDK observations are optional awaited typed callbacks in the existing SSE path.
The small conversation reducer supplies controlled Host React props. Cursor
validation uses a separate 4096-character ceiling; effect IDs retain 256.
A cold v2 load explicitly requests full durable recovery, clears temporary state,
reduces historical effect adds/removes without dispatch, then uses existing CURRENT
pending-effect bootstrap at the explicit catch-up boundary. Live/reconnect effect
handling retains existing receipt, in-flight and executed deduplication. Retry
state advances after each successfully observed record; failed callbacks do not
accept their cursor, and cancelled/error readers release the response socket.
Terminal authorization or nonrecoverable cold 400 rejection first awaits a reset
observation, preserving canonical messages while removing temporary previews.

SDK incoming records are bounded to 16 KiB for v2 and 8 MiB for legacy canonical
compatibility. A single large network enqueue containing many valid small records
is drained before checking the unfinished-record bound. Assembly remains bounded;
normalized Unicode canonical JSON avoids unnecessary ASCII-escape expansion.
Conversation content is bounded to 500 messages/8 MiB with bounded partial staging.

## Validation

Configured targeted regression covers actual owned PostgreSQL/Redis, trusted
Worker model callback sources, actual checkpoint queue/consumer, three signed
RS256 HTTP routes and PostgreSQL JTI consumption. Native cases cover full retained
prefix, lost closure ACK, canonical completion, namespace/fence/Turn/Run/privacy
changes, expired Grant, wrong endpoint cursor, exact partial live resume, missing
reader configuration and an owned loopback Redis blackhole. No paid model or
business operation was invoked. Credentials and private fixture environments are
not publication artifacts.

- Configured focused cohort before final outage additions: 187 passed, no skips.
- Native/wire cohort after three-route outage and no-call identity additions:
  27 passed in 57.34 seconds; final strengthened outage-body assertion refreshed
  in the configured cohort below.
- SDK build/type check passed; full clean-base SDK tests before QUALITY correction: 64 passed, no skips.
- Real Chromium over disposable synthetic Node SSE: Draft badge, stable response
  replacement, commit, cold refresh, partial resume and one tool receipt passed;
  three connections, zero browser errors.
- `make check`: file-size gate, Ruff, mypy and deterministic 30-case eval passed.
- Final configured cohort: 191 passed, no skips, 173.15 seconds.
  After the final no-Run legacy guard change, signed native HTTP plus both
  configured-reader no-Run probes passed 5/5 in 15.71 seconds; legacy regression
  30 legacy/API compatibility checks passed in 9.98 seconds; static gates were
  refreshed after the final source change.

The Chromium fixture uses synthetic wire and unsigned placeholder cursor IDs.
It proves actual SDK parser/reducer/controlled React behavior, not the combined
native Worker → consumer → signed HTTP → browser chain. Native signed HTTP is
separate evidence. One-reader 100-frame checks are not 100-subscriber capacity
proof. This branch starts from clean SDK base; primary unrelated dirty SDK/UI
changes are preserved by parent integration and require their own combined gates.

Initial failures retained in private local logs: 167 pass/9 fail/10 environment
skips exposed optional legacy fixture fields and a moved foreign-tenant probe;
shared compatibility defaults and exact probe target fixed them. Native fixture
Run identity/queue bootstrap and nonexistent connection-cache close were corrected
without weakening assertions. Missing-reader fixture originally attempted to
mutate frozen AgentApi. The extended AG-UI outage fixture initially contained only
zero-frame model-request facts; persisting a real response makes its check prove
actual durable text rather than recovery notices. An initial 250 ms budget including PG qualification caused
healthy partial-resume suppression; final startup budget covers metadata only and
fresh qualification remains mandatory after catch-up. These failed attempts do
not count as passing evidence.

## Operator key lifecycle and remaining gates

`ZEBRA_STREAM_V2_CURSOR_SIGNING_KEY` must contain at least 32 UTF-8 bytes and be
identical across API replicas serving the same cursors. Configuration repr hides
it; no key is committed. Rotation invalidates existing continuation tokens and
requires full canonical recovery. Keep compatible reader/key/transport available
while accepted v2 Runs exist. Multi-key rotation is not implemented in this slice.

Admission activation remains measured at approximately 81 SQL statements and
18 fresh PostgreSQL connections; total SQL reduction and complete first-token
latency are OPEN. Quiet-reader query rates are inferred from single measured
cycles, not sustained SLO results. New admissions remain disabled until product
acceptance. Follow-up plans retain explicit dependencies:

- `CLOUD_STREAM_PROOF_PERF_PLAN.md`: fresh proof batching/qualified head reads.
- `CLOUD_STREAM_RELIABILITY_PLAN.md`: durable hint relay, aggregate capacity,
  retention/GC and STOP display control acknowledgement.
- `CLOUD_STREAM_RUNTIME_ACCEPTANCE_PLAN.md`: paired actual Worker/HTTP/browser
  workload, SQL/latency, long idle, concurrency and rollout/rollback gates.

No claim of 80–95% measured total SQL reduction, 50 ms TTFT, 100 subscribers,
instant revocation, production readiness or full refactor completion is made.


## Reproduction and frozen evidence

Private local logs live under `.artifacts/stream-client/` and are excluded from
explicit publication staging. Configure the owned PostgreSQL/Redis and separate
header scratch fixture environment without printing credentials. The configured
cohort command runs these modules with `uv run pytest -q --tb=short`:

```text
tests/api/test_stream_v2_cursor.py tests/api/test_stream_v2_http.py
tests/api/test_stream_v2_reader.py tests/api/test_stream_v2_native.py
tests/agent_integrations/test_transient_discovery.py
tests/api/test_live_session_streaming.py tests/api/test_session_streaming.py
tests/test_session_stream_contract_matrix.py tests/api/test_cloud_stream_read_bounds.py
tests/api/test_agui_stream_routes.py tests/api/test_ag_ui_task_stream.py
tests/api/test_client_effect_agui_stream.py
tests/agent_integrations/test_ag_ui_checkpoint_consumer.py
tests/agent_integrations/test_redis_transient_output.py
tests/worker/test_transient_output_composition.py
tests/worker/test_transient_output_composition_native.py
tests/config/test_stream_settings.py tests/api/test_stream_command_admission_api.py
```

Static command: `make check`. SDK commands in `sdks/typescript`: `pnpm check`,
`pnpm test`, `node scripts/stream-v2-browser.mjs`, supported Node 22.23.1/pnpm
10.28.2. A clean cached offline install introduces no lockfile/dependency change.
Frozen owned-file SHA256 manifest and per-log hashes are retained in private
`.artifacts/stream-client/frozen-files.json`. Parent receives its aggregate digest
before independent read-only reviews. No source edits are allowed during review
without a coordinated new freeze.


## Independent SPEC correction and renewed freeze

First independent SPEC review was NOT GO: a set of all historical completed
model calls grew with replay history inside each SSE connection. The 5,000-call
reproduction exposed an O(history) memory bound violation despite successful
native and SDK tests. It was replaced with one boolean recording closure of the
currently attached descriptor; actual descriptor change resets that state.
Canonical history remains intact. A late-attached descriptor still requires
fresh canonical qualification, which rejects already completed calls.

The regression iterates the actual reader over 5,000 historical responses and a
current-call response both without an active generation and with one attached.
Suspended connection state remains bounded and no temporary read occurs after
current-call completion. These are controlled-source reader tests; native current
source closure, partial reconnect, privacy and HTTP tests are refreshed separately.
The reader/wire cohort passed 9/9 in 1.90 seconds. Renewed native/source/HTTP cohort: 29 passed in 54.48 seconds, no skips.
Final `make check`: file sizes3008, Ruff, mypy1264 and eval30 passed.
Native/static results and manifest digest are supplied to parent before renewed independent SPEC;
QUALITY has not started. SDK source and its previous 64-test/browser evidence
are unchanged by this correction.


## Independent QUALITY correction and parent-Session compatibility

QUALITY was NOT GO on two P2 issues. Canonical chunk assembly was deleted before
awaited observer/effect/current-bootstrap acknowledgement. Reducer final draft
and replacement staging also could not replay an unacknowledged final/intermediate
piece. Parser now retires assembly only after every awaited handler succeeds.
Reducer keeps one bounded exact-payload replay slot for the last chunk; duplicate
unacknowledged application is idempotent, conflicting payload fails closed.
Control notices preserve replacement retry state. A temporary reset clears draft
state and server live cursor/partial ordinal so the current generation restarts
with its full retained prefix instead of sending a suffix into empty UI state.

The second P2 was a valid bounded cloud source containing 800,000 DEL characters:
legacy ASCII escaping expanded its record beyond 4 MiB. The finite legacy record
ceiling is now 8 MiB, covering the existing 1 MiB source's worst ASCII-escape
expansion plus metadata. V2 retains 16 KiB records. Local historical sources
without the cloud source bound remain unsupported above the finite 8 MiB ceiling;
neither legacy serialization nor durable storage semantics were changed.
Wire chunk probing also uses the encoded-frame character upper bound instead of
repeatedly serializing arbitrarily large remaining bodies during binary search.

Tracing the existing canonical tenant guard found that a current verified Host
Task/thread/principal grant can read a parent Session after active-child handoff.
V2 no longer adds active-Segment equality as a canonical history restriction.
The actual requested Session is part of its signed cursor digest and context.
Parent history keeps its original Session event IDs/sequences and canonical
source/privacy/deadline checks; all transient discovery/proof/body/control reads
are disabled on that parent context. The active child retains its own scoped
normal draft stream. No Host or temporary authority was expanded.

Controlled SDK consumer + stateful reducer + awaited Host failures now cover
canonical final, draft final, intermediate/final replacement, downstream effect
and current-bootstrap ACK retries, intervening reset notices, exact/conflicting
payload replay, large DEL legacy and oversized unfinished records. Focused SDK:
20 passed; full build/type check and 73 tests passed, no skips. Chromium synthetic
fixture remains three connections/one receipt/zero errors. Native reader/cursor
cohort: 30 passed in 58.21 seconds; HTTP/discovery: 10 passed in 8.47 seconds.
Actual PostgreSQL handoff checks parent canonical response, exact original frontier,
continuation/cold recovery, zero child discovery/control/drafts, cross-child cursor
rejection and active-child Redis draft. Its guard uses the existing verified-Grant
fixture; actual RS256 decode/JTI HTTP checks remain separate native cases.

Evidence preservation error: the rejected `888e66...` manifest was saved before
editing, but its 64-test SDK raw final log filenames were overwritten before they
were archived. Those exact old SDK files are unavailable; their original digest
metadata and independent review result remain historical evidence only. They
must not be represented as currently verifying files. The old native 29-test
proof file remains intact. Renewed manifests reference current 73-test SDK/browser
logs and existing proof files by their actual hashes; no old logs were recreated.
Whole evidence directories will be archived with each subsequent frozen manifest
before any frozen proof filename is reused. Renewed SPEC then QUALITY are required.


Final QUALITY-fix configured refresh: **196 passed, no skips, 182.28 seconds**.
Final static gate: sizes3008, Ruff, mypy1264, eval30 all passed; diff check clean.
The renewed frozen manifest references only current proof log contents and labels
preserved native/SPEC/rejected snapshots as historical. The whole proof directory
is archived under its final manifest digest before any further review edits.
Production and full performance/reliability gates remain OPEN; admission OFF.


## Renewed SPEC reset/disconnect correction

Renewed SPEC was NOT GO on the reset-then-disconnect boundary: an acknowledged
partial draft cursor survived an unsigned reset that cleared browser staging.
Disconnect before the server's new prefix left reconnect requesting only a suffix.
V2 reset now drops continuation to null, including when an awaited Host reset
callback fails. This discards a continuation position rather than acknowledging
new canonical facts. Canonical messages/receipts and same-connection replacement
staging retain their existing handling. Same-connection live effects remain active;
only a subsequent connection with no cursor requests full canonical recovery and
suppresses historical effect adds/removes until the explicit catch-up bootstrap.
A new successfully handled frame can establish a valid cursor normally.

Terminal 401/403/410 and nonrecoverable cold 400 stop the stream even when Host
reset or terminal teardown hooks throw. An invalid old v2 cursor may trigger one
cold retry; cold rejection terminates. Actual consumer/reducer tests cover reset
then socket failure, reset Host failure, full-prefix cold recovery, committed
answer preservation, historical finalized-effect suppression, current bootstrap,
same-connection live effects and failed terminal teardown. Earlier canonical,
draft, intermediate/final replacement ACK retry cases remain in the full suite.

The whole `2419ca45...` proof archive and every original proof digest were verified
before any filenames were reused. Its manifest is also preserved separately as
`frozen-files-reset-rejected.json`. Python sources/tests remain byte-identical to
that freeze. Renewed native/source/HTTP checks passed 39/39 in 67.14 seconds, no
skips; static sizes3008/Ruff/mypy1264/eval30 passed. Final SDK/build/browser results
and the new complete archive are supplied at the renewed freeze. No acceptance,
commit, push or deployment is implied; independent SPEC then QUALITY remain.


Reset-fix final SDK refresh: **80 passed, no skips**, build/type check passed,
Chromium synthetic fixture three connections/one receipt/zero errors. Terminal
410 test also throws from the terminal hook and still observes exactly one request.
Native 39-test and static proofs remain current with byte-identical Python files.
Renewed archive includes the exact current owned source files as well as all proof
files and the manifest, allowing future fixes to retain both source and evidence.

## Independent acceptance on final freeze

Final reviewed freeze17dd8f7d1ba961b43c4d3bce0c00cb938e8b5199a44857d83dfc5a683af34f70:
renewed SPEC original reset/disconnect reproduction converges with full prefix,
historical effects suppressed and current bootstrap; independent SDK80/no-skips.
Renewed QUALITY original canonical/reducer retry and4,801,386-byte legacy probes
converge, no duplication; configured native39/no-skips68.69s and SDK80/no-skips.
Both reviewers verify41owned source/current5proof hashes and complete archives.
Root post-review changes only acceptance governance, not reviewed implementation.
Local integration and combined dirty SDK gates are subsequent evidence boundaries;
full total SQL/TTFT/reliability/capacity/runtime acceptance remains OPEN.

## Local integration and unrelated-work boundary

Commitc0e073fe fast-forwarded into cloud-agent-trench. Primary native40/no-skips
65.92s passed. Combined primary SDK99/no-skips7.07s and build/typecheck passed.
Initial98/99 retains timeline collapse assertion failure; isolated21 and full99
rerun pass. No unrelated UI fix or test weakening was performed.41originaldirty
hashes match, plus original UI-contract contents match after reversing only the
feature patch. Backup .artifacts/stream-client-integration-1791832903310151000
retains original files/hashes/patches; no artifacts staged or pushed.
CLOUD-STREAM-PROOF-PERF-01 Ready; overall product performance/reliability staysOPEN.
