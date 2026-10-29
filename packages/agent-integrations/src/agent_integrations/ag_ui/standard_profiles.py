"""Same explicit standard projector/state bindings for API and Worker composition."""

from agent_integrations.ag_ui.profiles import PROFILE_IDS, AgUiProjectionProfile
from agent_integrations.ag_ui.standard_interaction import InteractionAgUiProjector
from agent_integrations.ag_ui.standard_interaction_state import InteractionProjectionState
from agent_integrations.ag_ui.standard_projection import StandardAgUiProjector
from agent_integrations.ag_ui.standard_state import StandardProjectionState


def standard_profiles(*, interactions: bool = False) -> tuple[AgUiProjectionProfile, ...]:
    existing = tuple(
        AgUiProjectionProfile(name, StandardAgUiProjector(), state_type=StandardProjectionState)
        for name in PROFILE_IDS
    )

    if not interactions:
        return existing
    return existing + tuple(
        AgUiProjectionProfile(
            name, InteractionAgUiProjector(name), revision=2, state_type=InteractionProjectionState
        )
        for name in PROFILE_IDS
    )
