"""Opt-in child-only diagnostic; profile timings are not E1 SLO samples."""

import os
import sys

if (
    os.environ.get("ZEBRA_HA_E1_CHILD_PROFILE") == "1"
    and os.environ.get("ZEBRA_DEPLOYMENT_NAMESPACE") == "ha-e1-20261102"
    and sys.orig_argv[1:4] == ["-m", "zebra_agent_worker.session_process_child", "--execute"]
):
    import atexit
    import cProfile
    import tempfile

    # ponytail: one diagnostic Task per node; export profiles before further runs.
    descriptor, filename = tempfile.mkstemp(
        prefix=f"zebra-ha-e1-child-{os.getpid()}-", suffix=".pstats"
    )
    os.close(descriptor)
    profile = cProfile.Profile()
    atexit.register(profile.dump_stats, filename)
    profile.enable()
