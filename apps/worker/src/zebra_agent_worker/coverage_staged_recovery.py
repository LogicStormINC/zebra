"""Classify retained original responses for crash recovery; never grant MODEL transport."""

from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from agent_core.domain.artifact_objects import (
    ArtifactObjectExpectation,
    ArtifactObjectIntegrityError,
    ArtifactObjectVerificationStatus,
)
from agent_core.domain.coverage_contracts import coverage_digest
from agent_core.domain.coverage_model_budget import (
    CoverageModelReservation,
    CoverageModelUsageReceipt,
)
from agent_core.domain.coverage_model_checkpoint import (
    MODEL_CHECKPOINT_KIND,
    completion_usage,
    decode_model_checkpoint,
    model_checkpoint_id,
)
from agent_integrations.coverage_model_derivation import derive_semantic_observation
from agent_storage.postgres.coverage_artifacts import MAX_COVERAGE_ARTIFACT_BYTES
from agent_storage.postgres.coverage_model_checkpoint import verify_model_checkpoint


def prove_uploaded_responses(
    transcript: Any, artifacts: Any, external: Callable[[], None], deadlines: list[datetime],
) -> tuple[set[str], list[tuple[Any, Any, bytes]]]:
    pending = [call for call in transcript.calls.values() if call["receipt"] is None]
    if len(pending) != transcript.state.unresolved or len(pending) > 1000:
        raise ValueError(
            "unresolved response count requires reconciliation before bounded recovery"
        )
    binding, source = transcript.binding, getattr(artifacts, "artifacts", artifacts)
    keys, originals, spent = set(), [], transcript.spent
    for call in pending:
        reservation = CoverageModelReservation.model_validate(call["reservation"])
        identifier = model_checkpoint_id(binding, reservation)
        record = source._record(identifier)
        if record is None or record.lifecycle_status not in {"staged", "finalized"}:
            raise ValueError("unknown model attempt requires reconciliation, never another HTTP")
        stored = record.reservation
        identity = coverage_digest(binding.model_dump(mode="json"))
        if (record.deployment_namespace != transcript.deployment
                or record.session_id != binding.session_id
                or stored.idempotency_key != f"coverage:{identity}:{identifier}"
                or stored.kind != MODEL_CHECKPOINT_KIND or stored.mime_type != "application/json"
                or stored.retained_until is None or stored.retained_until <= datetime.now(UTC)):
            raise ValueError("uploaded original response has foreign or expired provenance")
        spent += stored.size_bytes
        if spent > MAX_COVERAGE_ARTIFACT_BYTES:
            raise ValueError("uploaded original responses exceed cumulative recovery bound")
        expectation = ArtifactObjectExpectation(
            deployment_namespace=transcript.deployment, artifact_id=identifier,
            sha256=stored.sha256, size_bytes=stored.size_bytes,
        )
        external()
        verified = source.objects.verify(expectation)
        external()
        if (verified.status is not ArtifactObjectVerificationStatus.VERIFIED
                or verified.receipt is None):
            raise ValueError("unknown model attempt requires retained original response bytes")
        try:
            body = source.objects.read_version_verified(
                expectation, verified.receipt.object_version,
            )
        except ArtifactObjectIntegrityError as error:
            raise ValueError("uploaded original response integrity conflicts") from error
        external()
        if source._record(identifier) != record:
            raise ValueError("uploaded response metadata changed during recovery")
        checkpoint = decode_model_checkpoint(body)
        if (checkpoint.binding != binding or checkpoint.reservation != reservation
                or checkpoint.artifact_id != identifier or checkpoint.canonical_bytes != body
                or len(body) != stored.size_bytes or sha256(body).hexdigest() != stored.sha256):
            raise ValueError("uploaded original response conflicts with reserved request")
        counts = completion_usage(checkpoint.completion, reservation)
        receipt = CoverageModelUsageReceipt(
            reservation=reservation, input_tokens=counts[0], output_tokens=counts[1],
            total_tokens=counts[2], checkpoint_ref=f"artifact://{identifier}",
            checkpoint_digest=stored.sha256,
        )
        derive_semantic_observation(
            body, receipt, transcript.definition, reservation.key,
            transcript.indexed[reservation.key.record_id],
        )
        if record.lifecycle_status == "finalized":
            verify_model_checkpoint(
                transcript.connection, transcript.deployment, binding, receipt, artifacts,
                reserved_sequence=call["reserved_sequence"], receipt_sequence=None,
                retention_deadlines=deadlines,
            )
        elif (record.lifecycle_revision, record.object_receipt is not None) not in {
            (0, False), (1, True),
        }:
            raise ValueError("staged original response has inconsistent receipt state")
        originals.append((record, verified.receipt, sha256(body).digest()))
        deadlines.append(stored.retained_until)
        keys.add(coverage_digest(reservation.key.model_dump(mode="json")))
    return keys, originals


def uploaded_responses_digest(originals: list[tuple[Any, Any, bytes]]) -> str:
    return coverage_digest([
        (row.model_dump(mode="json"), version.model_dump(mode="json"), digest.hex())
        for row, version, digest in originals
    ])


def revalidate_uploaded_responses(
    artifacts: Any, originals: list[tuple[Any, Any, bytes]], external: Callable[[], None],
    deadline: float,
) -> None:
    from agent_storage.postgres.coverage_recovery_preparation import (
        CoverageRecoveryDeferred,
        remaining_recovery_time,
    )

    source = getattr(artifacts, "artifacts", artifacts)
    for record, receipt, digest in originals:
        remaining_recovery_time(deadline)
        external()
        if source._record(record.artifact_id) != record:
            raise ValueError("uploaded response metadata changed before approval")
        try:
            body = source.objects.read_version_verified_before(
                receipt.expectation, receipt.object_version, deadline,
            )
        except TimeoutError:
            raise CoverageRecoveryDeferred("staged original proof timed out") from None
        external()
        if (source._record(record.artifact_id) != record or sha256(body).digest() != digest
                or record.reservation.retained_until <= datetime.now(UTC)):
            raise ValueError("uploaded original response changed before approval")
        remaining_recovery_time(deadline)
