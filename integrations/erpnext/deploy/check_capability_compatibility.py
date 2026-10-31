"""Read-only Native114 storage/authority compatibility over the actual ERP clone.

This is not JWT, HTTP, S3, Worker execution or browser capability acceptance.
"""

import importlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
from agent_core.application import project_turns
from agent_core.domain.host_authority import HostResourceRef
from agent_core.domain.identifiers import SessionId, TaskId
from agent_core.domain.task_bindings import require_task_host_context
from agent_storage.postgres.agent_tasks import PostgresAgentTaskStore
from agent_storage.postgres.direct_control import PostgresDirectControl
from agent_storage.postgres.events import PostgresEventStore
from agent_storage.postgres.projections import PostgresProjectionStore
from check_capability_upgrade import read_inventory, require_isolated


def must_refuse(binding, context, task_id):
    try:
        require_task_host_context(
            binding,
            context,
            task_id=task_id,
            now=datetime.now(UTC),
            authority_issuer=binding.host_capability.authority_issuer,
        )
    except ValueError:
        return
    raise AssertionError("Native accepted a mismatched or expired context")


def main():
    dsn = os.environ["ERP_CAPABILITY_QA_DSN"]
    require_isolated(dsn)
    output = Path(os.environ["ERP_CAPABILITY_QA_OUTPUT"])
    if output.exists():
        raise ValueError("Refusing to overwrite earlier compatibility evidence")
    modules = [
        "zebra_agent_api.http",
        "zebra_agent_worker.loop",
        "zebra_agent_scheduler.main",
        "agent_runtime.mcp_catalog_refresh",
    ]
    for module in modules:
        imported = importlib.import_module(module)
        if not str(imported.__file__).startswith("/candidate/"):
            raise ValueError("Candidate imported a frozen105 application module")
    definitions, before = read_inventory(dsn)
    tasks = PostgresAgentTaskStore(dsn, deployment_namespace="erpnext")
    sessions = PostgresProjectionStore(dsn, deployment_namespace="erpnext")
    events = PostgresEventStore(dsn, deployment_namespace="erpnext")
    control = PostgresDirectControl(dsn, deployment_namespace="erpnext")
    with psycopg.connect(dsn) as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        task_ids = [
            r[0]
            for r in connection.execute(
                "SELECT task_id FROM agent_tasks WHERE deployment_namespace='erpn"
                "ext' ORDER BY task_id"
            )
        ]
        source_sessions = connection.execute(
            "SELECT session_id,status,current_sequence "
            "FROM session_projections WHERE deployment_namespace='erpnext' ORDER BY session_id"
        ).fetchall()
    checks, bound, denied, unbound, page_count, event_count = [], 0, 0, 0, 0, 0
    for identity in task_ids:
        task = tasks.get_task(TaskId(identity))
        assert task is not None and task.task_id == identity
        members = tasks.segments(TaskId(identity))
        assert task.active_segment_id in {m.session_id for m in members}
        binding = control.load_task_binding(TaskId(identity))
        if binding is None:
            unbound += 1
            continue  # Historical operator-only rows do not gain Host authority.
        bound += 1
        context = binding.host_capability.host_context
        assert context is not None
        current = context.model_copy(
            update={"expires_at": datetime.now(UTC) + timedelta(minutes=5)}
        )
        require_task_host_context(
            binding,
            current,
            task_id=str(identity),
            now=datetime.now(UTC),
            authority_issuer=binding.host_capability.authority_issuer,
        )
        for key in ["workspace_ref", "namespace_id", "host_app_id", "origin"]:
            must_refuse(binding, current.model_copy(update={key: "other-scope"}), str(identity))
            denied += 1
        refs = tuple(
            HostResourceRef(type="principal", id="other-principal")
            if ref.resource_type == "principal"
            else ref
            for ref in current.resource_refs
        )
        must_refuse(binding, current.model_copy(update={"resource_refs": refs}), str(identity))
        must_refuse(
            binding,
            current.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}),
            str(identity),
        )
        denied += 2
    for identity, status, highwater in source_sessions:
        session = sessions.get_session(SessionId(identity))
        assert session is not None and session.status.value == status
        assert session.current_sequence == highwater
        after, rows = -1, []
        while after < highwater:
            page = events.read_session_event_page(
                SessionId(identity), after, through_sequence=highwater, limit=256, max_bytes=1048576
            )
            assert page.next_sequence > after and page.byte_count <= 1048576
            rows.extend(page.events)
            after = page.next_sequence
            page_count += 1
            event_count += len(page.events)
            assert event_count <= 250000
        turns = project_turns(rows)
        checks.append(
            {
                "session_id": str(identity),
                "status": status,
                "events": len(rows),
                "turns": len(turns),
            }
        )
    _, after = read_inventory(dsn, definitions)
    assert before == after, "Compatibility observation mutated cloned durable data"
    result = {
        "stage": "native_storage_authority_compatible",
        "tasks": len(task_ids),
        "bound_tasks": bound,
        "unbound_operator_only_tasks": unbound,
        "current_scope_refusals": denied,
        "sessions": checks,
        "pages": page_count,
        "events": event_count,
        "candidate_imports": modules,
        "all_tables_unchanged": True,
        "model_calls": 0,
        "search_calls": 0,
        "worker_started": False,
        "pending": [
            "JWT/HTTP and ERP BFF",
            "Worker/runtime/fresh authorization",
            "S3/private quotas",
            "capability-specific and browser acceptance",
        ],
    }
    output.write_text(json.dumps(result, indent=2) + "\n")
    output.chmod(0o600)
    print(json.dumps({k: v for k, v in result.items() if k != "sessions"}), flush=True)


if __name__ == "__main__":
    main()
