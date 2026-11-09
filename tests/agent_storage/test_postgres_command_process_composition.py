"""Real schema cutover markers and actual-DSN process selection without process startup."""

from dataclasses import replace
from types import SimpleNamespace

import psycopg
import pytest
from zebra_agent_worker.command_process_state import command_cutover_state
from zebra_agent_worker.loop import build_worker_loop_service

from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, _enable
from tests.agent_storage.test_postgres_command_wakeup import dsn as _dsn
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _pg
from tests.agent_storage.test_postgres_command_wakeup_discovery import begin_command_backfill
from tests.agent_storage.test_postgres_direct_control_api import _app
from tests.test_cloud_api_worker_profile_composition import _cloud_settings

dsn = _dsn
postgres_dsn = _pg


def test_unmigrated_default_and_explicit_broker_require_cutover(dsn):
    assert command_cutover_state(dsn, NAMESPACE) is False
    with pytest.raises(ValueError, match="cutover"):
        command_cutover_state(dsn, NAMESPACE, require_ready=True)


def test_durable_backfill_marker_cannot_revert_to_legacy_when_admission_disabled(dsn, monkeypatch):
    begin_command_backfill(dsn, deployment_namespace=NAMESPACE)
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE command_wakeup_rollouts SET admission_enabled=false")
    statements = []
    execute = psycopg.Connection.execute

    def record(connection, query, *args, **kwargs):
        statements.append(str(query))
        return execute(connection, query, *args, **kwargs)

    monkeypatch.setattr(psycopg.Connection, "execute", record)
    assert command_cutover_state(dsn, NAMESPACE) is True
    reads = [query for query in statements if query.startswith(("SELECT", "WITH"))]
    assert len(reads) == 2
    assert "zebra_schema_migrations" in reads[-1]


@pytest.mark.parametrize("migrated", [False, True])
def test_actual_composition_selects_exactly_one_consumer_and_its_actual_dsn(
    dsn, tmp_path, monkeypatch, migrated
):
    if migrated:
        _enable(dsn)
    app = _app(dsn)
    captured = {}

    def process(**kwargs):
        captured["same_dsn"] = kwargs["dsn"] == dsn
        captured["namespace"] = kwargs["namespace"]
        captured["method"] = kwargs["execute"].__name__
        return SimpleNamespace(run=lambda **kwargs: None)

    monkeypatch.setattr("zebra_agent_worker.command_process.CommandWorkerProcess", process)
    monkeypatch.setattr(
        "zebra_agent_worker.loop.configure_stream_hint_relay", lambda *_: (None, lambda _: None)
    )
    service = build_worker_loop_service(
        database_path=tmp_path / "unused",
        settings=app.settings,
        cloud_composition=replace(_cloud_settings(), dsn=dsn, deployment_namespace=NAMESPACE),
    )
    assert (service.migrated_run is not None) is migrated
    assert (service._command_consumer is None) is migrated
    if migrated:
        assert captured == {
            "same_dsn": True,
            "namespace": NAMESPACE,
            "method": "execute_claimed_session",
        }
    else:
        assert captured == {}
        _enable(dsn)
        result = service.run(worker_id="worker", max_cycles=1)
        assert result.stop_reason == "cutover_requires_restart" and result.cycles_completed == 0
