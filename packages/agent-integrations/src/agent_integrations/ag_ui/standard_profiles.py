"""Same explicit standard projector/state bindings for API and Worker composition."""

from agent_integrations.ag_ui.profiles import PROFILE_IDS, AgUiProjectionProfile
from agent_integrations.ag_ui.standard_projection import StandardAgUiProjector
from agent_integrations.ag_ui.standard_state import StandardProjectionState


def standard_profiles() -> tuple[AgUiProjectionProfile, ...]:
    return tuple(
        AgUiProjectionProfile(name, StandardAgUiProjector(), state_type=StandardProjectionState)
        for name in PROFILE_IDS
    )
