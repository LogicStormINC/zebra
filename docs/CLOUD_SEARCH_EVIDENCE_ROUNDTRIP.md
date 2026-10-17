# Cloud search evidence round-trip optimization

## Scope and measured cause

CLOUD-SEARCH-EVIDENCE-ROUNDTRIP-01, base d3dda323. Generic Cloud Agent only; no Trench product logic. Preserve fresh authorization, high thinking, transient_v2, autonomous tool selection and v103 function-scoped PostgreSQL plan reuse.

Previous B2 (conversation conv_1792214937987_288213) used five execution model responses and seven successful tools, one candidate, no provider retries. First body22.121s, total25.099s. Initial Redis search did not return the GA announcement. Fetching its generic release landing returned1,559,266 decoded HTML bytes, mostly navigation, without the required historical date. Two subsequent parallel query paraphrases both ranked the same exact official GA announcement first. Final announcement fetch was necessary evidence; it was not a duplicate fetch. PostgreSQL was searched and fetched once.

The existing execution guidance already preferred primary sources but left candidate suitability and same-gap query scheduling implicit. This is an observed decision gap, not proof that every extra search is redundant or a transport retry bug. Parallel query overlap alone does not prove all lower-ranked results interchangeable.

## Minimal implementation

Refine existing AGENT_EXECUTION_GUIDANCE in model_step_support.py: source/event-specific queries; assess candidate title/snippet against missing historical facts; prefer a version-matching dated announcement; refine search before fetching a generic landing that does not address that fact; parallelize independent evidence gaps and inspect results before paraphrasing one gap unless distinct coverage is required. Existing completeness/conflict/exact-URL/private-reasoning rules remain. No runtime cap, forced engine, hardcoded source, query rewriting, cross-task cache or dependency.

A standalone no-network/no-model check exercises actual HarnessModelStep.build_initial_messages with default and host identities, confirming guidance is wired once and safety/completeness instructions retained. This is a composition regression only; it cannot prove model decisions or latency.

## Acceptance protocol

Freeze source before four real page Runs A1/B1/B2/A2, same official PostgreSQL18/Redis8 prompt, DeepSeek Flash/high, transient_v2. Same observers and six startup requests, fresh grant/authority each time. Exactly one execute=false readiness Task before each sample, zero model execution. Only Worker guidance differs. API pool, schema103 function settings, Search service, environment and original composition stay identical. Retain every outcome; no favorable extra Run. Capture actual committed-body DOM prefix latency, whole turn, API+Worker driver/nonempty SQL, model stage/count, tools and quality. Restore normal original API and candidate Worker, verify source hashes and authenticated completed page.

## Results

Fixed cohort, all completed, Flash/high/transient_v2, 12 execution model responses (retry0),16 successful tools,0 failed tools, one candidate/quality pass each. Every Run used two searches then two exact observed official announcement fetches; no generic landing fetch or parallel same-gap paraphrases occurred in either variant. Old B2 was not reproduced even by controls, so5→3 model /7→4 tool comparisons to that historical outlier are NOT a causal gain estimate.

| Sample | First committed-body prefix seen (s) | Whole turn (s) | Nonempty driver SQL | Models | Tools |
| --- | ---: | ---: | ---: | ---: | ---: |
| A1 |15.6510|19.222|3279|3|4|
| B1 |13.9495|17.332|3177|3|4|
| B2 |15.1536|19.246|3231|3|4|
| A2 |12.0065|14.949|3190|3|4|
| A mean |13.8288|17.0855|3234.5|3|4|
| B mean |14.5516|18.2890|3204|3|4|

No stable page speedup or model/tool reduction proven. Body+0.723s(+5.2%), whole+1.204s(+7.0%); SQL−30.5(−0.94%) is not a structural reduction. These are two samples per variant, not a p95/statistical guarantee. SQL is API request scopes plus Worker scopes, excluding empty driver transaction checks; trigger-internal statements are not counted as additional driver calls. Variable background projection/polling work remains in the measurement.

B click→first provider2.632s vs A1.982s(+0.650s); this precedes the changed model guidance being acted on and cannot be attributed to its semantics. Total model latency A7.237s/B8.052s; final candidate A3.598–5.423s/B5.383–5.554s. Search calls1.35–3.00s and fetches1.31–3.49s varied; paired batch critical-path maxima roughly A5.093s/B4.826s. These explain the sample variation without an extra model round. No tuning of unrelated startup/Trench/provider behavior is added to this slice.

Old B2 tool-path timings: initial search batch2.37s, fetch batch4.60s, recovery searches1.61s, final GA fetch1.36s; model responses0.969/1.332/1.664/1.095/4.434s. The two extra tool-loop model responses total2.759s. The4.60s broad fetch must not all be called removable latency: necessary PostgreSQL fetch ran concurrently and took4.517s. Similarly the two paraphrase searches ran concurrently, so removing one is not equivalent to subtracting both wall times. A better initial candidate can collapse dependent recovery rounds, but this cohort did not isolate its causal saving.

## Validation and local runtime

- Standalone composition check red on baseline missing targeted-search guidance, green after change; both default/host identities exercised; actual restored normal Worker ran the same no-model check successfully. This verifies wiring, not model obedience.
- Existing focused core autonomy/model-step tests12passed. Default clean tracked-source `make check` passed. No full-suite claim or unrelated fixture repair.
- Four readiness HTTP201 controls and one restored-normal HTTP201 control all have0 accepted commands/0 model requests, verified from canonical events. No fifth model Run.
- Every page Task keeps67 nonempty admission SQL +7 empty driver checks and6 fresh authority SQL. Startup remains6 Cloud requests /156 nonempty +13 empty SQL; Worker pre-provider448 executes including33 empty,5 TaskIO opens. No authorization bypass/cache or admission/SQL rewrite.
- Both variants retain schema103, both projection functions `plan_cache_mode=force_generic_plan`; global config/trigger bodies/migration logic unchanged.
- Restore normal original API eb4f695b / candidate Worker2a4b0ace / Search245b675f. Original six Compose files, env hashes, commands, entrypoints, healthy/0 restarts and109 accepted source hashes verified. Only Worker model_step_support.py hash changes. Diagnostic launchers/DOM listeners/loopback receiver removed; original B2 result visible after authenticated read-only reload, high retained, screenshot saved.
- Local staged integration into cloud-agent-trench is authorized; preserve27 unrelated dirty entries, no push/npm/remote deployment. Detailed private evidence under `.artifacts/cloud-search-evidence-roundtrip-20261017/`.

## Remaining boundary

This is a minimal general guidance improvement with successful live compatibility checks. It does not guarantee prevention of all same-gap searches, remove necessary evidence collection or prove lower first-body latency. Broader SQL reduction, long-run p95, provider/network variation and unrelated performance milestones remain open. Stronger runtime deduplication is deliberately not introduced: paraphrased searches can provide distinct evidence, and forcibly suppressing them would change the agent's tool authority/behavior beyond this measured fix.
