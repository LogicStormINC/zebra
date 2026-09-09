import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from agent_core.contracts import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.extension_snapshots import ExtensionSnapshot, ExtensionTaskCeiling
from agent_core.domain.extensions import SkillInstallation, SkillVersion
from agent_core.domain.identifiers import SessionId
from agent_core.domain.turns import derive_turn_id
from agent_core.ports.extensions import ExtensionStore, SkillInstallationPage
from agent_security.extension_authority import extension_runtime_scope_from_grant
from agent_storage import SQLiteEventStore, SQLiteProjectionStore
from zebra_agent_api.command_submission import submit_session_command
from zebra_agent_api.extension_turn_admission import CloudExtensionTurnAdmission
from zebra_agent_api.responses import ApiResponse
from zebra_agent_api.routes import RouteAdapter, RouteRequest

from tests.agent_security.test_extension_authority import _task_binding, _verified
from tests.api.test_session_command_routes import _seed_ready_session


class _AtomicEventStore:
    def __init__(self, inner: SQLiteEventStore) -> None:
        self.inner = inner
        self.bindings: list[tuple[object, ExtensionSnapshot]] = []

    def list_for_session(self, session_id):
        return self.inner.list_for_session(session_id)

    def append_with_extension_snapshot(self, event, *, scope, snapshot, task_ceiling):
        assert scope == snapshot.scope
        assert task_ceiling.task_id == task_ceiling.binding.task_id
        self.bindings.append((event, snapshot))
        return self.inner.append(event)


class _Snapshots:
    def __init__(self) -> None:
        self.values: dict[tuple[object, str, str], ExtensionSnapshot] = {}

    async def get(self, *, scope, session_id, turn_id, expected_digest):
        snapshot = self.values[(scope, session_id, turn_id)]
        assert snapshot.digest == expected_digest
        return snapshot

    async def exists(self, *, scope, session_id, turn_id):
        return (scope, session_id, turn_id) in self.values


class _TaskAuthority:
    def __init__(self, ceiling: ExtensionTaskCeiling) -> None:
        self.ceiling = ceiling

    def resolve_task_ceiling(self, *, session_id: str) -> ExtensionTaskCeiling:
        del session_id
        return self.ceiling


def _admission(
    count: int = 1, *, allowed: tuple[str, ...] | None = None
) -> tuple[CloudExtensionTurnAdmission, AsyncMock, _Snapshots]:
    verified = _verified(scopes=["agent.run"])
    scope = extension_runtime_scope_from_grant(verified)
    installations = tuple(
        SkillInstallation(
            scope=scope,
            installation_id=f"install-{index:02}",
            revision=1,
            version=SkillVersion(
                skill_id=f"skill-{index:02}",
                version_id="v1",
                artifact_ref=f"artifact://{index}",
                content_digest="a" * 64,
            ),
            enabled=index % 3 != 0,
        )
        for index in range(count)
    )
    store = AsyncMock(spec=ExtensionStore)
    store.list_skills.return_value = SkillInstallationPage(items=installations)
    skill_ids = tuple(item.version.skill_id for item in installations)
    ceiling = ExtensionTaskCeiling(
        task_id="task-a",
        binding=_task_binding(verified),
        skill_components=skill_ids if allowed is None else allowed,
    )
    snapshots = _Snapshots()
    return CloudExtensionTurnAdmission(store, snapshots, _TaskAuthority(ceiling)), store, snapshots


def test_selector_is_exact_scope_bounded_and_enabled_only(tmp_path: Path) -> None:
    _, session_id, _ = _seed_ready_session(tmp_path)
    verified = _verified(scopes=["agent.run"])
    allowed = tuple(f"skill-{index:02}" for index in range(32))
    admission, store, _ = _admission(40, allowed=allowed)
    events = SQLiteEventStore(tmp_path / "sessions.sqlite").list_for_session(session_id)

    scope, snapshot, _ = admission.prepare(
        verified=verified, session_id=session_id, events=events, client_payload={"content": "go"}
    )

    assert snapshot.scope == scope == extension_runtime_scope_from_grant(verified)
    assert len(snapshot.skills) == 21
    assert all(item.enabled for item in snapshot.skills)
    assert snapshot.turn_id == str(derive_turn_id(session_id, 1))
    assert store.list_skills.await_args.kwargs["scope"] == scope


def test_selector_intersects_task_skill_ceiling_and_empty_means_none(tmp_path: Path) -> None:
    _, session_id, _ = _seed_ready_session(tmp_path)
    events = SQLiteEventStore(tmp_path / "sessions.sqlite").list_for_session(session_id)
    admission, store, _ = _admission(3, allowed=("skill-01",))
    _, snapshot, _ = admission.prepare(
        verified=_verified(scopes=["agent.run"]),
        session_id=session_id,
        events=events,
        client_payload={"content": "go"},
    )
    assert tuple(item.version.skill_id for item in snapshot.skills) == ("skill-01",)

    empty, empty_store, _ = _admission(3, allowed=())
    _, snapshot, _ = empty.prepare(
        verified=_verified(scopes=["agent.run"]),
        session_id=session_id,
        events=events,
        client_payload={"content": "go"},
    )
    assert snapshot.skills == ()
    empty_store.list_skills.assert_not_awaited()


def test_selector_fails_closed_instead_of_truncating_enabled_skills(tmp_path: Path) -> None:
    del tmp_path
    allowed = tuple(f"skill-{index:02}" for index in range(33))
    admission, store, _ = _admission(1)
    scope = extension_runtime_scope_from_grant(_verified(scopes=["agent.run"]))
    store.list_skills.return_value = SkillInstallationPage(
        items=tuple(
            SkillInstallation(
                scope=scope,
                installation_id=f"install-{index:02}",
                revision=1,
                enabled=True,
                version=SkillVersion(
                    skill_id=f"skill-{index:02}",
                    version_id="v1",
                    artifact_ref=f"artifact://{index}",
                    content_digest="a" * 64,
                ),
            )
            for index in range(33)
        )
    )
    with pytest.raises(ValueError, match="too many enabled Skills"):
        asyncio.run(admission._list_enabled_skills(scope, frozenset(allowed)))


def test_duplicate_skill_conflict_precedes_unique_skill_limit(tmp_path: Path) -> None:
    database, session_id, revision = _seed_ready_session(tmp_path)
    allowed = tuple(f"skill-{index:02}" for index in range(32))
    admission, store, _ = _admission(1, allowed=allowed)
    scope = extension_runtime_scope_from_grant(_verified(scopes=["agent.run"]))
    installations = [
        SkillInstallation(
            scope=scope,
            installation_id=f"install-{index:02}",
            revision=1,
            enabled=True,
            version=SkillVersion(
                skill_id=f"skill-{index:02}",
                version_id="v1",
                artifact_ref=f"artifact://{index}",
                content_digest="a" * 64,
            ),
        )
        for index in range(32)
    ]
    installations.append(installations[0].model_copy(update={"installation_id": "duplicate-last"}))
    store.list_skills.return_value = SkillInstallationPage(items=tuple(installations))
    stores = SimpleNamespace(
        events=_AtomicEventStore(SQLiteEventStore(database)),
        sessions=SQLiteProjectionStore(database),
    )

    response = submit_session_command(
        stores,
        str(session_id),
        {"kind": "message", "expected_revision": revision, "payload": {"content": "go"}},
        idempotency_key="duplicate-over-limit",
        extension_admission=admission,
        verified_host_grant=_verified(scopes=["agent.run"]),
    )

    assert response.status_code == 409
    assert response.body["status"] == "extension_configuration_conflict"


def test_clarification_reuses_current_open_turn(tmp_path: Path) -> None:
    _, session_id, _ = _seed_ready_session(tmp_path)
    admission, _, _ = _admission()
    events = SQLiteEventStore(tmp_path / "sessions.sqlite").list_for_session(session_id)
    clarification_id = str(uuid4())
    events.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=events[-1].sequence + 1,
            event_type=EventType.CLARIFICATION_REQUESTED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_number": 1,
                "clarification_id": clarification_id,
                "tool_call_id": clarification_id,
                "question": "Which source?",
                "assistant_message": "I need one choice.",
                "conversation": [],
                "model_calls_used": 1,
                "tool_calls_executed": 0,
            },
        )
    )
    _, snapshot, _ = admission.prepare(
        verified=_verified(scopes=["agent.run"]),
        session_id=session_id,
        events=events,
        client_payload={"content": "choice", "clarification_id": clarification_id},
    )
    assert snapshot.turn_id == events[1].payload["turn_id"]


def test_clarification_field_cannot_bind_a_running_turn(tmp_path: Path) -> None:
    _, session_id, _ = _seed_ready_session(tmp_path)
    admission, _, _ = _admission()
    events = SQLiteEventStore(tmp_path / "sessions.sqlite").list_for_session(session_id)

    with pytest.raises(ValueError, match="no active clarification"):
        admission.prepare(
            verified=_verified(scopes=["agent.run"]),
            session_id=session_id,
            events=events,
            client_payload={"content": "choice", "clarification_id": "invented"},
        )


def test_selector_bounds_pages_even_when_every_skill_is_disabled(tmp_path: Path) -> None:
    _, session_id, _ = _seed_ready_session(tmp_path)
    admission, store, _ = _admission(1, allowed=("skill-00",))
    store.list_skills.side_effect = [
        SkillInstallationPage(items=(), next_cursor=f"page-{index}") for index in range(4)
    ]
    events = SQLiteEventStore(tmp_path / "sessions.sqlite").list_for_session(session_id)
    with pytest.raises(ValueError, match="bounded scan"):
        admission.prepare(
            verified=_verified(scopes=["agent.run"]),
            session_id=session_id,
            events=events,
            client_payload={"content": "go"},
        )
    assert store.list_skills.await_count == 4


def test_duplicate_message_reuses_original_binding_after_configuration_change(
    tmp_path: Path,
) -> None:
    database, session_id, revision = _seed_ready_session(tmp_path)
    admission, store, _ = _admission(2)
    events = _AtomicEventStore(SQLiteEventStore(database))
    stores = SimpleNamespace(events=events, sessions=SQLiteProjectionStore(database))
    payload = {"kind": "message", "expected_revision": revision, "payload": {"content": "go"}}
    verified = _verified(scopes=["agent.run"])

    first = submit_session_command(
        stores,
        str(session_id),
        payload,
        idempotency_key="same",
        extension_admission=admission,
        verified_host_grant=verified,
    )
    store.list_skills.return_value = SkillInstallationPage(items=())
    second = submit_session_command(
        stores,
        str(session_id),
        payload,
        idempotency_key="same",
        extension_admission=admission,
        verified_host_grant=verified,
    )

    assert first.status_code == 202
    assert second.status_code == 200 and second.body["status"] == "duplicate"
    assert len(events.bindings) == 1
    assert store.list_skills.await_count == 1


def test_duplicate_message_revalidates_exact_principal_before_disclosing_metadata(
    tmp_path: Path,
) -> None:
    database, session_id, revision = _seed_ready_session(tmp_path)
    admission, store, _ = _admission(2)
    events = _AtomicEventStore(SQLiteEventStore(database))
    stores = SimpleNamespace(events=events, sessions=SQLiteProjectionStore(database))
    payload = {"kind": "message", "expected_revision": revision, "payload": {"content": "go"}}
    owner = _verified(scopes=["agent.run"])
    other = _verified(
        scopes=["agent.run"],
        sub="subject-b",
        resource_refs=[
            {"type": "principal", "id": "subject-b"},
            {"type": "event", "id": "event-a"},
        ],
    )

    accepted = submit_session_command(
        stores,
        str(session_id),
        payload,
        idempotency_key="same",
        extension_admission=admission,
        verified_host_grant=owner,
    )
    replay = submit_session_command(
        stores,
        str(session_id),
        payload,
        idempotency_key="same",
        extension_admission=admission,
        verified_host_grant=other,
    )

    assert accepted.status_code == 202
    assert replay.status_code == 403
    assert replay.body == {
        "session_id": str(session_id),
        "status": "extension_authority_rejected",
    }
    assert not ({"command_id", "current_revision", "event_sequence"} & replay.body.keys())
    assert len(events.bindings) == 1
    assert store.list_skills.await_count == 1


def test_legacy_duplicate_enabled_skill_state_is_a_specific_conflict(tmp_path: Path) -> None:
    database, session_id, revision = _seed_ready_session(tmp_path)
    admission, store, _ = _admission(1, allowed=("skill-00",))
    scope = extension_runtime_scope_from_grant(_verified(scopes=["agent.run"]))
    version = SkillVersion(
        skill_id="skill-00",
        version_id="v1",
        artifact_ref="artifact://same-skill",
        content_digest="a" * 64,
    )
    store.list_skills.return_value = SkillInstallationPage(
        items=(
            SkillInstallation(
                scope=scope,
                installation_id="install-a",
                revision=1,
                version=version,
                enabled=True,
            ),
            SkillInstallation(
                scope=scope,
                installation_id="install-b",
                revision=1,
                version=version,
                enabled=True,
            ),
        )
    )
    stores = SimpleNamespace(
        events=_AtomicEventStore(SQLiteEventStore(database)),
        sessions=SQLiteProjectionStore(database),
    )

    response = submit_session_command(
        stores,
        str(session_id),
        {"kind": "message", "expected_revision": revision, "payload": {"content": "go"}},
        idempotency_key="legacy-conflict",
        extension_admission=admission,
        verified_host_grant=_verified(scopes=["agent.run"]),
    )

    assert response.status_code == 409
    assert response.body["status"] == "extension_configuration_conflict"
    assert stores.events.bindings == []


def test_second_pending_message_is_rejected_before_turn_selection(tmp_path: Path) -> None:
    database, session_id, revision = _seed_ready_session(tmp_path)
    admission, store, _ = _admission(2)
    events = _AtomicEventStore(SQLiteEventStore(database))
    stores = SimpleNamespace(events=events, sessions=SQLiteProjectionStore(database))
    verified = _verified(scopes=["agent.run"])
    first = submit_session_command(
        stores,
        str(session_id),
        {"kind": "message", "expected_revision": revision, "payload": {"content": "one"}},
        idempotency_key="one",
        extension_admission=admission,
        verified_host_grant=verified,
    )
    second = submit_session_command(
        stores,
        str(session_id),
        {
            "kind": "message",
            "expected_revision": revision + 1,
            "payload": {"content": "two"},
        },
        idempotency_key="two",
        extension_admission=admission,
        verified_host_grant=verified,
    )
    assert first.status_code == 202
    assert second.status_code == 409 and second.body["status"] == "message_pending"
    assert len(events.bindings) == 1
    assert store.list_skills.await_count == 1


def test_pending_message_indexing_is_linear_for_long_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import zebra_agent_api.extension_turn_admission as admission_module

    session_id = SessionId(UUID("11111111-1111-1111-1111-111111111111"))
    events: list[SessionEvent] = []
    for index in range(100):
        command = SessionCommand(
            session_id=session_id,
            kind=SessionCommandKind.MESSAGE,
            expected_revision=index * 2,
            idempotency_key=f"linear-{index}",
            payload={"content": str(index)},
        )
        accepted = SessionEvent.create(
            session_id=session_id,
            sequence=index * 2 + 1,
            event_type=EventType.SESSION_COMMAND_ACCEPTED,
            actor=EventActor.USER,
            payload=command.event_payload(),
            idempotency_key=command.idempotency_key,
        )
        events.extend(
            (
                accepted,
                SessionEvent.create(
                    session_id=session_id,
                    sequence=index * 2 + 2,
                    event_type=EventType.USER_MESSAGE_RECEIVED,
                    actor=EventActor.USER,
                    payload={
                        "content": str(index),
                        "turn_id": str(derive_turn_id(session_id, index)),
                        "turn_index": index,
                        "origin": "human",
                    },
                    causation_id=accepted.event_id,
                    idempotency_key=f"command-input:{accepted.event_id}",
                ),
            )
        )
    checks = {"integrity": 0, "association": 0}
    original_integrity = admission_module.validate_accepted_session_command
    original_association = admission_module.is_command_message_materialization

    def count_integrity(*args, **kwargs):
        checks["integrity"] += 1
        return original_integrity(*args, **kwargs)

    def count_association(**kwargs):
        checks["association"] += 1
        return original_association(**kwargs)

    monkeypatch.setattr(admission_module, "validate_accepted_session_command", count_integrity)
    monkeypatch.setattr(admission_module, "is_command_message_materialization", count_association)
    assert not CloudExtensionTurnAdmission._has_pending_message(events)
    assert checks == {"integrity": 100, "association": 100}


def test_later_clarification_reuses_original_turn_snapshot_after_config_change(
    tmp_path: Path,
) -> None:
    _, session_id, _ = _seed_ready_session(tmp_path)
    verified = _verified(scopes=["agent.run"])
    admission, store, snapshots = _admission(2)
    events = SQLiteEventStore(tmp_path / "sessions.sqlite").list_for_session(session_id)
    turn_id = str(events[1].payload["turn_id"])
    scope = extension_runtime_scope_from_grant(verified)
    original = ExtensionSnapshot(
        scope=scope,
        session_id=str(session_id),
        turn_id=turn_id,
        skills=(store.list_skills.return_value.items[1],),
    )
    snapshots.values[(scope, str(session_id), turn_id)] = original
    prior = SessionCommand(
        session_id=session_id,
        kind=SessionCommandKind.MESSAGE,
        expected_revision=events[-1].sequence,
        idempotency_key="prior-clarification",
        payload={"content": "first answer"},
    )
    events.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=events[-1].sequence + 1,
            event_type=EventType.SESSION_COMMAND_ACCEPTED,
            actor=EventActor.USER,
            payload=prior.event_payload(
                extension_snapshot_digest=original.digest,
                extension_turn_id=turn_id,
            ),
            idempotency_key=prior.idempotency_key,
        )
    )
    events.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=events[-1].sequence + 1,
            event_type=EventType.CLARIFICATION_RESPONDED,
            actor=EventActor.USER,
            payload={
                "clarification_id": "old-question",
                "content": "first answer",
                "selected_choice": False,
            },
            idempotency_key="prior-clarification:message",
        )
    )
    clarification_id = str(uuid4())
    events.append(
        SessionEvent.create(
            session_id=session_id,
            sequence=events[-1].sequence + 1,
            event_type=EventType.CLARIFICATION_REQUESTED,
            actor=EventActor.HARNESS,
            payload={
                "attempt_number": 1,
                "clarification_id": clarification_id,
                "tool_call_id": clarification_id,
                "question": "Again?",
                "assistant_message": "Need one more choice.",
                "conversation": [],
                "model_calls_used": 1,
                "tool_calls_executed": 0,
            },
        )
    )
    store.list_skills.reset_mock()
    _, reused, _ = admission.prepare(
        verified=verified,
        session_id=session_id,
        events=events,
        client_payload={"content": "second answer", "clarification_id": clarification_id},
    )
    assert reused == original
    store.list_skills.assert_not_awaited()


@pytest.mark.parametrize(
    "field",
    ("extension_snapshot_digest", "extension_turn_id", "extension_snapshot", "snapshot_ref"),
)
def test_client_cannot_supply_trusted_binding_fields(tmp_path: Path, field: str) -> None:
    database, session_id, revision = _seed_ready_session(tmp_path)
    admission, _, _ = _admission()
    stores = SimpleNamespace(
        events=_AtomicEventStore(SQLiteEventStore(database)),
        sessions=SQLiteProjectionStore(database),
    )
    response = submit_session_command(
        stores,
        str(session_id),
        {
            "kind": "message",
            "expected_revision": revision,
            "payload": {"content": "go", field: "client-controlled"},
        },
        idempotency_key="forged",
        extension_admission=admission,
        verified_host_grant=_verified(scopes=["agent.run"]),
    )
    assert response.status_code == 400
    assert "server-owned" in str(response.body)
    assert stores.events.bindings == []


def test_cloud_message_route_forwards_only_verified_server_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("zebra_agent_api.routes.tenant_scope_response", lambda *_: None)
    verified = _verified(scopes=["agent.run"])
    admission, _, _ = _admission()
    app = SimpleNamespace(
        settings=SimpleNamespace(deployment="cloud"),
        submit_command=Mock(return_value=ApiResponse(status_code=202, body={})),
    )
    request = RouteRequest(
        method="POST",
        path="/sessions/session/messages",
        body={"content": "go", "expected_revision": 1},
        headers={"Idempotency-Key": "key"},
        verified_host_grant=verified,
    )

    RouteAdapter(app, admission).handle(request)

    assert app.submit_command.call_args.kwargs["extension_admission"] is admission
    assert app.submit_command.call_args.kwargs["verified_host_grant"] is verified


def test_session_create_route_forwards_only_verified_server_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("zebra_agent_api.routes.tenant_scope_response", lambda *_: None)
    verified = _verified(scopes=["agent.run"])
    app = SimpleNamespace(
        create_session=Mock(return_value=ApiResponse(status_code=201, body={})),
    )

    RouteAdapter(app).handle(
        RouteRequest(
            method="POST",
            path="/sessions",
            body={"prompt": "go"},
            verified_host_grant=verified,
            host_context=verified.context,
        )
    )

    assert app.create_session.call_args.kwargs["host_context"] is verified.context
    assert app.create_session.call_args.kwargs["verified_host_grant"] is verified


def test_task_create_route_forwards_only_verified_server_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("zebra_agent_api.routes.tenant_scope_response", lambda *_: None)
    verified = _verified(scopes=["agent.run"])
    session_id = str(uuid4())
    task = SimpleNamespace(
        task_id=UUID(session_id),
        active_segment_id=UUID(session_id),
        current_sequence=0,
    )
    app = SimpleNamespace(
        create_session=Mock(
            return_value=ApiResponse(status_code=201, body={"session_id": session_id})
        ),
        stores=SimpleNamespace(
            tasks=SimpleNamespace(ensure_for_session=lambda _: task),
            sessions=SimpleNamespace(get_session=lambda _: SimpleNamespace(current_sequence=0)),
        ),
    )

    response = RouteAdapter(app).handle(
        RouteRequest(
            method="POST",
            path="/tasks",
            body={"prompt": "go"},
            verified_host_grant=verified,
            host_context=verified.context,
        )
    )

    assert response.status_code == 201
    assert app.create_session.call_args.kwargs["verified_host_grant"] is verified
