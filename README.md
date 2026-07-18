![Zebra Agent](./assets/logo.png)

# Zebra Agent

Zebra Agent is a local-first runtime and desktop workspace for general-purpose
executing agents. It combines durable sessions, typed tools, resumable execution,
deterministic policy, human approval, context compilation, and trace-driven
validation in one modular workspace.

Coding and Git delivery are optional tool domains. The normal desktop flow is
task input, truthful execution evidence, approval or clarification when required,
and durable result review.

## Current Status

The current mainline is a feature-complete local Beta and a single-host production
candidate. It includes:

- durable provider-to-desktop Assistant streaming
- recoverable context compaction and explicit stage Session handoff
- DeepSeek Flash/Pro profiles with fail-closed capability validation
- trusted-local, rootless OCI, and production gVisor runtime classes
- pull-request and `main` quality gates for backend, desktop, and real gVisor

Private-cloud, multi-tenant, ACP, and optional code-intelligence work remains
outside the active implementation scope. Read [PROGRESS.md](./PROGRESS.md) for
the live project snapshot and [docs/AGENT_TASKS.md](./docs/AGENT_TASKS.md) for
task ownership and status.

## Capability Baseline

### Execution and recovery

- durable event store and deterministic projections
- bounded Harness loops with model and tool budgets
- worker leases, cancellation, recovery, suspension, and snapshot restore
- correlated model, tool, approval, clarification, artifact, memory, and trace evidence
- explicit stage Session handoff with authority narrowing and side-effect replay guards

### Runtime, policy, and tools

- typed general and coding tool profiles with independent Policy authority
- bounded local file, command, patch, Git, Web, Skill, MCP, and Research paths
- `trusted-local`, `oci-rootless`, and `gvisor` runtime classes
- production fail-close on missing gVisor, mutable images, authority drift, or
  incompatible snapshots
- default-deny network profiles, approval gates, credential boundaries, and audit

### Model and context

- OpenAI-compatible provider adapter with public Assistant text streaming
- model-aware context-window planning and hard outbound request gates
- deterministic compaction with durable, transparent Context Capsules
- Artifact-backed bounded projection for large tool outputs
- provider continuation with deterministic Capsule fallback
- DeepSeek stable and default-off Beta capability profiles

### Operator surfaces

- CLI, FastAPI, worker, and Tauri/React desktop composition roots
- replay-plus-tail SSE with cursor recovery
- durable approval and clarification continuation
- artifact, diff, audit, memory, commit, and guarded pull-request operations
- context inspection, manual compaction, and stage-handoff controls

## Explicit Boundaries

The current repository does not claim:

- Kubernetes or distributed Sandbox orchestration
- private-cloud or multi-tenant production readiness
- PostgreSQL/object-storage control-plane durability
- centralized production Credential/Egress Broker services
- ACP or optional code-intelligence adapters
- unrestricted browser automation or autonomous production deployment

Production gVisor support is Linux-first. Restore creates a fresh sandbox from
durable state; it is not process-memory checkpointing. Workspace disk hard quota
must be enforced by the production storage layer.

Provider credentials belong only in ignored backend configuration. Never place
them in frontend storage, request payloads, tracked files, responses, or logs.

## Repository Shape

- `apps/`: API, CLI, config, and worker composition roots
- `packages/`: core, context, integrations, observability, runtime, security,
  storage, and tools
- `UI/desktop/`: React, Ant Design X, and Tauri desktop workspace
- `tests/`: deterministic, contract, smoke, and integration coverage
- `evals/`: release and provider evaluation cases
- `docs/`: architecture, governance, acceptance records, and operator runbooks

`agent-core` remains infrastructure-independent. Other packages may depend on
core; packages must not import from applications.

## Local Development

Prerequisites: Python 3.12, `uv`, Node 22.17.0, and pnpm 10.28.2.

```bash
make sync
make test
make check
```

Useful entry points:

```bash
uv run zebra-agent --help
make api-serve
make ui-dev
```

Start local provider configuration from `.env.example` and keep real values in
ignored files.

## Operator Entry

Start with [docs/operator_runbook.md](./docs/operator_runbook.md).

Focused references:

- production Runtime: [docs/生产级Runtime实施方案_v1.0.md](./docs/生产级Runtime实施方案_v1.0.md)
- context lifecycle: [docs/上下文生命周期与混合压缩架构方案_v1.0.md](./docs/上下文生命周期与混合压缩架构方案_v1.0.md)
- stage handoff: [docs/阶段性Session_Handoff与短线程链架构方案_v1.0.md](./docs/阶段性Session_Handoff与短线程链架构方案_v1.0.md)
- DeepSeek profiles: [docs/DeepSeek_V4_模型适配与专项优化方案_v1.0.md](./docs/DeepSeek_V4_模型适配与专项优化方案_v1.0.md)
- CI gates: [docs/主线CI质量门禁说明_v1.0.md](./docs/主线CI质量门禁说明_v1.0.md)
- architecture: [docs/Codex-like工程Agent平台最终架构设计_v1.0.md](./docs/Codex-like工程Agent平台最终架构设计_v1.0.md)

## Governance Entry

| Question | Source of truth |
|---|---|
| What is the product and how do I run it? | `README.md`, operator runbook |
| What is true on the current mainline? | `PROGRESS.md` |
| What task is active, owned, or locked? | `docs/AGENT_TASKS.md` |
| What architecture boundaries apply? | final architecture document |
| What did the original implementation sequence require? | `docs/实施任务拆解与阶段验收.md` |
| Who owns and reviews a change? | RACI reference and the current task card |

Repository precedence and working rules are defined in `AGENTS.md`.
