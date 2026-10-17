# Cloud search stopping conditions — 2026-10-17

## Root cause and smallest change

Varied real-page questions exposed a deterministic conflict beneath existing
minimum-evidence guidance. A factual Node.js lifecycle lookup mentions “首次发布”.
The shared task heuristic treats publication as an operation but does not
recognize “核对” as an information request. It infers operate, operation_completed
and result_verified. After an adequate first candidate, runtime feedback demands
an operation postcondition. Two extra models and one extra fetch cannot prove an
operation the user never requested; the original Run pauses verification_required.

The fix changes only agent_core.harness.task_contracts._task_type (16added lines):
recognize factual lookup verbs; preserve explicit compound action commands.
No source/domain/query is hardcoded. No new prompt/model classifier/tool cap,
auto-fetch, cache, dependency, policy bypass or Trench logic. Agent tool selection
remains autonomous. This repairs an inferred completion contract, not authority.

This is not the cause of every repeated search. The prior B1 release-date task
was already an answer task; this fix does not prove that B1's detour is solved.

## Fixed three-question page pairs

Exactly six new Runs: R1/R2/R3 baseline, C3/C2/C1 candidate, no replacement or old
Run replay. Candidate selection followed the baseline, so this is a diagnostic
cohort, not an independent general benchmark. The identical question within each
pair is sent through the actual Trench page, general/Flash/high/transient_v2.
Every model receipt confirms enabled/high/retry0; no failed tools.

Questions:

1. 请联网核对 Python 3.13.0 的正式发布日期和两项主要新特性，仅采用官方来源并附链接，简明回答。
2. 请联网查 SQLite 官方文档，说明 WAL 模式下读写能否并发、是否支持多个同时写入者，以及相比回滚日志的一项限制，附官方链接，简明回答。
3. 请联网核对 Node.js 22 和 Node.js 24 各自首次进入 LTS 的日期与代号，只采用官方来源并附链接，区分首次发布与进入 LTS，简明回答。

| Question | Run | First visible body | Send → terminal | Models / tools | Status |
| --- | --- | ---: | ---: | ---: | --- |
| Python | R1 |7.750s|9.281s|2 / 2|completed|
| Python | C1 |9.664s|11.681s|2 / 2|completed|
| SQLite | R2 |19.932s|23.203s|4 / 4|completed|
| SQLite | C2 |13.346s|15.699s|3 / 2|completed|
| Node.js | R3 |18.762s draft|32.962s to pause|7 / 8|awaiting_input|
| Node.js | C3 |16.444s|20.395s|4 / 7|completed|

Send is the DOM click; first body is the earliest visible text containing the
final public answer's normalized16-character prefix. Terminal is canonical Trench
completion timestamp. R3 has only an unaccepted draft and a later pause, **no
accepted-answer latency**. Do not label its terminal time successful completion.

The decisive mechanism: after the first candidate R3 adds2models/1fetch; C3 adds0/0.
Total7→4models also includes a different autonomous pre-candidate grouping, so not
all three rounds are attributable. The first-body difference2.318s also mixes
model/source/external wait variation.

No pooled speedup percentage is justified: Python is slower, SQLite's acceptance
contract is logically identical before/after, and R3 fails. Whole-turn SQL was not
measured. No authorization/database read was removed.

## Why existing guidance did not prevent extra work

- Platform conflict: live Worker imports the expected stop/source guidance, but
  later runtime feedback requires verified operation completion. R3's canonical
  suspension explicitly records operate, missing task_contract_verification.
  Fix the shared contract instead of repeating the generic guidance.
- Necessary missing text: R2's official SQLite fetch omits middle content including
  concurrency facts. It reads artifact ranges9000+6000 and6400+5000. They overlap,
  but the second reaches an earlier missing section. These are not duplicate web
  fetches. C2 instead reads5000+6000 once. No projection/reader change was made.
- Autonomous choice: R1 chooses search+fetch; C1 chooses two official fetches.
  Node pre-candidate reads distinguish Current releases and LTS announcements;
  date/table corroboration can overlap. No hard rule removes those sources.
  B1's landing-page detour remains a model/source-selection variability issue.

Candidate pages cover requested facts and official links. This is a bounded
review of required outcomes, not certification of every optional sentence or
citation. Models still add optional facts despite “简明回答”; this remains a limit.

## Shared path and validation

All inference/parse callers were inspected: model acceptance messages, quality
evaluation and Worker recovery use this function. Partial Host constraints inherit
correct inference; explicit requireVerification/taskType still override it.
Actual “查询后发布”, “核对配置并部署”, “查找问题再修复” and “请执行一次测试，然后查询结果”
retain verification. Post-mutation checks and signed Host/fresh grant/profile,
DNS/SSRF and request cancellation code are unchanged. No old Run is reinterpreted.

- scripts/check_search_task_intent.py fails on the original Node goal before the
  fix, passes7factual goals (inferred and partial Host),11compound actions,
  explicit Host override and negation. No model/network/framework required.
- Existing quality/negation/artifact publication/search guidance:64passed.
  Target Ruff, one-module mypy, diff/file-size checks pass.
- Built Worker smoke with network disabled, then actual normal Worker smoke.
  Only task_contracts.py overlaid onto accepted Worker9953a04d; base module was
  byte-equal to prepatch tracked source. Candidate9e1a5f957a4d excludes inherited
  unaccepted thread/progress and user dirty security files.
- Normal APIca0a85f2/Search19f3942f untouched; original env hashes, entrypoints,
  managed Cloud/Yahoo exit and proxy settings preserved; services healthy/restart0.

Existing check_cloud_search_critical_path.py assumes disjoint search/fetch stages.
Mixed R1/R2 violate that assumption, so its failures are retained; checker unchanged.
C1/C2/C3 decomposition passes. Overall DOM/canonical/counts are separately
reconciled for all6; no invalid baseline stage sums are reported.

## Evidence, reproduction and rollback

Feature ignored .artifacts/cloud-search-decision/ contains canonical and public
tool arguments/results, page DOM frames, summary.safe.json, contract-differential,
image/activation and original-service identity evidence. No private reasoning,
credentials or headers collected. Contract differential proves Python/SQLite
unchanged and Node operate→answer with operation outcomes removed.

Run the assertion check from this repo with primary .venv/bin/python and
PYTHONPATH=packages/agent-core/src: scripts/check_search_task_intent.py.

Original/candidate conversations and Runs:

- R1 conv_1792232813763_17260d /06ec6a0e-ee3e-4736-953b-c1f212671cd2
- R2 conv_1792232837531_bc7bd9 /a4e47e0c-2b42-4457-a561-1f8d4ed7a233
- R3 conv_1792232883911_3bcde6 /082a3425-3419-4452-9f92-a14c194cefa7
- C1 conv_1792233203193_233c29 /e1a05858-f445-4f7d-b8c4-70f1806a888d
- C2 conv_1792233156442_698935 /923ceeb9-cc8a-4b03-a71d-74820a10077d
- C3 conv_1792233110262_b6c6d3 /1fa5a259-6e1e-4fd0-a2ae-b25ed6843178

Rollback retags saved Worker9953a04d as zebra-application-zebra-worker and recreates
only zebra-worker with original six Compose files/env-file. API/Search unchanged.
Temporary receiver/DOM observer removed after capture. No push/remote deploy or
unrelated fixture changes. Further source selection improvements require a larger
predeclared corpus; artifact navigation needs measured benefit. Do not rerun one
question until it looks faster, or claim a bounded heuristic understands all intent.
