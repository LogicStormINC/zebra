from __future__ import annotations

import io
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

import pytest
from agent_core.domain.artifact_objects import (
    ArtifactObjectExpectation,
    ArtifactObjectIntegrityError,
    ArtifactObjectUnavailableError,
)
from agent_core.domain.identifiers import new_artifact_id
from agent_storage.artifact_objects import S3ArtifactObjectStore

PAYLOAD = b"bounded-object"


class Body(io.BytesIO):
    def __init__(self, payload: bytes, error: bool = False) -> None:
        super().__init__(payload)
        self.requests: list[int] = []
        self.error = error

    def read(self, size: int | None = -1) -> bytes:
        assert size is not None and size >= 0, "unbounded physical read"
        self.requests.append(size)
        if self.error:
            raise OSError("broken stream")
        return super().read(size)


class Client:
    def __init__(self, payload: bytes = PAYLOAD) -> None:
        self.expectation = ArtifactObjectExpectation(
            deployment_namespace="coverage",
            artifact_id=new_artifact_id(),
            sha256=sha256(PAYLOAD).hexdigest(),
            size_bytes=len(PAYLOAD),
        )
        self.payload = payload
        self.override: dict[str, object] = {}
        self.body: Body | None = None
        self.read_error = False

    def head_object(self, **kwargs: object) -> Mapping[str, object]:
        return {
            "ContentLength": len(PAYLOAD),
            "Metadata": {
                "zebra-sha256": self.expectation.sha256,
                "zebra-size-bytes": str(len(PAYLOAD)),
            },
            "VersionId": "v1",
            "LastModified": datetime(2026, 10, 8, tzinfo=UTC),
        }

    def get_object(self, **kwargs: object) -> Mapping[str, object]:
        response = dict(self.head_object())
        if kwargs.get("Range"):
            # Deliberately dishonest: advertise the requested range, send all bytes.
            response.update(ContentLength=3, ContentRange=f"bytes 2-4/{len(PAYLOAD)}")
        self.body = Body(self.payload, self.read_error)
        response.update(Body=self.body)
        response.update(self.override)
        return response

    def put_object(self, **kwargs: object) -> Mapping[str, object]:
        raise AssertionError("unexpected publication")

    def delete_object(self, **kwargs: object) -> Mapping[str, object]:
        raise AssertionError("unexpected deletion")


def _read(store: S3ArtifactObjectStore, client: Client, method: str) -> bytes:
    if method == "full":
        return store.read_verified(client.expectation)
    if method == "version":
        return store.read_version_verified(client.expectation, "v1")
    return store.read_version_range_verified(client.expectation, "v1", 2, 4)


@pytest.mark.parametrize("method", ["full", "version", "range"])
@pytest.mark.parametrize("body", [PAYLOAD * 100, b"", b"x" * len(PAYLOAD)])
def test_dishonest_stream_is_bounded_and_closed(method: str, body: bytes) -> None:
    client = Client(body)
    store = S3ArtifactObjectStore(client, bucket="artifacts")
    with pytest.raises(ArtifactObjectIntegrityError):
        _read(store, client, method)
    assert client.body is not None and client.body.closed
    assert client.body.requests == [4 if method == "range" else len(PAYLOAD) + 1]


@pytest.mark.parametrize("method", ["full", "version", "range"])
def test_success_uses_bounded_read_and_closes(method: str) -> None:
    client = Client(PAYLOAD[2:5] if method == "range" else PAYLOAD)
    store = S3ArtifactObjectStore(client, bucket="artifacts")
    assert _read(store, client, method) == (PAYLOAD[2:5] if method == "range" else PAYLOAD)
    assert client.body is not None and client.body.closed
    assert client.body.requests == [4 if method == "range" else len(PAYLOAD) + 1]


@pytest.mark.parametrize("method", ["full", "version", "range"])
def test_read_error_closes_stream(method: str) -> None:
    client = Client()
    client.read_error = True
    with pytest.raises(ArtifactObjectUnavailableError, match="body read failed"):
        _read(S3ArtifactObjectStore(client, bucket="artifacts"), client, method)
    assert client.body is not None and client.body.closed


@pytest.mark.parametrize("method", ["full", "version", "range"])
@pytest.mark.parametrize(
    "override",
    [
        {"ContentLength": 999},
        {"VersionId": "wrong"},
    ],
)
def test_invalid_response_evidence_closes_without_read(
    method: str,
    override: dict[str, object],
) -> None:
    client = Client()
    client.override = override
    with pytest.raises(ArtifactObjectIntegrityError):
        _read(S3ArtifactObjectStore(client, bucket="artifacts"), client, method)
    assert client.body is not None and client.body.closed
    assert client.body.requests == []


def test_invalid_full_response_timestamp_closes_without_read() -> None:
    client = Client()
    client.override = {"LastModified": None}
    with pytest.raises(ArtifactObjectUnavailableError):
        _read(S3ArtifactObjectStore(client, bucket="artifacts"), client, "version")
    assert client.body is not None and client.body.closed
    assert client.body.requests == []


def test_whole_object_range_also_checks_digest() -> None:
    client = Client(b"x" * len(PAYLOAD))
    client.override = {
        "ContentLength": len(PAYLOAD),
        "ContentRange": f"bytes 0-{len(PAYLOAD) - 1}/{len(PAYLOAD)}",
    }
    with pytest.raises(ArtifactObjectIntegrityError, match="bytes do not match"):
        S3ArtifactObjectStore(client, bucket="artifacts").read_version_range_verified(
            client.expectation,
            "v1",
            0,
            len(PAYLOAD) - 1,
        )
    assert client.body is not None and client.body.closed
    assert client.body.requests == [len(PAYLOAD) + 1]


@pytest.mark.parametrize("limit", [-1, True, 1.5, "8", None])
@pytest.mark.parametrize("method", ["full", "version", "range"])
def test_invalid_expected_lengths_never_read(limit: Any, method: str) -> None:
    client = Client()
    client.expectation = client.expectation.model_copy(update={"size_bytes": limit})
    with pytest.raises(ValueError, match="non-negative integer"):
        _read(S3ArtifactObjectStore(client, bucket="artifacts"), client, method)
    assert client.body is None


@pytest.mark.parametrize("start,end", [(True, 4), (0, False), (-1, 4), (5, 4), (0, 999)])
def test_invalid_ranges_never_read(start: Any, end: Any) -> None:
    client = Client()
    with pytest.raises(ValueError, match="range is invalid"):
        S3ArtifactObjectStore(client, bucket="artifacts").read_version_range_verified(
            client.expectation,
            "v1",
            start,
            end,
        )
    assert client.body is None
