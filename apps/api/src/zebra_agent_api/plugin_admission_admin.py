"""Explicit CAS approval of a product publisher; no startup DDL or automatic trust."""

import argparse

import psycopg
from agent_storage.postgres.host_management import HostManagementStore
from zebra_agent_config import load_settings

from zebra_agent_api.plugin_admission_config import load_plugin_approval


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-revision", type=int, required=True)
    parser.add_argument("--deployment-namespace", required=True)
    args = parser.parse_args()
    try:
        settings = load_settings()
        config = load_plugin_approval(settings.plugin_admission_config, args.deployment_namespace)
        if not settings.database_url.startswith(("postgres://", "postgresql://")):
            raise ValueError("POSTGRES_REQUIRED")
        HostManagementStore(
            settings.database_url, deployment_namespace=args.deployment_namespace
        ).approve(config.trust, args.expected_revision)
    except (OSError, ValueError, TypeError, PermissionError, psycopg.Error):
        print("Plugin publisher approval rejected; inspect private configuration/schema/revision")
        return 1
    print("Plugin publisher approval committed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
