# Trench settings and media repair — 2026-10-18

Task: `TRN-SETTINGS-MEDIA-01`; human owner Luke Ding, executor Codex.
Both primary checkouts use `codex/trench-settings-media-01`. The user authorized
remaining full-gate repairs followed by commit and push on 2026-10-18.
Validated local baselines: Zebra `0fc2651f`, Trench `59773b7`. The repair
branches inherit these locally integrated histories; delivery targets the new
GitHub topic branches, with mainline integration handled separately.

## Confirmed causes and changes

1. User-management endpoints supplied random UUIDs to the Task-aware grant
   helper. The helper correctly rejected IDs absent from durable Host bindings
   with `task_host_thread_unavailable`, which the BFF exposed as 502. Memory,
   personalization, usage, extensions and schedules now explicitly pass `None`
   for Task identity. The shared helper reuses the existing user/workspace
   bootstrap identity. Real Task IDs still require the existing durable binding.
2. `Literal[7, 30]` rejected the string-valued HTTP query `?days=7` with 422.
   The usage route accepts the two string literals and converts them to integers
   for Zebra. Unsupported periods remain rejected.
3. Artifact policy treated every non-text tool payload as sensitive, including
   intentionally delivered `files.publish` JSON, images and video. The access
   descriptor now has a default-false `published` flag. API and CLI derive it
   solely from the canonical successful `files.publish` ToolRun projection.
   The shared policy allows these local published payloads under workspace
   policy; internal binaries, redacted previews, external references and
   read-only sessions retain their previous restrictions. No HTTP input can
   assert publication. Namespace, Task ownership, grant scopes, event binding,
   lifecycle, integrity and byte ceilings remain enforced.
4. After the original chart previews returned 200, the chart guard rejected
   numeric conditional expressions such as `datum.pct >= 0`. The renderer now
   converts a single finite numeric comparison into a declarative field
   predicate and renders the validated copy. Input objects are unchanged.
   Supported operators are `===`, `<`, `<=`, `>` and `>=`; fields use simple
   dot access or quoted bracket access, including Chinese field names.
   Calls, compound expressions, coercive equality, nested paths, infinity,
   executable transforms and remote data remain rejected. Richer conditions
   must use declarative predicates directly. See the
   [Vega-Lite predicate contract](https://vega.github.io/vega-lite/docs/predicate.html).

5. Full-gate follow-up corrected coverage replay assertions to parse the URL
   and check the exact Task path and durable cursor independently of additional
   transient query parameters. The Host integration assertion now matches the
   existing goal-only contract; runtime intent/evidence inference is unchanged.
   Both background title tests wait for the actual write with a bounded timeout
   instead of assuming an 80/400 ms scheduling window. Local `.artifacts/`
   operator output is ignored using Git's existing mechanism; source Ruff rules
   remain unchanged. No historical evidence scripts were deleted or reformatted.
6. Zebra's full suite exposed stale expectations for retryable checkpoint hints
   (failed notification must retain work until successful publication), audited
   parallel `web.fetch` registration, and optional private reasoning in Responses.
   Updated their tests to the existing implementation and deterministic contracts;
   real provider tool continuation, reviewer output and public stream checks stay.
   The Unix-socket Redis probe now follows its sibling's explicit configuration
   guard, so an absent owned fixture skips instead of raising `KeyError`.
   The early extension-read regression now checks both shorter parent and
   shorter two-second child deadlines instead of requiring parent equality.
7. Search configuration tests now read the sole `docker/web-search/config/`
   authority and recognize explicitly disabled Exa. Cloud composition fixtures
   supply the now-required Redis URL, assert the native publisher is composed,
   and drain it without starting network or maintenance work. Exact approval
   continuation still forces compaction and preserves the pending call, using a
   1,000-token budget that includes the protected instruction ledger. The Host
   identity assertion follows the existing per-step recovery wording.
8. The local recorder double explicitly declares no cloud mutation authority.
   The publication-lock regression checks the typed `WorkerProgressTimeout`,
   preparation stage, uncommitted boundary and original lock-timeout cause;
   timer termination and absence of late writes remain required. The shared
   cloud settings fixture also fixes the transient-output composition caller.

The patched react-charts tarball is vendored in Trench. Its lockfile change is
only that tarball's SHA-512 integrity; existing dependency versions are pinned.

## Validation and local activation

Regressions reproduced the settings grant failures, published-media policy
rejections, numeric chart guard rejection and usage HTTP 422 before repairs.
The first complete Zebra run found 18 failing cases (9,615 passed / 2,920 skips);
the affected regressions now pass. The final complete rerun passed in 1,183.87
seconds: 9,633 passed / 2,921 environment-dependent skips, zero failures.

| Gate | Result |
| --- | --- |
| Zebra `make test` | Passed: 9,633 tests / 2,921 environment-dependent skips; no test-selection exclusions |
| Zebra `make check` | Passed: file sizes (3,149 files), Ruff, Mypy (1,292 sources), deterministic eval (30/30), postcommit repair and risk boundaries |
| SDK `pnpm verify`, Node 22.23.1 | Passed: 104 tests, TypeScript/build, package audit, React 18/19 with Vite/Next SSR/RSC, Chromium/WebKit interactions and Next hydration |
| Trench `make check` | Passed: 233 API tests / 62 infrastructure-dependent skips; 80 cleaning tests; 472 frontend tests; ESLint; Admin Vite and ToC Next builds; single Alembic head and offline SQL; whitespace |
| Trench management/grant regressions | 33 passed; actual grant helper, authenticated request/scope boundaries and HTTP query validation |
| Trench final standalone TypeScript | Passed after restoring the original development `next-env.d.ts` reference; title synchronization passed three consecutive two-case runs |
| Published-media regressions | 43 Zebra artifact/policy tests and 26 CLI tests passed; JSON/PNG/MP4 preview, download, HEAD and Range; failed/redacted/internal/external/read-only denials |
| Owned Redis frontier/Unix-socket checks | 10 passed, zero skips against the dedicated loopback stream-test fixture; no fixture restart or global Redis mutation |

The vendored chart JS/CJS/types exactly match the verified SDK build. Lockfile
changes only its tarball integrity; dependency versions remain pinned. Live
provider smoke tests are included in Zebra validation; returned private reasoning
is optional, but real tool continuation and streamed public output are required.
Native PostgreSQL and other service-specific cases retain explicit environment
requirements; skipped cases do not claim native service acceptance.

After explicit user approval, only the local Zebra API image was replaced with
`zebra-api:trench-settings-media-01`, image
`sha256:7aa5c7600f11ae386f4a4a75f83577fd5b17b52f2b12bb8b55b364deed2ce3d0`.
The overlay changes exactly three Python files above the live base image.
Activation checked exact environment, command, mounts and security options and
zero active Worker leases; deployed source bytes match the checkout. API health
is healthy. This task did not update the Worker; concurrent local work can
change it independently. The previous API image remains tagged
`zebra-api:settings-media-base-20261018` for rollback.

Trench's existing reloading API loaded the route changes; Next's development
compiler was refreshed for the new vendored chart package. No business data,
model-generated answer, immutable artifact or database schema was rewritten.
No model run, commit, push or remote deployment was performed for acceptance.

## Authenticated browser acceptance

Using the existing signed-in localhost account:

- Personalization loaded revision zero normally; no preferences were changed.
- Memory showed zero active and zero pending entries normally.
- Both 7-day and 30-day usage displayed committed-event data and charts.
- Skill showed one installed/enabled entry; MCP showed the existing connection.
- Original conversation `conv_1792255932098_ac062e`: both original artifact
  previews return 200 and all four chart presentations contain rendered SVGs,
  with no loading-failure/retry placeholders. This validates loading/rendering;
  it does not certify model-authored chart specifications or economic claims.
- Existing external WebM in `conv_1791864335461_7699b7`: 640x360,
  duration 143.46 seconds, readyState 4, no media error; playback advanced past
  28 seconds and was paused after the check. Private generated-video Range/HEAD
  behavior is covered by backend tests, not a new browser-generated video.

Local screenshots and activation evidence are under
`.artifacts/trn-settings-media-01/`. These are operator evidence, not release
artifacts. Unrelated dirty files in both checkouts remain untouched.
