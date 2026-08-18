"""Payload-aware methods mixed into the PostgreSQL Effect aggregate."""

from agent_core.domain.cloud_artifact_requests import ArtifactFinalizeRequest
from agent_core.domain.effect_dispatch import (
    EffectClaim,
    EffectDispatch,
    EffectDispatchStateError,
    EffectDispatchStatus,
    EffectEvidence,
    EffectScheduleRequest,
)
from agent_core.domain.events import SessionEvent
from agent_core.domain.leases import LeaseLostError
from agent_core.domain.tools import ToolCallStatus, ToolResult
from agent_core.ports.aggregate_mutation import WorkerMutationAuthority
from psycopg import errors

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.effect_payload_transactions import (
    finish_claim_with_payload_in_transaction,
    schedule_effect_with_payload_in_transaction,
)
from agent_storage.postgres.effects import find_initial_dispatch, same_schedule
from agent_storage.postgres.leases import assert_current_lease_fence


class EffectPayloadDispatchMixin:
    """Add Artifact-finalizing transitions to an Effect store."""

    _database: PostgresDatabase

    def schedule_with_payload(
        self,
        request: EffectScheduleRequest,
        *,
        authority: WorkerMutationAuthority,
        artifact_finalize: ArtifactFinalizeRequest,
    ) -> EffectDispatch:
        if (
            authority.deployment_namespace != self._namespace
            or authority.session_id != request.execution_session_id
        ):
            raise LeaseLostError("Effect payload authority has the wrong scope")
        try:
            with self._database.connect() as connection:
                return schedule_effect_with_payload_in_transaction(
                    connection,
                    self._namespace,
                    request,
                    authority,
                    artifact_finalize,
                )
        except (errors.UniqueViolation, ValueError):
            with self._database.connect() as connection:
                assert_current_lease_fence(
                    connection,
                    self._namespace,
                    request.execution_session_id,
                    authority.lease_fence,
                )
                existing = find_initial_dispatch(
                    connection,
                    self._namespace,
                    request.root_session_id,
                    request.ledger_key,
                )
            if existing is None:
                raise
            return same_schedule(existing, request)

    def complete_with_payload(
        self,
        claim: EffectClaim,
        *,
        result: ToolResult,
        terminal_event: SessionEvent,
        authority: WorkerMutationAuthority,
        artifact_finalize: ArtifactFinalizeRequest,
    ) -> SessionEvent:
        if result.status is not ToolCallStatus.EXECUTED:
            raise EffectDispatchStateError("successful Effect requires an executed result")
        return self._finish_claim_with_payload(
            claim,
            status=EffectDispatchStatus.SUCCEEDED,
            terminal_event=terminal_event,
            authority=authority,
            artifact_finalize=artifact_finalize,
            result=result,
        )

    def mark_uncertain_with_payload(
        self,
        claim: EffectClaim,
        *,
        evidence: EffectEvidence,
        terminal_event: SessionEvent,
        authority: WorkerMutationAuthority,
        artifact_finalize: ArtifactFinalizeRequest,
    ) -> SessionEvent:
        return self._finish_claim_with_payload(
            claim,
            status=EffectDispatchStatus.UNCERTAIN,
            terminal_event=terminal_event,
            authority=authority,
            artifact_finalize=artifact_finalize,
            evidence=evidence,
        )

    @property
    def _namespace(self) -> str:
        return self._database.deployment_namespace

    def _finish_claim_with_payload(
        self,
        claim: EffectClaim,
        *,
        status: EffectDispatchStatus,
        terminal_event: SessionEvent,
        authority: WorkerMutationAuthority,
        artifact_finalize: ArtifactFinalizeRequest,
        result: ToolResult | None = None,
        evidence: EffectEvidence | None = None,
    ) -> SessionEvent:
        with self._database.connect() as connection:
            return finish_claim_with_payload_in_transaction(
                connection,
                self._namespace,
                claim,
                status=status,
                terminal_event=terminal_event,
                authority=authority,
                artifact_finalize=artifact_finalize,
                result=result,
                evidence=evidence,
            )
