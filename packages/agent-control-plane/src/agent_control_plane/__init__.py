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

__all__ = ["AgentAction", "route_action"]
