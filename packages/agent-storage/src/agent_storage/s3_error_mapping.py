from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from agent_core.domain.artifact_objects import ArtifactObjectUnavailableError
from botocore.exceptions import ClientError  # type: ignore


def is_not_found(error: ClientError) -> bool:
    status = _status(error)
    if status is not None:
        return status == 404
    return _code(error) in {
        "404",
        "NoSuchKey",
        "NoSuchVersion",
        "NotFound",
    }


def is_precondition_failed(error: ClientError) -> bool:
    status = _status(error)
    return status == 412 if status is not None else _code(error) == "PreconditionFailed"


def unavailable(message: str, error: Exception) -> ArtifactObjectUnavailableError:
    return ArtifactObjectUnavailableError(f"{message}: {type(error).__name__}")


def _code(error: ClientError) -> str:
    response = cast(Mapping[str, object], error.response)
    detail = response.get("Error")
    error_detail = cast(Mapping[str, object], detail) if isinstance(detail, Mapping) else {}
    return str(error_detail.get("Code", ""))


def _status(error: ClientError) -> int | None:
    response = cast(Mapping[str, object], error.response)
    metadata = response.get("ResponseMetadata")
    response_metadata = (
        cast(Mapping[str, object], metadata) if isinstance(metadata, Mapping) else {}
    )
    status = response_metadata.get("HTTPStatusCode")
    return status if isinstance(status, int) and not isinstance(status, bool) else None
