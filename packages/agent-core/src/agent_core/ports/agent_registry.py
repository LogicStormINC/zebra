from typing import Protocol

from agent_core.domain.agent_definition_drafts import (
    AgentDefinitionDraft,
    AgentDefinitionDraftValidation,
)
from agent_core.domain.agent_definitions import (
    AgentDefinition,
    AgentDefinitionScope,
    AgentDefinitionVersion,
    AgentRelease,
)
from agent_core.domain.identifiers import AgentDefinitionVersionId


class AgentRegistryPort(Protocol):
    """Definition metadata authority; never a source of execution facts."""

    def get_definition(self, scope: AgentDefinitionScope) -> AgentDefinition | None: ...

    def get_draft(self, scope: AgentDefinitionScope) -> AgentDefinitionDraft | None: ...

    def save_draft(
        self,
        draft: AgentDefinitionDraft,
        *,
        expected_revision: int | None = None,
    ) -> AgentDefinitionDraft: ...

    def append_draft_validation(
        self, validation: AgentDefinitionDraftValidation
    ) -> None: ...

    def latest_draft_validation(
        self, scope: AgentDefinitionScope
    ) -> AgentDefinitionDraftValidation | None: ...

    def get_version(
        self,
        scope: AgentDefinitionScope,
        version_id: AgentDefinitionVersionId,
    ) -> AgentDefinitionVersion | None: ...

    def save_definition(
        self,
        definition: AgentDefinition,
        *,
        expected_revision: int | None = None,
    ) -> AgentDefinition: ...

    def save_version(self, version: AgentDefinitionVersion) -> AgentDefinitionVersion: ...

    def resolve_published(
        self,
        scope: AgentDefinitionScope,
        *,
        environment: str,
    ) -> AgentRelease | None: ...

    def append_release(
        self,
        release: AgentRelease,
        *,
        expected_revision: int | None = None,
    ) -> AgentRelease: ...
