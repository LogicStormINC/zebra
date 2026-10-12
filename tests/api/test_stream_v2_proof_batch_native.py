"""Actual API proof includes every SQL and opens one fresh snapshot per phase."""

import asyncio
from datetime import UTC, datetime
from time import monotonic

import pytest
from agent_integrations.redis_transient_discovery import discover

from tests.api.test_stream_v2_native import opened
from tests.stream_storage.telemetry import Telemetry, phase
from tests.worker.test_transient_output_composition_native import owned as _owned_fixture

owned = _owned_fixture


def test_native_api_bind_and_qualification_each_use_one_fresh_snapshot(
    owned, monkeypatch, record_property
):
    run, writer, _, reader, bound, _ = opened(owned, monkeypatch, frames=1)
    descriptor, _ = discover(reader.port._client, bound.lane)
    telemetry = Telemetry()
    try:
        with telemetry.installed():
            started = monotonic()
            with phase("bind"):
                assert reader.authority.bind(run.task_id, bound.run_id, bound.host) == bound
            record_property("api_bind_seconds", f"{monotonic() - started:.4f}")
            started = monotonic()
            with phase("qualify"):
                assert reader.authority.qualify(bound, descriptor) > datetime.now(UTC)
            record_property("api_qualify_seconds", f"{monotonic() - started:.4f}")
        for stage in ("bind", "qualify"):
            for metric in ("new_pg_socket", "client_commit", "statement:set"):
                assert telemetry.calls[f"initial/{stage}/{metric}"] == 1
            sql = sum(value for key, value in telemetry.calls.items() if f"/{stage}/sql:" in key)
            record_property(f"api_{stage}_sql", sql)
            record_property(
                f"api_{stage}_sockets", telemetry.calls[f"initial/{stage}/new_pg_socket"]
            )
        run.stores.leases.release(run.session_id, fence=writer._auth.lease_fence)
        with pytest.raises(ValueError, match="lease fence"):
            reader.authority.qualify(bound, descriptor)
    finally:
        writer.close()
        asyncio.run(reader.close())
