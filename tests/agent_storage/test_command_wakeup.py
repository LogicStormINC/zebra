"""No-infrastructure checks for canonical command wakeup admission."""

from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest
from agent_core.contracts import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import SessionId
from agent_core.domain.task_bindings import TaskBindingSnapshot, host_context_digest
from agent_storage.postgres import command_wakeup, events
from psycopg import errors


def _binding(task_id: str, *, tenant: str = "tenant-a", workspace: str = "workspace-a"):
    now = datetime.now(UTC)
    context = HostContextEnvelope(
        grant_id="grant-a",
        host_app_id="trench",
        namespace_id=tenant,
        workspace_ref=workspace,
        resource_refs=({"type": "principal", "id": "user-a"},),
        scopes=("agent.run",),
        limits={"max_runtime_seconds": 60, "max_model_tokens": 100, "max_artifact_bytes": 1024},
        origin="https://trench.example",
        policy_version="test-v1",
    )
    return TaskBindingSnapshot(
        task_id=task_id,
        binding_revision=1,
        bound_at=now,
        zebra_policy_digest="a" * 64,
        effective_capabilities=frozenset({"agent.execute"}),
        agent_capability_ceiling={
            "definition_snapshot_digest": "b" * 64,
            "capability_profile_ref": "test@1",
            "capabilities": ["agent.execute"],
            "resolved_at": now,
        },
        host_capability={
            "host_app_id": "trench",
            "authority_issuer": context.origin,
            "namespace_id": tenant,
            "grant_digest": host_context_digest(context),
            "connector_id": "trench",
            "connector_profile_revision": 1,
            "connector_profile_digest": "c" * 64,
            "manifest_digest": "d" * 64,
            "capabilities": ["agent.execute"],
            "resource_binding_digest": "e" * 64,
            "bound_at": now,
            "host_context": context,
        },
    )


def _command(session_id=None, *, sequence: int = 3, key: str = "command-a"):
    session_id = session_id or SessionId(uuid4())
    command = SessionCommand(
        session_id=session_id,
        kind=SessionCommandKind.RUN,
        expected_revision=sequence - 1,
        idempotency_key=key,
    )
    return SessionEvent.create(
        session_id=session_id,
        sequence=sequence,
        event_type=EventType.SESSION_COMMAND_ACCEPTED,
        actor=EventActor.USER,
        payload=command.event_payload(),
        idempotency_key=key,
    )


def _scope_row(event):
    binding = _binding(str(event.session_id))
    return {
        "namespace_id": "tenant-a",
        "task_id": event.session_id,
        "snapshot_json": binding.model_dump(mode="json"),
        "binding_digest": binding.binding_digest,
    }


class _Connection:
    def __init__(self, rows):
        self.rows = list(rows)
        self.calls = []

    def execute(self, query, params):
        self.calls.append((query, params))
        return SimpleNamespace(fetchone=lambda: self.rows.pop(0))


@pytest.mark.parametrize("rollout", [None, {"admission_enabled": False}])
def test_disabled_does_not_resolve_scope_or_validate_legacy_commands(rollout):
    event = _command().model_copy(update={"payload": {"legacy": True}})
    connection = _Connection([rollout])
    command_wakeup.record_command_wakeup_in_transaction(connection, "deployment", event)
    assert len(connection.calls) == 1 and not connection.rows


def test_non_command_does_not_query_rollout():
    command_wakeup.record_command_wakeup_in_transaction(
        None, "deployment", _command().model_copy(update={"event_type": EventType.SESSION_CREATED})
    )


def test_enabled_missing_scope_refuses_before_any_derived_write():
    connection = _Connection([{"admission_enabled": True}, None])
    with pytest.raises(ValueError, match="authoritative Session"):
        command_wakeup.record_command_wakeup_in_transaction(connection, "deployment", _command())
    assert all("INSERT" not in query for query, _ in connection.calls)


@pytest.mark.parametrize(
    "field,value",
    [
        ("namespace_id", "other-tenant"),
        ("task_id", uuid4()),
        ("binding_digest", "f" * 64),
    ],
)
def test_db_binding_mismatch_refuses(field, value):
    event = _command()
    connection = _Connection([_scope_row(event) | {field: value}])
    with pytest.raises(ValueError, match="matching bounded Host scope"):
        command_wakeup._scope_from_binding(connection, "deployment", event)


@pytest.mark.parametrize("workspace", ["x" * 257, "bad\nworkspace"])
def test_oversize_or_invalid_host_scope_not_truncated(workspace):
    event = _command()
    binding = _binding(str(event.session_id), workspace=workspace)
    row = _scope_row(event) | {
        "snapshot_json": binding.model_dump(mode="json"),
        "binding_digest": binding.binding_digest,
    }
    with pytest.raises(ValueError, match="matching bounded Host scope"):
        command_wakeup._scope_from_binding(_Connection([row]), "deployment", event)


def test_db_context_digest_is_checked_without_copying_hash_rules():
    event = _command()
    row = _scope_row(event)
    row["snapshot_json"]["host_capability"]["host_context"]["workspace_ref"] = "tampered"
    with pytest.raises(ValueError, match="matching bounded Host scope"):
        command_wakeup._scope_from_binding(_Connection([row]), "deployment", event)


def test_envelope_uses_db_scope_and_canonical_event_epoch_key():
    event = _command().model_copy(update={"idempotency_key": "wakeup:parent:epoch"})
    scope = command_wakeup._scope_from_binding(
        _Connection([_scope_row(event)]), "deployment", event
    )
    envelope = command_wakeup._envelope("deployment", event, scope)
    assert envelope.scope.tenant_id == "tenant-a"
    assert envelope.scope.workspace_id == "workspace-a"
    assert envelope.idempotency_key == "wakeup:parent:epoch"
    assert envelope.accepted_event_id == str(event.event_id)
    assert envelope.accepted_sequence == event.sequence
    assert envelope.operation_id == event.payload["command_id"]
    assert command_wakeup._envelope("deployment", event, scope) == envelope


@pytest.mark.parametrize("path", ["existing", "cas_race", "insert"])
def test_every_canonical_return_projects_only_canonical_event(monkeypatch, path):
    canonical = _command()
    request = canonical.model_copy(update={"event_id": uuid4(), "sequence": 99})
    find = Mock(
        side_effect={"existing": [canonical], "cas_race": [None, canonical], "insert": [None]}[path]
    )
    monkeypatch.setattr(events, "_find_idempotent_event", find)
    monkeypatch.setattr(events, "_advance_stream", lambda *_a: path == "insert")
    record = Mock()
    monkeypatch.setattr(events, "record_command_wakeup_in_transaction", record)
    connection = _Connection([])
    result = events.append_event_in_transaction(connection, "deployment", request)
    assert result is (request if path == "insert" else canonical)
    record.assert_called_once_with(
        connection, "deployment", result, is_new_admission=path == "insert"
    )


def test_unique_violation_rollback_replay_also_projects_canonical(monkeypatch):
    canonical = _command()
    request = canonical.model_copy(update={"event_id": uuid4()})
    failed, replay = MagicMock(), MagicMock()
    failed.execute.side_effect = errors.UniqueViolation("simulated append race")
    contexts = [MagicMock(), MagicMock()]
    contexts[0].__enter__.return_value = failed
    contexts[1].__enter__.return_value = replay
    store = events.PostgresEventStore("not-opened", deployment_namespace="deployment")
    monkeypatch.setattr(store._database, "connect", Mock(side_effect=contexts))
    monkeypatch.setattr(events, "_find_idempotent_event", Mock(side_effect=[None, canonical]))
    monkeypatch.setattr(events, "_advance_stream", lambda *_a: True)
    record = Mock()
    monkeypatch.setattr(events, "record_command_wakeup_in_transaction", record)
    assert store.append(request) is canonical
    record.assert_called_once_with(replay, "deployment", canonical, is_new_admission=False)


def test_conflicting_retry_never_creates_wakeup(monkeypatch):
    canonical = _command()
    request = canonical.model_copy(
        update={"payload": canonical.payload | {"command_id": str(uuid4())}}
    )
    monkeypatch.setattr(events, "_find_idempotent_event", lambda *_a: canonical)
    record = Mock()
    monkeypatch.setattr(events, "record_command_wakeup_in_transaction", record)
    with pytest.raises(ValueError):
        events.append_event_in_transaction(None, "deployment", request)
    record.assert_not_called()


def test_envelope_time_is_stable_after_postgres_timezone_normalization():
    event = _command()
    scope = command_wakeup._scope_from_binding(
        _Connection([_scope_row(event)]), "deployment", event
    )
    offset_event = event.model_copy(
        update={"created_at": event.created_at.astimezone(timezone(timedelta(hours=8)))}
    )
    assert command_wakeup._envelope("deployment", event, scope) == command_wakeup._envelope(
        "deployment", offset_event, scope
    )
