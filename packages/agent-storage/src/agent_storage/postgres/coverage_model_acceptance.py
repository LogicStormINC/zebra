"""Strict semantic acceptance under the existing native run/lifecycle locks."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
from datetime import datetime
from typing import TYPE_CHECKING, Any

from agent_core.application.coverage_checks import merge_observations
from agent_core.application.coverage_executor import observation_id
from agent_core.domain.cloud_artifact_requests import canonical_artifact_reserve_hash
from agent_core.domain.coverage_contracts import coverage_digest
from agent_core.domain.coverage_execution import CoverageObservation, PublishedCoverageCheck
from agent_core.domain.coverage_model_budget import CoverageModelPolicy, CoverageModelUsageReceipt
from agent_core.domain.coverage_model_checkpoint import decode_model_checkpoint
from agent_core.domain.coverage_persistence import CoverageRunBinding, canonical_coverage_bytes
from agent_core.domain.coverage_snapshot import CoverageRecord
from agent_core.domain.coverage_task_admission import coverage_admission_input
from agent_core.domain.coverage_validation import (
    AcceptedCoverageUnit,
    CoverageUnitKey,
)
from agent_core.domain.events import EventType, SessionEvent
from agent_core.ports.coverage import CoverageCommit
from psycopg.types.json import Jsonb

from agent_storage.postgres.artifact_payload_rows import artifact_payload_from_row
from agent_storage.postgres.coverage_artifacts import (
    MAX_COVERAGE_ARTIFACT_BYTES,
    check_artifact_lifecycle,
    pinned_payload_row,
    read_artifact,
    verify_results,
)
from agent_storage.postgres.coverage_execution_receipts import VerifiedCommitFacts
from agent_storage.postgres.coverage_model_checkpoint import (
    check_checkpoint_retention,
    verify_model_checkpoint,
)
from agent_storage.postgres.coverage_model_source import params
from agent_storage.postgres.coverage_proof_prefetch import materialized_sources, prefetch_proof
from agent_storage.postgres.coverage_transactions import validate_event_fence

if TYPE_CHECKING:
    from agent_storage.postgres.coverage_model_verification import _ModelVerification

ModelObservationDeriver = Callable[
    [bytes, CoverageModelUsageReceipt, PublishedCoverageCheck, CoverageUnitKey, CoverageRecord],
    object,
]


def pin_evidence(
    connection: Any,
    deployment: str,
    binding: CoverageRunBinding,
    artifacts: Any,
    ref: str,
    digest: str,
    deadlines: list[datetime],
) -> int:
    metadata = check_artifact_lifecycle(
        artifacts, ref, digest, binding.session_id, connection=connection, deployment=deployment
    )
    if metadata.retained_until is not None:
        deadlines[:] = [
            min(deadlines[0], metadata.retained_until) if deadlines else metadata.retained_until
        ]
    return metadata.size_bytes


def verify_model_results(
    connection: Any,
    deployment: str,
    binding: CoverageRunBinding,
    results: tuple[AcceptedCoverageUnit, ...],
    *,
    artifacts: Any,
    derive: ModelObservationDeriver | None,
    deadlines: list[datetime],
    request: CoverageCommit | None = None,
    before_sequence: int | None = None,
    rebuild: bool = False,
    incremental_commit: bool = False,
    verified_commits: list[VerifiedCommitFacts] | None = None,
) -> CoverageModelPolicy | None:
    from agent_storage.postgres.coverage_model_verification import _ModelVerification

    qualify = getattr(artifacts, "_execution_receipt_verifier", None)
    verifier = qualify(derive) if callable(qualify) else None
    scope = getattr(artifacts, "_locked_proof_scope", None)
    # This entrypoint is inside lock_run. Other proof phases keep their existing
    # readers; no scope is carried into recovery/publication or a subsequent call.
    context = (
        scope(connection, deployment, binding, derive=derive)
        if incremental_commit and not rebuild and callable(scope) else nullcontext(artifacts)
    )
    with context as reader:
        transcript = _ModelVerification(
            connection, deployment, binding, artifacts=reader, derive=derive, rebuild=rebuild,
            _commit_results=results if incremental_commit else None,
            _membership_qualified=verifier is not None,
        )
        policy = transcript.verify(
            results, deadlines=deadlines, request=request, before_sequence=before_sequence
        )
        if (
            verified_commits is not None and incremental_commit and not rebuild
            and policy is not None and policy.validation_mode == "final_certification"
            and transcript.state is not None and transcript.state.unresolved == 0
        ):
            from agent_core.domain.coverage_validation import expected_units

            keys = () if transcript.membership is not None else expected_units(
                binding.contract, transcript.records,
            )
            # Incremental transcripts intentionally omit unrelated settled calls.
            # New runs use sealed exact part transitions, not transcript size.
            # ponytail: unqualified/legacy roots retain the O(n) exact predicate;
            # they never upgrade from an unchecked projection or count equality.
            remaining = transcript.membership["remaining_parts"] > 0 if (
                transcript.membership is not None
            ) else connection.execute(
                """SELECT EXISTS (SELECT 1 FROM unnest(%s::jsonb[]) AS u(unit_key)
                   WHERE NOT EXISTS (
                       SELECT 1 FROM coverage_model_calls c
                       WHERE c.deployment_namespace=%s
                         AND c.namespace=%s AND c.run_id=%s
                         AND c.reservation->'key'=u.unit_key AND c.receipt IS NOT NULL))
                   AS remaining""",
                ([Jsonb(key.model_dump(mode="json")) for key in keys if key.kind == "part"],
                 *params(deployment, binding)),
            ).fetchone()["remaining"]
            verified_commits.append(VerifiedCommitFacts(
                state=transcript.state,
                expected_count=(transcript.membership["expected_count"]
                                if transcript.membership is not None else len(keys)),
                expected_digest=(transcript.membership["expected_digest"]
                                 if transcript.membership is not None else coverage_digest(
                                     [key.model_dump(mode="json") for key in keys])),
                model_work_remaining=remaining,
                verifier_contract=verifier,
            ))
        return policy


def _verify_model_results(
    transcript: _ModelVerification,
    results: tuple[AcceptedCoverageUnit, ...],
    *,
    deadlines: list[datetime],
    request: CoverageCommit | None = None,
    before_sequence: int | None = None,
) -> CoverageModelPolicy | None:
    connection, deployment, binding = (
        transcript.connection, transcript.deployment, transcript.binding,
    )
    artifacts, derive, policy = transcript.artifacts, transcript.derive, transcript.policy
    transcript.merge_deadlines(deadlines)
    if policy is None:
        return None
    assert callable(derive)
    definition = transcript.definition
    spent, settled = transcript.spent, transcript.settled
    prefetch_proof(artifacts, (
        *((request.result_artifact_ref,) if request is not None else ()),
        *(f"artifact://{observation_id(binding, item.key)}" for item in results),
    ))
    if request is not None:
        spent += pin_evidence(
            connection,
            deployment,
            binding,
            artifacts,
            request.result_artifact_ref,
            request.result_artifact_digest,
            deadlines,
        )
        if spent > MAX_COVERAGE_ARTIFACT_BYTES:
            raise ValueError("strict MODEL evidence exceeds cumulative read bound")
        verify_results(artifacts, request)
    indexed = transcript.indexed
    if len({item.key for item in results}) != len(results):
        raise ValueError("strict MODEL duplicate record/result identity")

    def bounded(size: int) -> None:
        nonlocal spent
        spent += size
        if spent > MAX_COVERAGE_ARTIFACT_BYTES:
            raise ValueError("strict MODEL evidence exceeds cumulative read bound")

    bounded(0)

    def observation(result: AcceptedCoverageUnit, derived: CoverageObservation) -> None:
        if (
            derived.key != result.key
            or derived.digest != result.result_digest
            or derived.outcome != result.outcome
        ):
            raise ValueError("accepted MODEL digest/outcome differs from original derivation")
        ref = f"artifact://{observation_id(binding, result.key)}"
        bounded(
            pin_evidence(connection, deployment, binding, artifacts, ref, derived.digest, deadlines)
        )
        metadata = artifacts.get_payload(observation_id(binding, result.key))
        if (
            metadata.kind != "coverage_observation"
            or metadata.mime_type != "application/octet-stream"
        ):
            raise ValueError("canonical MODEL observation kind conflicts")
        native = pinned_payload_row(
            artifacts, connection, deployment, metadata.artifact_id, binding.session_id
        )
        record = artifact_payload_from_row(native)
        event_binding = record.event_binding
        sources = materialized_sources(artifacts, connection, deployment, binding, ref)
        if len(sources) != 1 or event_binding is None or record.lifecycle_revision != 2:
            raise ValueError("canonical MODEL observation materialized Event missing/conflicting")
        event = SessionEvent.model_validate(sources[0])
        validate_event_fence(event.payload)
        previous = event.payload.get("previous_reservation")
        if (
            type(previous) is not str
            or len(previous) != 64
            or any(character not in "0123456789abcdef" for character in previous)
        ):
            raise ValueError("canonical MODEL observation previous reservation conflicts")
        if (
            event.event_type != EventType.COVERAGE_ARTIFACT_MATERIALIZED
            or event.actor.value != "system"
            or event.session_id != binding.session_id
            or event.event_id != event_binding.event_id
            or event.sequence != event_binding.sequence
            or event.sequence != record.reservation.intended_event_sequence
            or event_binding.artifact_uri != ref
            or event.payload.get("namespace") != binding.namespace
            or event.payload.get("run_id") != binding.run_id
            or event.payload.get("sha256") != derived.digest
            or event.payload.get("metadata") != {"artifact_uri": ref}
            or event.payload.get("reservation")
            != canonical_artifact_reserve_hash(deployment, record.reservation)
            or native["request_hash"] != event.payload.get("reservation")
            or native["expected_stream_revision"] != event.sequence - 1
            or record.reservation.kind != metadata.kind
            or record.reservation.mime_type != metadata.mime_type
            or record.reservation.idempotency_key
            != f"coverage:{coverage_digest(binding.model_dump(mode='json'))}:{metadata.artifact_id}"
            or set(event.payload)
            != {
                "namespace",
                "run_id",
                "fence",
                "metadata",
                "sha256",
                "reservation",
                "previous_reservation",
            }
            or (before_sequence is not None and event.sequence >= before_sequence)
        ):
            raise ValueError("canonical MODEL observation Event linkage conflicts")
        body = read_artifact(artifacts, ref, derived.digest, binding.session_id)
        if body != canonical_coverage_bytes(derived.model_dump(mode="json")):
            raise ValueError("canonical MODEL observation differs from original derivation")

    def part(result: AcceptedCoverageUnit, record: CoverageRecord) -> CoverageObservation:
        proof = settled.get(result.key)
        if proof is None:
            raise ValueError("strict MODEL part has no settled original receipt")
        call, receipt = proof
        if before_sequence is not None and call["receipt_sequence"] >= before_sequence:
            raise ValueError("MODEL acceptance preceded original settlement")
        body = verify_model_checkpoint(
            connection,
            deployment,
            binding,
            receipt,
            artifacts,
            reserved_sequence=call["reserved_sequence"],
            receipt_sequence=call["receipt_sequence"],
            retention_deadlines=deadlines,
        )
        bounded(len(body))
        if decode_model_checkpoint(body).request is None:
            raise ValueError("response-only v1 is budget evidence, not strict MODEL provenance")
        derived = CoverageObservation.model_validate(
            coverage_admission_input(derive(body, receipt, definition, result.key, record)),
            strict=True,
        )
        observation(result, derived)
        return derived

    expected = transcript.expected
    for result in results:
        if result.key not in expected:
            raise ValueError("strict MODEL result is outside exact manifest membership")
        record = indexed[result.key.record_id]
        if result.key.kind == "part":
            part(result, record)
            continue
        rows = connection.execute(
            """SELECT result FROM coverage_units WHERE deployment_namespace=%s
               AND namespace=%s AND run_id=%s AND unit_key->>'record_id'=%s
               AND unit_key->>'kind'='part' ORDER BY ordinal LIMIT 4097""",
            (*params(deployment, binding), record.record_id),
        ).fetchall()
        if len(rows) != len(record.parts) or any(row["result"] is None for row in rows):
            raise ValueError("MODEL merge requires every accepted canonical part")
        parts = tuple(AcceptedCoverageUnit.model_validate(row["result"]) for row in rows)
        if tuple(item.key for item in parts) != tuple(
            result.key.model_copy(
                update={"kind": "part", "part_id": item.id, "part_digest": item.digest}
            )
            for item in record.parts
        ):
            raise ValueError("MODEL merge canonical part membership/order conflicts")
        transcript.batches()
        bounded(transcript.batch_bytes)
        transcript.merge_deadlines(deadlines)
        record_sources = transcript.part_sources.get(record.record_id, {})
        if set(record_sources) != {item.key for item in parts}:
            raise ValueError("MODEL merge part accepted source missing/conflicting")
        for item in parts:
            sources = record_sources.get(item.key, ())
            if not sources:
                raise ValueError("MODEL merge part has no canonical accepted batch source")
            if len(sources) != 1 or sources[0][1] != item or (
                before_sequence is not None and sources[0][0] >= before_sequence
            ):
                raise ValueError("MODEL merge part accepted source missing/conflicting")
        derived = merge_observations(
            result.key,
            tuple(item.id for item in record.parts),
            tuple(part(item, record) for item in parts),
        )
        observation(result, derived)
    check_checkpoint_retention(connection, deadlines)
    return policy
