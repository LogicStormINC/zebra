"""Explicit gate approval/namespace binding; no DDL, drain, open or deployment."""

import argparse

from agent_storage.postgres.host_management import HostManagementStore
from agent_storage.postgres.runtime_gates import RuntimeGateStore
from zebra_agent_config import load_settings

from zebra_agent_api.runtime_gate_termination_config import (
    RuntimeGateTerminationApproval,
    load_runtime_gate_termination_approval,
)
from zebra_agent_api.runtime_gates_config import RuntimeGateApproval, load_runtime_gate_approval


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--termination", action="store_true", help="separate original termination approval only"
    )
    parser.add_argument("--deployment-namespace", required=True)
    parser.add_argument("--expected-revision", required=True, type=int)
    args = parser.parse_args()
    try:
        settings = load_settings()
        approval: RuntimeGateApproval | RuntimeGateTerminationApproval
        if args.termination:
            approval = load_runtime_gate_termination_approval(
                settings.runtime_gate_termination_config, args.deployment_namespace
            )
        else:
            approval = load_runtime_gate_approval(
                settings.runtime_gate_config, args.deployment_namespace
            )
        HostManagementStore(
            settings.database_url, deployment_namespace=args.deployment_namespace
        ).approve(approval.trust, args.expected_revision)
        if not args.termination:
            RuntimeGateStore(settings.database_url, approval.scope, approval.trust).initialize()
    except Exception:
        print("Gate approval incomplete; inspect schema/current approval before explicit retry")
        return 1
    print("Runtime gate authority committed; termination approval does not initialize a namespace")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
