"""Owned CPU preparation delegates authority to actual I/O and mutation entries."""

from time import monotonic
from types import MethodType
from typing import Any, cast

from agent_core.application.coverage_checks import PublishedCoverageRunner
from agent_core.application.coverage_executor import CoverageExecutor
from agent_core.domain.artifact_payloads import ArtifactPayloadWrite
from agent_core.domain.coverage_contracts import CoverageRefusalReason, CoverageRefusedError
from agent_core.domain.coverage_execution import PublishedCoverageCheck
from agent_core.domain.coverage_persistence import CoverageRunBinding
from agent_core.domain.coverage_snapshot import CoverageSnapshot
from agent_core.domain.identifiers import ArtifactId
from agent_core.domain.leases import LeaseFence
from agent_core.ports.coverage import CoverageCommit, CoverageCommitReceipt
from agent_integrations.coverage_model import SemanticCoverageModel
from agent_integrations.coverage_model_invocation import _utc_now
from agent_integrations.coverage_snapshot import HostCoverageSnapshotAdapter
from agent_integrations.coverage_snapshot_artifacts import CoverageArtifacts
from agent_integrations.coverage_snapshot_invocation import CoverageInvocation
from agent_integrations.coverage_snapshot_prepared import PreparedCoverageSnapshot
from agent_integrations.coverage_snapshot_source import HostCoverageSnapshotSource
from agent_integrations.host_tools.gateway import HostToolGateway
from agent_integrations.host_tools.http import HttpHostToolTransport
from agent_storage.postgres.coverage import PostgresCoverageStore
from agent_storage.postgres.coverage_evidence_selection import CoverageEvidenceUnavailable

from zebra_agent_worker.coverage_artifacts import CloudCoverageArtifacts
from zebra_agent_worker.coverage_native_model import (
    _NATIVE_SEMANTIC_AUTHORIZATION,
    _OWNED,
    NativeCoverageModelInvocation,
    NativeSemanticCoverageModel,
    _methods,
    _unmodified,
    owned_evidence_operation,
    qualified_final_reads,
)

_EXECUTOR = _methods(CoverageExecutor, (
    "__init__", "_live", "_bytes", "_read_scope", "_publish", "_prior", "execute_batch",
    "_payload", "_commit_results", "publish_report",
))
_STORE = _methods(PostgresCoverageStore, (
    "bind", "missing_units", "reserve_attempt", "accepted_for_record", "commit", "counts",
))
_RUNNER = _methods(PublishedCoverageRunner, ("__init__", "run"))
_SEMANTIC = _methods(SemanticCoverageModel, ("__init__", "__call__"))
_PREPARED = _methods(PreparedCoverageSnapshot, ("__init__", "read"))
_ADAPTER = _methods(HostCoverageSnapshotAdapter, (
    "manifest_artifact_id", "body_artifact_id", "_maximum", "_descriptor", "_live", "_get",
))
_SOURCE = _methods(HostCoverageSnapshotSource, (
    "manifest_artifact_id", "body_artifact_id", "_maximum", "_descriptor", "_live",
))
_HOST = _methods(CoverageInvocation, ("budget", "authority_check", "publication_time", "call"))
_ARTIFACTS = _methods(CoverageArtifacts, (
    "load", "load_payload", "_load_payload", "publish", "_publish",
))
_GATEWAY = _methods(HostToolGateway, ("invoke",))
_TRANSPORT = _methods(HttpHostToolTransport, ("request",))


class NativeCoverageExecutor(CoverageExecutor):
    def _qualified_preparation(self) -> bool:
        read, runner = self.read, self.runner
        if (type(self) is not NativeCoverageExecutor or self.now is not _utc_now
                or type(self.binding) is not CoverageRunBinding
                or any(name in vars(self) or getattr(type(self), name) is not method
                       for name, method in _EXECUTOR.items())
                or "_preparation_boundary" in vars(self)
                or type(self)._preparation_boundary is not _PREPARATION
                or "_qualified_preparation" in vars(self)
                or type(self)._qualified_preparation is not _QUALIFY
                or "_commit_evidence" in vars(self)
                or type(self)._commit_evidence is not _COMMIT_EVIDENCE
                or type(read) is not MethodType
                or read.__func__ is not _PREPARED["read"]
                or not _unmodified(read.__self__, PreparedCoverageSnapshot, _PREPARED)
                or not _unmodified(runner, PublishedCoverageRunner, _RUNNER)
                or not _unmodified(self.store, PostgresCoverageStore, _STORE)):
            return False
        prepared = cast(PreparedCoverageSnapshot, read.__self__)
        runner = cast(PublishedCoverageRunner, runner)
        model: Any = runner.model
        if (not _unmodified(prepared._adapter, HostCoverageSnapshotAdapter, _ADAPTER)
                or type(model) is not NativeSemanticCoverageModel
                or "_authorize" in vars(model)
                or type(model)._authorize is not _NATIVE_SEMANTIC_AUTHORIZATION
                or any(name in vars(model) or getattr(type(model), name) is not method
                       for name, method in _SEMANTIC.items())):
            return False
        adapter, host = prepared._adapter, prepared._adapter.host
        if not _unmodified(host, CoverageInvocation, _HOST):
            return False
        invoke = host.invoke
        if (not _unmodified(adapter.source, HostCoverageSnapshotSource, _SOURCE)
                or adapter.source.host is not host
                or host.now is not _utc_now or host.monotonic is not monotonic
                or type(invoke) is not MethodType or invoke.__func__ is not _GATEWAY["invoke"]
                or not _unmodified(invoke.__self__, HostToolGateway, _GATEWAY)
                or not _unmodified(cast(HostToolGateway, invoke.__self__).transport,
                                   HttpHostToolTransport, _TRANSPORT)
                or not _unmodified(adapter.artifacts, CoverageArtifacts, _ARTIFACTS)
                or type(prepared.snapshot) is not CoverageSnapshot
                or type(model._definition) is not PublishedCoverageCheck
                or type(runner.definitions) is not dict
                or len(runner.definitions) != 1
                or any(type(key) is not str or type(value) is not PublishedCoverageCheck
                       or type(value.id) is not str
                       for key, value in runner.definitions.items())):
            return False
        invocation: Any = model._invoke_or_replay
        return (
            type(invocation) is NativeCoverageModelInvocation
            and type(invocation.definition) is PublishedCoverageCheck
            and type(invocation.definition.id) is str
            and _OWNED["_qualified_preparation"](invocation)
            and self.binding == invocation.binding
            and self.artifacts is invocation.artifacts.store
            and qualified_final_reads(cast(CloudCoverageArtifacts, self.artifacts))
            and self.store is cast(PostgresCoverageStore, invocation.store)
            and self.check_authority is model._check_authority is invocation.check_authority
            and model._gateway is None and model._reserve_call is None
            and model._record_response is None and model._definition == invocation.definition
            and runner.definitions == {invocation.definition.id: invocation.definition}
            and prepared.snapshot == self.binding.snapshot
            and prepared._adapter.artifacts.store is self.artifacts
        )

    def _preparation_boundary(self) -> None:
        if _QUALIFY(self):
            if not self.binding.snapshot.as_of <= _utc_now() < self.binding.snapshot.expires_at:
                raise CoverageRefusedError(CoverageRefusalReason.SNAPSHOT_EXPIRED)
            return
        super()._preparation_boundary()

    def _commit_evidence(
        self, request: CoverageCommit,
        payloads: tuple[tuple[ArtifactId, ArtifactPayloadWrite], ...],
        *, fence: LeaseFence, batch: bool,
    ) -> None:
        if not _QUALIFY(self):
            return super()._commit_evidence(request, payloads, fence=fence, batch=batch)
        model = cast(NativeSemanticCoverageModel, cast(PublishedCoverageRunner, self.runner).model)
        invocation = cast(NativeCoverageModelInvocation, model._invoke_or_replay)
        operation = owned_evidence_operation(invocation)
        if operation is None:
            return super()._commit_evidence(request, payloads, fence=fence, batch=batch)
        try:
            receipt = operation.commit_evidence(self.binding, request, payloads, fence=fence)
        except CoverageEvidenceUnavailable:
            return super()._commit_evidence(request, payloads, fence=fence, batch=batch)
        if (type(receipt) is not CoverageCommitReceipt or receipt.namespace != request.namespace
                or receipt.run_id != request.run_id or receipt.commit_key != request.commit_key
                or receipt.result_artifact_digest != request.result_artifact_digest):
            raise ValueError("native evidence acceptance acknowledgement conflicts")
        self._live()


_PREPARATION = NativeCoverageExecutor._preparation_boundary
_QUALIFY = NativeCoverageExecutor._qualified_preparation
_COMMIT_EVIDENCE = NativeCoverageExecutor._commit_evidence
