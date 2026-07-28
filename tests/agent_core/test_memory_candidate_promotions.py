from datetime import UTC, datetime

import pytest
from agent_core.application import (
    MemoryCandidateExtractionCommand,
    MemoryCandidateExtractionService,
    MemoryCandidatePromotionService,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import new_memory_id, new_session_id
from agent_core.domain.memories import (
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    MemoryVisibility,
)
from agent_core.domain.sessions import Session, SessionStatus

NOW = datetime(2026, 7, 28, 10, 0, tzinfo=UTC)


@pytest.mark.parametrize("source", ["preference", "procedure", "agents"])
def test_promotes_only_reconstructable_local_evidence(source: str) -> None:
    session = _completed_session()
    event = _source_event(session, source)
    store = _MemoryStore()
    extraction = MemoryCandidateExtractionService(store).extract(
        session=session,
        events=[event],
        next_sequence=session.current_sequence + 1,
        command=MemoryCandidateExtractionCommand(repo_id="zebra-agent", extracted_at=NOW),
    )
    projected = session.model_copy(
        update={"current_sequence": session.current_sequence + len(extraction.events)}
    )

    promotion = MemoryCandidatePromotionService(store).promote(
        session=projected,
        source_events=[event],
        candidates=extraction.records,
        promoted_at=NOW,
    )

    assert promotion.events
    assert all(record.status is MemoryStatus.CONFIRMED for record in promotion.records)
    assert all(event.actor is EventActor.HARNESS for event in promotion.events)
    assert all(event.payload["operator"] == "system:auto-promotion" for event in promotion.events)


def test_conflicting_confirmed_memory_stays_candidate() -> None:
    session = _completed_session()
    event = _source_event(session, "preference")
    store = _MemoryStore()
    extraction = MemoryCandidateExtractionService(store).extract(
        session=session,
        events=[event],
        next_sequence=session.current_sequence + 1,
        command=MemoryCandidateExtractionCommand(repo_id="zebra-agent", extracted_at=NOW),
    )
    store.upsert(
        extraction.records[0].model_copy(
            update={
                "memory_id": new_memory_id(),
                "text": "Prefer detailed CLI output.",
                "status": MemoryStatus.CONFIRMED,
            }
        )
    )
    projected = session.model_copy(
        update={"current_sequence": session.current_sequence + len(extraction.events)}
    )

    promotion = MemoryCandidatePromotionService(store).promote(
        session=projected,
        source_events=[event],
        candidates=extraction.records,
        promoted_at=NOW,
    )

    assert promotion.records == ()
    assert promotion.events == ()
    assert store.get(extraction.records[0].memory_id).status is MemoryStatus.CANDIDATE


@pytest.mark.parametrize(
    ("memory_type", "text"),
    [
        (MemoryType.EPISODIC, "A model-authored session summary."),
        (MemoryType.PREFERENCE, "Prefer a different, forged instruction."),
    ],
)
def test_forged_or_unsupported_candidate_stays_candidate(
    memory_type: MemoryType,
    text: str,
) -> None:
    session = _completed_session()
    event = _source_event(session, "preference")
    forged = MemoryRecord(
        memory_id=new_memory_id(),
        memory_type=memory_type,
        text=text,
        confidence=1.0,
        status=MemoryStatus.CANDIDATE,
        visibility=MemoryVisibility.REPO,
        repo_id="zebra-agent",
        source_session_id=session.session_id,
        source_event_start=event.sequence,
        source_event_end=event.sequence,
        created_at=NOW,
        updated_at=NOW,
    )
    store = _MemoryStore([forged])

    promotion = MemoryCandidatePromotionService(store).promote(
        session=session,
        source_events=[event],
        candidates=(forged,),
        promoted_at=NOW,
    )

    assert promotion.records == ()
    assert promotion.events == ()
    assert store.get(forged.memory_id).status is MemoryStatus.CANDIDATE


class _MemoryStore:
    def __init__(self, records: list[MemoryRecord] | None = None) -> None:
        self.records = list(records or [])

    def get(self, memory_id):
        return next((record for record in self.records if record.memory_id == memory_id), None)

    def upsert(self, record):
        self.records = [item for item in self.records if item.memory_id != record.memory_id]
        self.records.append(record)
        return record

    def list(self, query):
        records = self.records
        if query.repo_id is not None:
            records = [record for record in records if record.repo_id == query.repo_id]
        if query.visibility is not None:
            records = [record for record in records if record.visibility is query.visibility]
        if query.memory_types:
            records = [record for record in records if record.memory_type in query.memory_types]
        if query.statuses:
            records = [record for record in records if record.status in query.statuses]
        return records[: query.limit]


def _completed_session() -> Session:
    return Session(
        session_id=new_session_id(),
        title="memory promotion",
        status=SessionStatus.COMPLETED,
        current_sequence=4,
        created_at=NOW,
        updated_at=NOW,
    )


def _source_event(session: Session, source: str) -> SessionEvent:
    if source == "preference":
        return SessionEvent.create(
            session_id=session.session_id,
            sequence=4,
            event_type=EventType.USER_MESSAGE_RECEIVED,
            actor=EventActor.USER,
            payload={"content": "Preference: Prefer concise CLI output."},
            created_at=NOW,
        )
    output = ""
    tool_name = "tests.run"
    metadata: dict[str, object] = {
        "preset": "smoke",
        "command": ["make", "check"],
        "cwd": ".",
        "exit_code": 0,
        "stderr": "",
        "timed_out": False,
    }
    if source == "agents":
        tool_name = "files.read"
        output = (
            "## Local Commands\n\n- `make sync`\n- `make check`\n\n"
            "### packages/\n\n- packages may depend on `agent-core`\n"
            "- `agent-core` must not depend on other `agent-*` packages\n"
        )
        metadata = {"path": "AGENTS.md", "truncated": False, "byte_count": len(output)}
    return SessionEvent.create(
        session_id=session.session_id,
        sequence=4,
        event_type=EventType.TOOL_EXECUTION_COMPLETED,
        actor=EventActor.TOOL,
        payload={
            "attempt_number": 1,
            "tool_name": tool_name,
            "status": "executed",
            "output": output,
            "metadata": metadata,
        },
        created_at=NOW,
    )
