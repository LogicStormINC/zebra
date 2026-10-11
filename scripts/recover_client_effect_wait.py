"""Dry-run by default; repair one browser wait using configured database authority."""

import argparse
import os
from uuid import UUID

from agent_core.domain.identifiers import SessionId
from agent_storage.postgres.client_effect_recovery import ClientEffectRecovery


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_id", type=UUID)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    recovery = ClientEffectRecovery(
        os.environ["ZEBRA_DATABASE_URL"],
        deployment_namespace=os.environ["ZEBRA_DEPLOYMENT_NAMESPACE"],
    )
    count = recovery.reconcile(session_id=SessionId(args.session_id), dry_run=not args.apply)
    print(f"{'appended' if args.apply else 'eligible'}_recovery_commands={count}")


if __name__ == "__main__":
    main()
