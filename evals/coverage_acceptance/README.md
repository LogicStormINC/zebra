# Coverage acceptance evidence

The user currently has no independently labeled business corpus. Do not turn
these deliberately small controls, or model-generated labels, into business
accuracy evidence. Processing coverage and semantic correctness are separate.

## Reproduce controlled native Worker load

Provide `ZEBRA_TEST_POSTGRES_DSN` for a disposable scratch PostgreSQL database,
using the installed repository environment and package/app source paths. Run:

```sh
python -m pytest -q -s -o junit_family=legacy \
  --junitxml=evals/coverage_acceptance/worker-admitted-load-rerun.xml \
  tests/worker/test_coverage_acceptance_load.py
```

The existing native fixture creates and removes its own UUID schema. Admission,
handoff, continuation, original proof and certification execute actual Worker
and PostgreSQL code; Host, model and S3 are controlled transports. Each wake uses
a fresh eligible native consumer because the callback fixture has no process
heartbeat. This does not measure a live broker or concurrent Worker processes.
The current same-profile admitted matrix is 1/6/9 records, one part each.
At 1,048,576 context tokens per part, the unchanged 10,000,000-token ceiling
admits at most nine parts. Twelve is separately tested as typed budget refusal
before any model call, not performance GO. Never raise a product limit to pass
this test. Keep previous failed/fixture-error XML files as historical evidence.
`physical_connections` counts opens after fixture setup through certification,
including handoff/execution; `database_queries` separately counts native execute
calls, including transaction timeout/reset statements. Per-recovery verifier
construction must be at most one, not one per accepted batch. Byte reuse remains
preparation-local; final physical tamper/delete tests must refuse, never publish.
Timing excludes fixture setup and includes replacement handoff to certification;
GET counts exclude initial fixture reads. The one-part case profiles cumulative
CPU/I/O calls; its timing is diagnostic, not directly equivalent to unprofiled
larger cases. Hard gates assert exact progress, frozen expected membership,
one certificate and one model call per part. No latency SLO or semantic claim.

## Reproduce isolated component load

Use the repository environment and package source paths. Provide credentials
through environment variables only, never command-line arguments or reports:

- `COVERAGE_LOAD_POSTGRES_DSN`: local disposable PostgreSQL database.
- `COVERAGE_LOAD_S3_ENDPOINT`: local disposable MinIO HTTP endpoint.
- `COVERAGE_LOAD_S3_ACCESS_KEY`, `COVERAGE_LOAD_S3_SECRET_KEY`.

Run `python scripts/coverage_acceptance_load.py --rows 10003 --objects 128`.
It creates one fresh UUID-named schema and one fresh versioned bucket, then
removes only those resources. Do not run against a production database. Local
endpoint validation is a guard, not proof that a local server is disposable.
The report contains no credentials. Failures are errors, not successful timing
samples. Real PostgreSQL/MinIO with synthetic contents proves component behavior,
not signed-Host/Worker/model/browser performance or business accuracy.

The load gates are predefined: exact row/byte equality, smaller Python allocation
peak for paged history, and one physical GET rather than three per object inside
one private proof invocation. Time is reported, not retrospectively turned into
a latency SLO. Python tracemalloc is not process RSS or database/server memory.
Disk-spooled rebuild must still compare exact saved native rows; digest comparison
in this benchmark is measurement-only and never publication authority.

## Score offline semantic outputs

Each label JSONL record needs unique `case_id`, source `text`, and explicit
`expected` (`finding`, `clear`, `unresolved`). Predictions require the same exact
ID set, `outcome`, and explicit `quotes` with Unicode code-point `start`, `end`,
and `text`. A finding requires quotes; a clear result must not contain them.

Example control check, which intentionally fails recall:

```sh
python scripts/coverage_acceptance_semantic.py \
  --labels evals/coverage_acceptance/controls-labels.jsonl \
  --predictions evals/coverage_acceptance/controls-predictions.jsonl \
  --label-source controls --profile controls-no-model \
  --min-precision 0.9 --min-recall 0.9 --max-unknown 0.1
```

Expected exit code: 1; precision 1, recall 0.5, unknown rate 1/3, one missed
finding, exact quote correctness 1. Unresolved findings count as misses, never
successful negatives. Empty, duplicate, missing, extra or malformed records
refuse evaluation. Thresholds must be chosen before evaluating the held-out data.
Exact quotes prove substrings, not their semantic relevance to a finding.

For business acceptance, obtain independently adjudicated representative labels,
freeze corpus/check definition/model profile, capture actual runtime predictions,
then evaluate with `--label-source independent`. This flag and `--profile` are
caller declarations, not verified model provenance. Report sample size, class
distribution, confusion matrix, quote relevance review and uncertainty; approval
remains a human acceptance decision. The script never automatically claims
business accuracy, even if the numeric gates pass. No dataset exists yet.
