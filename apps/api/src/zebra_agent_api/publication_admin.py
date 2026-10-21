"""Explicit native approval tool; never migrates or changes execution data."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

import psycopg
from agent_storage.postgres.host_management import HostManagementStore
from zebra_agent_config import load_settings

from zebra_agent_api.publication_config import load_publication_approval


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-revision", type=int, required=True)
    parser.add_argument("--deployment-namespace", required=True)
    args = parser.parse_args()
    try:
        settings = load_settings()
        if not settings.database_url.startswith(("postgres://", "postgresql://")):
            raise ValueError("PostgreSQL configuration required")
        namespace = args.deployment_namespace
        config = load_publication_approval(settings.publication_management_config, namespace)
        if config.trust.expires_at <= datetime.now(UTC):
            raise ValueError("expired approval")
        HostManagementStore(settings.database_url, deployment_namespace=namespace).approve(
            config.trust, args.expected_revision
        )
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        OverflowError,
        RecursionError,
        TimeoutError,
        PermissionError,
        psycopg.Error,
    ):
        print("Publication management approval rejected; inspect private config/schema/revision")
        return 1
    print("Publication management approval committed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
