"""Orchestration Control Plane application package (ADR-021).

Boundary rules frozen by AL-BOUNDARY-ORCH-01:

- depends only on ``agent-core`` domain models/Ports and ``agent-tools``
  contracts; it may call ``agent-control-plane`` application services, but
  the control plane never imports this package;
- owns the deterministic orchestration domain: plan/budget contracts, DAG
  validation and scheduling, child-task materialization coordination, the
  five-layer completion gate, the worktree merge-gate fix loop, Agent Team
  contracts, and the ordinary ``system/orchestrator@1`` definition;
- never imports the Worker, the Runtime, HTTP frameworks, storage adapters
  or provider integrations — those stay in their own packages behind Ports;
- composition happens in ``apps/`` composition roots.
"""
