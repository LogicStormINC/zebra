# Production Turn admission and commentary projection repair, 2026-10-22

## Actual failures and root causes

Conversation `conv_1792653198852_670a75` has three distinct submissions:

| Run | Preserved state | Finding |
| --- | --- | --- |
| 7a11f93c-de36-4179-ab6c-4474de620265 | awaiting_input | Shell execution requires approval; terminal projection corrupted prior commentary |
| 7c12c641-3dd3-48b2-bd40-7bc0db41d97f | completed | Answer637characters retained; subscription write was described as unconfirmed |
| f888fded-51ef-41fd-8f1d-f2701bd4a1ca | failed | Command403 before execution; authorization selection exceeded the reused Task ceiling |

The third request includes one newly authorized source and topic `picture`, absent
from the second Task's frozen resource ceiling. Fresh grants were accepted, but
renewal correctly refuses resource expansion. Trench's Task generation considered
mode and Skills but omitted source/topic authority, so it reused an incompatible
Task and appended a message before command rejection. Do not weaken the ceiling.

Exact replay of the running frontend found `model commentary restored text changed`:
one commentary item held an80character source with its valid SHA256, but its visible
message had been overwritten by the61character terminal approval notice. The item
also inherited confirmed/final while retaining commentary identity/proof. Both API
and browser projectors selected the last streamed identity for `done` and overwrote
it. The browser's strict validation correctly refused this inconsistent projection.

Initial local-source inspection suggested HTTP lacked WebCrypto. A real browser
confirmed insecure context/subtle absent, but actual-image inspection showed the
existing Noble fallback already worked. That hypothesis was disproved; the duplicate
candidate fallback was discarded. Six real saved commentary items were replayed,
with exactly one bad terminal overwrite. Inspect deployed bytes, not only Git tags.

## Minimal shared changes

1. Reuse the existing bounded generation digest for canonical source/topic sets
   plus Skill selection; mode remains explicit. Resource changes select a successor
   Task before appending messages/commands. Ordering/duplicates do not cause churn;
   narrowing and changed IDs do change selection. Fresh signed authorization and
   frozen ceiling checks remain intact. Stored generation fits VARCHAR(64), including
   maximal Skill selection; actual saved request generations are50characters.
2. In both ordered-output projectors, terminal replies targeting commentary use
   `result:<commentary-message-id>`. Keep original commentary and its digest/IDs;
   replay is idempotent, and exact terminal selection remains separate. No validation
   bypass, proof deletion or fabricated completion.
3. Commit the already deployed HTTP compatibility baseline (Noble2.4.0, exact lock,
   existing SHA helper and its two callers) into source so a future rebuild does
   not lose it. Production Node22.14.0; no new production dependency or runtime
   behavior introduced by this sync. Local dependency acquisition reused the exact
   pinned production package without replacing other installed packages.

## Controlled production activation

After0active execution leases,0pending commands and0active Trench execution Turns,
only Trench API/frontend were replaced. Preserve original three Compose layers plus
`/home/ubuntu/releases/20261022-turn-admission-commentary/trench-override.json`.
Only two backend source modules and the frontend projector changed in the running
images; existing HTTP compatibility remains. Runtime configuration, commands,
mounts, security and base image layers match before/after. No database migration.

- API image: `trench-backend:turn-commentary-20261022`, ID7f4866a7….
- Frontend image: `trench-frontend:turn-commentary-20261022`, IDe45ad671….
- Full source hashes/base identities: build.safe.json in the release directory.
- Zebra API/Worker (workspace-io images), persistent10GiB mount, Search/TLS/Yahoo,
  Exa/MCP processes/cooldown, Broker and other stable containers are unchanged.
- Existing Caddy/pgAdmin restart loops retain IDs/config; not repaired here.

The one proven corrupt Turn projection was repaired under row locks using original
stored public events and their chunk hashes. Rebuild only its commentary item and
separate the terminal item through the fixed projector. Repair the Turn metadata,
assistant history metadata and one matching legacy derived copy; advance the native
snapshot watermark. Preserve answer bytes, Run/status/request/cursor, event logs,
feedback and other items. The first Run remains awaiting_input, the third failed.
No model/search, execution command replay, subscription retry or automatic approval.

## Validation and boundaries

-74focused API tests: generation, normal stream handoff, immutable projection,
 replay and explicit/implicit terminal identity. No old-Task message; one successor
 and one command for a newly submitted test case; no hidden retry.
-83focused frontend tests: ordered output, stream validation, coverage reports,
 no-WebCrypto SHA vectors. TSC, Ruff and whitespace/file-size checks pass.
-Actual new images: network-none saved-data replay validates all6commentaries with
 WebCrypto unavailable; deliberately altered content is still rejected.
-Real saved request selections resolve to different bounded generations through
 the normal client helper; duplicates/reordering remain equivalent.
-Native owned snapshot returns6messages/latest failed; real logged-in Chrome reload
 now displays historical content, without model_commentary_conflict. Existing failed
 submission remains visible as historical failure. No response interception.
-Original/protected8Session event hashes/model counts and all three Turn answer/
 request/status/cursors unchanged. Suggestion generation POSTs after API restart0.
 Both readiness URLs200. These health checks are not the E2E proof.

No new real-model Run was authorized or executed for successor admission acceptance;
that boundary is covered by focused protocol tests and actual deployed helper/data
checks, not a claim of a new live model run. Subscription host_effect_unconfirmed is
preserved; this repair is not proof of a confirmed subscription receipt. Do not retry
its write or relabel it successful merely from the displayed answer.

Evidence/scripts: private same-task .artifacts directory and remote release directory.
Rollback application images under idle guards to the previous three Compose layers;
never roll back authoritative Run events or automatically resubmit a command. Derived
projection backup and source events are retained; any projection rollback also uses
snapshot watermarks and must preserve later feedback. Local source integration only;
no GitHub push.


## Source integration

Trench source commit b159d1a is locally fast-forwarded into main; only the owned
implementation/tests and accepted HTTP compatibility baseline are included. Zebra
cloud-agent receives this focused deployment/acceptance record. Frozen Trench archive
refs remain untouched; unrelated user dirty files are preserved. No GitHub push.
