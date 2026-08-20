import hmac
import json
from hashlib import sha256

from agent_core.domain.agent_definitions import AgentDefinition
from agent_tools import resolve_agent_definition_context
from zebra_agent_config import ZebraAgentSettings

from zebra_agent_api.skills_admin import runtime_skills_state, scoped_skill_roots


def bind_server_resolved_agent_definition(
    definition: AgentDefinition | None,
    settings: ZebraAgentSettings,
) -> AgentDefinition | None:
    if definition is None:
        return None
    if _has_trusted_context(definition) and not (
        definition.system_prompt_ref or definition.skill_refs
    ):
        raise ValueError("trusted context requires a server-resolved system or Skill reference")
    definition = _bind_trusted_context_claim(definition, settings)
    context = resolve_agent_definition_context(
        definition,
        scoped_skill_roots(settings),
        skills_state=runtime_skills_state(settings),
    )
    if not (
        definition.system_prompt_ref
        or definition.skill_refs
        or _has_trusted_context(definition)
    ):
        return definition
    if context is None:
        raise ValueError("agent definition context could not be resolved")
    return definition.model_copy(
        update={"resolved_context_digest": context.resolved_context_digest}
    )


def _has_trusted_context(definition: AgentDefinition) -> bool:
    return bool(definition.trust_policy.get("trusted_context")) or (
        definition.trusted_context_claim is not None
    )


def _bind_trusted_context_claim(
    definition: AgentDefinition,
    settings: ZebraAgentSettings,
) -> AgentDefinition:
    claim = definition.trusted_context_claim
    if claim is None:
        return definition
    token = settings.api.auth_token
    if not token:
        raise ValueError("trusted context requires configured API authentication")
    expected = _trusted_context_signature(
        token,
        agent_id=definition.agent_id,
        version=definition.version,
        system_prompt_ref=definition.system_prompt_ref,
        skill_refs=definition.skill_refs,
        context=claim.context,
    )
    if not hmac.compare_digest(claim.signature, expected):
        raise ValueError("trusted context claim signature is invalid")
    return definition.model_copy(
        update={
            "trust_policy": {"trusted_context": claim.context},
            "trusted_context_claim": None,
        }
    )


def _trusted_context_signature(
    token: str,
    *,
    agent_id: str,
    version: str,
    system_prompt_ref: str | None,
    skill_refs: tuple[str, ...],
    context: dict[str, object],
) -> str:
    payload = json.dumps(
        {
            "version": "1",
            "agent_id": agent_id,
            "agent_version": version,
            "system_prompt_ref": system_prompt_ref,
            "skill_refs": list(skill_refs),
            "context": context,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    key = hmac.new(token.encode("utf-8"), b"zebra-trusted-context-v1", sha256).digest()
    return hmac.new(key, payload, sha256).hexdigest()
