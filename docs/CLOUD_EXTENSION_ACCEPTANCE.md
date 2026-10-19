# Skill, MCP and Plugin functional acceptance

CLOUD-EXTENSION-ACCEPT-01, locally completed 2026-10-20.

The current local Cloud runtime passed both focused no-model checks and one
ordinary Trench page Run. This verifies the configured test combination, not
every possible Skill package, MCP provider or Plugin.

## Actual execution

- Conversation: `conv_1792428159027_cf3074`.
- Task: `f81afa29-cc40-42fd-b759-c9e7ece5b64f`.
- Run: `10234587-9ace-4bea-bbaf-9b45af40d8cb`.
- Host Turn: `559767bd-4548-461a-bbd9-ea39ccc96187`.
- DeepSeek Flash, reasoning `high`, `transient_v2`, tool choice `auto`.
- One submitted Turn, one accepted command, one frozen extension snapshot,
  five model rounds, seven successful tool calls, zero model retries/searches.
- Host status `completed`; committed answer and closed Turn present. The page
  shows the complete result and restores the same answer after refresh. Durable
  Run events/snapshot remain exactly unchanged by that refresh.

| Capability | Evidence from the actual Run |
| --- | --- |
| Skill | `skills.list` exposed the selected Skill; `skills.read` successfully read `SKILL.md` and `references/marker.txt`, returning `CLOUD-PLUGIN-UI-02`. Raw file sizes were 165 and 19 bytes. |
| MCP | Existing ModelScope SSE `fetch` returned actual public example.com content; a second successful call with `raw: true` returned HTML containing `<title>Example Domain</title>`. Both durable results were `executed`, `mcp_is_error=false`. |
| Plugin | Normal admission selected the enabled UI-02 Plugin revision 5. Its frozen snapshot contains both Skill and MCP bindings, one resolved Skill and one resolved MCP. Direct Skill selection is empty, so this Skill reached the Run through the Plugin. |
| Inventory | Current Skill reports available/readable; another installed but unselected Skill reports `not_selected_for_turn` without a read name. MCP reports verified stored catalog, one tool and no unnecessary refresh advice. |

The same MCP is also selected directly by ordinary admission and deduplicated in
the resolved catalog. This Run proves the Plugin's binding is present and the
shared real connection executes; it does not independently isolate Plugin-only
MCP selection. Deterministic Plugin composition/revocation checks cover that
additional boundary. No fabricated response or HTTP interception was used.

Tool sequence: `skills.list` ×1, `skills.read` ×2, `extensions.list` ×2, MCP
`fetch` ×2. The second fetch requested a different representation to obtain the
title missing from the successful simplified response; it was not a failed-call
retry. Skill procedural guidance remained untrusted, and explicit user task
instructions governed the read-only MCP request.

## Measurements and limits

- Send wall time to Host persisted completion: **46.162 seconds**.
- Host Turn creation to persisted completion: **45.334 seconds**.
- Sum of reported provider latencies: **14.118 seconds**, across five rounds.
- MCP execution spans: **17.943 seconds** and **4.194 seconds**.
- Skill list/read spans: 0.645 / 0.740 / 0.313 seconds; the first two overlap.
- The Host generated one separate follow-up suggestions request. It is excluded
  from the five main Run rounds; no additional Run was created.

These are observed spans, not a performance A/B result, final DOM paint time or
first-body latency. The first MCP call is the largest single span, but this test
does not distinguish remote initialization, transport and upstream fetch time.
No additional requests were made to investigate that latency.

## No-model checks and preparation

116 focused tests passed in 3.89 seconds: Cloud Skill reading/wiring, MCP catalog
and lifecycle wiring, Plugin resolution/installations/suspension/composition/
recovery/child authority, normal admission and extension inventory. Those tests
use deterministic doubles for safety cases; real remote execution is established
separately by the page Run above. Existing pilot Skill/Plugin package contents
were also read through their stored snapshot without creating a Run.

One earlier protected MCP catalog refresh returned HTTP 404 because the normal
API's management refresh feature is disabled. It stopped at that error without
remote discovery or retry. Pinned-catalog execution is independent and the actual
MCP calls above succeeded. The refresh flag was neither enabled nor changed.

Only the pre-existing isolated UI-02 Skill/Plugin were temporarily enabled and
bound to the original same-scope real MCP. The normal API temporarily approved
that previously accepted package digest using the same image and configuration.
No credentials were copied, connection created or remote catalog replaced.

## Cleanup and protection

The test Plugin and Skill are disabled again at immutable revisions 6 and 5.
The existing MCP record is exactly unchanged. Fifteen other extension heads are
unchanged; snapshot count increased only by this Run's one snapshot. Global
durable model/tool counter deltas match exactly five model requests/responses and
seven tool starts/completions. Effective leases and pending commands are zero.

The normal API was restored to its exact original image, environment values,
mounts, startup/security/resource configuration and is healthy. Its container
identity and generated Compose metadata changed because it was recreated; these
are not claimed to be byte-identical. Worker, legacy API, Search and Search TLS
container IDs/start times/restart counts are preserved. Original Search process
IDs and persistent Exa cooldown hash are unchanged; transient operator processes
are not mistaken for a service restart. Original MCP/Search processes were not
restarted and no search request was added.

Both protected original partial Turns retain exact status, answer, request and
metadata hashes. No production source, Trench product logic, global proxy,
credentials, high/v2/deduplication behavior or original Run was changed.

Evidence/scripts are in the primary checkout
`.artifacts/cloud-extension-accept-01/`: `result.safe.json`, filtered
`network.safe.json`, `page-completed.png`, private durable Run evidence,
`capture.py` and read-only `verify_result.py`. Raw MCP endpoints and credentials
are excluded from public evidence. Activation/Send helpers are consumed; do not
rerun them. Local documentation integration only; no push or remote deployment.
