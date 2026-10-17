# Citation prose-boundary repair — 2026-10-17

## Outcome and relation to B1

Historical B1 source selection remains unproven to be fixed. The separate
four-question checklist experiment failed:13→14models,14→15tools, median first
body12.466→13.040s. That code is not promoted; accepted original research guidance
remains active. See CLOUD_SOURCE_DECISION_CHECK.md.

This slice repairs a reproduced source of unnecessary **candidate regeneration**:
the citation validator includes Chinese parentheses and adjacent prose in a bare
URL, falsely treating a collected link as an invented destination. It does not
rerank search, select sources, force stopping, or resolve the historical B1 detour.

Two real candidates in the varied cohort reproduce it with unchanged evidence:

- SQLite B2: https://www.sqlite.org/wal.html），要点如下
- PG/Redis A4: https://www.postgresql.org/docs/18/release-18.html）

Both actual URLs were collected, and no tool adds evidence between the two
candidate generations. Native replay of each original public candidate initially
fails citation_uses_exact_collected_url. This is a deterministic gate defect,
not model thinking time or a network retry. Their extra provider calls cost
2612/3823ms respectively; these are observed calls, not a promised page saving.

## Smallest correct shared repair

The original URL regex remains unchanged. In _unsupported_urls, normalize Chinese
parenthesized prose only when the extracted candidate is not already a collected
URL and is not in an explicit Markdown/angle/quoted destination. Scan only the
immediate preceding whitespace/context; no full-prefix copies or new dependency.
Already collected full Unicode URLs remain exact. Unknown paths, query suffixes,
fragments, domains and explicit malformed link targets still fail.

A blanket two-character regex exclusion was rejected: the existing regression
correctly requires [原文](collectedURL（补充说明）) to fail because its literal href
is wrong. That test was kept unchanged. The final distinction between prose and
explicit targets is necessary; a shorter regex-only change is not correct.

This remains the existing citation heuristic, not a complete Markdown parser.
Exotic syntax is not certified. No authority, fresh Host/grant/profile, DNS/SSRF,
request cancellation, quality postconditions, model/high/v2, Trench, gateway,
storage, tool schema, source allowlist or global proxy change is included.

## Native checks and retained intermediate problems

- New assert-only scripts/check_citation_delimiters.py: eight prose formats,
  eight unknown-URL controls, four invalid explicit destinations, known Unicode
  URL and missing-evidence control. Original source fails; final source passes.
- Original public candidates A4, B2 and preliminary Q1 pass unchanged with their
  unchanged collected references. No model invocation, old Run replay or event
  mutation occurs during replay.
- Existing targeted quality/negation/publication/search regressions:64passed;
  Ruff, one-module mypy, diff/file bounds pass. No full-suite claim.
- Network-disabled actual image smoke before final activation verifies prose
  acceptance and explicit bad-target rejection. Only quality_gates.py is overlaid
  onto accepted9e1a5f95; rejected checklist absent, original guidance hash verified.

Preliminary right-parenthesis-only Q1 still produces2candidates: another annotation
starts with a LEFT parenthesis. Retained as a failed optimization sample, not
replaced. The blanket exclusion then fails one existing explicit-href regression;
a diagnostic command continued to image activation because it did not stop on
pytest failure. That image was rolled back before any model/page call. Subsequent
build/activation uses stop-on-failure. Final model traffic uses the corrected
prose-versus-explicit implementation. No existing test was weakened or repaired.

## Final fixed two-page verification

Exactly3new quality-stage Runs: preliminary Q1 plus final frozen Q2SQLite/Q3PGRedis.
No additional favorable replacements. Final two compare to retained original-guide
A2/A4 controls from the previous8Run experiment. This is a small chronological
comparison, not a balanced independent benchmark. All3canonical completed,
high/Flash/transient_v2, retry0 and no tool failures; tools remain autonomous.

| Workload | Version | First visible prefix | Send→completed | Models / tools | Candidates |
| --- | --- | ---: | ---: | ---: | ---: |
| SQLite | A2 original |11.721s|14.265s|3 / 2|1|
| SQLite | Q1 preliminary |14.204s|19.764s|4 / 3|2|
| SQLite | Q2 final |12.262s|14.494s|3 / 2|1|
| PG/Redis | A4 original |11.807s|19.784s|4 / 4|2|
| PG/Redis | Q3 final |12.386s|15.725s|3 / 4|1|

First prefix is the earliest visible DOM text containing the final answer's
normalized16char prefix; v2 may show provisional draft text. Completion is the
canonical timestamp. Final requested facts and official links are present, but
this is not certification of every optional sentence. Both final pages have only
one candidate. PG whole -4.059s is consistent with removing one regeneration,
but model/transport variability prevents attributing the entire difference.
SQLite is slightly slower. **No stable first-body or general SQL improvement
is proved.** SQL was not measured. The same-candidate native replay, not two
random future model choices, establishes the validator correction.

Final identities:

- Q1 conv_1792234539410_4e50a2 /2b023423-e352-4d1f-b593-138619880bbd
- Q2 conv_1792234817362_96af30 /8d12691d-ff9b-4f9c-91c7-d98aba8565a0
- Q3 conv_1792234860010_cb5c81 /06f885f4-3bec-4311-8839-50af01b0d252

## Local state, evidence and rollback

Normal Worker d246fa25481c contains only the final quality module change on9e1a5f95.
APIca0a85f2/Search19f3942f, original environment/entrypoints and existing
classification/egress/connection gains remain. No remote push/deploy, global
proxy changes, old Run resumption or unrelated source/test fixture repair.
Temporary DOM observer and loopback receivers are removed after capture.

Ignored .artifacts/cloud-citation-delimiter/ contains final-replay.safe.json,
summary.safe.json, canonical/tools/page records, red checks, image/activation
logs and original service identities. Prior8Run evidence remains separately in
.artifacts/cloud-source-decision-check/. No credentials, headers or private
reasoning collected. Across both experiments exactly11newCloudRuns,37canonical
model responses and38successful tools; native replay adds0model calls.

Run scripts/check_citation_delimiters.py using the primary .venv/bin/python from
the repo. Rollback restores saved Worker9e1a5f95 through the original six Compose
files/env-file and recreates only zebra-worker; API/Search remain unchanged.
The larger B1 semantic source-selection problem stays open; do not relabel this
citation repair as a general retrieval optimization.
