![Zebra Agent](./assets/logo.png)

# Zebra Agent

Zebra Agent is an embeddable, local-first Agent Runtime microservice with an
optional desktop operator surface. It turns Agent requests into durable,
streamable, stoppable, resumable, and auditable execution while remaining
independent of the business system that calls it.

Zebra owns Task, Conversation, Session, Model, Context, Tool, Agent Memory,
Artifact, Worker, Sandbox, streaming, concurrency, and recovery. It does not own
user registration, organizations, memberships, business RBAC, subscriptions, or
billing. Authentication is external; the selected default is Authelia through
OIDC. The calling business system supplies signed Agent authority, an opaque
namespace for isolation, and technical execution limits.

Coding and Git delivery are optional tool domains. The normal desktop flow is
task input, truthful execution evidence, approval or clarification when required,
and durable result review.

## Product Boundary

```text
Authelia / external identity
             │ OIDC
             ▼
Business system / API gateway
  users · organizations · membership · business authorization · billing
             │ signed Agent authority + opaque namespace
             ▼
Zebra Agent Runtime
  task · conversation · session · model · tool · memory · artifact
  stream · worker · sandbox · concurrency · HA · recovery · usage evidence
```

Zebra validates the external authority and enforces Agent-specific Policy,
Approval, Sandbox, namespace isolation, and technical limits. It never expands
the caller's authority and does not query or duplicate the caller's user,
membership, subscription, or billing database.

Business quota and Zebra execution limits are distinct. The business system
decides entitlements; Zebra enforces supplied ceilings such as concurrent tasks,
model tokens, runtime seconds, CPU, memory, disk, and network. Zebra emits usage
and audit evidence for external capacity or billing systems but never calculates
prices or invoices.

## Current Status

The current mainline is a feature-complete local Beta and a single-host production
candidate. It includes:

- durable provider-to-desktop Assistant streaming
- stable Task identity with recoverable context compaction and automatic,
  backend-internal execution segmentation
- DeepSeek Flash/Pro profiles with fail-closed capability validation
- trusted-local, rootless OCI, and production gVisor runtime classes
- pull-request and `main` quality gates for backend, desktop, and real gVisor

Private-cloud deployment, external-namespace isolation, ACP, and optional
code-intelligence work remains outside the active implementation scope. Cloud
deployment does not change the product boundary above. The Zebra Embedded / Trench
production target is now being consolidated as a documentation-only architecture
task: Trench owns CopilotKit React v2 and its Runtime/BFF, while Zebra exposes an
AG-UI adapter and retains durable Task/Event/Policy authority. This does not
activate cloud or Trench implementation. Read
[PROGRESS.md](./PROGRESS.md) for the live project snapshot and
[docs/AGENT_TASKS.md](./docs/AGENT_TASKS.md) for task ownership and status. The
adaptive execution boundary is specified in
[docs/自适应Agent循环与预算治理方案_v1.0.md](./docs/自适应Agent循环与预算治理方案_v1.0.md).

## Capability Baseline

### Execution and recovery

- durable event store and deterministic projections
- adaptive Harness loops: model/tool call counts are unlimited by default while
  caller-supplied hard ceilings remain available as explicit execution contracts
- progress-preserving budget handling: an oversized hard-budget batch starts
  nothing and suspends recoverably instead of partially executing or failing
- model-native Subagent selection: direct answers and parent tools stay local;
  only an explicit valid bounded research call creates a non-recursive child
- recoverable tool failures return structured evidence to the model so it can
  correct the call, choose an alternative, or answer within remaining budgets
- worker leases, cancellation, recovery, suspension, and snapshot restore
- correlated model, tool, approval, clarification, artifact, memory, and trace evidence
- backend-internal handoff safety contracts with authority narrowing and side-effect replay guards
- stable Task projection, cross-Segment event cursor, and active-Segment command routing
- bounded prior user/Assistant checkpoints for context-correct terminal follow-ups

### Runtime, policy, and tools

- typed general and coding tool profiles with independent Policy authority
- bounded local file, command, patch, Git, Web, Skill, MCP, and Research paths
- `trusted-local`, `oci-rootless`, and `gvisor` runtime classes
- production fail-close on missing gVisor, mutable images, authority drift, or
  incompatible snapshots
- core and non-local deployments default-deny network access; explicit
  `local + trusted-local` mode gives Desktop/API/CLI/Worker one operator trust
  boundary, including automatic upgrade of existing Tasks without approval popups
- bounded HTTPS/URL/redirect/size controls; direct connections retain public-DNS
  checks, while trusted local execution honors the operator's system HTTPS proxy
- non-local MCP and side-effecting operations retain approval gates; trusted local
  still enforces workspace paths, tool schemas, runtime boundaries, and audit

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
- real-Chromium regression coverage for long streaming, reload recovery,
  cancellation, and completed-Task follow-up across an invisible Segment
- durable approval and clarification continuation
- artifact, diff, audit, memory, commit, and guarded pull-request operations
- context inspection and manual compaction; internal execution boundaries are not user controls

## Explicit Boundaries

The current repository does not claim:

- Kubernetes or distributed Sandbox orchestration
- private-cloud or multi-tenant production readiness
- PostgreSQL/object-storage control-plane durability
- centralized production Credential/Egress Broker services
- ACP or optional code-intelligence adapters
- unrestricted browser automation or autonomous production deployment

The following are external business responsibilities, not deferred Zebra
features: registration/login UI, user and organization directories, membership
and invitations, business RBAC, subscriptions, plans, billing, and invoices.

Production gVisor support is Linux-first. Restore creates a fresh sandbox from
durable state; it is not process-memory checkpointing. Workspace disk hard quota
must be enforced by the production storage layer.

Provider credentials belong only in ignored backend configuration. Never place
them in frontend storage, request payloads, tracked files, responses, or logs.

## Repository Shape

- `apps/`: API, CLI, config, and worker composition roots
- `packages/`: core, context, integrations, observability, runtime, security,
  storage, and tools
- `UI/desktop/`: React, Ant Design X, Lobe UI, and Tauri desktop workspace
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

Run the real browser streaming gate after `make sync`:

```bash
cd UI/desktop
pnpm exec playwright install chromium
pnpm e2e
```

The gate starts the live Vite Desktop, FastAPI, Worker path, and an isolated
SQLite event store. Only the external model endpoint is replaced by a local,
deterministic OpenAI-compatible streaming provider.

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

- service boundary: [docs/ADR-012_Zebra_Agent_Runtime微服务与外部业务边界.md](./docs/ADR-012_Zebra_Agent_Runtime微服务与外部业务边界.md)
- Embedded target: [docs/Zebra Embedded 生产级目标架构.md](./docs/Zebra%20Embedded%20生产级目标架构.md)
- CopilotKit/AG-UI boundary: [docs/ADR-015_Zebra_Embedded与CopilotKit_AGUI边界.md](./docs/ADR-015_Zebra_Embedded与CopilotKit_AGUI边界.md)
- Embedded task roadmap: [docs/Zebra Embedded与Trench实施任务拆解_v1.0.md](./docs/Zebra%20Embedded与Trench实施任务拆解_v1.0.md)
- production Runtime: [docs/生产级Runtime实施方案_v1.0.md](./docs/生产级Runtime实施方案_v1.0.md)
- context lifecycle: [docs/上下文生命周期与混合压缩架构方案_v1.0.md](./docs/上下文生命周期与混合压缩架构方案_v1.0.md)
- context continuity and governed memory v1.1: [docs/上下文连续性与治理记忆改进方案_v1.1.md](./docs/上下文连续性与治理记忆改进方案_v1.1.md)
- Task continuity and internal Segments: [docs/ADR-013_用户任务连续性与内部执行分段.md](./docs/ADR-013_用户任务连续性与内部执行分段.md)
- automatic rollover roadmap: [docs/透明Context_Segment与自动Rollover实施方案_v1.0.md](./docs/透明Context_Segment与自动Rollover实施方案_v1.0.md)
- historical handoff safety contract: [docs/阶段性Session_Handoff与短线程链架构方案_v1.0.md](./docs/阶段性Session_Handoff与短线程链架构方案_v1.0.md)
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
