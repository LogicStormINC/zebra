"""Agent Layer application services (Agent Control Plane).

Boundary rules frozen by AL-BOUNDARY-CON-01 and ADR-017:

- depends only on ``agent-core`` domain models and Ports;
- never imports the Worker, the Runtime, FastAPI/HTTP frameworks, or the
  PostgreSQL/SQLite storage adapters;
- application composition happens in ``apps/`` composition roots.

Successor cards fill the service modules; this package intentionally starts
with only the admission service seam so the dependency gate has real code to
guard from day one.
"""

from agent_control_plane.admission import AgentAction, route_action
from agent_control_plane.agui_client_admission import (
    AgUiClientAdmission,
    AgUiClientAdmissionError,
    admit_agui_client_payload,
    mounted_snapshot_from_admission,
    redact_client_state,
)
from agent_control_plane.client_admission import (
    ClientAdmission,
    ClientAdmissionError,
    ClientAdmissionService,
    ClientBindingService,
)
from agent_control_plane.client_effects import (
    ClientEffectReceiptService,
    ClientEffectServiceError,
    build_client_effect_continuation,
    build_client_effect_request,
)
from agent_control_plane.frontend_profiles import (
    FrontendProfileService,
    FrontendProfileServiceError,
    ProfilePublication,
)

__all__ = [
    "AgentAction",
    "route_action",
    "AgUiClientAdmission",
    "AgUiClientAdmissionError",
    "admit_agui_client_payload",
    "mounted_snapshot_from_admission",
    "redact_client_state",
    "ClientAdmission",
    "ClientAdmissionError",
    "ClientAdmissionService",
    "ClientBindingService",
    "ClientEffectReceiptService",
    "ClientEffectServiceError",
    "build_client_effect_continuation",
    "build_client_effect_request",
    "FrontendProfileService",
    "FrontendProfileServiceError",
    "ProfilePublication",
]
