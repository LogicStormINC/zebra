"""Narrow infrastructure collaborator, independent of storage implementation."""

from collections.abc import Mapping
from typing import Protocol


class RuntimeInstanceLifecycle(Protocol):
    engine_identity: str

    def reserve(self, instance_id: str, session_id: str, spec_digest: str) -> Mapping[str, str]: ...

    def created(self, instance_id: str, container_id: str) -> None: ...

    def authorize(self, instance_id: str, container_id: str) -> None: ...

    def removed(self, instance_id: str, container_id: str) -> None: ...
