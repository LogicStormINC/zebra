"""Fenced PostgreSQL Effect dispatch and durable outbox aggregate."""

from datetime import timedelta
from uuid import UUID, uuid4

from agent_core.domain.effect_dispatch import (
    EffectClaim,
    EffectDispatch,
    EffectDispatchConflictError,
    EffectDispatchStateError,
    EffectDispatchStatus,
    EffectEvidence,
    EffectResolutionOutcome,
    EffectScheduleRequest,
)
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.leases import LeaseFence
from agent_core.domain.tools import ToolCallStatus, ToolResult
from agent_core.ports.effect_dispatch import EffectDispatchPort
from agent_core.ports.effect_state import EffectStateReadPort
from psycopg import errors
from psycopg.types.json import Jsonb

from agent_storage.postgres.database import PostgresDatabase
from agent_storage.postgres.effect_payload_dispatch import EffectPayloadDispatchMixin
from agent_storage.postgres.effect_payload_transactions import (
    finish_claim_in_transaction,
    schedule_effect_in_transaction,
)
from agent_storage.postgres.effects import (
    assert_terminal_event,
    effect_claim_from_row,
    effect_dispatch_from_row,
    find_initial_dispatch,
    find_retry,
    lock_dispatch,
    lock_latest_dispatch,
    positive_ttl,
    read_dispatch,
    require_event,
    require_same_claim,
    required_text,
    same_retry,
    same_schedule,
    write_terminal,
)
from agent_storage.postgres.events import append_event_in_transaction
from agent_storage.postgres.leases import assert_current_lease_fence


class PostgresEffectDispatchStore(
    EffectPayloadDispatchMixin,
    EffectDispatchPort,
    EffectStateReadPort,
):
    """Keep Event intent, delivery state, and terminal fact in one transaction."""

    def __init__(self, dsn: str, *, deployment_namespace: str) -> None:
        self._database = PostgresDatabase(dsn, deployment_namespace=deployment_namespace)

    def terminal_keys(self, root_session_id: SessionId) -> frozenset[str]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT ledger_key FROM effect_outbox
                WHERE deployment_namespace = %s AND root_session_id = %s
                  AND status = 'succeeded'
                """,
                (self._namespace, root_session_id),
            ).fetchall()
        return frozenset(row["ledger_key"] for row in rows)

    def has_uncertain(self, root_session_id: SessionId) -> bool:
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM effect_outbox
                WHERE deployment_namespace = %s AND root_session_id = %s
                  AND status IN ('pending', 'claimed', 'uncertain')
                LIMIT 1
                """,
                (self._namespace, root_session_id),
            ).fetchone()
        return row is not None

    def schedule(
        self,
        request: EffectScheduleRequest,
        *,
        fence: LeaseFence,
    ) -> EffectDispatch:
        try:
            with self._database.connect() as connection:
                assert_current_lease_fence(
                    connection,
                    self._namespace,
                    request.execution_session_id,
                    fence,
                )
                return schedule_effect_in_transaction(connection, self._namespace, request)
        except (errors.UniqueViolation, ValueError):
            with self._database.connect() as connection:
                existing = find_initial_dispatch(
                    connection,
                    self._namespace,
                    request.root_session_id,
                    request.ledger_key,
                )
            if existing is None:
                raise
            return same_schedule(existing, request)

    def claim_next(
        self,
        execution_session_id: SessionId,
        *,
        fence: LeaseFence,
        claim_ttl: timedelta,
    ) -> EffectClaim | None:
        ttl = positive_ttl(claim_ttl)
        with self._database.connect() as connection:
            assert_current_lease_fence(connection, self._namespace, execution_session_id, fence)
            row = connection.execute(
                """
                WITH candidate AS (
                    SELECT dispatch_id FROM effect_outbox
                    WHERE deployment_namespace = %s
                      AND execution_session_id = %s AND status = 'pending'
                    ORDER BY created_at, dispatch_id
                    FOR UPDATE SKIP LOCKED LIMIT 1
                )
                UPDATE effect_outbox AS effect
                SET status = 'claimed', claim_epoch = %s,
                    claim_fencing_token = %s, claim_owner_instance_id = %s,
                    claim_expires_at = transaction_timestamp() + %s::interval,
                    updated_at = transaction_timestamp()
                FROM candidate
                WHERE effect.deployment_namespace = %s
                  AND effect.dispatch_id = candidate.dispatch_id
                RETURNING effect.*
                """,
                (
                    self._namespace,
                    execution_session_id,
                    fence.control_plane_epoch,
                    fence.fencing_token,
                    fence.owner_instance_id,
                    ttl,
                    self._namespace,
                ),
            ).fetchone()
        return None if row is None else effect_claim_from_row(row)

    def complete(
        self,
        claim: EffectClaim,
        *,
        result: ToolResult,
        terminal_event: SessionEvent,
    ) -> SessionEvent:
        if result.status is not ToolCallStatus.EXECUTED:
            raise EffectDispatchStateError("successful Effect requires an executed result")
        return self._finish_claim(
            claim,
            status=EffectDispatchStatus.SUCCEEDED,
            terminal_event=terminal_event,
            result=result,
        )

    def list_reconcilable(
        self,
        execution_session_id: SessionId,
        *,
        current_fence: LeaseFence,
        limit: int = 100,
    ) -> tuple[EffectClaim, ...]:
        if limit < 1 or limit > 1000:
            raise ValueError("reconciliation limit must be between 1 and 1000")
        with self._database.connect() as connection:
            assert_current_lease_fence(
                connection,
                self._namespace,
                execution_session_id,
                current_fence,
            )
            rows = connection.execute(
                """
                SELECT * FROM effect_outbox
                WHERE deployment_namespace = %s AND execution_session_id = %s
                  AND status = 'claimed'
                  AND (
                    claim_expires_at <= transaction_timestamp()
                    OR claim_epoch != %s OR claim_fencing_token != %s
                    OR claim_owner_instance_id != %s
                  )
                ORDER BY claim_expires_at, dispatch_id
                LIMIT %s
                """,
                (
                    self._namespace,
                    execution_session_id,
                    current_fence.control_plane_epoch,
                    current_fence.fencing_token,
                    current_fence.owner_instance_id,
                    limit,
                ),
            ).fetchall()
        return tuple(effect_claim_from_row(row) for row in rows)

    def fail_no_effect(
        self,
        claim: EffectClaim,
        *,
        evidence: EffectEvidence,
        terminal_event: SessionEvent,
    ) -> SessionEvent:
        return self._finish_claim(
            claim,
            status=EffectDispatchStatus.FAILED_NO_EFFECT,
            terminal_event=terminal_event,
            evidence=evidence,
        )

    def mark_uncertain(
        self,
        claim: EffectClaim,
        *,
        evidence: EffectEvidence,
        terminal_event: SessionEvent,
    ) -> SessionEvent:
        return self._finish_claim(
            claim,
            status=EffectDispatchStatus.UNCERTAIN,
            terminal_event=terminal_event,
            evidence=evidence,
        )

    def reconcile_expired(
        self,
        dispatch_id: UUID,
        *,
        old_claim: EffectClaim,
        current_fence: LeaseFence,
        evidence: EffectEvidence,
    ) -> EffectDispatch:
        with self._database.connect() as connection:
            dispatch = read_dispatch(connection, self._namespace, dispatch_id)
            assert_current_lease_fence(
                connection,
                self._namespace,
                dispatch.execution_session_id,
                current_fence,
            )
            row = lock_dispatch(connection, self._namespace, dispatch_id)
            require_same_claim(row, old_claim)
            expired = connection.execute(
                "SELECT %s::timestamptz <= transaction_timestamp() AS is_expired",
                (old_claim.claim_expires_at,),
            ).fetchone()
            assert expired is not None
            if not expired["is_expired"] and old_claim.claim_fence == current_fence:
                raise EffectDispatchStateError("current claim has not expired")
            updated = connection.execute(
                """
                UPDATE effect_outbox SET status = 'uncertain', evidence = %s,
                    evidence_history = evidence_history || %s,
                    claim_epoch = NULL, claim_fencing_token = NULL,
                    claim_owner_instance_id = NULL, claim_expires_at = NULL,
                    updated_at = transaction_timestamp()
                WHERE deployment_namespace = %s AND dispatch_id = %s
                  AND status = 'claimed'
                RETURNING *
                """,
                (
                    Jsonb(evidence.model_dump(mode="json")),
                    Jsonb([evidence.model_dump(mode="json")]),
                    self._namespace,
                    dispatch_id,
                ),
            ).fetchone()
        if updated is None:
            raise EffectDispatchStateError("effect claim is no longer reconcilable")
        return effect_dispatch_from_row(updated)

    def resolve_uncertain(
        self,
        dispatch_id: UUID,
        *,
        current_fence: LeaseFence,
        evidence: EffectEvidence,
        outcome: EffectResolutionOutcome,
        terminal_event: SessionEvent,
        result: ToolResult | None = None,
    ) -> SessionEvent:
        status = EffectDispatchStatus(outcome.value)
        if (status is EffectDispatchStatus.SUCCEEDED) != (result is not None):
            raise EffectDispatchStateError("successful resolution requires one ToolResult")
        if result is not None and result.status is not ToolCallStatus.EXECUTED:
            raise EffectDispatchStateError("successful Effect requires an executed result")
        with self._database.connect() as connection:
            dispatch = read_dispatch(connection, self._namespace, dispatch_id)
            assert_terminal_event(dispatch, status, terminal_event)
            assert_current_lease_fence(
                connection,
                self._namespace,
                dispatch.execution_session_id,
                current_fence,
            )
            row = lock_dispatch(connection, self._namespace, dispatch_id)
            dispatch = effect_dispatch_from_row(row)
            if dispatch.status is not EffectDispatchStatus.UNCERTAIN:
                raise EffectDispatchStateError("only uncertain effects can be resolved")
            append_event_in_transaction(connection, self._namespace, terminal_event)
            write_terminal(
                connection,
                self._namespace,
                dispatch_id,
                status=status,
                terminal_event=terminal_event,
                result=result,
                evidence=evidence,
            )
        return terminal_event

    def retry_failed_no_effect(
        self,
        dispatch_id: UUID,
        *,
        current_fence: LeaseFence,
        retry_key: str,
        started_event: SessionEvent,
    ) -> EffectDispatch:
        retry_key = required_text(retry_key, "retry_key")
        require_event(started_event, EventType.TOOL_EXECUTION_STARTED)
        try:
            with self._database.connect() as connection:
                assert_current_lease_fence(
                    connection,
                    self._namespace,
                    started_event.session_id,
                    current_fence,
                )
                old_row = lock_dispatch(connection, self._namespace, dispatch_id)
                old = effect_dispatch_from_row(old_row)
                existing = find_retry(connection, self._namespace, old, retry_key)
                if existing is not None:
                    return same_retry(connection, self._namespace, existing, old, started_event)
                latest = lock_latest_dispatch(
                    connection,
                    self._namespace,
                    old.root_session_id,
                    old.ledger_key,
                )
                if latest.dispatch_id != old.dispatch_id:
                    raise EffectDispatchStateError(
                        "only the latest failed-no-effect attempt can be retried"
                    )
                if old.status is not EffectDispatchStatus.FAILED_NO_EFFECT:
                    raise EffectDispatchStateError("only failed-no-effect can be retried")
                append_event_in_transaction(connection, self._namespace, started_event)
                row = connection.execute(
                    """
                    INSERT INTO effect_outbox (
                        deployment_namespace, dispatch_id, execution_session_id,
                        root_session_id, ledger_key, attempt, retry_key, request_hash,
                        effect_identity, payload_artifact_ref, status, intent_event_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s)
                    RETURNING *
                    """,
                    (
                        self._namespace,
                        uuid4(),
                        started_event.session_id,
                        old.root_session_id,
                        old.ledger_key,
                        old.attempt + 1,
                        retry_key,
                        old.request_hash,
                        Jsonb(old.identity.model_dump(mode="json")),
                        old.payload_artifact_ref,
                        started_event.event_id,
                    ),
                ).fetchone()
                assert row is not None
            return effect_dispatch_from_row(row)
        except errors.UniqueViolation:
            with self._database.connect() as connection:
                old = effect_dispatch_from_row(
                    lock_dispatch(connection, self._namespace, dispatch_id)
                )
                existing = find_retry(connection, self._namespace, old, retry_key)
            if existing is None:
                raise EffectDispatchConflictError("concurrent Effect retry conflicted") from None
            with self._database.connect() as connection:
                return same_retry(connection, self._namespace, existing, old, started_event)

    def mark_dead_letter(
        self,
        dispatch_id: UUID,
        *,
        current_fence: LeaseFence,
        evidence: EffectEvidence,
        terminal_event: SessionEvent,
    ) -> SessionEvent:
        with self._database.connect() as connection:
            dispatch = read_dispatch(connection, self._namespace, dispatch_id)
            if dispatch.status not in {
                EffectDispatchStatus.UNCERTAIN,
                EffectDispatchStatus.FAILED_NO_EFFECT,
            }:
                raise EffectDispatchStateError("effect is not eligible for dead letter")
            assert_terminal_event(dispatch, EffectDispatchStatus.DEAD_LETTER, terminal_event)
            assert_current_lease_fence(
                connection,
                self._namespace,
                dispatch.execution_session_id,
                current_fence,
            )
            row = lock_dispatch(connection, self._namespace, dispatch_id)
            dispatch = effect_dispatch_from_row(row)
            if dispatch.status not in {
                EffectDispatchStatus.UNCERTAIN,
                EffectDispatchStatus.FAILED_NO_EFFECT,
            }:
                raise EffectDispatchStateError("effect is not eligible for dead letter")
            append_event_in_transaction(connection, self._namespace, terminal_event)
            write_terminal(
                connection,
                self._namespace,
                dispatch_id,
                status=EffectDispatchStatus.DEAD_LETTER,
                terminal_event=terminal_event,
                evidence=evidence,
            )
        return terminal_event

    @property
    def _namespace(self) -> str:
        return self._database.deployment_namespace

    def _finish_claim(
        self,
        claim: EffectClaim,
        *,
        status: EffectDispatchStatus,
        terminal_event: SessionEvent,
        result: ToolResult | None = None,
        evidence: EffectEvidence | None = None,
    ) -> SessionEvent:
        with self._database.connect() as connection:
            return finish_claim_in_transaction(
                connection,
                self._namespace,
                claim,
                status=status,
                terminal_event=terminal_event,
                result=result,
                evidence=evidence,
            )
