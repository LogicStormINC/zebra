"""Dependency wiring for a source-owned coverage producer and its check runner."""

from collections.abc import Callable
from contextlib import nullcontext
from typing import Any

from agent_core.application.coverage_checks import PublishedCoverageRunner
from agent_core.application.coverage_semantic import semantic_check
from agent_core.domain.coverage_model_budget import CoverageModelPolicy
from agent_core.domain.host_authority import HostContextEnvelope, HostResourceRef
from agent_core.domain.leases import WorkerLease
from agent_integrations import ModelProviderSettings
from agent_integrations.coverage_model_invocation import _utc_now
from agent_integrations.coverage_model_policy import REVIEWER_PROFILE, OfficialDeepSeekPolicy
from agent_integrations.coverage_snapshot import HostCoverageSnapshotAdapter
from agent_integrations.coverage_snapshot_invocation import HostCoverageInvoke
from agent_integrations.coverage_snapshot_prepared import PreparedCoverageSnapshot
from agent_integrations.host_tools.contracts import HostToolManifest
from agent_storage.postgres.coverage import PostgresCoverageStore
from agent_storage.postgres.coverage_evidence_operation import PostgresCoverageEvidenceOperation

from zebra_agent_worker.coverage_bootstrap import CloudCoverageBootstrap
from zebra_agent_worker.coverage_native_publication import NativeCoverageArtifacts


def compose_coverage_checks(
    *, boot: CloudCoverageBootstrap, store: PostgresCoverageStore, lease: WorkerLease,
    policy: CoverageModelPolicy, proof: OfficialDeepSeekPolicy, settings: ModelProviderSettings,
    host: HostContextEnvelope, manifest: HostToolManifest,
    invoke: HostCoverageInvoke, effect: HostCoverageInvoke, check: Callable[[], None],
    invocation_factory: Callable[..., Any], model_factory: Callable[..., Any],
) -> tuple[PreparedCoverageSnapshot, PublishedCoverageRunner]:
    operation = PostgresCoverageEvidenceOperation(
        store, boot.artifacts.publisher, boot.artifacts.authority, check,
        check_local_authority=boot.artifacts.check_local_authority,
    )
    invocation = invocation_factory(
        binding=boot.binding,
        artifacts=NativeCoverageArtifacts(boot.artifacts, lease.session_id, nullcontext()),
        budget_store=store, original_policy=policy, fence=lease.fence, settings=settings,
        check_authority=check, trusted_proof=proof, evidence_operation=operation,
    )
    resource_id = boot.binding.snapshot.source_resource_ref
    if resource_id is None:
        raise ValueError("coverage checks require retained source authority")
    adapter = HostCoverageSnapshotAdapter(
        session_id=lease.session_id, authority=host, contract=boot.binding.contract,
        source_ref=HostResourceRef(
            type=boot.binding.contract.source_definition.resource_type, id=resource_id,
        ), manifest=manifest,
        invoke=invoke, artifacts=boot.artifacts, publication_lock=nullcontext(),
        admitted_effect_invoke=effect, now=_utc_now,
    )
    prepared = adapter.prepare(boot.binding.snapshot.snapshot_id, authority=host)
    runner = PublishedCoverageRunner(
        (semantic_check(REVIEWER_PROFILE),),
        model=model_factory(
            model_profile=REVIEWER_PROFILE, check_authority=check, invoke_or_replay=invocation,
        ),
    )
    return prepared, runner
