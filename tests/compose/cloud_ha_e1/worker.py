"""E1 operator factory constructed inside the native CLI resource lifecycle."""

from e1_composition import compose
from zebra_agent_worker.main import main

raise SystemExit(main(cloud_worker_composition_factory=compose))
