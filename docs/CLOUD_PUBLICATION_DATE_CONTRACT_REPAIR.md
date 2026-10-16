# Publication-date intent boundary and real search acceptance

Task `QUALITY-PUBLICATION-DATE-01`; human owner Luke Ding, executor Codex.
Branch `codex/quality-publication-date-01`, base `a20c6a94`.
Local `cloud-agent-trench` integration and local service activation only.

## Root and minimum correction

The B1 official-release information search completed nine read tools, but its
fallback task contract matched 发布 inside 正式发布日期. It classified the task
as `operate`, required `operation_completed` / `result_verified`, and ultimately
suspended with `task_contract_verification` after six model rounds. This was a
contract false positive, not a missing publication operation by the model.

Only the fallback noun/action boundary in `harness/task_contracts.py` changes:
发布日期 and 发布时间 do not alone imply a publication action. Explicit publish
requests still count, including publishing a release date to an announcement.
Existing artifact publication exclusions and negation handling are reused.
No new classifier, model call, dependency, project-specific product name rule,
or new orchestration layer is introduced. The model continues choosing tools.
Explicit supplied contracts, real operation verification, evidence/citation
requirements, authority/nonce/STOP and all final completion checks remain.

## Focused validation

`uv run python scripts/check_task_contract_publication_dates.py` provides twelve
standalone assert checks: the exact page prompt and generic date/time questions
retain evidence and matching-citation requirements without operation outcomes;
nine actual publish/deploy prompts retain operation verification. The original
exact prompt reproduced `operate`; all twelve checks pass after the correction.

Existing artifact-publication, negated-action and quality-gate tests: 62 passed.
Source/script Ruff, mypy1283, file-size3091 and deterministic eval30 pass. This
is focused acceptance; no full-suite claim or unrelated fixture repair.

## One fresh real confirmation

Same prompt as A1/B1: “请联网搜索并核对 PostgreSQL 18、Redis 8 的正式发布日期和
各两项主要新特性，只采用官方来源并附链接，简明回答。”
Flash / high / exploration / `transient_v2` remain selected. No old Run resumes.

- Conversation: `conv_1792125747131_1cf60f`.
- Run: `a133e0c8-7f21-42c4-8d66-e7e750d9698f`.
- Cloud session: `10390abd-6c6a-4ccb-8875-9501ff6d90a8`.
- Canonical `answer_committed` then `turn_completed`; Host status `completed`.
- Four model receipts, all thinking enabled / effort high / retry0.
- Six successful tools: three `web.search`, three `web.fetch`; zero failures.
- No runtime provisioning event or local OCI call in this request.

| C1 measured span | Time |
| --- | ---: |
| Click → first Cloud HTTP (Host/Broker aggregate) | 1023 ms |
| First Cloud HTTP → command response | 1106 ms |
| Command response → Worker entry | 331 ms |
| Worker entry → actual Provider HTTP | 1482 ms |
| Click → actual Provider HTTP | 3942 ms |
| Provider HTTP → first public delta | 972 ms |
| First delta → Redis draft / API first tail | 2.3 / 4.3 ms |
| First visible process update | 5407 ms |
| First substantive answer block, still provisional | 27700 ms |
| First dated facts inside that answer block | 28107 ms |
| First official links inside that answer block | 29198 ms |
| Canonical completion / Host completion | 31233 / 31857 ms |

The 5.41s process update says it will search; it is not the answer body. An
intermediate 19.39s update mentions one date while asking for another search;
it is also not counted as the final substantive answer block. The 27.70s
answer prefix is classified from the captured visible timeline, not the
observer's broad `answer` field, which also sees progress text. Provisional
output visibly carries the existing pending-verification label until commit.

The last Provider request starts at 23.87s; its first public answer delta arrives
at 27.36s, and the browser shows it at 27.70s (about339ms later). The six tool
handler durations are 1.26–3.04s, arranged in three two-tool batches. These
network reads, four model requests and intervening durable scheduling still
account for substantial latency; this slice does not establish a sub-10s
network-search SLA or isolate every Host/Broker substage.

## Comparison and retained gains

B1: six models / nine successful tools / provisional body33.57s / final paused.
C1: four models / six successful tools / provisional body27.70s / completed.
The false operation-verification path is eliminated, with actual operation
checks retained by regression tests. Different model decisions, network and
cold/warm conditions preclude treating the timing difference as a causal
performance percentage or a percentile/SLA.

Startup remains398 explicit SQL statements /53 TaskIO connections in A1, B1
and C1. Full-worker B1/C1 observed SQL4085/2859 and connections943/637 have
different model/tool paths and terminal outcomes: no normalized SQL reduction
claim is made. Existing v2 persistence and previous performance source changes
remain present; the projection repair fairness fix from `a20c6a94` is retained.

## Normal service and page acceptance

After C1 terminated and a zero-active-intent guard passed, replaced temporary
trace services with the prepared normal source-only images:
API `b0f0832b`, Worker `e46c3823`. Both are healthy;66 source fingerprints,
original six Compose files, environment, entrypoints, commands and search
image/config/proxy match their expected receipts. No temporary trace launcher
is active. Reloading the same completed page under normal services displays
the committed answer and official links, with an enabled composer; it sends
no message or model request. Browser timing instrumentation is removed.

Safe traces, selected canonical events, timing JSON, native/static checks,
source receipts and page screenshots remain private under
`.artifacts/quality-publication-date-20261016/`. A1 failure and B1 suspension
are retained. No old Run replay, push, npm publication or remote deployment.
