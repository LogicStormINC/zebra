# Client release and admission closure

Owner: Luke Ding. Task: CLIENT-RELEASE-CLOSURE-01.
Branches: Zebra `cloud-agent-trench`, paired Trench `main`.
Date: 2026-10-02. Local implementation and release verification; runtime
activation of the final worker fix remains user-operated.

## Root causes and minimal repairs

1. Trench changed an action description without increasing the frontend
   profile revision. The configured revision/digest no longer matched code.
   A task was created before that local check, then failed as generic unavailable.
2. An optional frontend mount could disable an otherwise valid backend query.
3. A real read-only query containing `不修改订阅` was inferred as a change task.
   All eight executed tools were read-only, with mutation epoch zero; nevertheless
   the acceptance contract required mutation verification and paused the answer.
4. AG-UI used mutation-specific copy for every verification-required pause,
   even when no mutation existed.

Trench now pins revision 3 and a complete immutable release manifest. Admission
checks local configuration before task creation. Optional capability mismatches
clear client state/tools, emit a durable availability warning and continue with
backend tools. Explicitly required client integration fails before submission.
Authentication, authority, fencing, turn ownership and storage failures still
fail closed; uncertain commands/writes are never automatically resubmitted.

Core task inference excludes bounded negated action phrases, without removing
positive actions elsewhere in the request. Explicit acceptance contracts remain
authoritative; actual writes still require fresh verification. AG-UI distinguishes
unverified mutations from other unmet verification requirements.

## Durable configuration

Paired Trench files:

- `services/api/src/trench_api/trench_ai_client_profile.py`: canonical profile.
- `configs/trench-client-release.json`: complete pinned deployment artifact.
- `.env`: actual local deployment revision/digest; secrets are not in this doc.
- `.env.example`: documented non-secret release settings.

Current release:

```text
ZEBRA_CLIENT_PROFILE_REVISION=3
ZEBRA_CLIENT_PROFILE_DIGEST=80119aee72270eabdc3ef4099f274845130ff734b794860df1f5203592bdb566
```

Do not edit action descriptions, schemas or risks under a published revision.
Increase the revision, generate the matching manifest, validate it, publish it
and verify the namespace binding before enabling the matching host deployment.
Retain the previous release artifact and deployment configuration for rollback.

## Release gate

In Trench:

```sh
PYTHONPATH=packages/models/src:packages/core/src:services/api/src \
  pdm run python -m trench_api.trench_ai_client_profile --check-config
```

In Zebra, with the existing operator credential supplied securely through
`ZEBRA_PLATFORM_OPERATOR_TOKEN` (never echoed or added to shell history):

```sh
uv run python scripts/publish_client_profile.py \
  --base-url http://127.0.0.1:18080 --host-app-id trench \
  --namespace-id trench-prod \
  --profile ../Trench/configs/trench-client-release.json --verify-only
```

`--check-only` is offline validation, not proof of publication.
`--verify-only` performs only GETs and rejects a missing release, changed digest,
inactive lifecycle or mismatched binding. Publication without that flag creates
new profile versions using the versions endpoint, updates the binding with CAS,
then reads it back. Never infer a namespace from a product name: this installation
uses `trench-prod`, not `trench`.

Rollback uses the retained previous manifest plus matching Trench configuration;
switch the binding via CAS and re-run verification. Do not delete release
history or rewrite an existing revision. This turn did not execute rollback.

## Health and degradation contract

`GET /api/health/ready` checks DB/Redis and local runtime settings. It reports
`capabilities.client_integration` and `verification=local_configuration_only`.
It deliberately does not claim remote profile publication or end-to-end health.
The operator release gate above establishes remote profile/binding evidence;
authenticated browser execution establishes the joint runtime boundary.

`client_integration_required` is persisted with each Turn. A degraded Turn
does not mount/retry the browser client bridge. Its warning is rendered alongside
the answer and replayed through existing Turn metadata. No UI state or frontend
tools are forwarded if no trusted client surface has been established.

## Evidence and remaining acceptance

### Restart replay and contract follow-up

User-operated activation was verified against the image IDs below. Exact query
replay still paused after 11 successful reads because Trench sent `taskType=change`
and `requireVerification=true` for `不修改订阅`. The redundant Host keyword
classifier is now removed: the Host sends a partial contract containing the
current goal and, when required, positive evidence/citation constraints only.
It does not override task type, outcomes, verification or artifact requirements.

Live replay verified the new partial contract was accepted in session
`d274e269-5f6d-464c-a236-7da76184b9e5`, but still paused: the fallback user input
included appended conversation history containing publication language. Core
`parse_task_contract` now infers defaults from the explicit bounded contract goal,
not the history-bearing fallback. Missing goals still use the fallback; explicit
Host fields remain authoritative. Regression checks cover read-only negation,
information-only requests, actual writes, publication, creation and history
contamination. No verification gate, authority or historical event was weakened
or rewritten. This second live replay is failure evidence, not completed acceptance.

Follow-up validation: Trench contract/runtime 57 passed; admission/progress/store/
health 59 passed; core regression 16 passed; Zebra `make check` passed, including
30 deterministic evals; quality-gate/core tests 40 passed and worker recovery
tests 11 passed. Actual Trench serializer output was piped into Zebra parsing:
read-only remained research/no verification, positive changes retained verification,
even with publication language in the fallback history.
API/worker builds completed with IDs
`f79b71f0d8430029a5f05fac2f4a4b27e31f7865ac0743ec315adf07a051f452` /
`bd3530b3ad6696093ed0f479537d863490b491b61db31c8b43d38b5190650afc`.
New image activation and exact-wording live replay remain pending.
Restarts remain user-operated; no commit/push is claimed.

- Trench focused backend suite: 123 passed, including local/remote optional
  failure, exact errors, authority non-degradation, Turn replay and progress.
- Frontend focused suite: 25 passed; production build passed.
- Zebra focused core/projection/release suite: 56 passed.
- Zebra `make check`: passed (size gate, Ruff, mypy, deterministic evals).
- Remote release revision 3 was published and bound, then `--verify-only` passed
  against the actual `trench/trench-prod/trench-web` binding revision 3.
- Live browser conversation `conv_1790936113592_1920ec`: latest read-only query
  completed with six successful tools, four durable public updates, Markdown
  tables, source names and an actual collected source URL. Turn:
  `305785cc-f7ad-47f1-9a75-e125bcb55822`. Refresh preserved earlier updates.
- Earlier query with negated action paused as `verification_required`; its
  history was retained, not rewritten. The regression is fixed locally, but
  replay of that exact wording requires activation of the rebuilt worker.
- Browser screenshot: `.artifacts/client-release-acceptance.png`.
- Docker API/worker images built; existing containers were not restarted.
- No new video/image playback acceptance was claimed by this text-query test.
- Full Zebra `make test`: 4896 passed, 913 skipped in 145.44 seconds;
  skipped live/dependency-specific tests are not production acceptance.
- Final image IDs: API `c4ce05317d873d2a55b78ed246517610789e903f8e04b457ce3423d819f1c7a5`,
  worker `95ccab63d69727f8084132c70e788d8fd2cf0dd4a785bde4072eeb8c6e7624ac`.

User-operated activation (no migration/data reset required by this slice):

```sh
docker compose --env-file docker/trench-acceptance.env \
  -f docker/compose.application.yml \
  up -d --no-build --force-recreate --wait zebra-api zebra-worker
```

Trench API changes hot-reload in the current development process. A stable API
or production frontend needs its normal user-operated restart. After activation,
repeat the negated-action read-only request, confirm terminal completion, refresh
to confirm four-update-style replay, and separately test an actual authorized
mutation to confirm the write-verification gate remains enforced. This is not
yet an unconditional 100-percent production acceptance claim.
