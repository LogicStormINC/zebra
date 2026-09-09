from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest
from agent_core.contracts import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.extension_snapshots import ExtensionSnapshot, ExtensionTaskCeiling
from agent_core.domain.extensions import ExtensionScope, SkillInstallation, SkillVersion
from agent_core.domain.identifiers import SessionId
from agent_core.domain.turns import derive_turn_id
from agent_core.ports.extension_snapshots import ExtensionSnapshotNotFoundError
from zebra_agent_worker.context_materialization import prepare_worker_context
from zebra_agent_worker.execution_events import DurableHarnessEventRecorder
from zebra_agent_worker.extension_recovery import WorkerExtensionStore, recover_turn_extension
from zebra_agent_worker.task_recovery import RecoveredTask

from tests.agent_security.test_extension_authority import _task_binding, _verified

SESSION_ID = SessionId(UUID("11111111-1111-1111-1111-111111111111"))
OTHER_SESSION_ID = SessionId(UUID("22222222-2222-2222-2222-222222222222"))


class _Store:
    def __init__(
        self,
        snapshot: ExtensionSnapshot,
        ceiling: ExtensionTaskCeiling,
        *,
        snapshot_exists: bool = False,
    ) -> None:
        self.snapshot = snapshot
        self.ceiling = ceiling
        self.gets = 0
        self.ceiling_reads = 0
        self.exists_reads = 0
        self.snapshot_exists = snapshot_exists

    async def save(self, **_: object) -> None:
        raise AssertionError("recovery is read-only")

    async def get(self, **kwargs: object) -> ExtensionSnapshot:
        self.gets += 1
        assert kwargs == {
            "scope": self.snapshot.scope,
            "session_id": str(SESSION_ID),
            "turn_id": self.snapshot.turn_id,
            "expected_digest": self.snapshot.digest,
        }
        return self.snapshot

    async def exists(self, **kwargs: object) -> bool:
        self.exists_reads += 1
        assert kwargs == {
            "scope": self.snapshot.scope,
            "session_id": str(SESSION_ID),
            "turn_id": self.snapshot.turn_id,
        }
        return self.snapshot_exists

    def resolve_task_ceiling(self, *, session_id: str) -> ExtensionTaskCeiling:
        self.ceiling_reads += 1
        assert session_id == str(SESSION_ID)
        return self.ceiling


def _fixtures(*, bound: bool = True):
    verified = _verified(
        iss="https://api.trench.example.com",
        origin="https://trench.example.com",
        scopes=["agent.run"],
    )
    binding = _task_binding(verified).model_copy(update={"task_id": str(SESSION_ID)})
    ceiling = ExtensionTaskCeiling(
        task_id=str(SESSION_ID), binding=binding, skill_components=("summarize",)
    )
    scope = ExtensionScope(
        authority_issuer=verified.authority_issuer,
        namespace_id=verified.context.namespace_id,
        principal_id=verified.subject_ref,
        workspace_id=verified.context.workspace_ref,
    )
    turn_id = str(derive_turn_id(SESSION_ID, 1))
    snapshot = ExtensionSnapshot(
        scope=scope,
        session_id=str(SESSION_ID),
        turn_id=turn_id,
        skills=(
            SkillInstallation(
                scope=scope,
                installation_id="installed",
                revision=1,
                version=SkillVersion(
                    skill_id="summarize",
                    version_id="v1",
                    artifact_ref="artifact://skill",
                    content_digest="a" * 64,
                ),
            ),
        ),
    )
    command = SessionCommand(
        session_id=SESSION_ID,
        kind=SessionCommandKind.MESSAGE,
        expected_revision=1,
        idempotency_key="follow-up",
        payload={"content": "continue"},
    )
    accepted = SessionEvent.create(
        session_id=SESSION_ID,
        sequence=2,
        event_type=EventType.SESSION_COMMAND_ACCEPTED,
        actor=EventActor.USER,
        payload=command.event_payload(
            extension_snapshot_digest=snapshot.digest if bound else None,
            extension_turn_id=turn_id if bound else None,
        ),
        idempotency_key=command.idempotency_key,
    )
    message = SessionEvent.create(
        session_id=SESSION_ID,
        sequence=3,
        event_type=EventType.USER_MESSAGE_RECEIVED,
        actor=EventActor.USER,
        payload={"content": "continue", "turn_id": turn_id, "turn_index": 1, "origin": "human"},
        idempotency_key="follow-up:message",
    )
    return snapshot, ceiling, [accepted, message]


def test_exact_server_bound_snapshot_is_recovered_across_restart() -> None:
    snapshot, ceiling, events = _fixtures()
    first = _Store(snapshot, ceiling)
    restarted = _Store(snapshot, ceiling)

    recovered = recover_turn_extension(
        store=cast(WorkerExtensionStore, first),
        events=events,
        session_id=SESSION_ID,
        task_binding=ceiling.binding,
    )
    replayed = recover_turn_extension(
        store=cast(WorkerExtensionStore, restarted),
        events=events,
        session_id=SESSION_ID,
        task_binding=ceiling.binding,
    )

    assert recovered == replayed
    assert recovered is not None and recovered.snapshot.digest == snapshot.digest
    assert (first.gets, restarted.gets) == (1, 1)


def test_disabled_and_legacy_turns_perform_zero_extension_reads() -> None:
    snapshot, ceiling, events = _fixtures(bound=False)
    store = _Store(snapshot, ceiling)
    legacy_payload = dict(events[-1].payload)
    legacy_payload.pop("turn_id")
    legacy_message = events[-1].model_copy(update={"payload": legacy_payload})

    assert (
        recover_turn_extension(store=None, events=events, session_id=SESSION_ID, task_binding=None)
        is None
    )
    assert (
        recover_turn_extension(
            store=cast(WorkerExtensionStore, store),
            events=[events[0], legacy_message],
            session_id=SESSION_ID,
            task_binding=None,
        )
        is None
    )
    assert (store.gets, store.ceiling_reads, store.exists_reads) == (0, 0, 0)


def test_enabled_unbound_turn_probes_exact_snapshot_without_loading_it() -> None:
    snapshot, ceiling, events = _fixtures(bound=False)
    store = _Store(snapshot, ceiling)
    assert recover_turn_extension(
        store=cast(WorkerExtensionStore, store),
        events=events,
        session_id=SESSION_ID,
        task_binding=ceiling.binding,
    ) is None
    assert (store.ceiling_reads, store.exists_reads, store.gets) == (1, 1, 0)


def test_deleted_binding_fields_cannot_downgrade_a_persisted_snapshot() -> None:
    snapshot, ceiling, events = _fixtures()
    payload = dict(events[0].payload)
    payload.pop("extension_snapshot_digest", None)
    payload.pop("extension_turn_id", None)
    accepted = events[0].model_copy(update={"payload": payload})
    store = _Store(snapshot, ceiling, snapshot_exists=True)
    with pytest.raises(ValueError, match="missing its accepted command binding"):
        recover_turn_extension(
            store=cast(WorkerExtensionStore, store),
            events=[accepted, events[1]],
            session_id=SESSION_ID,
            task_binding=ceiling.binding,
        )
    assert (store.ceiling_reads, store.exists_reads, store.gets) == (1, 1, 0)


def test_tampered_turn_and_task_ceiling_fail_closed() -> None:
    snapshot, ceiling, events = _fixtures()
    bad_message = events[-1].model_copy(
        update={"payload": events[-1].payload | {"turn_id": "other-turn"}}
    )
    with pytest.raises(ValueError, match="does not match"):
        recover_turn_extension(
            store=cast(WorkerExtensionStore, _Store(snapshot, ceiling)),
            events=[events[0], bad_message],
            session_id=SESSION_ID,
            task_binding=ceiling.binding,
        )

    narrowed = ceiling.model_copy(update={"skill_components": ()})
    with pytest.raises(ValueError, match="frozen Task Skill ceiling"):
        recover_turn_extension(
            store=cast(WorkerExtensionStore, _Store(snapshot, narrowed)),
            events=events,
            session_id=SESSION_ID,
            task_binding=ceiling.binding,
        )


def test_cross_tenant_snapshot_cannot_be_substituted() -> None:
    snapshot, ceiling, events = _fixtures()

    class _CrossTenant(_Store):
        async def get(self, **_: object) -> ExtensionSnapshot:
            self.gets += 1
            return self.snapshot.model_copy(
                update={
                    "scope": self.snapshot.scope.model_copy(
                        update={"principal_id": "other-principal"}
                    )
                }
            )

    with pytest.raises(ValueError):
        # The real PostgreSQL store rejects this before returning. This fake
        # proves a dishonest adapter still cannot produce an accepted result.
        recover_turn_extension(
            store=cast(WorkerExtensionStore, _CrossTenant(snapshot, ceiling)),
            events=events,
            session_id=SESSION_ID,
            task_binding=ceiling.binding,
        )


@pytest.mark.parametrize("drift", ["payload_session", "outer_session", "actor"])
def test_bound_accepted_identity_drift_fails_before_extension_reads(drift: str) -> None:
    snapshot, ceiling, events = _fixtures()
    accepted = events[0]
    if drift == "payload_session":
        accepted = accepted.model_copy(
            update={"payload": accepted.payload | {"session_id": str(OTHER_SESSION_ID)}}
        )
    elif drift == "outer_session":
        accepted = accepted.model_copy(update={"session_id": OTHER_SESSION_ID})
    else:
        accepted = accepted.model_copy(update={"actor": EventActor.HARNESS})
    store = _Store(snapshot, ceiling)

    with pytest.raises(ValueError, match="identity is not canonical|integrity check failed"):
        recover_turn_extension(
            store=cast(WorkerExtensionStore, store),
            events=[accepted, events[1]],
            session_id=SESSION_ID,
            task_binding=ceiling.binding,
        )

    assert (store.ceiling_reads, store.gets) == (0, 0)


def test_missing_or_ambiguous_materialization_fails_or_reads_nothing() -> None:
    snapshot, ceiling, events = _fixtures()
    store = _Store(snapshot, ceiling)
    with pytest.raises(ValueError, match="missing canonical materialization"):
        recover_turn_extension(
            store=cast(WorkerExtensionStore, store),
            events=[events[0]],
            session_id=SESSION_ID,
            task_binding=ceiling.binding,
        )
    with pytest.raises(ValueError, match="ambiguous canonical materialization"):
        recover_turn_extension(
            store=cast(WorkerExtensionStore, store),
            events=[
                *events,
                events[-1].model_copy(
                    update={
                        "event_id": UUID("33333333-3333-3333-3333-333333333333"),
                        "sequence": 4,
                    }
                ),
            ],
            session_id=SESSION_ID,
            task_binding=ceiling.binding,
        )


def test_execution_and_extension_task_binding_loaders_must_agree() -> None:
    snapshot, ceiling, events = _fixtures()
    drifted = ceiling.binding.model_copy(update={"binding_revision": 2})

    with pytest.raises(ValueError, match="Task bindings disagree"):
        recover_turn_extension(
            store=cast(WorkerExtensionStore, _Store(snapshot, ceiling)),
            events=events,
            session_id=SESSION_ID,
            task_binding=drifted,
        )


def test_completed_bound_turn_is_validated_then_ignored_for_next_bound_turn() -> None:
    first, ceiling, events = _fixtures()
    completed = SessionEvent.create(
        session_id=SESSION_ID,
        sequence=4,
        event_type=EventType.TURN_COMPLETED,
        actor=EventActor.HARNESS,
        payload={"turn_id": first.turn_id, "turn_index": 1, "closes_segment": False},
    )
    second_turn = str(derive_turn_id(SESSION_ID, 2))
    second = first.model_copy(update={"turn_id": second_turn})
    command = SessionCommand(
        session_id=SESSION_ID,
        kind=SessionCommandKind.MESSAGE,
        expected_revision=4,
        idempotency_key="second-bound",
        payload={"content": "continue"},
    )
    second_accepted = SessionEvent.create(
        session_id=SESSION_ID,
        sequence=5,
        event_type=EventType.SESSION_COMMAND_ACCEPTED,
        actor=EventActor.USER,
        payload=command.event_payload(
            extension_snapshot_digest=second.digest,
            extension_turn_id=second_turn,
        ),
        idempotency_key=command.idempotency_key,
    )
    second_message = SessionEvent.create(
        session_id=SESSION_ID,
        sequence=6,
        event_type=EventType.USER_MESSAGE_RECEIVED,
        actor=EventActor.USER,
        payload={
            "content": "continue",
            "turn_id": second_turn,
            "turn_index": 2,
            "origin": "human",
        },
        causation_id=second_accepted.event_id,
        idempotency_key=f"command-input:{second_accepted.event_id}",
    )

    recovered = recover_turn_extension(
        store=cast(WorkerExtensionStore, _Store(second, ceiling)),
        events=[*events, completed, second_accepted, second_message],
        session_id=SESSION_ID,
        task_binding=ceiling.binding,
    )

    assert recovered is not None and recovered.snapshot == second


def test_missing_bound_snapshot_fails_before_attempt_authority_is_persisted() -> None:
    snapshot, ceiling, events = _fixtures()

    class _Missing(_Store):
        async def get(self, **_: object) -> ExtensionSnapshot:
            raise ExtensionSnapshotNotFoundError("missing")

    class _NoWrite:
        def append(self, *_: object, **__: object) -> None:
            raise AssertionError("attempt authority must not be persisted")

    with pytest.raises(ValueError, match="unavailable or invalid"):
        prepare_worker_context(
            store=None,
            task_binding_loader=lambda _: ceiling.binding,
            resolver=None,
            static_scope=None,
            scope_provider=None,
            recovery_service=cast(object, SimpleNamespace()),
            event_store=cast(object, SimpleNamespace()),
            recorder=cast(DurableHarnessEventRecorder, _NoWrite()),
            claimed=cast(
                object,
                SimpleNamespace(lease=SimpleNamespace(session_id=SESSION_ID)),
            ),
            events=events,
            task=cast(RecoveredTask, SimpleNamespace()),
            active_capsule_id=None,
            as_of=datetime(2026, 9, 7, tzinfo=UTC),
            extension_store=cast(WorkerExtensionStore, _Missing(snapshot, ceiling)),
        )


def test_bound_command_fingerprint_tamper_fails_before_extension_reads() -> None:
    snapshot, ceiling, events = _fixtures()
    store = _Store(snapshot, ceiling)
    accepted = events[0].model_copy(
        update={"payload": events[0].payload | {"payload": {"content": "tampered"}}}
    )
    with pytest.raises(ValueError, match="integrity"):
        recover_turn_extension(
            store=cast(WorkerExtensionStore, store),
            events=[accepted, events[1]],
            session_id=SESSION_ID,
            task_binding=ceiling.binding,
        )
    assert (store.ceiling_reads, store.gets) == (0, 0)


@pytest.mark.parametrize("corruption", ["missing", "payload", "ambiguous"])
def test_completed_bound_command_association_is_still_validated(corruption: str) -> None:
    snapshot, ceiling, events = _fixtures()
    completed = SessionEvent.create(
        session_id=SESSION_ID,
        sequence=4,
        event_type=EventType.TURN_COMPLETED,
        actor=EventActor.HARNESS,
        payload={"turn_id": snapshot.turn_id, "turn_index": 1, "closes_segment": False},
    )
    history = [*events, completed]
    if corruption == "missing":
        history.pop(1)
    elif corruption == "payload":
        history[1] = history[1].model_copy(
            update={"payload": history[1].payload | {"content": "tampered"}}
        )
    else:
        history.insert(
            2,
            events[1].model_copy(
                update={
                    "event_id": UUID("44444444-4444-4444-4444-444444444444"),
                    "sequence": 4,
                }
            ),
        )
        history[-1] = completed.model_copy(update={"sequence": 5})
    store = _Store(snapshot, ceiling)
    with pytest.raises(ValueError, match="missing|corrupt|ambiguous"):
        recover_turn_extension(
            store=cast(WorkerExtensionStore, store),
            events=history,
            session_id=SESSION_ID,
            task_binding=ceiling.binding,
        )
    assert (store.ceiling_reads, store.gets) == (0, 0)


def test_canonical_and_distinct_legacy_materializations_are_ambiguous() -> None:
    snapshot, ceiling, events = _fixtures()
    accepted, legacy = events
    canonical = legacy.model_copy(
        update={
            "event_id": UUID("55555555-5555-5555-5555-555555555555"),
            "sequence": 4,
            "causation_id": accepted.event_id,
            "idempotency_key": f"command-input:{accepted.event_id}",
        }
    )
    with pytest.raises(ValueError, match="ambiguous"):
        recover_turn_extension(
            store=cast(WorkerExtensionStore, _Store(snapshot, ceiling)),
            events=[accepted, legacy, canonical],
            session_id=SESSION_ID,
            task_binding=ceiling.binding,
        )


def test_legacy_key_with_wrong_non_null_causation_is_not_an_association() -> None:
    snapshot, ceiling, events = _fixtures()
    wrong = events[1].model_copy(
        update={"causation_id": UUID("66666666-6666-6666-6666-666666666666")}
    )
    with pytest.raises(ValueError, match="missing canonical materialization"):
        recover_turn_extension(
            store=cast(WorkerExtensionStore, _Store(snapshot, ceiling)),
            events=[events[0], wrong],
            session_id=SESSION_ID,
            task_binding=ceiling.binding,
        )


def test_partial_or_non_message_extension_binding_fails_closed() -> None:
    snapshot, ceiling, events = _fixtures()
    partial_payload = dict(events[0].payload)
    partial_payload.pop("extension_turn_id")
    partial = events[0].model_copy(update={"payload": partial_payload})
    with pytest.raises(ValueError, match="binding must be complete"):
        recover_turn_extension(
            store=cast(WorkerExtensionStore, _Store(snapshot, ceiling)),
            events=[partial, events[1]],
            session_id=SESSION_ID,
            task_binding=ceiling.binding,
        )

    kind_tamper = events[0].model_copy(
        update={"payload": events[0].payload | {"kind": SessionCommandKind.RUN.value}}
    )
    with pytest.raises(ValueError, match="integrity"):
        recover_turn_extension(
            store=cast(WorkerExtensionStore, _Store(snapshot, ceiling)),
            events=[kind_tamper, events[1]],
            session_id=SESSION_ID,
            task_binding=ceiling.binding,
        )

    command = SessionCommand(
        session_id=SESSION_ID,
        kind=SessionCommandKind.RUN,
        expected_revision=1,
        idempotency_key="bound-run",
    )
    non_message = events[0].model_copy(
        update={
            "payload": command.event_payload(
                extension_snapshot_digest=snapshot.digest,
                extension_turn_id=snapshot.turn_id,
            ),
            "idempotency_key": command.idempotency_key,
        }
    )
    with pytest.raises(ValueError, match="not its active Turn"):
        recover_turn_extension(
            store=cast(WorkerExtensionStore, _Store(snapshot, ceiling)),
            events=[non_message, events[1]],
            session_id=SESSION_ID,
            task_binding=ceiling.binding,
        )


def test_long_completed_history_uses_linear_integrity_and_association_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import zebra_agent_worker.extension_recovery as recovery

    snapshot, ceiling, _ = _fixtures()
    events: list[SessionEvent] = []
    for index in range(120):
        turn_id = str(derive_turn_id(SESSION_ID, index))
        command = SessionCommand(
            session_id=SESSION_ID,
            kind=SessionCommandKind.MESSAGE,
            expected_revision=index * 3,
            idempotency_key=f"history-{index}",
            payload={"content": f"message-{index}"},
        )
        accepted = SessionEvent.create(
            session_id=SESSION_ID,
            sequence=index * 3 + 1,
            event_type=EventType.SESSION_COMMAND_ACCEPTED,
            actor=EventActor.USER,
            payload=command.event_payload(
                extension_snapshot_digest="a" * 64,
                extension_turn_id=turn_id,
            ),
            idempotency_key=command.idempotency_key,
        )
        events.extend(
            (
                accepted,
                SessionEvent.create(
                    session_id=SESSION_ID,
                    sequence=index * 3 + 2,
                    event_type=EventType.USER_MESSAGE_RECEIVED,
                    actor=EventActor.USER,
                    payload={
                        "content": f"message-{index}",
                        "turn_id": turn_id,
                        "turn_index": index,
                        "origin": "human",
                    },
                    causation_id=accepted.event_id,
                    idempotency_key=f"command-input:{accepted.event_id}",
                ),
                SessionEvent.create(
                    session_id=SESSION_ID,
                    sequence=index * 3 + 3,
                    event_type=EventType.TURN_COMPLETED,
                    actor=EventActor.HARNESS,
                    payload={
                        "turn_id": turn_id,
                        "turn_index": index,
                        "closes_segment": False,
                    },
                ),
            )
        )
    checks = {"integrity": 0, "association": 0}
    original_integrity = recovery.validate_accepted_session_command
    original_association = recovery.is_command_message_materialization

    def count_integrity(*args, **kwargs):
        checks["integrity"] += 1
        return original_integrity(*args, **kwargs)

    def count_association(**kwargs):
        checks["association"] += 1
        return original_association(**kwargs)

    monkeypatch.setattr(recovery, "validate_accepted_session_command", count_integrity)
    monkeypatch.setattr(recovery, "is_command_message_materialization", count_association)
    assert recover_turn_extension(
        store=cast(WorkerExtensionStore, _Store(snapshot, ceiling)),
        events=events,
        session_id=SESSION_ID,
        task_binding=ceiling.binding,
    ) is None
    assert checks == {"integrity": 120, "association": 120}
