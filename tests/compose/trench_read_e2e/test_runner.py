from __future__ import annotations

import json
import os
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from run_acceptance import (
    MANIFEST,
    READ_TOOL_NAMES,
    REQUIRED_ENV,
    SCENARIOS,
    append_task_message,
    control_command,
    run_command,
    wait_task_terminal,
    worker_restart,
)
from support import ConfigError, decode_sse, load_config, missing_environment, task_state


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Protocol fixture only; never inspects, launches or faults real containers."""
    from support import origin

    scope = "zebra-progress-e2e-fixture01"
    roles = (
        "trench_api",
        "zebra_api",
        "worker",
        "broker",
        "operator",
        "redis",
        "object_store",
        "postgres",
    )
    ids = {role: sha256(role.encode()).hexdigest() for role in roles}
    env = {name: "https://127.0.0.1:19001" for name in REQUIRED_ENV}
    env.update(
        {
            "ZEBRA_E2E_BASE_URL": "https://127.0.0.1:19002",
            "TRENCH_E2E_RUNTIME_TASKS_URL": "https://scratch-zebra-api:8443/tasks",
            "ZEBRA_E2E_HEALTH_URL": "https://127.0.0.1:19002/health",
            "ZEBRA_E2E_GRANT_EXCHANGE_URL": "https://127.0.0.1:19004/exchange",
            "ZEBRA_E2E_WORKER_RESTART_URL": "https://127.0.0.1:19005/worker-restart",
            "TRENCH_E2E_BUSINESS_SNAPSHOT_URL": "https://127.0.0.1:19005/business-snapshot",
            "TRENCH_E2E_REDIS_URL": "redis://127.0.0.1:19006/0",
            "ZEBRA_E2E_REDIS_URL": "redis://127.0.0.1:19006/1",
            "TRENCH_E2E_OBJECT_STORE_HEALTH_URL": "https://127.0.0.1:19007/health",
            "ZEBRA_E2E_OBJECT_STORE_HEALTH_URL": "https://127.0.0.1:19007/health",
            "TRENCH_E2E_DATABASE_DSN": f"postgresql://127.0.0.1:19008/{scope}_trench",
            "ZEBRA_E2E_DATABASE_DSN": f"postgresql://127.0.0.1:19008/{scope}_zebra",
            "TRENCH_E2E_SESSION_COOKIE": "session=fixture",
            "TRENCH_E2E_EVENT_ID": "event-1",
            "TRENCH_E2E_USER_ID": "user-1",
            "TRENCH_E2E_WORKSPACE_ID": "workspace-1",
            "ZEBRA_E2E_ISOLATION_MANIFEST": str(tmp_path / "isolation.json"),
        }
    )
    config = load_config(env, REQUIRED_ENV)
    variables = {
        "trench_api": {
            "DATABASE_URL": f"postgresql://{scope}-postgres:5432/{scope}_trench",
            "ZEBRA_TASKS_URL": config.runtime_tasks_url,
        },
        "zebra_api": {
            "ZEBRA_DATABASE_URL": f"postgresql://{scope}-postgres:5432/{scope}_zebra",
            "ZEBRA_DEPLOYMENT_NAMESPACE": scope,
        },
        "worker": {
            "ZEBRA_DATABASE_URL": f"postgresql://{scope}-postgres:5432/{scope}_zebra",
            "ZEBRA_DEPLOYMENT_NAMESPACE": scope,
        },
        "broker": {
            "ZEBRA_GRANT_BROKER_NAMESPACE_ID": scope,
            "ZEBRA_GRANT_BROKER_ORIGIN": origin(config.bff_url),
            "ZEBRA_GRANT_BROKER_ISSUER": origin(config.grant_exchange_url),
        },
        "operator": {
            "E2E_WORKER_CONTAINER": ids["worker"],
            "TRENCH_SNAPSHOT_DATABASE_DSN": f"postgresql://{scope}-postgres:5432/{scope}_trench",
        },
    }
    rows = [
        {
            "Id": ids[role],
            "Name": f"/{scope}-{role}",
            "State": {"Running": True},
            "Config": {
                "Labels": {"zebra.e2e.scratch_id": "fixture01"},
                "Env": [f"{key}={value}" for key, value in variables.get(role, {}).items()],
            },
            "NetworkSettings": {
                "Networks": {
                    scope + "-network": {
                        "IPAddress": f"172.25.0.{index + 2}",
                        "Aliases": [f"{scope}-{role}"],
                    }
                },
                "Ports": {
                    "5432/tcp" if role == "postgres" else "8000/tcp": [
                        {"HostIp": "127.0.0.1", "HostPort": str(19001 + index)},
                    ]
                },
            },
        }
        for index, role in enumerate(roles)
    ]
    manifest = {
        "scratch_id": "fixture01",
        "namespace_id": scope,
        "containers": {
            role: {
                "id": row["Id"],
                "config_sha256": sha256(
                    json.dumps(row["Config"], sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
            }
            for role, row in zip(roles, rows, strict=True)
        },
    }
    Path(config.isolation_manifest).write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(
        "support.subprocess.run", lambda *_, **__: SimpleNamespace(stdout=json.dumps(rows))
    )
    monkeypatch.setattr("support.postgres_probe", lambda *_: None)
    return config, rows, manifest


def test_explicit_scratch_contract_accepts_only_pinned_resources(isolated_config):
    from support import validate_isolation

    config, _, _ = isolated_config
    validate_isolation(config)


def test_failed_readonly_database_probe_is_blocked_before_mutation(isolated_config, monkeypatch):
    from support import E2EError, validate_isolation

    monkeypatch.setattr(
        "support.postgres_probe", lambda *_: (_ for _ in ()).throw(E2EError("postgres_unavailable"))
    )
    with pytest.raises(ConfigError):
        validate_isolation(isolated_config[0])


def test_native_binding_old_task_scope_and_indexed_scale(isolated_config, monkeypatch):
    """Opt-in ONLY on a newly created QA database, not an application schema."""
    from urllib.parse import urlsplit

    import psycopg
    from support import E2EError, host_thread_for_task, product_task_binding

    dsn = os.environ.get("TRENCH_QA_NATIVE_BINDING_DSN")
    if not dsn:
        pytest.skip("explicit isolated native database required")
    if not urlsplit(dsn).path.lstrip("/").startswith("zebra-progress-e2e-qa-native-"):
        pytest.fail("explicit newly created scratch database URI required", pytrace=False)
    config = replace(isolated_config[0], trench_database_dsn=dsn)
    # Docker topology is independently tested above; this probe uses a real PG
    # source and real identity reads, no identity monkeypatch or alternate lookup.
    monkeypatch.setattr("support.validate_isolation", lambda *_: None)
    domain = sha256(config.runtime_tasks_url.encode()).hexdigest()
    assert domain != sha256(config.task_url.encode()).hexdigest()
    key = "trench_ai::user-1::workspace-1::conversation"
    old, current = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
    host = "trench-bootstrap-" + "a" * 32
    with psycopg.connect(dsn, autocommit=True) as connection, connection.cursor() as cursor:
        cursor.execute(
            "CREATE TABLE trench_ai_product_conversations (key text PRIMARY KEY, "
            "user_id text, workspace_id text, zebra_task_id text, "
            "deleted_at_ms bigint, messages_json text)"
        )
        cursor.execute(
            "CREATE TABLE trench_ai_task_bindings (runtime_domain text, task_id text, "
            "conversation_key text REFERENCES trench_ai_product_conversations(key), "
            "user_id text, workspace_id text, host_thread text, "
            "PRIMARY KEY(runtime_domain,task_id))"
        )
        cursor.execute(
            "INSERT INTO trench_ai_product_conversations VALUES (%s,%s,%s,%s,NULL,%s)",
            (key, "user-1", "workspace-1", current, "not json:" + "x" * 1_048_576),
        )
        for task in (old, current):
            cursor.execute(
                "INSERT INTO trench_ai_task_bindings VALUES (%s,%s,%s,%s,%s,%s)",
                (domain, task, key, "user-1", "workspace-1", host),
            )
        cursor.execute(
            "SELECT count(*) FROM trench_ai_task_bindings WHERE runtime_domain=%s AND task_id=%s",
            (sha256(config.task_url.encode()).hexdigest(), old),
        )
        assert cursor.fetchone() == (0,)  # The former external-URL lookup cannot recover H.
        assert host_thread_for_task(config, old) == host
        canonical = replace(config, runtime_tasks_url="https://SCRATCH-ZEBRA-API:8443/tasks/")
        assert host_thread_for_task(canonical, old) == host
        assert product_task_binding(config, "conversation") == current
        for changed in (
            replace(config, user_id="foreign"),
            replace(config, workspace_id="foreign"),
            replace(config, runtime_tasks_url="https://foreign-zebra-api:8443/tasks"),
        ):
            with pytest.raises(E2EError):
                host_thread_for_task(changed, old)
        with pytest.raises(E2EError):
            host_thread_for_task(config, "33333333-3333-4333-8333-333333333333")
        cursor.execute("UPDATE trench_ai_product_conversations SET deleted_at_ms=1")
        with pytest.raises(E2EError):
            host_thread_for_task(config, old)
        cursor.execute("UPDATE trench_ai_product_conversations SET deleted_at_ms=NULL")
        previous = 0
        for count in (1000, 10000, 100000):
            cursor.execute(
                "INSERT INTO trench_ai_task_bindings SELECT %s,"
                "'00000000-0000-4000-8000-'||lpad(n::text,12,'0'),%s,"
                "'user-1','workspace-1',%s FROM generate_series(%s::integer,%s::integer) n",
                (domain, key, host, previous + 1, count),
            )
            previous = count
            cursor.execute("ANALYZE trench_ai_task_bindings")
            cursor.execute(
                "EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) SELECT b.host_thread "
                "FROM trench_ai_task_bindings b JOIN trench_ai_product_conversations c "
                "ON c.key=b.conversation_key WHERE b.runtime_domain=%s AND b.task_id=%s "
                "AND b.user_id=%s AND b.workspace_id=%s AND c.deleted_at_ms IS NULL",
                (domain, old, "user-1", "workspace-1"),
            )
            plan = cursor.fetchone()[0][0]["Plan"]
            pending, visited = [plan], 0
            names = []
            while pending:
                node = pending.pop()
                names.append(node["Node Type"])
                visited += (node["Actual Rows"] + node.get("Rows Removed by Filter", 0)) * node[
                    "Actual Loops"
                ]
                pending.extend(node.get("Plans", []))
            assert "Index Scan" in names and visited <= 4
            assert host_thread_for_task(config, old) == host
            print(
                f"native_binding rows={count} actual_rows_and_filtered={visited} "
                "index_seek=true body_decode=false"
            )


@pytest.mark.parametrize(
    "failure",
    (
        "app_name",
        "app_network",
        "missing_label",
        "stale_config",
        "wrong_worker",
        "broker_namespace",
        "broker_origin",
        "application_db",
        "application_url",
        "wrong_port",
        "runtime_domain",
        "database_server",
        "native_database_route",
    ),
)
def test_isolation_rejects_application_or_retargeted_resources(isolated_config, failure):
    from support import validate_isolation

    config, rows, manifest = isolated_config
    if failure == "app_name":
        rows[2]["Name"] = "/zebra-application-zebra-worker-1"
    if failure == "app_network":
        rows[2]["NetworkSettings"]["Networks"] = {"zebra-dependencies": {}}
    if failure == "missing_label":
        rows[2]["Config"]["Labels"] = {}
    if failure == "stale_config":
        rows[2]["Config"]["Env"].append("NEW_SETTING=retargeted")
    if failure == "wrong_worker":
        rows[4]["Config"]["Env"][0] = "E2E_WORKER_CONTAINER=zebra-application-zebra-worker-1"
    if failure == "broker_namespace":
        rows[3]["Config"]["Env"][0] = "ZEBRA_GRANT_BROKER_NAMESPACE_ID=trench-prod"
    if failure == "broker_origin":
        rows[3]["Config"]["Env"][1] = "ZEBRA_GRANT_BROKER_ORIGIN=https://application.local"
    if failure == "application_db":
        config = replace(config, trench_database_dsn="postgresql://127.0.0.1/trench")
    if failure == "application_url":
        config = replace(config, bff_url="https://application.local")
    if failure == "wrong_port":
        config = replace(config, worker_restart_url="https://127.0.0.1:19001/worker-restart")
    if failure == "runtime_domain":
        config = replace(config, runtime_tasks_url="https://foreign-zebra-api:8443/tasks")
    if failure == "database_server":
        config = replace(
            config, trench_database_dsn=config.trench_database_dsn.replace("19008", "5432")
        )
    if failure == "native_database_route":
        database = config.trench_database_dsn.rsplit("/", 1)[-1]
        rows[0]["Config"]["Env"][0] = f"DATABASE_URL=postgresql://application-db/{database}"
    # Deep resource checks must reject even an operator-repinned invalid namespace/target.
    if failure in {"wrong_worker", "broker_namespace", "broker_origin", "native_database_route"}:
        for spec, row in zip(manifest["containers"].values(), rows, strict=True):
            spec["config_sha256"] = sha256(
                json.dumps(row["Config"], sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        Path(config.isolation_manifest).write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid_environment"):
        validate_isolation(config)


@pytest.mark.parametrize(
    "action,args",
    (
        ("create_product_conversation", ()),
        ("run_product_turn", ("conversation", "prompt")),
        ("command", ("task", "run", "stop", 1)),
        ("append_task_message", ("task", "run", "text")),
        ("worker_restart", ("task", "run")),
    ),
)
def test_every_mutating_helper_checks_isolation_before_request(monkeypatch, action, args):
    import run_acceptance

    monkeypatch.setattr(
        "run_acceptance.validate_isolation",
        lambda *_: (_ for _ in ()).throw(ConfigError([], ["scratch_isolation"])),
    )
    requests = []
    monkeypatch.setattr("run_acceptance.request", lambda *_, **__: requests.append(True))
    with pytest.raises(ConfigError):
        getattr(run_acceptance, action)(object(), *args)
    assert not requests


def test_fourteen_joint_contracts_and_100_samples_are_not_nine_smoke_results():
    document = json.loads(MANIFEST.read_text(encoding="utf-8"))["joint_acceptance"]
    assert len(document["cases"]) == len({case["id"] for case in document["cases"]}) == 14
    assert document["minimum_healthy_turns"] == 100
    assert document["fault_samples_separate"] is True
    assert document["legacy_nine_scenarios_are_not_joint_closure"] is True
    assert all(case["requires"] for case in document["cases"])


def test_production_origins_are_rejected_before_any_runner_writes(tmp_path, monkeypatch):
    from run_acceptance import _run

    monkeypatch.setattr("run_acceptance.load_config", lambda *_: object())
    monkeypatch.setattr(
        "run_acceptance.validate_isolation",
        lambda *_: (_ for _ in ()).throw(ConfigError([], ["scratch_isolation"])),
        raising=False,
    )
    writes = []
    monkeypatch.setattr("run_acceptance.request", lambda *args, **kwargs: writes.append(args))
    assert _run(tmp_path) == 2
    assert not writes


def test_task_header_uses_durable_host_thread_for_grant_not_task_uuid(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "support.host_thread_for_task", lambda *_: "trench-bootstrap-opaque", raising=False
    )
    monkeypatch.setattr(
        "support.obtain_grant", lambda _config, thread, run: calls.append((thread, run)) or "grant"
    )
    monkeypatch.setattr(
        "support.request",
        lambda _method, url, **_: calls.append(url)
        or type(
            "Response", (), {"status": 200, "json": lambda self: {"active_segment_sequence": 7}}
        )(),
    )
    config = type(
        "Config",
        (),
        {"task_url": "https://scratch.local/tasks", "request_id": "r", "timeout_seconds": 30},
    )()
    assert task_state(config, "task-k", "run-r") == 7
    assert calls == [
        ("trench-bootstrap-opaque", "run-r"),
        "https://scratch.local/tasks/task-k/header",
    ]


def test_manifest_covers_each_acceptance_scenario_and_required_input() -> None:
    document = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert document["schema_version"] == "zebra.trench-read-e2e.runner-manifest.v1"
    assert {item["id"] for item in document["scenarios"]} == set(SCENARIOS)
    assert set(document["required_environment"]) == set(REQUIRED_ENV)
    script = Path(__file__).with_name("run_acceptance.py")
    assert script.is_file()


def test_missing_environment_is_explicit_and_never_a_skip() -> None:
    missing = missing_environment({}, REQUIRED_ENV)
    assert set(missing) == set(REQUIRED_ENV)
    try:
        load_config({}, REQUIRED_ENV)
    except ConfigError as error:
        assert error.missing == missing
        assert error.invalid == []
    else:
        raise AssertionError("empty environment must be blocked")


def test_database_and_redis_dsns_are_not_validated_as_http_endpoints() -> None:
    environment = {name: "https://service.local" for name in REQUIRED_ENV}
    environment.update(
        {
            "TRENCH_E2E_SESSION_COOKIE": "trench_ai_session=fixture",
            "TRENCH_E2E_EVENT_ID": "event-1",
            "TRENCH_E2E_DATABASE_DSN": "postgresql://localhost/trench",
            "TRENCH_E2E_REDIS_URL": "redis://localhost:6379/0",
            "ZEBRA_E2E_DATABASE_DSN": "postgresql://localhost/zebra",
            "ZEBRA_E2E_REDIS_URL": "redis://localhost:6379/1",
        }
    )

    config = load_config(environment, REQUIRED_ENV)

    assert config.trench_redis_url == "redis://localhost:6379/0"
    assert config.zebra_redis_url == "redis://localhost:6379/1"


def test_sse_decoder_keeps_opaque_cursor_and_bounded_payload() -> None:
    event = decode_sse("cursor-1", ['{"type":"RUN_STARTED","runId":"run-1"}'])
    assert event is not None
    assert event.cursor == "cursor-1"
    assert event.data["type"] == "RUN_STARTED"
    assert decode_sse(None, []) is None


def test_read_tool_contract_includes_trench_native_history_tools() -> None:
    assert READ_TOOL_NAMES == {
        "events.get_event",
        "events.get_evidence",
        "events.get_related_events",
        "events.get_entity_timeline",
        "events.get_topic",
        "sources.list",
        "sources.get_status",
        "subscriptions.list_history",
        "events.search_history",
        "events.get_historical_event",
        "events.trace_historical_event",
        "sources.add",
        "sources.inspect_url",
        "sources.pause",
        "sources.remove",
        "sources.resolve_candidate",
        "sources.resume",
        "sources.search",
    }


def test_worker_restart_uses_declared_operator_header(monkeypatch) -> None:
    monkeypatch.setattr("run_acceptance.validate_isolation", lambda *_: None)
    captured = {}

    class Response:
        status = 200

    monkeypatch.setattr(
        "run_acceptance.request",
        lambda method, url, **kwargs: captured.update(kwargs) or Response(),
    )
    config = type(
        "Config",
        (),
        {
            "operator_token": "operator-token",
            "request_id": "request-id",
            "worker_restart_url": "https://operator.local/worker-restart",
            "timeout_seconds": 30,
        },
    )()

    worker_restart(config, "task", "run")

    assert captured["headers"]["X-E2E-Operator-Token"] == "operator-token"
    assert "Authorization" not in captured["headers"]


def test_append_task_message_uses_rollover_revision(monkeypatch) -> None:
    captured = {}

    class Response:
        status = 201

        @staticmethod
        def json():
            return {"active_segment_sequence": 42, "current_sequence": 43}

    monkeypatch.setattr("run_acceptance.obtain_grant", lambda *_args: "grant")
    monkeypatch.setattr("run_acceptance.validate_isolation", lambda *_: None)
    monkeypatch.setattr("run_acceptance.host_thread_for_task", lambda *_: "trench-bootstrap-opaque")
    monkeypatch.setattr(
        "run_acceptance.request",
        lambda method, url, **kwargs: captured.update({"method": method, "url": url, **kwargs})
        or Response(),
    )
    config = type(
        "Config",
        (),
        {
            "task_url": "https://zebra.local/tasks",
            "request_id": "request-id",
            "timeout_seconds": 30,
        },
    )()

    revision = append_task_message(config, "task/1", "run-1", "Continue safely.")

    assert revision == 42
    assert captured["method"] == "POST"
    assert captured["url"] == "https://zebra.local/tasks/task%2F1/messages"
    assert captured["headers"]["Authorization"] == "Bearer grant"
    assert captured["payload"]["reasoning_effort"] == "high"


def test_control_command_retries_a_revision_race(monkeypatch) -> None:
    seen = []

    monkeypatch.setattr("run_acceptance.task_state", lambda *_args: 10)

    def fake_command(_config, _task_id, _run_id, action, revision, input_payload):
        seen.append((action, revision, input_payload))
        if len(seen) == 1:
            from support import E2EError

            raise E2EError("http_409_revision_conflict_current_12")
        return {"status": "accepted"}

    monkeypatch.setattr("run_acceptance.command", fake_command)
    monkeypatch.setattr("run_acceptance.time.sleep", lambda _seconds: None)

    result = control_command(object(), "task", "run", "resume")

    assert result == {"status": "accepted"}
    assert [revision for _, revision, _ in seen] == [10, 12]
    assert seen[-1][2]["forwardedProps"]["expectedRevision"] == 12


def test_run_command_rebuilds_input_after_revision_race(monkeypatch) -> None:
    seen = []

    monkeypatch.setattr("run_acceptance.task_state", lambda *_args: 20)

    def fake_command(_config, _task_id, _run_id, action, revision, input_payload):
        seen.append((action, revision, input_payload))
        if len(seen) == 1:
            from support import E2EError

            raise E2EError("http_409_https_zebra_invalid_problems_revision_conflict_current_22")
        return {"status": "accepted"}

    monkeypatch.setattr("run_acceptance.command", fake_command)
    monkeypatch.setattr("run_acceptance.time.sleep", lambda _seconds: None)

    result = run_command(object(), "task", "run", "Continue safely.")

    assert result == {"status": "accepted"}
    assert [revision for _, revision, _ in seen] == [20, 22]
    assert seen[-1][2]["forwardedProps"]["expectedRevision"] == 22


def test_task_state_uses_active_segment_revision(monkeypatch) -> None:
    class Response:
        status = 200

        @staticmethod
        def json():
            return {"active_segment_sequence": 7, "current_sequence": 99}

    monkeypatch.setattr("support.obtain_grant", lambda *_args: "grant")
    monkeypatch.setattr("support.host_thread_for_task", lambda *_: "trench-bootstrap-opaque")
    monkeypatch.setattr("support.request", lambda *_args, **_kwargs: Response())
    config = type(
        "Config",
        (),
        {
            "task_url": "https://zebra.local/tasks",
            "request_id": "request-id",
            "timeout_seconds": 30,
        },
    )()

    assert task_state(config, "task", "run") == 7


def test_wait_task_terminal_waits_for_task_projection(monkeypatch) -> None:
    statuses = iter(("running", "awaiting_turn"))

    class Response:
        status = 200

        @staticmethod
        def json():
            return {"status": next(statuses)}

    monkeypatch.setattr("run_acceptance.obtain_grant", lambda *_args: "grant")
    monkeypatch.setattr("run_acceptance.host_thread_for_task", lambda *_: "trench-bootstrap-opaque")
    monkeypatch.setattr("run_acceptance.request", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr("run_acceptance.time.sleep", lambda _seconds: None)
    config = type(
        "Config",
        (),
        {
            "task_url": "https://zebra.local/tasks",
            "request_id": "request-id",
            "timeout_seconds": 30,
        },
    )()

    wait_task_terminal(config, "task", "run")
