from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from hashlib import sha256
from typing import Protocol, cast

from agent_core.domain.artifact_objects import (
    ArtifactObjectConflictError,
    ArtifactObjectDeleteRequest,
    ArtifactObjectDeleteResult,
    ArtifactObjectDeleteStatus,
    ArtifactObjectExpectation,
    ArtifactObjectIntegrityError,
    ArtifactObjectNotFoundError,
    ArtifactObjectPutRequest,
    ArtifactObjectReceipt,
    ArtifactObjectUnavailableError,
    ArtifactObjectVerification,
    ArtifactObjectVerificationStatus,
)
from botocore.exceptions import BotoCoreError, ClientError  # type: ignore

from agent_storage.s3_error_mapping import (
    is_not_found,
    is_precondition_failed,
    unavailable,
)


class _S3Client(Protocol):
    def put_object(self, **kwargs: object) -> Mapping[str, object]: ...

    def head_object(self, **kwargs: object) -> Mapping[str, object]: ...

    def get_object(self, **kwargs: object) -> Mapping[str, object]: ...

    def delete_object(self, **kwargs: object) -> Mapping[str, object]: ...


class _ReadableBody(Protocol):
    def read(self) -> bytes: ...

    def close(self) -> None: ...


class S3ArtifactObjectStore:
    """S3-compatible immutable object adapter; PostgreSQL owns lifecycle metadata."""

    def __init__(
        self,
        client: _S3Client,
        *,
        bucket: str,
        key_prefix: str = "zebra/artifacts/v1",
    ) -> None:
        self._client = client
        self._bucket = _canonical_text(bucket, field_name="bucket")
        self._key_prefix = _canonical_prefix(key_prefix)

    def put_if_absent(self, request: ArtifactObjectPutRequest) -> ArtifactObjectReceipt:
        key = self._key(request.expectation)
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=request.payload,
                IfNoneMatch="*",
                Metadata=_metadata(request.expectation),
            )
        except ClientError as error:
            if not is_precondition_failed(error):
                raise unavailable("conditional object put failed", error) from error
            verification = self.verify(request.expectation)
            if verification.status is ArtifactObjectVerificationStatus.VERIFIED:
                assert verification.receipt is not None
                return verification.receipt
            if verification.status is ArtifactObjectVerificationStatus.MISMATCH:
                raise ArtifactObjectConflictError(
                    "artifact object identity already contains different bytes"
                ) from error
            raise ArtifactObjectUnavailableError(
                "conditional put conflicted but the existing object is not observable"
            ) from error
        except BotoCoreError as error:
            raise unavailable("conditional object put failed", error) from error

        verification = self.verify(request.expectation)
        if verification.status is not ArtifactObjectVerificationStatus.VERIFIED:
            raise ArtifactObjectUnavailableError(
                "written artifact object could not be verified"
            )
        assert verification.receipt is not None
        return verification.receipt

    def verify(self, expectation: ArtifactObjectExpectation) -> ArtifactObjectVerification:
        try:
            response = self._client.head_object(
                Bucket=self._bucket,
                Key=self._key(expectation),
            )
        except ClientError as error:
            if is_not_found(error):
                return ArtifactObjectVerification(
                    expectation=expectation,
                    status=ArtifactObjectVerificationStatus.NOT_FOUND,
                )
            raise unavailable("artifact object head failed", error) from error
        except BotoCoreError as error:
            raise unavailable("artifact object head failed", error) from error
        return self._verification(expectation, response)

    def read_verified(self, expectation: ArtifactObjectExpectation) -> bytes:
        verification = self.verify(expectation)
        if verification.status is ArtifactObjectVerificationStatus.NOT_FOUND:
            raise ArtifactObjectNotFoundError("artifact object was not found")
        if verification.status is ArtifactObjectVerificationStatus.MISMATCH:
            raise ArtifactObjectIntegrityError(
                "artifact object metadata does not match expectation"
            )
        receipt = verification.receipt
        assert receipt is not None
        return self.read_version_verified(expectation, receipt.object_version)

    def read_version_verified(
        self,
        expectation: ArtifactObjectExpectation,
        object_version: str,
    ) -> bytes:
        try:
            response = self._client.get_object(
                Bucket=self._bucket,
                Key=self._key(expectation),
                VersionId=object_version,
            )
        except ClientError as error:
            if is_not_found(error):
                raise ArtifactObjectNotFoundError(
                    "artifact object version was not found"
                ) from error
            raise unavailable("artifact object read failed", error) from error
        except BotoCoreError as error:
            raise unavailable("artifact object read failed", error) from error
        try:
            verification = self._verification(expectation, response)
        except Exception:
            _close_response_body(response)
            raise
        receipt = verification.receipt
        if (
            verification.status is not ArtifactObjectVerificationStatus.VERIFIED
            or receipt is None
            or receipt.object_version != object_version
        ):
            _close_response_body(response)
            raise ArtifactObjectIntegrityError(
                "artifact object version does not match read expectation"
            )
        raw_body = response.get("Body")
        read = getattr(raw_body, "read", None)
        close = getattr(raw_body, "close", None)
        if not callable(read) or not callable(close):
            raise ArtifactObjectUnavailableError("artifact object response has no body")
        body = cast(_ReadableBody, raw_body)
        read_error: Exception | None = None
        try:
            payload = body.read()
        except Exception as error:
            read_error = error
            payload = b""
        finally:
            try:
                body.close()
            except Exception as error:
                if read_error is None:
                    raise ArtifactObjectUnavailableError(
                        "artifact object body close failed"
                    ) from error
        if read_error is not None:
            raise ArtifactObjectUnavailableError(
                "artifact object body read failed"
            ) from read_error
        if not isinstance(payload, bytes):
            raise ArtifactObjectUnavailableError("artifact object body did not return bytes")
        if (
            len(payload) != expectation.size_bytes
            or sha256(payload).hexdigest() != expectation.sha256
        ):
            raise ArtifactObjectIntegrityError("artifact object bytes do not match expectation")
        return payload

    def delete_if_version(
        self,
        request: ArtifactObjectDeleteRequest,
    ) -> ArtifactObjectDeleteResult:
        key = self._key(request.expectation)
        if not self._version_exists(request):
            return ArtifactObjectDeleteResult(
                request=request,
                status=ArtifactObjectDeleteStatus.ALREADY_ABSENT,
            )
        try:
            self._client.delete_object(
                Bucket=self._bucket,
                Key=key,
                VersionId=request.object_version,
            )
        except ClientError as error:
            if is_not_found(error):
                status = ArtifactObjectDeleteStatus.ALREADY_ABSENT
            else:
                raise unavailable("artifact object delete failed", error) from error
        except BotoCoreError as error:
            raise unavailable("artifact object delete failed", error) from error
        else:
            status = ArtifactObjectDeleteStatus.DELETED
        return ArtifactObjectDeleteResult(request=request, status=status)

    def _version_exists(self, request: ArtifactObjectDeleteRequest) -> bool:
        try:
            response = self._client.head_object(
                Bucket=self._bucket,
                Key=self._key(request.expectation),
                VersionId=request.object_version,
            )
        except ClientError as error:
            if is_not_found(error):
                return False
            raise unavailable("artifact object version head failed", error) from error
        except BotoCoreError as error:
            raise unavailable("artifact object version head failed", error) from error
        verification = self._verification(request.expectation, response)
        if verification.status is ArtifactObjectVerificationStatus.MISMATCH:
            raise ArtifactObjectIntegrityError(
                "object version does not match delete expectation"
            )
        receipt = verification.receipt
        if receipt is None or receipt.object_version != request.object_version:
            raise ArtifactObjectIntegrityError(
                "object version evidence does not match delete request"
            )
        return True

    def _verification(
        self,
        expectation: ArtifactObjectExpectation,
        response: Mapping[str, object],
    ) -> ArtifactObjectVerification:
        metadata = response.get("Metadata")
        metadata_map = cast(Mapping[str, object], metadata) if isinstance(metadata, Mapping) else {}
        size = response.get("ContentLength")
        if (
            metadata_map.get("zebra-sha256") != expectation.sha256
            or metadata_map.get("zebra-size-bytes") != str(expectation.size_bytes)
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size != expectation.size_bytes
        ):
            return ArtifactObjectVerification(
                expectation=expectation,
                status=ArtifactObjectVerificationStatus.MISMATCH,
            )
        version = response.get("VersionId")
        if (
            not isinstance(version, str)
            or not version
            or version != version.strip()
            or version == "null"
            or len(version) > 1024
        ):
            raise ArtifactObjectUnavailableError(
                "artifact bucket did not return object version evidence"
            )
        last_modified = response.get("LastModified")
        if not isinstance(last_modified, datetime) or last_modified.tzinfo is None:
            raise ArtifactObjectUnavailableError("artifact object head has no verified timestamp")
        receipt = ArtifactObjectReceipt(
            expectation=expectation,
            object_version=version,
            verified_at=last_modified,
        )
        return ArtifactObjectVerification(
            expectation=expectation,
            status=ArtifactObjectVerificationStatus.VERIFIED,
            receipt=receipt,
        )

    def _key(self, expectation: ArtifactObjectExpectation) -> str:
        namespace_hash = sha256(expectation.deployment_namespace.encode()).hexdigest()
        return f"{self._key_prefix}/{namespace_hash}/{expectation.artifact_id}"


def _metadata(expectation: ArtifactObjectExpectation) -> dict[str, str]:
    return {
        "zebra-sha256": expectation.sha256,
        "zebra-size-bytes": str(expectation.size_bytes),
    }


def _close_response_body(response: Mapping[str, object]) -> None:
    close = getattr(response.get("Body"), "close", None)
    if not callable(close):
        return
    try:
        close()
    except Exception as error:
        raise ArtifactObjectUnavailableError("artifact object body close failed") from error


def _canonical_text(value: str, *, field_name: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-blank and trimmed")
    return value


def _canonical_prefix(value: str) -> str:
    value = _canonical_text(value, field_name="key_prefix").strip("/")
    if not value or any(segment in {"", ".", ".."} for segment in value.split("/")):
        raise ValueError("key_prefix must contain canonical non-empty segments")
    return value
