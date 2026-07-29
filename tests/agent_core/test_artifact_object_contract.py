from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import pytest
from agent_core.domain import (
    ArtifactObjectCleanupEvidence,
    ArtifactObjectDeleteRequest,
    ArtifactObjectDeleteResult,
    ArtifactObjectDeleteStatus,
    ArtifactObjectExpectation,
    ArtifactObjectPutRequest,
    ArtifactObjectReceipt,
    ArtifactObjectVerification,
    ArtifactObjectVerificationStatus,
)
from agent_core.domain.identifiers import ArtifactId
from pydantic import ValidationError

NOW = datetime(2026, 7, 29, tzinfo=UTC)
PAYLOAD = b"zebra"
DIGEST = sha256(PAYLOAD).hexdigest()


def _expectation() -> ArtifactObjectExpectation:
    return ArtifactObjectExpectation(
        deployment_namespace="cloud-a",
        artifact_id=ArtifactId(uuid4()),
        sha256=DIGEST,
        size_bytes=len(PAYLOAD),
    )


def test_object_put_validates_exact_bytes() -> None:
    expectation = _expectation()

    assert ArtifactObjectPutRequest(expectation=expectation, payload=PAYLOAD).payload == PAYLOAD
    with pytest.raises(ValidationError, match="size"):
        ArtifactObjectPutRequest(expectation=expectation, payload=b"shorter")
    wrong_digest = expectation.model_copy(update={"sha256": "0" * 64})
    with pytest.raises(ValidationError, match="digest"):
        ArtifactObjectPutRequest(expectation=wrong_digest, payload=PAYLOAD)


def test_object_verification_has_provider_neutral_shape() -> None:
    expectation = _expectation()
    receipt = ArtifactObjectReceipt(
        expectation=expectation,
        object_version="version-1",
        verified_at=NOW,
    )
    verification = ArtifactObjectVerification(
        expectation=expectation,
        status=ArtifactObjectVerificationStatus.VERIFIED,
        receipt=receipt,
    )

    assert verification.receipt == receipt
    assert not {
        "provider",
        "bucket",
        "key",
        "endpoint",
        "etag",
        "url",
    }.intersection(ArtifactObjectReceipt.model_fields)
    with pytest.raises(ValidationError):
        ArtifactObjectVerification(
            expectation=expectation,
            status=ArtifactObjectVerificationStatus.NOT_FOUND,
            receipt=receipt,
        )


def test_object_delete_binds_exact_version() -> None:
    request = ArtifactObjectDeleteRequest(
        expectation=_expectation(),
        object_version="version-1",
    )
    result = ArtifactObjectDeleteResult(
        request=request,
        status=ArtifactObjectDeleteStatus.ALREADY_ABSENT,
    )

    assert result.request.object_version == "version-1"


def test_compensation_cleanup_requires_deleted_or_proven_absent_object() -> None:
    expectation = _expectation()
    missing = ArtifactObjectVerification(
        expectation=expectation,
        status=ArtifactObjectVerificationStatus.NOT_FOUND,
    )

    assert ArtifactObjectCleanupEvidence(verification=missing).verification == missing
    with pytest.raises(ValidationError):
        ArtifactObjectCleanupEvidence(
            verification=ArtifactObjectVerification(
                expectation=expectation,
                status=ArtifactObjectVerificationStatus.MISMATCH,
            )
        )
    with pytest.raises(ValidationError):
        ArtifactObjectCleanupEvidence()
