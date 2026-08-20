from collections.abc import Mapping, Sequence
from pathlib import Path

from agent_core.domain.agent_definitions import (
    AgentDefinition,
    AgentDefinitionContext,
    normalize_trusted_context,
)

from agent_tools.skills_catalog import (
    LocalSkillCatalog,
    ScopedSkillRoot,
    SkillCatalogError,
    SkillEnablementState,
    SkillReadResult,
    SkillScope,
)

_TRUSTED_DEFINITION_SKILL_SCOPES = frozenset({SkillScope.SYSTEM, SkillScope.ADMIN})


def resolve_agent_definition_context(
    definition: AgentDefinition | None,
    roots: Sequence[str | Path | ScopedSkillRoot],
    skills_state: SkillEnablementState | None = None,
    require_digest: bool = False,
) -> AgentDefinitionContext | None:
    if definition is None:
        return None
    catalog = LocalSkillCatalog(tuple(roots), skills_state=skills_state)
    system_prompt = None
    if definition.system_prompt_ref is not None:
        name = _reference_name(definition.system_prompt_ref, "system")
        result = _read(catalog, name, definition.system_prompt_ref)
        if result.metadata.scope is not SkillScope.SYSTEM:
            raise ValueError("system prompt reference must resolve to a system skill")
        system_prompt = result.content
    skill_guidance: list[tuple[str, str]] = []
    for reference in definition.skill_refs:
        name = _reference_name(reference, "skill")
        result = _read(catalog, name, reference)
        if result.metadata.scope not in _TRUSTED_DEFINITION_SKILL_SCOPES:
            raise ValueError("agent definition skill reference must resolve from a trusted scope")
        skill_guidance.append((result.metadata.name, result.content))
    context = AgentDefinitionContext(
        agent_id=definition.agent_id,
        version=definition.version,
        system_prompt=system_prompt,
        skill_guidance=tuple(skill_guidance),
        trusted_context=_trusted_context(definition.trust_policy),
    )
    if require_digest and (
        definition.system_prompt_ref
        or definition.skill_refs
        or context.trusted_context
    ):
        if definition.resolved_context_digest is None:
            raise ValueError("agent definition resolved context digest is missing")
    if (
        definition.resolved_context_digest is not None
        and definition.resolved_context_digest != context.resolved_context_digest
    ):
        raise ValueError("agent definition resolved context digest mismatch")
    return context


def _trusted_context(policy: object) -> dict[str, object]:
    if not isinstance(policy, Mapping):
        raise ValueError("agent definition trust policy must be an object")
    value = policy.get("trusted_context")
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("agent definition trusted context must be an object")
    return normalize_trusted_context(value)


def _reference_name(reference: str, scheme: str) -> str:
    prefix = f"{scheme}://"
    if not reference.startswith(prefix):
        raise ValueError(f"agent definition reference must use {prefix}")
    return reference.removeprefix(prefix)


def _read(catalog: LocalSkillCatalog, name: str, reference: str) -> SkillReadResult:
    try:
        return catalog.read(name)
    except SkillCatalogError as exc:
        raise ValueError(f"agent definition reference cannot be resolved: {reference}") from exc
