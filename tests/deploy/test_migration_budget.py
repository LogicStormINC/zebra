"""The standalone operator migration uses declared external capacity, not an API root."""

import json
import runpy
from types import SimpleNamespace

import pytest
from agent_storage.postgres import epoch, migration_runner
from agent_storage.postgres.connection_capacity import PROFILE_ENV, capacity_for

from tests.agent_storage.test_postgres_connection_capacity import profile_data


def test_budgeted_operator_migration_can_read_epoch_without_application_root(monkeypatch):
    import zebra_agent_config
    from agent_storage import runtime_composition

    calls = []
    monkeypatch.setenv(PROFILE_ENV, json.dumps(profile_data()))
    monkeypatch.setattr(zebra_agent_config, "load_settings", lambda: SimpleNamespace(
        storage_authority="postgresql", database_url="dbname=one",
    ))
    monkeypatch.setattr(runtime_composition, "cloud_composition_from_environment",
                        lambda: SimpleNamespace(deployment_namespace="operator-test"))
    monkeypatch.setattr(migration_runner, "apply_postgres_migrations",
                        lambda dsn: calls.append("migration"))

    def read_epoch(dsn, **kwargs):
        assert capacity_for(dsn) is None
        calls.append("epoch")

    monkeypatch.setattr(epoch, "read_control_plane_epoch", read_epoch)
    runpy.run_path("docker/migrate.py", run_name="__main__")
    assert calls == ["migration", "epoch"]


def test_operator_does_not_ignore_invalid_budget_profile(monkeypatch):
    monkeypatch.setenv(PROFILE_ENV, "{")
    with pytest.raises(ValueError):
        runpy.run_path("docker/migrate.py", run_name="__main__")
