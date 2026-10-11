"""Pure SQL-witness checks for invocation-local Task policy source reuse."""

from collections import Counter
from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID
from weakref import ref

import pytest
from agent_core.domain.coverage_contracts import coverage_digest
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.task_bindings import TaskBindingSnapshot, host_context_digest
from agent_storage.postgres import coverage_model_source
from agent_storage.postgres.coverage_model_source import task_policy

from tests.agent_core.test_coverage_task_admission import NOW, admission, host
from tests.agent_storage.test_command_wakeup import _binding


@pytest.fixture
def policy_source():
    identity, context = admission(), host()
    session = SessionId(UUID(int=1))
    data = _binding(
        str(session), tenant=context.namespace_id, workspace=context.workspace_ref
    ).model_dump()
    data["host_capability"].update(
        host_context=context, grant_digest=host_context_digest(context),
        grant_expires_at=context.expires_at,
    )
    authority = TaskBindingSnapshot.model_validate(data)
    rows = [
        SessionEvent.create(
            session_id=session, sequence=index, event_type=EventType.TASK_PREPARED,
            actor=EventActor.SYSTEM, created_at=NOW,
            payload={
                "title": "strict", "user_input": "review",
                "coverage_admission": identity.model_dump(mode="json"),
                "host_context": context.model_dump(mode="json"),
            },
        ).model_dump(mode="json")
        for index in range(101)
    ]
    binding = SimpleNamespace(
        session_id=session, task_id=authority.task_id, contract=identity.contract,
        snapshot=SimpleNamespace(source_resource_ref=identity.history_ref),
    )

    class Connection:
        def __init__(self):
            self.counts = Counter()
            self.rows = rows
            self.stream = {"current_version": 100}
            self.history = {"count": 101, "first": 0, "last": 100}
            self.authority = {
                "snapshot_json": authority.model_dump(mode="json"),
                "binding_digest": authority.binding_digest,
            }

        def execute(self, sql, parameters):
            if "event_type='task_prepared'" in sql:
                self.counts["task_pages"] += 1
                assert "ORDER BY sequence LIMIT 100" in sql
                assert parameters[:2] == ("deployment", session)
                selected = [r for r in self.rows if r["sequence"] > parameters[2]][:100]
                return SimpleNamespace(fetchall=lambda: deepcopy(selected))
            if "FROM session_streams" in sql:
                assert "CROSS JOIN LATERAL" in sql
                assert "e.deployment_namespace=s.deployment_namespace" in sql
                assert "e.session_id=s.session_id" in sql
                name = "history"
                result = None if self.stream is None else {**self.stream, **self.history}
            elif "FROM task_binding_snapshots" in sql:
                assert "ORDER BY binding_revision DESC LIMIT 1" in sql
                assert parameters == ("deployment", binding.task_id)
                name, result = "binding", self.authority
            else:
                pytest.fail(f"unexpected query: {sql}")
            self.counts[name] += 1
            return SimpleNamespace(fetchone=lambda: deepcopy(result))

    return Connection(), binding, authority


def test_policy_reads_original_task_pages_once_and_refreshes_binding_each_call(policy_source):
    connection, binding, authority = policy_source
    policy = task_policy(connection, "deployment", binding)
    assert policy.admission_event_digest == coverage_digest(connection.rows[0])
    assert policy.admission_digest == coverage_digest(admission().model_dump(mode="json"))
    assert policy.task_binding_digest == authority.binding_digest
    assert policy.started_at == NOW and policy.max_calls == admission().max_model_calls
    assert connection.counts == Counter(task_pages=3, history=1, binding=1)
    connection.authority["binding_digest"] = "0" * 64
    with pytest.raises(ValueError, match="Task binding"):
        task_policy(connection, "deployment", binding)
    assert connection.counts == Counter(task_pages=6, history=2, binding=2)


@pytest.mark.parametrize("strict", [True, False])
def test_policy_streams_one_traversal_without_retaining_events(policy_source, monkeypatch, strict):
    connection, binding, _ = policy_source
    if not strict:
        for row in connection.rows:
            row["payload"] = {"legacy": row["sequence"]}
    original = coverage_model_source.task_events
    traversals, yielded = [], []

    def streaming(*args):
        traversals.append(1)
        for event in original(*args):
            yielded.append(ref(event))
            yield event
            assert sum(item() is not None for item in yielded) <= 2

    monkeypatch.setattr(coverage_model_source, "task_events", streaming)
    for _ in range(2):
        assert (task_policy(connection, "deployment", binding) is not None) == strict
    assert len(traversals) == 2 and len(yielded) == 202
    assert all(item() is None for item in yielded)


@pytest.mark.parametrize("damage", ["admission", "host", "missing", "before_origin"])
def test_policy_rejects_tampered_originals_including_later_pages(policy_source, damage):
    connection, binding, _ = policy_source
    payload = connection.rows[0 if damage == "before_origin" else -1]["payload"]
    if damage == "admission":
        payload["coverage_admission"]["max_model_calls"] -= 1
    elif damage == "host":
        payload["host_context"]["grant_id"] = "changed"
    else:
        payload.pop("coverage_admission")
    with pytest.raises(ValueError, match="strict Task identity changed or disappeared"):
        task_policy(connection, "deployment", binding)
    assert connection.counts["binding"] == 0
    assert connection.counts["stream"] == connection.counts["history"] == 0


@pytest.mark.parametrize("damage", ["stream", "first", "last", "count", "binding"])
def test_policy_preserves_history_and_binding_guards(policy_source, damage):
    connection, binding, _ = policy_source
    assert task_policy(connection, "deployment", binding) is not None
    connection.counts.clear()
    if damage == "stream":
        connection.stream = None
    elif damage == "binding":
        connection.authority = None
    else:
        connection.history[damage] -= 1
    with pytest.raises(ValueError, match="persisted Task binding|unpruned exact Session history"):
        task_policy(connection, "deployment", binding)
    assert connection.counts == Counter(
        task_pages=3, history=1, **({"binding": 1} if damage == "binding" else {})
    )


def test_policy_without_admission_only_reads_original_task_pages(policy_source):
    connection, binding, _ = policy_source
    for row in connection.rows:
        row["payload"].pop("coverage_admission")
    assert task_policy(connection, "deployment", binding) is None
    assert connection.counts == Counter(task_pages=3)


@pytest.mark.parametrize("provided", [True, False])
def test_replay_forwards_native_policy_to_scoped_preflight(policy_source, monkeypatch, provided):
    from agent_storage.postgres import coverage_model_index

    connection, binding, _ = policy_source
    native = task_policy(connection, "deployment", binding).model_copy(
        update={"validation_mode": "final_certification"}
    )
    connection.counts.clear()
    seen = []

    def lookup(*args):
        seen.append(args)
        return native

    class PreflightReached(Exception):
        pass

    def preflight(*args, **kwargs):
        assert args == (connection, "deployment", binding)
        assert kwargs["_policy"] is native
        assert kwargs["_incremental_keys"] == set()
        raise PreflightReached

    monkeypatch.setattr(coverage_model_source, "task_policy", lookup)
    monkeypatch.setattr(coverage_model_source, "preflight_original_volume", preflight)

    def index(*args, **kwargs):
        assert args == (connection, "deployment", binding)
        assert kwargs["_policy"] is native
        return None  # This fake exercises policy forwarding, not native MODEL integrity.

    monkeypatch.setattr(coverage_model_index, "indexed_state", index)
    for _ in range(2):
        with pytest.raises(PreflightReached):
            coverage_model_source.replay_model(
                connection, "deployment", binding, _incremental_keys=set(),
                **({"_policy": native} if provided else {}),
            )
    assert len(seen) == (0 if provided else 2)


def test_supplied_no_admission_is_not_reloaded_or_promoted(policy_source, monkeypatch):
    connection, binding, _ = policy_source
    monkeypatch.setattr(coverage_model_source, "task_policy", lambda *_: pytest.fail("relookup"))
    with pytest.raises(ValueError, match="explicit admission"):
        coverage_model_source.replay_model(
            connection, "deployment", binding, _incremental_keys=set(), _policy=None
        )
