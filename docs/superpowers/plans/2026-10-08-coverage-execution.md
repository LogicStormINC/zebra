# Coverage execution implementation plan

> **For agentic workers:** Use subagent-driven-development for implementation
> and separate specification/quality reviews. Steps use checkboxes.

**Goal:** Adapt the sealed Trench canonical-body protocol to governed Zebra
Artifacts before implementing deterministic, recoverable exhaustive execution.

**Architecture:** Reuse CoverageSnapshotPort and existing signed Host Tool
invocation. Strict wire validation precedes Artifact publication. Creating a
snapshot is an admitted Effect operation; the adapter never creates a new HTTP
client or replaces the Policy/Effect pipeline. No runtime activation in this
adapter slice; worker composition follows executor and publication guard work.

**Tech stack:** Python 3.12, existing Pydantic contracts, ArtifactPayloadStorePort.

## Chunk 1: Host snapshot adaptation

Files: agent-integrations/coverage_snapshot.py and focused sibling wire/artifact
modules if required to keep each under 300 lines; corresponding focused tests;
docs/COVERAGE_EXECUTION.md. Core contracts remain unchanged.

- [x] Add failing tests against actual Trench descriptor/page/read shapes:
  descriptors lack manifest Artifact refs, pages include provenance/digests,
  reads split UTF-8 bytes using base64. Do not fabricate refs in Host responses.
- [x] Implement CoverageSnapshotPort through an injected admitted Host invocation,
  requiring a frozen manifest, live HostContextEnvelope and exact history resource.
  Check every response status, schema/binding, expiry, scope and digest.
- [x] Enumerate all pages, bounded at 100000 records/32 MiB manifest; reject gaps,
  duplicate IDs/ordinals, cursor loops, extra records and incorrect manifest digest.
  Use canonical coverage_manifest_bytes and store verified session-bound Artifact.
  Reject page sizes above Host's 100; permit shorter positive pages. Verify the
  digest of the complete response excluding only page_digest before projecting
  core fields. Host manifest_digest hashes descriptors/scope; Artifact sha256
  hashes coverage_manifest_bytes: verify both independently, including empty sets.
- [x] Implement get/page without process-only state; resolve/revalidate Host data,
  strip transport fields before extra-forbid core parsing, retain opaque cursors.
  Use deterministic session/snapshot/digest-derived Artifact IDs and readable
  persisted metadata, not an in-memory cache; fresh instances can reconstruct.
- [x] Implement reads with strictly contiguous offsets, canonical base64 and full
  part length/digest checks; bounded body bytes; publish governed body Artifact.
  Body and manifest maximum: 32 MiB each, additionally capped by Host grant.
  A public operation has a configurable call budget (default 2048) and elapsed
  budget (default 60 seconds); check before/after calls and before allocation.
  Every chunk is at most 32768 bytes, next_offset equals offset+received bytes,
  nonterminal chunks are nonempty, and termination matches declared byte length.
  Each read verifies exact record/part membership in the sealed manifest and
  current authority even when its Artifact already exists. No unbounded retries.
- [x] Test refusal on authority change, expiry, malformed types, corrupt bytes,
  scope/namespace mismatch, missing pages, storage corruption and budgets.
  Include short/empty pages, premature termination, large declared bodies,
  cross-session Artifacts, fresh-adapter recovery, and revoked cached reads.
  Create requires admitted write capability and forwards the same Effect
  idempotency key unchanged; lost-response retry cannot manufacture a new key.
- [x] Run focused pytest, Ruff and Mypy; independent spec and quality reviews.
- [x] Record measured evidence; commit explicit paths only. No automatic merge.

Adapter slice verification: 95 focused tests and 168 related tests pass; spec and
quality reviews approve. Ruff, full Mypy, sizes and deterministic eval pass.
Full pytest has 5,044 passes / 939 skips / one inherited runtime-capabilities
assertion failure, independently reproduced at the clean merged base. See
WORKLOG.md. No full-green or integration-readiness claim.
The existing Artifact Port's whole-byte reads, injected process-local publication
lock and O(N²) repeated manifest validation are explicit ceilings recorded in
COVERAGE_EXECUTION.md; they must be resolved before production activation.

Commands run from this isolated worktree:
```sh
PYTHONPATH="$(find apps packages -type d -name src | paste -sd: -):." \
 /Users/lukeding/Desktop/playground/2026/product/zebra-agent/.venv/bin/python \
 -m pytest tests/agent_integrations/test_coverage_snapshot.py -q
/Users/lukeding/Desktop/playground/2026/product/zebra-agent/.venv/bin/ruff \
 check packages/agent-integrations/src/agent_integrations/coverage_snapshot*.py \
 tests/agent_integrations/test_coverage_snapshot*.py
MYPYPATH="$(find apps packages -type d -name src | paste -sd: -)" \
 /Users/lukeding/Desktop/playground/2026/product/zebra-agent/.venv/bin/mypy \
 packages/agent-integrations/src/agent_integrations/coverage_snapshot*.py
```
Expected: all focused tests and changed-module lint/type checks pass. No install.

## Remaining executor boundary

Next slice uses stored manifest membership and indexed missing_units, accepted
batch Artifact/commit receipt, deterministic batch identities and existing lease
fences. It must reuse real storage rather than a process-local checkpoint.
An allowlisted versioned check validates model output before accepting results;
budgets, cancellation, expiry and lost fences stop without certification.
Worker composition paths must be added to registry ownership before editing.
Publication gates, coverage UI and joint deployed acceptance remain separate
tasks. Adapter tests alone do not establish COV-EXEC-01 completion.
