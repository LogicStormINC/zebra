"""One marked production canary, no provider/search dispatch or legacy mutations."""

import base64
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

RECEIPT = Path("/tmp/full-production-canary.json")


def save(value):
    RECEIPT.write_text(json.dumps(value, indent=2))
    RECEIPT.chmod(0o600)


def host_prepare():
    import frappe

    from zebra_erpnext import chat, cloud, extensions, features, knowledge, runtime, schedules

    assert frappe.local.site == "192.168.110.42" and not RECEIPT.exists()
    frappe.set_user("Administrator")
    assert not cloud.config()["runtimes"][runtime.FULL]["acceptance_passed"]
    item = chat.create("DEPLOYMENT-CANARY-20261029-" + uuid4().hex[:8])
    frappe.db.set_value("Zebra Conversation", item["name"], "runtime_ref", runtime.FULL)
    frappe.db.commit()
    state = {"conversation": item["name"], "model_calls": 0, "search_calls": 0}
    save(state)  # Persist identity before every external write; never retry blind.
    name = item["name"]
    catalog = features.catalog(name)
    assert catalog["runtime"]["status"] == "available", catalog["runtime"]
    assert all(g["status"] == "available" for g in catalog["groups"] if g["id"] != "erp")
    extensions.configure(name, "analysis", {"skills": [], "mcp": []})
    for kind in ("skills", "mcp"):
        assert isinstance(extensions.inventory(name, kind)["items"], list)
    payload = b"Production deployment canary; no customer data.\n"
    source = knowledge.create(
        name,
        "Deployment canary only",
        {
            "file_name": "deployment-canary.txt",
            "media_type": "text/plain",
            "content_base64": base64.b64encode(payload).decode(),
        },
    )
    frappe.db.commit()
    state["knowledge"] = source["name"]
    save(state)
    knowledge.select(name, [source["name"]])
    schedule = schedules.create(
        name,
        "Deployment canary: never fire",
        "Read canary only",
        {"kind": "once", "fire_at": "2099-01-01T00:00:00Z"},
        str(uuid4()),
    )
    state["schedule"] = schedule["name"]
    save(state)
    schedules.action(name, schedule["name"], "pause", schedule["schedule_version"])
    assert schedules.detail(name, schedule["name"])["status"] == "paused"
    doc = cloud.owned(name)
    run_id = str(uuid4())
    frappe.db.set_value(
        "Zebra Conversation", name, {"active_run_id": run_id, "status": "dispatching"}
    )
    frappe.db.commit()
    state["run_id"] = run_id
    save(state)
    doc = cloud.owned(name)
    task = cloud.request(
        doc,
        "POST",
        "/tasks",
        run_id=run_id,
        key="deployment-canary-" + name,
        body=dict(
            prompt="Deployment canary: no model execution",
            title=doc.title,
            execute=False,
            interaction_mode="conversation",
            history_session_ids=[],
            attachments=knowledge.materialize(doc),
            **chat.saved_options(doc),
            **runtime.profile(doc, cloud.config()),
            skill_components=[],
            workspace_source=dict(kind="host_reference", locator="erpnext://workspace/" + name),
        ),
    )
    state["task"] = task
    state["task_id"] = task["task_id"]
    save(state)
    frappe.db.set_value(
        "Zebra Conversation", name, {"task_id": task["task_id"], "status": "running"}
    )
    frappe.db.commit()
    doc = cloud.owned(name)
    body = chat._run_body(doc, run_id, task["current_sequence"], {}, None, [])
    receipt = cloud.request(
        doc,
        "POST",
        "/agui/commands",
        run_id=run_id,
        key="deployment-canary-admit-" + name,
        body=body,
    )
    state["admission"] = receipt
    save(state)
    print(
        json.dumps(
            {"stage": "production_prepared_no_model", "conversation": name, "task": task["task_id"]}
        )
    )


def worker_check():
    from agent_core.domain.identifiers import SessionId
    from agent_core.ports.runtime import RuntimeExecutionRequest
    from agent_storage import cloud_composition_from_environment
    from agent_storage.postgres.database import PostgresDatabase
    from agent_storage.postgres.task_admission import read_session_task_binding
    from full_worker import compose
    from zebra_agent_config import load_settings
    from zebra_agent_worker.bound_execution_authority import BoundHostExecutionAuthorityResolver
    from zebra_agent_worker.host_execution_authority import HostExecutionAuthority
    from zebra_agent_worker.loop import build_worker_loop_service
    from zebra_agent_worker.runtime_authority import persist_attempt_authority
    from zebra_agent_worker.runtime_setup import build_prepared_runtime, destroy_runtime

    state = json.loads(Path(sys.argv[2]).read_text())
    settings = load_settings()
    cloud = cloud_composition_from_environment()
    assert cloud.deployment_namespace == "erpnext-full" and "native-full-db" in cloud.dsn
    sid = SessionId(UUID(state["task"]["session_id"]))
    composition = compose(settings, cloud)
    service = build_worker_loop_service(
        database_path=Path(settings.database_url),
        settings=settings,
        cloud_worker_composition=composition,
    )
    claims = service._execution_service._claim_service
    claimed = claims.claim_session(
        sid,
        worker_id="production-no-model-canary",
        claimed_at=datetime.now(UTC),
        lease_ttl_seconds=120,
    )
    runtime = prepared = None
    try:
        resolver = composition.workspace_resolver_factory()
        path = resolver.resolve(state["task"]["workspace"], session_id=sid)
        assert resolver.resolve_ready(state["task"]["workspace"], session_id=sid) == path
        db = PostgresDatabase(cloud.dsn, deployment_namespace=cloud.deployment_namespace)
        with db.connect_task_io() as connection:
            binding = read_session_task_binding(connection, cloud.deployment_namespace, sid)
        assert binding is not None and binding.task_id == state["task_id"]
        scope = composition.authority_scope_provider(claimed.recovery.session)
        execution = service._execution_service
        fresh = HostExecutionAuthority.for_execution(execution, sid)
        assert fresh is not None

        def owned():
            claims.heartbeat_lease(claimed.lease, lease_ttl_seconds=120)

        fresh.before_private_input(owned)
        recorder = execution._projection_recorder_factory.build(
            session=claimed.recovery.session,
            workspace=claimed.recovery.workspace,
            lease=claimed.lease,
            ownership_check=owned,
        )
        events = execution._event_store.list_for_session(sid)
        persist_attempt_authority(
            recorder,
            BoundHostExecutionAuthorityResolver(binding=binding),
            scope,
            session_id=sid,
            existing_events=events,
            attempt_number=1,
            created_at=datetime.now(UTC),
        )
        fresh.bind(lambda: recorder, execution._event_store.list_for_session(sid))

        def factory(engine):
            return composition.runtime_instance_factory(
                claimed.lease, scope, binding.host_capability.host_context.workspace_ref, engine
            )

        runtime, prepared = build_prepared_runtime(
            settings,
            Path(settings.database_url),
            workspace_root=path,
            network_profile="none",
            session_id=sid,
            attempt_number=1,
            artifact_store=None,
            created_at=datetime.now(UTC),
            instance_factory=factory,
        )
        code = (
            "import os,socket,json;from pathlib import Path;assert os.getuid("
            ")==65532;assert {n for _,n in socket.if_nameindex()}=={'lo'};ass"
            "ert os.statvfs('/workspace').f_blocks*os.statvfs('/workspace').f"
            "_frsize<=268435456;Path('/workspace/deployment-canary-result.txt"
            "').write_text('6');print(json.dumps({'sum':sum([1,2,3]),'uid':os"
            ".getuid(),'network':'none'}))"
        )
        result = runtime.execute(
            RuntimeExecutionRequest(("python", "-c", code), timeout_seconds=20)
        )
        assert result.succeeded, (result.failure_reason, result.stderr[-1500:])
        assert json.loads(result.stdout)["sum"] == 6
        print(
            json.dumps(
                {
                    "stage": "production_worker_real_gvisor",
                    "probe": json.loads(result.stdout),
                    "fresh_volume_proof": True,
                    "real_lease": True,
                    "quota_bytes": 268435456,
                    "model_calls": 0,
                    "search_calls": 0,
                }
            )
        )
    finally:
        error = destroy_runtime(runtime, None if prepared is None else prepared.handle)
        claims.release_lease(claimed.lease)
        if error:
            raise error


def host_finish():
    import frappe

    from zebra_erpnext import chat, cloud, knowledge, schedules

    assert frappe.local.site == "192.168.110.42"
    frappe.set_user("Administrator")
    state = json.loads(RECEIPT.read_text())
    doc = cloud.owned(state["conversation"])
    assert doc.title.startswith("DEPLOYMENT-CANARY-") and doc.task_id == state["task_id"]
    knowledge.memory(
        doc.name, "create", text="Deployment canary memory only; no business preference."
    )
    assert any(
        m["text"].startswith("Deployment canary memory only")
        for m in knowledge.memory(doc.name)["memories"]
    )
    result = chat.cancel(doc.name)  # Stop only the newly prepared canary before any Worker loop.
    state["stop"] = result
    state["cancelled"] = True
    save(state)
    assert cloud.owned(doc.name).status == "cancelled"
    assert schedules.detail(doc.name, state["schedule"])["status"] == "paused"
    print(
        json.dumps(
            {
                "stage": "production_canary_cancelled",
                "conversation": doc.name,
                "model_calls": 0,
                "search_calls": 0,
            }
        )
    )


def consume_canary_stop():
    from agent_core.contracts import SessionCommand, SessionCommandKind
    from agent_core.contracts.session_commands import validate_accepted_session_command
    from agent_core.domain.identifiers import SessionId
    from agent_storage import cloud_composition_from_environment
    from full_worker import compose
    from zebra_agent_config import load_settings
    from zebra_agent_worker.loop import build_worker_loop_service

    state = json.loads(Path(sys.argv[2]).read_text())
    assert state["cancelled"]
    settings = load_settings()
    cloud = cloud_composition_from_environment()
    assert cloud.deployment_namespace == "erpnext-full"
    sid = SessionId(UUID(state["task"]["session_id"]))
    bundle = compose(settings, cloud)
    service = build_worker_loop_service(
        database_path=Path(settings.database_url),
        settings=settings,
        cloud_worker_composition=bundle,
    )
    event = bundle.stores.events.list_for_session(sid)[-1]
    accepted = validate_accepted_session_command(
        event.payload, session_id=sid, idempotency_key=event.idempotency_key
    )
    assert accepted.kind in {SessionCommandKind.STOP, SessionCommandKind.CANCEL}
    command = SessionCommand(
        command_id=UUID(accepted.command_id),
        session_id=sid,
        kind=accepted.kind,
        expected_revision=accepted.expected_revision,
        idempotency_key=accepted.idempotency_key,
        payload=accepted.payload,
    )
    service._command_consumer._cancel(
        command
    )  # Existing admitted-control path only, never consume RUN.
    assert bundle.stores.sessions.get_session(sid).status.value == "cancelled"
    print(
        json.dumps({"stage": "admitted_canary_stop_applied", "model_calls": 0, "search_calls": 0})
    )


def enable():
    import frappe

    from zebra_erpnext import chat, cloud, features, runtime

    assert frappe.local.site == "192.168.110.42"
    frappe.set_user("Administrator")
    state = json.loads(RECEIPT.read_text())
    assert state["cancelled"]
    p = Path(frappe.get_site_path("site_config.json"))
    config = json.loads(p.read_text())
    config["zebra_agent"]["runtimes"][runtime.FULL]["acceptance_passed"] = True
    p.write_text(json.dumps(config, indent=2))
    frappe.conf.update(config)
    frappe.clear_cache()
    new = chat.create("DEPLOYMENT-ENTRY-CHECK-20261029")
    frappe.db.commit()
    doc = cloud.owned(new["name"])
    assert runtime.release(doc) == runtime.FULL and not doc.task_id
    assert chat.saved_options(doc)["reasoning_effort"] == "high"
    assert features.catalog(doc.name)["runtime"]["status"] == "available"
    state["ordinary_entry"] = doc.name
    state["enabled"] = True
    save(state)
    print(
        json.dumps(
            {
                "stage": "ordinary_new_conversation_full_enabled",
                "conversation": doc.name,
                "runtime": runtime.FULL,
                "model_calls": 0,
                "search_calls": 0,
            }
        )
    )


def host_reads():
    import frappe

    from zebra_erpnext import api as api
    from zebra_erpnext import cloud as cloud
    from zebra_erpnext import knowledge as knowledge
    from zebra_erpnext import resources as resources
    from zebra_erpnext import runtime as runtime

    assert frappe.local.site == "192.168.110.42"
    state = json.loads(RECEIPT.read_text())
    assert state["cancelled"]
    frappe.set_user("Administrator")
    name = state["conversation"]
    assert len(resources.attachments(name)["attachments"]) == 1
    assert len(resources.segments(name)["segments"]) == 1
    assert any(
        m["text"].startswith("Deployment canary memory only")
        for m in knowledge.memory(name)["memories"]
    )
    assert api.snapshot(name)["run_state"]["outcome"] == "cancelled"
    old = frappe.get_doc("Zebra Conversation", "f1p4qpa1me")
    frappe.set_user(old.user)
    assert runtime.release(old) == runtime.LEGACY
    before = (old.task_id, old.active_run_id, old.status)
    restored = api.snapshot(old.name)
    assert restored["messages"] and (old.task_id, old.active_run_id, old.status) == before
    result = dict(
        stage="production_saved_reads",
        legacy_messages=len(restored["messages"]),
        legacy_status=restored["status"],
        canary_attachments=1,
        canary_cancelled=True,
        memory_persisted=True,
        model_calls=0,
        search_calls=0,
    )
    Path("/tmp/full-production-read-gate.json").write_text(json.dumps(result))
    print(json.dumps(result))


def cleanup():
    import frappe

    from zebra_erpnext import chat, cloud, knowledge, schedules

    assert frappe.local.site == "192.168.110.42"
    frappe.set_user("Administrator")
    state = json.loads(RECEIPT.read_text())
    assert state["enabled"]
    doc = cloud.owned(state["conversation"])
    assert doc.title.startswith("DEPLOYMENT-CANARY-")
    memories = knowledge.memory(doc.name)["memories"]
    for item in memories:
        if item["text"] == "Deployment canary memory only; no business preference.":
            knowledge.memory(doc.name, "delete", memory_id=item["memory_id"])
    knowledge.remove(doc.name, state["knowledge"])
    frappe.db.commit()
    detail = schedules.detail(doc.name, state["schedule"])
    assert detail["status"] == "paused"
    schedules.action(doc.name, state["schedule"], "delete", detail["schedule_version"])
    chat.manage(doc.name, delete=True)
    entry = cloud.owned(state["ordinary_entry"])
    assert entry.title == "DEPLOYMENT-ENTRY-CHECK-20261029" and not entry.task_id
    chat.manage(entry.name, delete=True)
    state["fixtures_hidden"] = True
    save(state)
    print(json.dumps({"stage": "canary_only_cleanup", "original_runs_unchanged": True}))


if __name__ == "__main__":
    {"worker": worker_check, "cancel": consume_canary_stop}[sys.argv[1]]()
