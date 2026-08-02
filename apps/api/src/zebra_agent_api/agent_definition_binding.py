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
    context = resolve_agent_definition_context(
        definition,
        scoped_skill_roots(settings),
        skills_state=runtime_skills_state(settings),
    )
    if not (definition.system_prompt_ref or definition.skill_refs):
        return definition
    if context is None:
        raise ValueError("agent definition context could not be resolved")
    return definition.model_copy(
        update={"resolved_context_digest": context.resolved_context_digest}
    )
