from __future__ import annotations

import os
from hashlib import sha256
from typing import Any
from uuid import uuid4

import pytest
from agent_core.domain.artifact_objects import (
    ArtifactObjectConflictError,
    ArtifactObjectDeleteRequest,
    ArtifactObjectDeleteStatus,
    ArtifactObjectExpectation,
    ArtifactObjectPutRequest,
    ArtifactObjectVerificationStatus,
)
from agent_core.domain.identifiers import ArtifactId
from agent_storage import S3ArtifactObjectStore
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.session import Session  # type: ignore[import-untyped]

PAYLOAD = b"real minio immutable artifact"


def _client() -> Any:
    required = {
        name: os.environ.get(name)
        for name in (
            "ZEBRA_TEST_S3_ENDPOINT",
            "ZEBRA_TEST_S3_ACCESS_KEY",
            "ZEBRA_TEST_S3_SECRET_KEY",
        )
    }
    if not all(required.values()):
        pytest.skip("set ZEBRA_TEST_S3_* variables to run real MinIO tests")
    return Session().create_client(
        "s3",
        endpoint_url=required["ZEBRA_TEST_S3_ENDPOINT"],
        aws_access_key_id=required["ZEBRA_TEST_S3_ACCESS_KEY"],
        aws_secret_access_key=required["ZEBRA_TEST_S3_SECRET_KEY"],
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def _expectation(
    *,
    namespace: str,
    artifact_id: ArtifactId,
    payload: bytes = PAYLOAD,
) -> ArtifactObjectExpectation:
    return ArtifactObjectExpectation(
        deployment_namespace=namespace,
        artifact_id=artifact_id,
        sha256=sha256(payload).hexdigest(),
        size_bytes=len(payload),
    )


def test_real_minio_preserves_immutable_versioned_objects() -> None:
    bucket = os.environ.get("ZEBRA_TEST_S3_BUCKET", "zebra-artifacts")
    raw_client_a = _client()
    raw_client_b = _client()
    assert raw_client_a.get_bucket_versioning(Bucket=bucket)["Status"] == "Enabled"
    store_a = S3ArtifactObjectStore(raw_client_a, bucket=bucket)
    store_b = S3ArtifactObjectStore(raw_client_b, bucket=bucket)
    artifact_id = ArtifactId(uuid4())
    namespace = f"minio-test-{uuid4()}"
    expectation = _expectation(namespace=namespace, artifact_id=artifact_id)
    request = ArtifactObjectPutRequest(expectation=expectation, payload=PAYLOAD)

    first = store_a.put_if_absent(request)
    assert first.object_version != "null"
    assert store_b.put_if_absent(request) == first
    assert store_b.read_verified(expectation) == PAYLOAD

    replacement = b"different immutable bytes"
    conflicting = _expectation(
        namespace=namespace,
        artifact_id=artifact_id,
        payload=replacement,
    )
    with pytest.raises(ArtifactObjectConflictError):
        store_b.put_if_absent(
            ArtifactObjectPutRequest(expectation=conflicting, payload=replacement)
        )
    assert store_a.read_verified(expectation) == PAYLOAD

    isolated = _expectation(namespace=f"{namespace}-other", artifact_id=artifact_id)
    isolated_receipt = store_b.put_if_absent(
        ArtifactObjectPutRequest(expectation=isolated, payload=PAYLOAD)
    )
    assert isolated_receipt.object_version != "null"

    deletion = ArtifactObjectDeleteRequest(
        expectation=expectation,
        object_version=first.object_version,
    )
    assert store_a.delete_if_version(deletion).status is ArtifactObjectDeleteStatus.DELETED
    assert (
        store_b.verify(expectation).status
        is ArtifactObjectVerificationStatus.NOT_FOUND
    )
    assert (
        store_b.delete_if_version(deletion).status
        is ArtifactObjectDeleteStatus.ALREADY_ABSENT
    )
    assert store_a.read_verified(isolated) == PAYLOAD
    assert store_b.delete_if_version(
        ArtifactObjectDeleteRequest(
            expectation=isolated,
            object_version=isolated_receipt.object_version,
        )
    ).status is ArtifactObjectDeleteStatus.DELETED
