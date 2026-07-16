from zebra_agent_api.session_memory_follow_through_outcome_mixin import (
    SessionMemoryFollowThroughOutcomeMixin,
)
from zebra_agent_api.session_memory_follow_through_verification_mixin import (
    SessionMemoryFollowThroughVerificationMixin,
)


class SessionMemoryFollowThroughMixin(
    SessionMemoryFollowThroughOutcomeMixin,
    SessionMemoryFollowThroughVerificationMixin,
):
    pass
