# Cloud Agent progressive output

## Follow-up implementation plan (2026-10-02)

Preserve AG-UI message IDs through deltas, classification, durable Turn
snapshots and React keys. Do not move text between separate DOM containers
when a streamed message becomes progress. Keep candidate text visibly
provisional until commitment, replacing it only when a new candidate arrives.
Use the existing sanitized XMarkdown renderer in both streaming and completed
states, including mathematics and supported media. Show reconnecting and
verification states without invented progress. Retain public progress on
failure and use existing cursor deduplication on reconnect, never resubmit.

Acceptance: deterministic mapping/store/UI tests for stable identity, streaming
Markdown, candidate transitions, duplicate replay and failure preservation;
typecheck and build; authenticated live read-only run with mid-run refresh.
Record live limitations separately. Restarts remain user-operated.

## Contract

Zebra remains the authority for the durable model text stream. Its existing
`MODEL_RESPONSE_DELTA` events project to AG-UI text messages. The existing
`zebra.model_response` marker identifies a completed `tool_loop`, `candidate`,
or `final` response. Trench does not expose private reasoning events.

For a non-empty tool-loop assistant message, Trench emits `public_update`
with the AG-UI message ID and at most 4,000 characters of user-facing text.
The Turn event row is authoritative for SSE replay; `metadata.public_updates`
is a bounded 32-entry snapshot projection, deduplicated by message ID. A
candidate/final answer is kept in the separate answer field. Deltas now carry
`message_id`; Turn metadata persists `streaming_message_id`, `response_stage`
and `first_output_at_ms`. A new message replaces only the transient candidate;
same-ID replay tails append to its durable prefix. A tool-loop update clears
the transient answer but the UI promotes the same keyed DOM node to progress.
Candidate text stays visible with an explicit verification label until the
authoritative final answer replaces it in place. Historical string-form
progress entries remain readable. Tools retain the existing activity group.

The final answer is not published as authoritative until Zebra's final stage
or committed answer. Existing rich content parts remain on the same Turn.
SSE cursor replay and snapshot loading restore the progress without issuing
another model call or duplicating it in the conversation.

## Acceptance boundary

Focused API tests cover mapping, duplicate cursor groups, repeated update
IDs, snapshot recovery, and final-answer separation. Frontend tests cover
live update visibility, deduplication, and retained historical progress.
After the user rebuilds/restarts the local API and frontend, run a real
tool-using conversation, refresh during execution, and confirm one visible
progress item per model message, continuing tool activity, and a distinct
final answer. Build/test success alone is not live-service acceptance.

Local verification on 2026-10-02: paired API mapping/Turn/runtime tests passed
(`82`), frontend tests passed (`26`), Ruff, TypeScript and ESLint passed, and
the Next.js production build succeeded.

## Follow-up verification (2026-10-02)

- API regressions: 90 passed (mapping, Turn snapshots, runtime and grant recovery).
- Frontend regressions: 35 passed, including actual streaming Markdown tables,
  LaTeX, images/video elements, stable DOM identity and transport reconnect.
- Ruff, ESLint, TypeScript and Next.js production build passed. Existing dev
  output remains isolated in `.next-dev`; no process/container was restarted.
- Live conversation `conv_1790943451079_86e2a3`: source-list Turn
  `a480daa8-66d1-4d2f-a33f-cae39345a177` completed in 8,647ms; first text
  persisted 5,848ms after Turn creation. This is server persistence latency,
  not browser paint latency or a percentile performance claim.
- Media Turn `5bee412b-f606-4d1f-9c9a-7a2471317ba9`: refreshed while tools
  were running; four public updates restored without duplicate message IDs,
  original task completed in 57,426ms. Real browser image decode confirmed
  1920 x 1285 pixels. Screenshot: `.artifacts/progressive-output-acceptance.png`.
- A preceding failed Turn was traced to an incomplete TLS proxy response on
  Broker `/exchange`, before run command submission. Grant issuance alone now
  retries transport loss/502/503/504 at most three attempts with fresh nonce
  and principal validation. Tests prove 401/403 are not retried, exhaustion is
  bounded and no task command is replayed. A real proxy fault was not injected.

Remaining evidence limits: browser video playback/chart streaming were not
live-tested in this pass; rendering unit tests do not prove provider delivery.
The model still attempted unnecessary image downloads in a follow-up despite
Host guidance; rendering worked, but autonomous tool selection and narration
remain imperfect. No security gates were weakened to conceal those failures.
Source changes are local/uncommitted; no merge, push or deployment is claimed.

## Closure follow-up evidence

- Completed private reasoning/tool-argument output was incorrectly counted as
  public output, making a response validation failure non-repairable before any
  new tool ran. Chat and Responses adapters now distinguish completed private
  output from published text. Harness still permits only one repair, and neither
  interrupted semantic streams nor emitted text nor spent transport budgets replay.
- `content.present` documents remote Markdown images, external videos and the
  required Vega-Lite chart specification/description. An HTTP artifact argument
  returns actionable routing guidance, including long URLs, without downloading
  or resolving it. Existing artifact/URL validation remains intact.
- Explicit artifact publication is classified as CREATE (artifact still required),
  not external OPERATE. Actual deployment in the same request still requires
  operational verification. This addresses the live chart verification false gate.
- Trench rendering deduplicates progress IDs and separates an inherited-ID terminal
  error, preserving old snapshots without React key collisions.
- Chart SDK keeps its canvas mounted after failure, offers Retry chart, reloads
  on online events and finalizes stale asynchronous Vega views. The tarball and
  Trench lockfile are updated; no npm registry publication.

Validation: core/tools/integrations 1559 passed, 2 skipped; chart SDK 5 passed;
Trench rendering/state/hook tests 36 passed. make check (size/Ruff/mypy/30 evals),
TypeScript/ESLint, chart SDK build and Next production build passed.

Real browser evidence, same acceptance conversation:
- Turn `5ce44b96-efbc-4d54-87cd-d2ee0f3e9a2f` completed in 12,578ms.
  Bilibili iframe played from 00:02 through 00:23 of 17:22, then paused.
  No video file download or object-storage copy was involved.
  Screenshot: `.artifacts/progressive-video-acceptance.png`.
- Turn `2e78496a-c235-4f49-a189-346677585961` produced a Vega-Lite chart;
  renderer displayed the example A=3/B=5/C=2 after network recovery and reload.
  Runtime remained paused at the old artifact-publication verification gate.
  Browser-only offline/block rules were restored to normal after testing.
- The already-running Next dev process still displayed the old chart component
  without its new Retry button, despite installed package and production build
  containing it. Do not call this new recovery UI live-accepted yet.

Latest built API image: `fc13d8a78d39e0ca8fb42b88bbb0e9998cfdf51df5ee3c6b3d250ff71c99edfa`.
Latest built Worker image: `2d7c87ffaf795838ad98b8d212c6ee28d4925d6f584e1a203d930ffbbe825899`.
Both processes still use prior images. User must recreate API/Worker and restart
Trench frontend before final combined media, autonomous image-selection and
forced-disconnect/retry acceptance. Forced offline alone did not prove the live
SSE was interrupted; do not equate that test with verified reconnect semantics.

### Chart lifecycle follow-up

Chart spec/data and fallback-table fetches now share their effect's cancellation
signal. Unmount, replacement and retry cancel obsolete requests; a delayed
artifact resolver cannot start a fetch after cancellation. Synchronous fallback
resolver failures enter the existing fallback instead of escaping the effect.
The five SDK checks include pending-request cancellation and throwing fallback
resolvers. The component package is rebuilt and repacked for Trench; these are
local checks, not fresh-runtime browser acceptance. User-operated activation
requirements above still apply.

### Initial snapshot outage recovery

Two regression cases reproduced an idle observer after initial snapshot failure:
manual reload restored a running snapshot without attaching SSE, and the online
event did nothing. The paired hook now restarts observation after an explicit
successful reload of an active Turn, or network recovery after initial load
failure. Successful reads clear the stale error. Existing active observers and
terminal Turns are not restarted by online events; no task is resubmitted.
Existing same-turn cursor guards and conversation epoch isolation remain intact.
Validation: frontend 55 files / 199 tests, TypeScript, focused ESLint and Next
production build passed. Real browser outage recovery remains a separate check.

### Pause acknowledgement ordering

A regression reproduced a completed Turn reverting to running when a delayed
pause response arrived after the durable done event. Pause acknowledgements now
update only the same currently-active Turn, preserving terminal status and newer
Turns. The test delivers done before resolving the pause request and verifies
that the answer and non-busy state remain intact. No backend task is restarted.

### Cross-conversation operation isolation

Pending submit/pause state previously survived navigation; late acknowledgements
could clear a newer submission's busy state and late pause failures could appear
in another conversation. A conversation lifecycle generation now guards operation
responses, including navigation away and back to the same key. Navigation resets
local operation flags without cancelling server tasks or changing idempotency.
The workspace caller also ignores stale submit errors and consumes pause
rejections already reported by the hook. Regression cases cover switching,
returning to the original conversation and delayed errors at the caller.

### Empty stream reconnect pacing

An EOF without a terminal event used to bypass transport-error backoff, allowing
an empty successful response to trigger immediate stream/snapshot polling.
A fake-clock regression observed four requests without advancing time before
the fix. Both EOF and transport failure now share bounded exponential delay
(300 ms to 5 seconds); accepted new events reset that delay. The durable cursor
and terminal-event guards remain unchanged. Effect cleanup clears and resolves
the pending retry timer so navigation leaves no retry timer behind.

### SSE field and cancellation boundaries

The shared parser accepts data fields without optional whitespace, including
multiline JSON, for both durable Turn and legacy chat APIs. Turn observation
checks cancellation before and after dispatching each record, discards buffered
late events and exits without another network read. Existing generator cleanup
still cancels/releases the reader. Three regressions failed before the change
(two dropped-message cases and one timeout). Unterminated frames are not promoted
to complete events; cursor replay is unchanged. Validation: 26 focused tests,
TypeScript, focused ESLint, Next production build and diff checks passed.

### Unconfirmed submission recovery

When both idempotent submission responses and the reconciliation read fail,
the optimistic assistant previously stayed loading indefinitely. It now carries
the client request identity so only that placeholder is settled with an explicit
unconfirmed-delivery notice, retaining the user's question. Network recovery
re-reads the durable snapshot without resubmitting. Successful reconciliation of
an active Turn uses the existing reload/observer restart path. A regression
asserts the notice, stable request ID, preserved question and eventual restoration
without a third submission; it failed before this change.
