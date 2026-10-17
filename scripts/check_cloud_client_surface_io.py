"""Native client-admission pairs on an owned fixture DB; never invokes a model."""

from __future__ import annotations

import json
import os
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from time import monotonic
from uuid import uuid4

import psycopg
from agent_core.domain.client_capabilities import FrontendCapabilityBinding
from agent_storage.postgres.client_capabilities import PostgresClientCapabilityRegistry
from agent_storage.postgres.client_control_leases import PostgresClientControlLeaseStore
from agent_storage.postgres.client_sessions import PostgresClientSessionRegistry
from agent_storage.postgres.task_io import TaskIoConnections
from zebra_agent_api import client_surface
from zebra_agent_api.client_runtime_routes import handle_client_runtime_route

from tests.agent_storage.test_postgres_task_projection_checkpoints import checkpoint_dsn
from tests.api.test_client_surface_open import opening
from tests.api.test_task_resource_binding import binding_for
from tests.worker import test_model_commentary_native as native


def run(root: Path) -> None:
    assert os.environ.get("ZEBRA_TEST_POSTGRES_DSN"), "explicit owned scratch DSN required"
    root.mkdir(parents=True, exist_ok=True)
    assert not (root / "native-pairs.safe.json").exists(), "refuse to overwrite a completed cohort"
    fixture = checkpoint_dsn.__wrapped__()
    dsn = next(fixture)
    original_scope = client_surface.postgres_connection_scope
    original_open = TaskIoConnections._open
    originals = {cls: cls.execute for cls in (psycopg.Cursor, psycopg.ClientCursor)}
    active: dict[str, float] | None = None
    depth = 0

    def opened(self, *args, **kwargs):
        start = monotonic()
        try:
            return original_open(self, *args, **kwargs)
        finally:
            if active is not None:
                active["physical_opens"] += 1
                active["open_ms"] += (monotonic() - start) * 1000

    def wrap(original):
        def execute(self, query, *args, **kwargs):
            nonlocal depth
            depth += 1
            try:
                return original(self, query, *args, **kwargs)
            finally:
                if active is not None and depth == 1:
                    text = str(query).strip().upper()
                    key = "reset_sql" if text == "DISCARD ALL" else "driver_sql"
                    active[key] += 1
                depth -= 1

        return execute

    rows = []
    try:
        TaskIoConnections._open = opened
        for cls, original in originals.items():
            cls.execute = wrap(original)
        for pair, arms in enumerate(((False, True), (True, False), (True, False), (False, True))):
            for enabled in arms:
                native.NS = "start-admission-" + uuid4().hex
                state = native.native_state(dsn)
                app, fake, request = opening()
                shared = TaskIoConnections(dsn)
                options = dict(deployment_namespace=native.NS, task_io_connections=shared)
                profiles = PostgresClientCapabilityRegistry(dsn, **options)
                sessions = PostgresClientSessionRegistry(dsn, **options)
                leases = PostgresClientControlLeaseStore(dsn, **options)
                profile = next(iter(fake.frontend_capabilities.profiles.values()))
                profiles.publish_profile(profile)
                grant = request.verified_host_grant
                profiles.save_binding(
                    FrontendCapabilityBinding(
                        binding_id=uuid4(),
                        deployment_namespace=native.NS,
                        host_app_id=grant.context.host_app_id,
                        namespace_id=grant.context.namespace_id,
                        frontend_app_id=profile.frontend_app_id,
                        revision=profile.revision,
                        profile_digest=profile.profile_digest,
                        binding_revision=1,
                        bound_at=datetime.now(UTC),
                    ),
                    expected_binding_revision=0,
                )
                app.client_platform = replace(
                    fake,
                    frontend_capabilities=profiles,
                    client_sessions=sessions,
                    client_control_leases=leases,
                )
                task = state.tasks.ensure_for_session(state.session.session_id)
                app.stores.tasks = state.tasks
                app.cloud_control.load_task_binding = lambda _, grant=grant, task=task: binding_for(
                    grant, task=str(task.task_id)
                )
                request = replace(
                    request,
                    path=request.path.replace(
                        "11111111-1111-4111-8111-111111111111", str(task.task_id)
                    ),
                )
                client_surface.postgres_connection_scope = (
                    original_scope if enabled else lambda **_: nullcontext()
                )
                active = dict(physical_opens=0, open_ms=0.0, driver_sql=0, reset_sql=0)
                start = monotonic()
                result = handle_client_runtime_route(app, request)
                elapsed = (monotonic() - start) * 1000
                counts, active = active, None
                assert result.status_code == 201, result.body
                assert result.body["allowed_actions"] == ["app.ui.item.open"]
                assert result.body["controller"] is True
                rows.append(dict(pair=pair, enabled=enabled, ms=elapsed, **counts))
                print(json.dumps(rows[-1]), flush=True)
        old = [row["ms"] for row in rows if not row["enabled"]]
        new = [row["ms"] for row in rows if row["enabled"]]
        wins = sum(
            next(row["ms"] for row in rows if row["pair"] == pair and row["enabled"])
            < next(row["ms"] for row in rows if row["pair"] == pair and not row["enabled"])
            for pair in range(4)
        )
        gain = (1 - median(new) / median(old)) * 100
        report = dict(
            rows=rows,
            old_median_ms=median(old),
            new_median_ms=median(new),
            gain_pct=gain,
            wins=wins,
            gate=gain >= 10 and wins >= 3,
            limits=("Native real client/profile/lease stores; fixture Host target binding "
                "and namespace lookup. Not full HTTP or page latency."),
        )
        (root / "native-pairs.safe.json").write_text(json.dumps(report, indent=2))
        print(json.dumps({key: value for key, value in report.items() if key != "rows"}))
    finally:
        client_surface.postgres_connection_scope = original_scope
        TaskIoConnections._open = original_open
        for cls, original in originals.items():
            cls.execute = original
        fixture.close()


if __name__ == "__main__":
    import sys

    run(Path(sys.argv[1]))
