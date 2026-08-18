"""Storage-shaped Eval evidence value object for the Definition Registry (v19)."""

from __future__ import annotations

from uuid import UUID

from agent_core.domain.identifiers import (
    AgentDefinitionId,
    AgentDefinitionVersionId,
)


class AgentDefinitionEvalEvidence:
    """Storage-shaped value object; a future Core contract may replace it."""

    __slots__ = (
        "authority_issuer",
        "namespace_id",
        "definition_id",
        "version_id",
        "evidence_id",
        "definition_digest",
        "passed",
        "evaluator_actor",
        "case_summary",
    )

    def __init__(
        self,
        *,
        authority_issuer: str,
        namespace_id: str,
        definition_id: AgentDefinitionId,
        version_id: AgentDefinitionVersionId,
        evidence_id: UUID,
        definition_digest: str,
        passed: bool,
        evaluator_actor: str,
        case_summary: dict[str, object],
    ) -> None:
        self.authority_issuer = authority_issuer
        self.namespace_id = namespace_id
        self.definition_id = definition_id
        self.version_id = version_id
        self.evidence_id = evidence_id
        self.definition_digest = definition_digest
        self.passed = passed
        self.evaluator_actor = evaluator_actor
        self.case_summary = case_summary
