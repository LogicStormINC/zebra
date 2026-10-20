# Trench integration baseline archive — 2026-10-20

Task: CLOUD-TRENCH-ARCHIVE-20261020. Human owner: Luke Ding.

## Decision and scope

The user approved closing the Trench-centered optimization/integration phase and
synchronizing its committed baseline to GitHub. cloud-agent-trench becomes a
frozen compatibility baseline; cloud-agent inherits its COMPLETE committed
history for the next generic Cloud Runtime phase. Zebra main is unchanged.
Trench stays a compatibility consumer. This archive does not certify production
capacity, complete Runtime configurability or a working management backend.

This task changes governance documents and Git references only, with no source,
configuration, schema, service, original Run, model/search or remote MCP changes.
The existing untracked Jorice/runtime-platform draft stays unapproved/uncommitted;
all other dirty work and all worktree directories are preserved.

## Frozen identities

| Item | Identity |
|---|---|
| Accepted Zebra source | `06578c09158998a744fc63f1dc7295961fc0faca` |
| Zebra GitHub | `LogicStormINC/zebra` |
| Frozen compatibility branch | `cloud-agent-trench` |
| Next development base | `cloud-agent` |
| Paired Trench committed source | `f25ea8b9b1fb459e575435c5a85545cfda0a3fc7` |
| Trench GitHub / branch | `LogicStormINC/Trench` / `main` |
| Annotated tag in BOTH repositories | `cloud-agent-trench-archive-2026-10-20` |
| Application schema / retained dependency | v105 / v104 |
| TypeScript client-core / react | 0.1.0; exact source/lockfiles in Git |

The Zebra tag targets the documentation-only archive commit descending from the
accepted source; its annotation records paired Trench. The paired Trench tag
points directly to its existing committed source. Supply both repository and tag
identity when restoring the pair. A Git checkout is not a live runtime rollback.
Local service images below are identity evidence, not uploaded image artifacts.

## Running service identities (preserved)

| Service | Local immutable image |
|---|---|
| zebra-application-zebra-worker-1 | `sha256:e179099d4ac805f474eb9eaadf4c055967bfe72d3fe1df14b26e1161d9172ca7` |
| zebra-application-zebra-api-1 | `sha256:f4cc3bb457d685ae5975e5ffa07157885abfecb270a66280dde6ff66c42b4294` |
| zebra-application-zebra-api-legacy-1 | `sha256:e4d5f2739b00c1e6eb842af0e4b181bc851ce9d930b59cbf1ab5cebcc78948dd` |
| zebra-web-search-searxng-1 | `sha256:8509cb58177b275679ca3ca0a34461d90a7a4abfe7224799fa280cc24bf2ef7f` |
| zebra-web-search-search-tls-1 | `sha256:f6a2207268b0f0914df9d3569e1824d6adcfa7b59fbffe0f3cbc5d2d60423f71` |

Private resolved Compose/configuration, credentials, capability URLs, raw data and
local task artifacts are not committed. Search process and MCP session continue;
no service restart, schema migration, model or search query is part of archival.

## Accepted evidence and remaining gates

- One real ordinary-page high/v2 Run read Plugin-mounted Skill main/reference and
  executed remote MCP fetch: five model rounds, seven successful tools, no retry
  or search. Shared MCP was ALSO directly selected, so no Plugin-only isolation
  proof is inferred.
- Latest MCP preparation/timing slice: 414 focused no-model checks passed, one
  environment skip; Ruff/full Mypy/file-size and actual-Worker offline checks pass.
  No real-page speedup is claimed after that Worker update.
- Whole-chain matched-v1 SQL >=80%, multi-executing-Run capacity, STOP/takeover,
  reliable recovery and GC/fleet gates require individual reconciliation before
  production release. Existing local UI evidence does not close all these gates.
- Management UI still reads mock data. Full Runtime configuration and a real
  management backend belong to the next separately claimed phase.

Evidence: [extension acceptance](CLOUD_EXTENSION_ACCEPTANCE.md),
[MCP timings](CLOUD_MCP_PREPARE_TIMING.md),
[stream proof/performance](CLOUD_STREAM_PROOF_PERF_EVIDENCE.md),
[full runtime acceptance](CLOUD_STREAM_RUNTIME_ACCEPTANCE_PLAN.md),
[Runtime boundary](ADR-012_Zebra_Agent_Runtime微服务与外部业务边界.md).

## Branch policy

Fresh fetch found no divergence: Zebra cloud-agent-trench was 55 commits ahead of
origin; cloud-agent was its ancestor, 276 commits behind. Paired Trench main was
22 commits ahead of origin. No open Zebra PRs were present.

Delete only topic refs whose tips are ancestors of the accepted source AND whose
occupied worktrees are clean. Clean occupied worktrees detach at the SAME SHA;
all directories/ignored files/virtualenvs remain. Dirty worktrees and unique
commits are retained, not merged speculatively or declared delivered. The primary
checkout moves to cloud-agent with the same unrelated dirty files.

Synchronize only Zebra cloud-agent/cloud-agent-trench, the two archive tags and
already-committed Trench main. Remove the existing remote settings/media topic
only after its ancestor is reachable from remotely verified integration refs.
No force push, Zebra main integration, Gitee push, repository archival, release
asset upload or deployment. Both repositories stay active for future development.

### Redundant local topic refs eligible for removal

All exact tips below remain reachable from the frozen baseline:

| Topic branch | Tip |
|---|---|
| `codex/cloud-artifact-excerpts-01` | `270e4b8f95f3` |
| `codex/cloud-artifact-locate-01` | `268d3341f1eb` |
| `codex/cloud-b1-batch-boundary-01` | `64bf6100cf6e` |
| `codex/cloud-brave-optional-01` | `445fa13fdc6b` |
| `codex/cloud-client-recovery-04` | `020c85034623` |
| `codex/cloud-close-guard-03` | `fd2dc197189d` |
| `codex/cloud-close-recovery-02` | `41b7c0dd252f` |
| `codex/cloud-exa-cold-01` | `af0ca1b36ba9` |
| `codex/cloud-exa-latency-01` | `fa43cd21adfc` |
| `codex/cloud-exa-live-01` | `f6dec7b2f238` |
| `codex/cloud-exa-optional-01` | `0f0fae79c730` |
| `codex/cloud-exa-pair-02` | `1cd207d87a30` |
| `codex/cloud-explain-contract-01` | `ac7e6d6844b0` |
| `codex/cloud-extension-accept-01` | `7c8f769d0656` |
| `codex/cloud-extension-inventory-01` | `79dc9e188586` |
| `codex/cloud-keyless-provider-02` | `620ee18549cc` |
| `codex/cloud-keyless-recall-01` | `8dd4aac1bd2a` |
| `codex/cloud-mcp-prepare-timing-01` | `06578c091589` |
| `codex/cloud-paused-verifier-01` | `93f4b40743cc` |
| `codex/cloud-plugin-accept-01` | `b1d082b33268` |
| `codex/cloud-plugin-con-01` | `a0e1c3357df8` |
| `codex/cloud-plugin-e2e-01` | `46c9fc150d2a` |
| `codex/cloud-plugin-live-01` | `a5440b136f00` |
| `codex/cloud-plugin-normal-01` | `649712380610` |
| `codex/cloud-plugin-page-01` | `ba877a6e9a53` |
| `codex/cloud-plugin-plan-01` | `1d16073571bc` |
| `codex/cloud-plugin-run-01` | `ed450dab9e45` |
| `codex/cloud-plugin-store-01` | `51bd8d5825df` |
| `codex/cloud-plugin-ui-01` | `917df214cd68` |
| `codex/cloud-plugin-ui-02` | `5012d6b0ba9d` |
| `codex/cloud-recovery-verification-03` | `1cd4aef7abdb` |
| `codex/cloud-research-web-01` | `3f221bb344e3` |
| `codex/cloud-search-alternatives-01` | `99247cb8a457` |
| `codex/cloud-search-candidates-01` | `4f5b770dd6c3` |
| `codex/cloud-searxng-config-01` | `ad18a0c07afc` |
| `codex/cloud-searxng-page-01` | `0fc2651ff44e` |
| `codex/cloud-skill-runtime-01` | `fca31ada3c28` |
| `codex/cloud-snapshot-context-01` | `0ec59db7b957` |
| `codex/cloud-stream-contract-01` | `d8e856140683` |
| `codex/cloud-stream-read-bounds-01` | `3a3e59024635` |
| `codex/cloud-stream-writer-01` | `0d49f0b07ef8` |
| `codex/cloud-turn-close-01` | `6a1e116e25c1` |
| `codex/cloud-verification-defaults-01` | `62209ede1207` |
| `codex/trench-settings-media-01` | `b11334f2a39b` |
| `codex/trn-composer-suggestions-01` | `2a6966beb12a` |

### Retained local topic refs

| Topic branch | Tip | Reason |
|---|---|---|
| `codex/cloud-array-source-replay-01` | `b4e22127faf4` | unique committed history |
| `codex/cloud-b1-decision-profile-01` | `fa70133aa3af` | occupied worktree has local changes/artifacts |
| `codex/cloud-citation-delimiter-01` | `a9d7cfcf99fc` | unique committed history |
| `codex/cloud-evidence-use-01` | `2a17a30201db` | unique committed history |
| `codex/cloud-native-scope-01` | `e19c72054d70` | unique committed history |
| `codex/cloud-search-decision-01` | `cba442096889` | unique committed history |
| `codex/cloud-search-evidence-roundtrip-01` | `e206e26560d9` | occupied worktree has local changes/artifacts |
| `codex/cloud-skipped-waiting-02` | `02b3ea29489f` | occupied worktree has local changes/artifacts |
| `codex/cloud-source-decision-check-01` | `0824044c12f4` | unique committed history |
| `codex/cloud-source-provenance-audit-01` | `24eb69c171bd` | unique committed history |
| `codex/cloud-source-replay-01` | `f14afefab375` | unique committed history |
| `codex/cloud-source-replay-diverse-01` | `876b7d8b03cb` | unique committed history |
| `codex/cloud-stream-admission-01` | `ffe8f38ba69f` | occupied worktree has local changes/artifacts |
| `codex/cloud-stream-baseline-01` | `f16d8324f592` | occupied worktree has local changes/artifacts |
| `codex/cloud-stream-capacity-01` | `dd66539abdff` | occupied worktree has local changes/artifacts |
| `codex/cloud-stream-client-01` | `249f4e6de22c` | occupied worktree has local changes/artifacts |
| `codex/cloud-stream-control-01` | `0d374048b0b0` | unique committed history |
| `codex/cloud-stream-proof-perf-01` | `0f8c1716936d` | occupied worktree has local changes/artifacts |
| `codex/cloud-stream-read-01` | `4a79a2701295` | occupied worktree has local changes/artifacts |
| `codex/cloud-stream-relay-01` | `6bea341dd6a7` | occupied worktree has local changes/artifacts |
| `codex/cloud-stream-storage-spec` | `d836b04cef7d` | occupied worktree has local changes/artifacts |
| `codex/cloud-version-scope-01` | `a5f031c14bd3` | occupied worktree has local changes/artifacts |
| `codex/cloud-version-state-01` | `badd6a204b91` | occupied worktree has local changes/artifacts |
| `codex/cloud-web-input-dns-repair` | `91ed10d8e628` | unique committed history |
| `codex/trench-exhaustive-admission-01` | `bcdc9f6dd2e2` | occupied worktree has local changes/artifacts |

Detached historical worktrees with local changes are retained too. Full initial
inventory and preservation hashes stay local under
`.artifacts/cloud-trench-archive-20261020/`.

## Verification and handoff

Check docs-only diff, inherited source trees, ancestry and protected dirty/service
identities before freezing. After push, compare local refs and peeled annotated
tags with git ls-remote, remove only redundant refs, then record final receipt on
cloud-agent. Archive docs/ref checks are fresh; earlier runtime gates remain
historical evidence. No new model/search or production fault/performance suite.

Next implementation starts from inherited cloud-agent through a separately
claimed task. Trench compatibility remains a regression target. Management must
use public contracts and cannot create a second execution-fact authority or sit
on the model/tool synchronous execution path.
