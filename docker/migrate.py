"""Retry-only readiness wrapper for the lock-protected PostgreSQL migrations."""

from __future__ import annotations

import time

_MAX_ATTEMPTS = 30
_RETRY_DELAY_SECONDS = 2


def main() -> None:
    from zebra_agent_config import load_settings

    settings = load_settings()
    if settings.storage_authority != "postgresql":
        raise SystemExit(
            f"{settings.profile} profile cannot run PostgreSQL migrations"
        )
    dsn = settings.database_url
    import psycopg
    from agent_storage.postgres.epoch import (
        PostgresControlPlaneEpochError,
        bootstrap_control_plane_epoch,
        read_control_plane_epoch,
    )
    from agent_storage.postgres.migration_runner import apply_postgres_migrations
    from agent_storage.runtime_composition import cloud_composition_from_environment

    deployment_namespace = cloud_composition_from_environment().deployment_namespace

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            apply_postgres_migrations(dsn)
            try:
                read_control_plane_epoch(
                    dsn, deployment_namespace=deployment_namespace
                )
            except PostgresControlPlaneEpochError:
                bootstrap_control_plane_epoch(
                    dsn, deployment_namespace=deployment_namespace
                )
            return
        except psycopg.OperationalError:
            if attempt == _MAX_ATTEMPTS:
                raise
            time.sleep(_RETRY_DELAY_SECONDS)


if __name__ == "__main__":
    main()
