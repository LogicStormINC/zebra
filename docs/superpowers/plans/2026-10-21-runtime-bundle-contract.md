# Runtime Bundle contract implementation plan

> For agentic workers: REQUIRED subagent-driven-development. Delegate core models/validator/tests to one fresh implementer; root owns CLI/golden artifacts/legacy checks/docs/evidence. Spec review then fresh quality/security review; no concurrent implementation agents.

**Goal:** publish runnable native versioned Bundle validation/compatibility while old execution/history stays unchanged.
**Architecture:** immutable Pydantic domain values plus pure bounded parser/compatibility, generated schema/catalog and stdlib local CLI; no DB/network/Worker/HTTP composition.
**Tech stack:** Python3.12+, existing Pydantic2/pytest/uv; no new dependencies.
**Approved design:** [spec](../specs/2026-10-21-runtime-bundle-contract-design.md); user delegated routine decisions and explicitly authorized scoped implementation/push, no deployment/migration.

## Chunk1: native domain models and validator (delegated)

Files: new packages/agent-core/src/agent_core/domain/runtime_bundle_types.py (frozen primitives/assets/scope/parameters/bindings), runtime_bundle_catalog.py (20native descriptors/source refs/schema hashes), runtime_bundle.py (manifest/envelope/closure/parser/canonical/compatibility); tests/agent_core/test_runtime_bundle.py and test_runtime_bundle_validation.py. Split a focused runtime_bundle_*.py before500lines only if required; tests<700. Do not modify __init__, old models, storage, apps or dependencies.

- [x] Write a smallest failing import/parse test before implementation; run uv run pytest -q tests/agent_core/test_runtime_bundle.py and retain RED.
- [x] Implement ArtifactPin,EngineBinding,BundleScope,ModelParameters,InstructionsParameters,PinnedDomain,ModelDomain,InstructionsDomain,RuntimeDomains,ResolvedRuntimeBundle,RuntimeBundleEnvelope. Every public field required, primitives strict, tuples/frozen models. Constant schemas cloud-agent.bundle-envelope/1,cloud-agent.runtime-bundle/1,cloud-agent.bundle/1; script ABI unsupported. Asset kind/id/version/digest exact; source refs must exist.
- [x] Expose runtime_bundle_catalog() returning a fresh JSON descriptor, runtime_bundle_catalog_digest(), builtin_component_pin(domain), canonical_runtime_bundle_bytes(manifest), seal_runtime_bundle(manifest), parse_runtime_bundle(raw:bytes), runtime_bundle_json_schema(), require_bundle_compatibility(envelope, *, supported_bundle_abis:frozenset[str], supported_component_digests:frozenset[str])->None. Exact names stable for root CLI/artifacts. Catalog descriptors bind param schemas, domain/mode/reason and source references, digest over deterministic canonical JSON excluding own digest.
- [x] Strict model/instruction parameters and all20exact domain bindings; other18pinned/no params. Artifact lock sorted/unique/exact closure of20components+image+baseline+modelprovider+outputschema+build evidence. One component pin per domain; catalog/component mismatch rejects.
- [x] Bounded raw256KiB/depth24/nodes8192, duplicate/nonfinite/float/bool-as-int/invalidUTF8/BOM/lone-surrogate checks; canonical ASCII sorted JSON no whitespace (not JCS), integer ranges. Seal/parse revalidate nested input; no echo private input in parser errors. Compatibility checks reader ABI and all20component digests, no version guess. No code execution/resolution.
- [x] Tests meaningful positives/negatives: helper valid_payload() returns JSON envelope dict for golden generation (build fully declared payload using catalog/seal). Include closure duplicate/missing/extra/conflict, all20required, unknown/altered metadata/schema/params, model bounds/instruction Unicode/text, raw limits, mutation immutability, changed contents/digest, reader mismatch. uv run pytest focused; uv run ruff check only owned files; uv run mypy packages/agent-core. Report exact results/paths; no commit until root scoped delivery.

## Chunk2: offline public CLI and stable artifacts (root)

Files: scripts/validate_runtime_bundle.py; tests/test_validate_runtime_bundle.py; tests/agent_core/test_runtime_bundle_compatibility.py; tests/fixtures/runtime_bundle_v1/; docs/contracts/runtime-bundle-v1/.

- [x] Implement argparse exclusive --input PATH/--schema/--catalog. Bounded regular-file read via O_NONBLOCK/fstat; JSON output only, invalid input gives fixed error INVALID_BUNDLE/exit2 with no raw detail. No remote/DB/env credentials reads. Success includes contract_version,bundle_digest,catalog_digest,validation_only=true,execution_supported=false. --schema and --catalog stdout equal generated artifacts; CLI uses current local pinned validation capabilities only.
- [x] Generate envelope.schema.json,component-catalog.json,example-envelope.json,manifest.canonical.json and digest-vectors.json from final native API. Include nonASCII/control escapes and integer edge, object reorder/whitespace no digest change. Capture immutable existing Definition/Snapshotv1 JSON plus legacy definition/snapshot digest bytes using baseline6dbb2a8d; never regenerate these from changed legacy logic.
- [x] Add tests matching generated schemas/catalog/positive goldens/canonical bytes/digest and drift sensitivity; CLI subprocess positive/negative/missingfile/directory/FIFO/oversize/secret-redaction and schema/catalog. Legacy v1 roundtrip/hash vectors, old/new reject each other, v1 algorithm/source unchanged. Run targeted suite then independent implementation spec review, then quality/security review.

## Chunk3: final gates, documentation and delivery (root)

Files: docs/RUNTIME_BUNDLE.md,RUNTIME_MANAGEMENT.md(scope/link only),README.md(entry),task registry,PROGRESS.md,WORKLOG.md,task_plan.md,this plan/spec,docs/evidence/ca-p2-01a/.

- [x] Document actual API/CLI, canonical exact bytes/number/string rules,20source-bound domains and pinned limits, native versus P0adapter distinction, compatibility matrix/reader rules and explicit no execution/HTTP/asset proof. Mark native descriptor unchanged unsupported; list CA-P2-01B exits without starting it.
- [x] Run uv run pytest -q tests/agent_core/test_runtime_bundle*.py tests/test_validate_runtime_bundle.py and existing Definition/Snapshot/Coverage compatibility suites. Run make test and make check (allow own temporary test resources only); no existing DSN/service operations. Record failures/fixes/skips separately.
- [x] Check source/contract/golden hashes, exact generated files and baseline legacy source unchanged, file limits/links/diff/secret signatures, original cloud-agent dirty work and P1fixedworktree unchanged. Update Review/actual results/progress/evidence.
- [x] Explicit-path normal commits, normal feature push origin codex/ca-p2-01a-bundle-contract, remoteSHA confirmed separately; no main/cloud-agent integration or branch cleanup, deploy or production migration.

Final: focused163pass/zero skip; preserved82pass/1PGskip; make test10620pass/3007skip (r2), make check30/30eval. Initial full run deliberately SIGINT-stopped to strengthen semantic negatives; it is not acceptance. Source freeze27files matches final gates; actual source/remote SHA confirmed separately at delivery.
