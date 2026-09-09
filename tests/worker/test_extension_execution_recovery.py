from typing import cast
from uuid import uuid4

import pytest
from agent_core.contracts import SessionCommand, SessionCommandKind
from agent_core.domain.events import EventActor, EventType, SessionEvent
from zebra_agent_worker.extension_recovery import WorkerExtensionStore, recover_turn_extension

from tests.worker.test_extension_recovery import SESSION_ID, _fixtures, _Store


@pytest.mark.parametrize("kind", [SessionCommandKind.RUN, SessionCommandKind.RESUME])
@pytest.mark.parametrize("wrong_turn", [False, True])
def test_execution_recovers_only_preexisting_current_turn(kind, wrong_turn: bool) -> None:
    snapshot, ceiling, events = _fixtures()
    message = events[-1]
    command = SessionCommand(
        session_id=SESSION_ID,
        kind=kind,
        expected_revision=message.sequence,
        idempotency_key="execute-existing",
    )
    accepted = SessionEvent.create(
        session_id=SESSION_ID,
        sequence=message.sequence + 1,
        event_type=EventType.SESSION_COMMAND_ACCEPTED,
        actor=EventActor.USER,
        idempotency_key=command.idempotency_key,
        payload=command.event_payload(
            extension_snapshot_digest=snapshot.digest,
            extension_turn_id=str(uuid4()) if wrong_turn else snapshot.turn_id,
        ),
    )
    store = _Store(snapshot, ceiling)

    def recover():
        return recover_turn_extension(
            store=cast(WorkerExtensionStore, store),
            events=[message, accepted],
            session_id=SESSION_ID,
            task_binding=ceiling.binding,
        )

    if wrong_turn:
        with pytest.raises(ValueError, match="not its active Turn"):
            recover()
        assert store.gets == 0
    else:
        assert recover().snapshot == snapshot
        assert recover().snapshot == snapshot
        assert store.gets == 2
