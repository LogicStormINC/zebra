"""Real Linux execute_isolated + held PG locks + exact OCI cleanup; no model/search."""

import json
import os
import select
import subprocess
from datetime import timedelta
from pathlib import Path
from time import monotonic
from urllib.parse import quote, urlencode
from uuid import uuid4

import psycopg
import pytest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.execution_authority import ExecutionAuthorityResolutionRequest
from agent_runtime.force_stop_cleanup import recover_force_stops
from agent_storage import PostgresLeaseStore
from psycopg.conninfo import conninfo_to_dict
from zebra_agent_api import RouteAdapter

from tests.agent_runtime.test_command_runtime_cleanup_live import engine as _engine_fixture
from tests.agent_storage.test_postgres_command_wakeup import NAMESPACE, _seed, _store
from tests.agent_storage.test_postgres_command_wakeup import dsn as _dsn_fixture
from tests.agent_storage.test_postgres_command_wakeup import postgres_dsn as _pg_fixture
from tests.agent_storage.test_postgres_direct_control import _rows
from tests.agent_storage.test_postgres_direct_control_api import _app
from tests.agent_storage.test_postgres_force_stop_recovery import due
from tests.agent_storage.test_postgres_force_stops import _force, _progress
from tests.agent_storage.test_postgres_runtime_instances import (
    SCOPE,
    _authority,
    _instances,
    _setup,
)
from tests.compose.rabbitmq_product_e2e.fixture import captured, host_environment

engine = _engine_fixture
dsn = _dsn_fixture
postgres_dsn = _pg_fixture
pytestmark = pytest.mark.skipif(
    os.environ.get("ZEBRA_FORCE_STOP_LIVE") != "1",
    reason="owned Linux/PG/OCI acceptance is explicitly opt-in",
)


def _second_lease(dsn):
    session = _seed(dsn)
    lease = PostgresLeaseStore(dsn, deployment_namespace=NAMESPACE).acquire(
        session.session_id, owner_instance_id="owned-sibling", ttl=timedelta(seconds=120)
    )
    snapshot = _authority(SCOPE).resolve_for_attempt(
        ExecutionAuthorityResolutionRequest(
            session_id=session.session_id,
            attempt_number=1,
            scope=SCOPE,
            validated_at=lease.acquired_at,
        )
    )
    _store(dsn).append(
        SessionEvent.create(
            session_id=session.session_id,
            sequence=session.current_sequence + 1,
            actor=EventActor.SYSTEM,
            event_type=EventType.EXECUTION_AUTHORITY_RESOLVED,
            payload=snapshot.model_dump(mode="json"),
        )
    )
    return lease


def _line(process, timeout=30):
    ready, _, _ = select.select([process.stdout], [], [], timeout)
    assert ready, "owned executor did not report readiness within its budget"
    line = process.stdout.readline().strip()
    assert line, "owned executor exited before reporting readiness (no automatic retry)"
    return line


def _probe(pinned, call, dsn, lease, names):
    image = captured(
        [
            "docker",
            "image",
            "inspect",
            "--format",
            "{{.Id}}",
            os.environ["ZEBRA_FORCE_STOP_TEST_IMAGE"],
        ]
    ).strip()
    repo = Path(__file__).resolve().parents[2]
    paths = [
        "/src",
        *(f"/src/{p.relative_to(repo)}" for p in sorted(repo.glob("packages/*/src"))),
        *(f"/src/{p.relative_to(repo)}" for p in sorted(repo.glob("apps/*/src"))),
    ]
    marker = str(uuid4())
    name = f"force-stop-probe-{marker}"
    result = call(
        "create",
        "--init",
        "--interactive",
        "--network",
        "container:" + os.environ["ZEBRA_FORCE_STOP_TEST_PG_CONTAINER"],
        "--pull=never",
        "--name",
        name,
        "--label",
        f"zebra.force.acceptance={marker}",
        "--mount",
        f"type=bind,src={repo},dst=/src,readonly",
        "--workdir",
        "/tmp",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--env",
        f"PYTHONPATH={':'.join(paths)}",
        "--entrypoint",
        "python",
        image,
        "-u",
        "-m",
        "tests.agent_runtime.force_stop_probe",
    )
    assert result.returncode == 0, "owned Linux executor container creation failed"
    container = result.stdout.strip()
    names.append((container, marker))
    values = conninfo_to_dict(dsn)
    query = urlencode(
        {"options": values.get("options", ""), "application_name": "owned-force-executor"},
        quote_via=quote,
    )
    url = (
        f"postgresql://{quote(values.get('user', 'postgres'), safe='')}:"
        f"{quote(values.get('password', ''), safe='')}@127.0.0.1:"
        f"5432/{values.get('dbname', 'postgres')}?{query}"
    )
    env = {
        "ZEBRA_PROFILE": "cloud",
        "ZEBRA_RUNTIME_CLASS": "gvisor",
        "ZEBRA_RUNTIME_IMAGE": "zebra/runtime@sha256:" + "a" * 64,
        "ZEBRA_RUNTIME_REQUIRE_WORKSPACE_QUOTA": "true",
        "ZEBRA_DATABASE_URL": url,
        "ZEBRA_DEPLOYMENT_NAMESPACE": NAMESPACE,
        "ZEBRA_AUTHORITY_ISSUER": SCOPE.authority_issuer,
        "ZEBRA_HISTORY_SCOPE_NAMESPACE": SCOPE.namespace_id,
        "ZEBRA_CONTINUATION_SCOPE_NAMESPACE": SCOPE.namespace_id,
        "ZEBRA_MEMORY_CURSOR_SIGNING_KEY": "owned-test-cursor-key-never-used-0000",
        "ZEBRA_S3_ENDPOINT": "http://127.0.0.1:1",
        "ZEBRA_S3_BUCKET": "owned-never-used",
        "ZEBRA_S3_ACCESS_KEY": "owned-unused",
        "ZEBRA_S3_SECRET_KEY": "owned-unused",
    }
    process = subprocess.Popen(
        ["docker", "--context", "orbstack", "start", "--attach", "--interactive", container],
        env=host_environment(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    process.stdin.write(json.dumps({"env": env, "lease": lease.model_dump(mode="json")}))
    process.stdin.close()
    try:
        assert _line(process) == "HUNG_FACTORY_READY"
    except AssertionError:
        error = process.stderr.read(24000)
        frames = [line.strip() for line in error.splitlines() if line.lstrip().startswith('File "')]
        tail = error.splitlines()[-1] if error.splitlines() else "no stderr"
        kind = tail.split(":", 1)[0]
        if kind in {"ModuleNotFoundError", "ImportError", "AttributeError"}:
            frames.append(tail)
        raise AssertionError(json.dumps({"startup_error": kind, "frames": frames})) from None
    return process, container


def test_real_stuck_executors_release_only_target_resources_and_sync_after_lock(dsn, engine):
    pinned, worker_dsn, create, call = engine
    lease = _setup(dsn)
    lease = PostgresLeaseStore(dsn, deployment_namespace=NAMESPACE).heartbeat(
        lease.session_id, fence=lease.fence, checkpoint=lease.checkpoint, ttl=timedelta(seconds=120)
    )
    sibling = _second_lease(dsn)
    containers, processes = [], []
    try:
        sandbox_ids = []
        for current in (lease, sibling):
            instances = _instances(dsn, current, engine=pinned.identity)
            instance = str(uuid4())
            labels = dict(instances.reserve(instance, str(current.session_id), "owned-force-spec"))
            labels.update(
                {
                    "zebra.agent.runtime": "1",
                    "zebra.agent.session": str(current.session_id),
                    "zebra.agent.spec": "owned-force-spec",
                }
            )
            cid = create(instance, labels)
            instances.created(instance, cid)
            sandbox_ids.append(cid)
        first, first_container = _probe(pinned, call, dsn, lease, containers)
        processes.append(first)
        second, second_container = _probe(pinned, call, dsn, sibling, containers)
        processes.append(second)
        adapter = RouteAdapter(_app(dsn))
        start = monotonic()
        accepted = adapter.handle(_force(lease.session_id))
        assert accepted.status_code == 202 and not accepted.body["resources_released"]
        assert json.loads(_line(first))["parent_survived"] is True
        assert first.poll() is None  # the shared Worker analogue survived
        detached_path = f"/tmp/force-detached-{lease.session_id}"
        detached_pid = call("exec", first_container, "cat", detached_path).stdout.strip()
        assert detached_pid.isdecimal()
        remaining = call(
            "exec",
            first_container,
            "python",
            "-c",
            f"import os; print(os.path.exists('/proc/{detached_pid}'))",
        )
        assert remaining.stdout.strip() == "False", "escaped process was not reaped"
        termination_ms = round((monotonic() - start) * 1000, 1)
        assert termination_ms < 15000
        # Unrelated transaction blocks ONLY canonical stream sync. Physical cleanup
        # must still complete; it must not be misrepresented as full synchronization.
        with psycopg.connect(dsn) as blocker:
            blocker.execute(
                "SELECT current_version FROM session_streams WHERE "
                "deployment_namespace=%s AND session_id=%s FOR UPDATE",
                (NAMESPACE, lease.session_id),
            )
            assert (
                recover_force_stops(worker_dsn, deployment_namespace=NAMESPACE, engine=pinned) == 0
            )
            pending = adapter.handle(_progress(lease.session_id)).body
            assert pending["execution"] == "stopped" and pending["lease"] == "revoked"
            assert pending["sandbox"] == "cleaned" and pending["synchronization"] == "pending"
            assert not pending["resources_released"]
            blocker.rollback()
        due(dsn)
        assert recover_force_stops(worker_dsn, deployment_namespace=NAMESPACE, engine=pinned) == 1
        done = adapter.handle(_progress(lease.session_id)).body
        assert done["state"] == "stopped" and done["resources_released"]
        assert (
            call("ps", "-aq", "--no-trunc", "--filter", f"id={sandbox_ids[0]}").stdout.strip() == ""
        )
        for cid in (second_container, sandbox_ids[1]):
            assert call("inspect", "--format", "{{.State.Running}}", cid).stdout.strip() == "true"
        assert (
            PostgresLeaseStore(dsn, deployment_namespace=NAMESPACE).get(sibling.session_id)
            is not None
        )
        events = _rows(dsn, "session_events")
        assert (
            sum(
                e["event_type"] == "session_cancelled" and e["session_id"] == lease.session_id
                for e in events
            )
            == 1
        )
        assert (
            sum(
                e["event_type"] == "turn_cancelled" and e["session_id"] == lease.session_id
                for e in events
            )
            == 1
        )
        assert not any(e["event_type"].startswith("model_request") for e in events)
        assert adapter.handle(_force(lease.session_id)).body == accepted.body
        assert recover_force_stops(worker_dsn, deployment_namespace=NAMESPACE, engine=pinned) == 0
        assert _rows(dsn, "session_events") == events
        evidence_path = os.environ.get("ZEBRA_FORCE_STOP_EVIDENCE_PATH")
        if evidence_path:
            path = Path(evidence_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "contract": "cloud-force-stop/1",
                        "termination_ms": termination_ms,
                        "model_requests": 0,
                        "search_requests": 0,
                        "private_descendants_reaped": True,
                        "expired_task_io_did_not_block_control": True,
                        "shared_worker_survived": True,
                        "sibling_executor_survived": True,
                        "sibling_sandbox_survived": True,
                        "raw_lease_revoked": True,
                        "cleanup_preceded_canonical_lock_release": True,
                        "final": done,
                        "idempotent_replay_added_events": 0,
                    },
                    indent=2,
                )
                + "\n"
            )
    finally:
        for cid, marker in containers:
            detail = call("inspect", "--format", "{{json .}}", cid)
            if detail.returncode == 0:
                assert (
                    json.loads(detail.stdout)["Config"]["Labels"]["zebra.force.acceptance"]
                    == marker
                )
                assert call("rm", "--force", cid).returncode == 0
        for process in processes:
            process.wait(timeout=10)
