from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from typing import cast
from uuid import uuid4

import pytest
from agent_core.domain.artifact_objects import (
    ArtifactObjectConflictError,
    ArtifactObjectDeleteRequest,
    ArtifactObjectDeleteStatus,
    ArtifactObjectExpectation,
    ArtifactObjectIntegrityError,
    ArtifactObjectPutRequest,
    ArtifactObjectUnavailableError,
    ArtifactObjectVerificationStatus,
)
from agent_core.domain.identifiers import ArtifactId
from agent_storage import S3ArtifactObjectStore
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

PAYLOAD = b"immutable artifact bytes"
NOW = datetime(2026, 7, 29, tzinfo=UTC)


class _Body:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.closed = False

    def read(self) -> bytes:
        return self.payload

    def close(self) -> None:
        self.closed = True


class _FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, dict[str, object]] = {}
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.next_error: tuple[str, ClientError] | None = None
        self.last_body: _Body | None = None

    def put_object(self, **kwargs: object) -> Mapping[str, object]:
        self._record("put_object", kwargs)
        key = cast(str, kwargs["Key"])
        if key in self.objects:
            raise _client_error("PreconditionFailed", 412)
        self.objects[key] = {
            "Body": kwargs["Body"],
            "Metadata": kwargs["Metadata"],
            "VersionId": "version-1",
            "LastModified": NOW,
        }
        return {"VersionId": "version-1"}

    def head_object(self, **kwargs: object) -> Mapping[str, object]:
        self._record("head_object", kwargs)
        item = self._item(kwargs)
        return {
            "ContentLength": len(cast(bytes, item["Body"])),
            "Metadata": item["Metadata"],
            "VersionId": item["VersionId"],
            "LastModified": item["LastModified"],
        }

    def get_object(self, **kwargs: object) -> Mapping[str, object]:
        self._record("get_object", kwargs)
        item = self._item(kwargs)
        self.last_body = _Body(cast(bytes, item["Body"]))
        return {"Body": self.last_body}

    def delete_object(self, **kwargs: object) -> Mapping[str, object]:
        self._record("delete_object", kwargs)
        item = self._item(kwargs)
        key = cast(str, kwargs["Key"])
        assert kwargs.get("VersionId") == item["VersionId"]
        del self.objects[key]
        return {}

    def _record(self, method: str, kwargs: dict[str, object]) -> None:
        if self.next_error is not None and self.next_error[0] == method:
            _, error = self.next_error
            self.next_error = None
            raise error
        self.calls.append((method, kwargs))

    def _item(self, kwargs: dict[str, object]) -> dict[str, object]:
        key = cast(str, kwargs["Key"])
        item = self.objects.get(key)
        if item is None or (
            "VersionId" in kwargs and kwargs["VersionId"] != item["VersionId"]
        ):
            raise _client_error("NoSuchKey", 404)
        return item


def _client_error(code: str, status: int) -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code, "Message": code},
            "ResponseMetadata": {"HTTPStatusCode": status},
        },
        "test",
    )


def _expectation(
    *,
    namespace: str = "tenant/private",
    artifact_id: ArtifactId | None = None,
) -> ArtifactObjectExpectation:
    return ArtifactObjectExpectation(
        deployment_namespace=namespace,
        artifact_id=artifact_id or ArtifactId(uuid4()),
        sha256=sha256(PAYLOAD).hexdigest(),
        size_bytes=len(PAYLOAD),
    )


def _request(expectation: ArtifactObjectExpectation) -> ArtifactObjectPutRequest:
    return ArtifactObjectPutRequest(expectation=expectation, payload=PAYLOAD)


def test_put_is_conditional_private_and_idempotent_for_same_content() -> None:
    client = _FakeS3Client()
    store = S3ArtifactObjectStore(client, bucket="artifacts")
    expectation = _expectation()

    first = store.put_if_absent(_request(expectation))
    second = store.put_if_absent(_request(expectation))

    assert first == second
    put_calls = [kwargs for method, kwargs in client.calls if method == "put_object"]
    assert len(put_calls) == 2
    assert put_calls[0]["IfNoneMatch"] == "*"
    assert put_calls[0]["Metadata"] == {
        "zebra-sha256": expectation.sha256,
        "zebra-size-bytes": str(expectation.size_bytes),
    }
    key = cast(str, put_calls[0]["Key"])
    assert expectation.deployment_namespace not in key
    assert key.endswith(f"/{expectation.artifact_id}")
    isolated = _expectation(
        namespace="tenant/other",
        artifact_id=expectation.artifact_id,
    )
    store.put_if_absent(_request(isolated))
    assert len(client.objects) == 2


def test_existing_identity_with_other_content_is_a_conflict() -> None:
    client = _FakeS3Client()
    store = S3ArtifactObjectStore(client, bucket="artifacts")
    expectation = _expectation()
    store.put_if_absent(_request(expectation))
    key = next(iter(client.objects))
    client.objects[key]["Metadata"] = {
        "zebra-sha256": "0" * 64,
        "zebra-size-bytes": str(expectation.size_bytes),
    }

    with pytest.raises(ArtifactObjectConflictError):
        store.put_if_absent(_request(expectation))


def test_verify_distinguishes_absence_mismatch_and_provider_failure() -> None:
    client = _FakeS3Client()
    store = S3ArtifactObjectStore(client, bucket="artifacts")
    expectation = _expectation()

    assert store.verify(expectation).status is ArtifactObjectVerificationStatus.NOT_FOUND
    store.put_if_absent(_request(expectation))
    key = next(iter(client.objects))
    client.objects[key]["Metadata"] = {"zebra-sha256": "0" * 64}
    assert store.verify(expectation).status is ArtifactObjectVerificationStatus.MISMATCH
    client.next_error = ("head_object", _client_error("AccessDenied", 403))
    with pytest.raises(ArtifactObjectUnavailableError):
        store.verify(expectation)
    client.next_error = ("head_object", _client_error("NoSuchKey", 403))
    with pytest.raises(ArtifactObjectUnavailableError):
        store.verify(expectation)


def test_conflicting_precondition_code_cannot_hide_permission_failure() -> None:
    client = _FakeS3Client()
    store = S3ArtifactObjectStore(client, bucket="artifacts")
    expectation = _expectation()
    client.next_error = ("put_object", _client_error("PreconditionFailed", 403))

    with pytest.raises(ArtifactObjectUnavailableError):
        store.put_if_absent(_request(expectation))


@pytest.mark.parametrize("version", ["", " version-1", "version-1 ", "null", "v" * 1025])
def test_verify_rejects_invalid_version_evidence(version: str) -> None:
    client = _FakeS3Client()
    store = S3ArtifactObjectStore(client, bucket="artifacts")
    expectation = _expectation()
    store.put_if_absent(_request(expectation))
    client.objects[next(iter(client.objects))]["VersionId"] = version

    with pytest.raises(ArtifactObjectUnavailableError):
        store.verify(expectation)


def test_read_uses_verified_version_closes_body_and_checks_bytes() -> None:
    client = _FakeS3Client()
    store = S3ArtifactObjectStore(client, bucket="artifacts")
    expectation = _expectation()
    receipt = store.put_if_absent(_request(expectation))

    assert store.read_verified(expectation) == PAYLOAD
    assert client.last_body is not None and client.last_body.closed
    get_call = next(kwargs for method, kwargs in client.calls if method == "get_object")
    assert get_call["VersionId"] == receipt.object_version

    key = next(iter(client.objects))
    client.objects[key]["Body"] = b"x" * expectation.size_bytes
    client.objects[key]["Metadata"] = {
        "zebra-sha256": expectation.sha256,
        "zebra-size-bytes": str(expectation.size_bytes),
    }
    with pytest.raises(ArtifactObjectIntegrityError):
        store.read_verified(expectation)
    assert client.last_body is not None and client.last_body.closed

    client.objects[key]["Body"] = "x" * expectation.size_bytes
    with pytest.raises(ArtifactObjectUnavailableError):
        store.read_verified(expectation)
    assert client.last_body is not None and client.last_body.closed


def test_delete_requires_matching_exact_version_and_is_idempotent() -> None:
    client = _FakeS3Client()
    store = S3ArtifactObjectStore(client, bucket="artifacts")
    expectation = _expectation()
    receipt = store.put_if_absent(_request(expectation))
    request = ArtifactObjectDeleteRequest(
        expectation=expectation,
        object_version=receipt.object_version,
    )

    wrong_version = request.model_copy(update={"object_version": "version-other"})
    assert (
        store.delete_if_version(wrong_version).status
        is ArtifactObjectDeleteStatus.ALREADY_ABSENT
    )
    assert not any(method == "delete_object" for method, _ in client.calls)

    key = next(iter(client.objects))
    expected_metadata = client.objects[key]["Metadata"]
    client.objects[key]["Metadata"] = {"zebra-sha256": "0" * 64}
    with pytest.raises(ArtifactObjectIntegrityError):
        store.delete_if_version(request)
    assert not any(method == "delete_object" for method, _ in client.calls)
    client.objects[key]["Metadata"] = expected_metadata

    assert store.delete_if_version(request).status is ArtifactObjectDeleteStatus.DELETED
    assert (
        store.delete_if_version(request).status
        is ArtifactObjectDeleteStatus.ALREADY_ABSENT
    )
    delete_call = next(kwargs for method, kwargs in client.calls if method == "delete_object")
    assert delete_call["VersionId"] == receipt.object_version


@pytest.mark.parametrize("bucket", ["", " artifacts", "artifacts "])
def test_rejects_noncanonical_bucket(bucket: str) -> None:
    with pytest.raises(ValueError):
        S3ArtifactObjectStore(_FakeS3Client(), bucket=bucket)
