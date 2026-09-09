from typing import Protocol

from pydantic import TypeAdapter

from agent_core.domain.artifact_objects import ArtifactObjectReceipt
from agent_core.domain.extensions import ExtensionIdempotencyKey, ExtensionScope
from agent_core.domain.skill_publications import SkillPublication

UPLOAD_IDEMPOTENCY_KEY = TypeAdapter(ExtensionIdempotencyKey)


class SkillPublicationConflictError(ValueError):
    """A named version already reserves different package metadata or archive bytes."""


class SkillPublicationNotFoundError(LookupError):
    """No publication exists within the supplied exact scope."""


class SkillPublicationStorePort(Protocol):
    async def reserve(
        self, *, scope: ExtensionScope, publication: SkillPublication,
        idempotency_key: ExtensionIdempotencyKey | None = None,
    ) -> SkillPublication: ...

    async def get(
        self, *, scope: ExtensionScope, skill_id: str, version_id: str,
    ) -> SkillPublication: ...

    async def mark_ready(
        self, *, scope: ExtensionScope, skill_id: str, version_id: str,
        receipt: ArtifactObjectReceipt,
    ) -> SkillPublication: ...
