"""Regression tests for the 2026-08-24 ADR-026 review findings (P1-3, P2-6..P2-8)."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from agent_core.application import (
    MemoryCandidateExtractionCommand,
    is_human_message,
    memory_extraction_window,
)
from agent_core.application.memory_candidates import (
    MemoryCandidateExtractionPlanner as Planner,
)
from agent_core.contracts.events import validate_event_payload
from agent_core.domain.cloud_scope import OpaqueAuthorityScope
from agent_core.domain.context_capsule import ContextCapsule
from agent_core.domain.context_materialization import (
    ContextMaterialization,
    ContextMaterializationRequest,
)
from agent_core.domain.events import EventActor, EventType, SessionEvent
from agent_core.domain.identifiers import SessionId
from agent_core.domain.session_history import SessionHistoryMessage
from agent_core.domain.sessions import Session, SessionStatus

NOW = datetime(2026, 8, 24, 15, 0, tzinfo=UTC)


def _event(
    session_id: SessionId,
    sequence: int,
    event_type: EventType,
    payload: dict[str, object],
    *,
    actor: EventActor = EventActor.HARNESS,
) -> SessionEvent:
    return SessionEvent.create(
        session_id=session_id,
        sequence=sequence,
        event_type=event_type,
        actor=actor,
        payload=payload,
        created_at=NOW,
    )


def _session_id() -> SessionId:
    return SessionId(UUID("00000000-0000-0000-0000-000000000cc1"))


# ---------------------------------------------------------------- P1-3


def test_refresh_targets_share_the_turn_window_and_zero_candidate_turns_advance() -> None:
    session_id = _session_id()
    events = [
        _event(
            session_id,
            0,
            EventType.USER_MESSAGE_RECEIVED,
            {
                "content": "run checks",
                "turn_id": "00000000-0000-0000-0000-0000000000a1",
                "turn_index": 0,
                "origin": "human",
            },
            actor=EventActor.USER,
        ),
        _event(
            session_id,
            1,
            EventType.TOOL_EXECUTION_COMPLETED,
            {
                "attempt_number": 1,
                "tool_name": "command.run",
                "tool_call_id": "tc-1",
                "status": "executed",
                "output": "ok",
                "metadata": {"command": ["make", "check"]},
            },
        ),
        _event(
            session_id,
            2,
            EventType.MODEL_RESPONSE_RECEIVED,
            {"assistant_message": "checks passed"},
        ),
        _event(
            session_id,
            3,
            EventType.TURN_COMPLETED,
            {
                "turn_id": "00000000-0000-0000-0000-0000000000a1",
                "turn_index": 0,
                "closes_segment": False,
            },
        ),
        _event(
            session_id,
            4,
            EventType.MEMORY_CANDIDATE_EXTRACTED,
            {
                "memory_id": "00000000-0000-0000-0000-0000000000b2",
                "memory_type": "procedure",
                "text": "run make check before delivery",
                "confidence": 1.0,
                "status": "candidate",
                "visibility": "repo",
                "repo_id": "repo-1",
                "source_event_start": 0,
                "source_event_end": 3,
            },
        ),
        _event(
            session_id,
            5,
            EventType.USER_MESSAGE_RECEIVED,
            {
                "content": "thanks",
                "turn_id": "00000000-0000-0000-0000-0000000000a3",
                "turn_index": 1,
                "origin": "human",
            },
            actor=EventActor.USER,
        ),
        _event(
            session_id,
            6,
            EventType.TURN_COMPLETED,
            {
                "turn_id": "00000000-0000-0000-0000-0000000000a3",
                "turn_index": 1,
                "closes_segment": False,
            },
        ),
    ]

    # The window advances past the turn-1 extraction even though turn 2
    # produced zero candidates; turn 1's refresh instruction stays out.
    assert memory_extraction_window(events) == 4

    session = Session.create(title="window").model_copy(
        update={"status": SessionStatus.AWAITING_TURN}
    )
    command = MemoryCandidateExtractionCommand(
        repo_id="repo-1",
        extracted_at=NOW,
        since_sequence=memory_extraction_window(events),
    )
    plan = Planner().plan(
        session=session,
        events=events,
        next_sequence=7,
        command=command,
    )
    assert plan.records == ()
    assert plan.stale_records == ()


def test_memory_window_anchors_on_previous_turn_close_without_extraction() -> None:
    session_id = _session_id()
    events = [
        _event(
            session_id,
            0,
            EventType.USER_MESSAGE_RECEIVED,
            {
                "content": "one",
                "turn_id": "00000000-0000-0000-0000-0000000000a1",
                "turn_index": 0,
                "origin": "human",
            },
            actor=EventActor.USER,
        ),
        _event(
            session_id,
            1,
            EventType.TURN_COMPLETED,
            {
                "turn_id": "00000000-0000-0000-0000-0000000000a1",
                "turn_index": 0,
                "closes_segment": False,
            },
        ),
        # turn 2 produced no extraction events at all
        _event(
            session_id,
            2,
            EventType.USER_MESSAGE_RECEIVED,
            {
                "content": "two",
                "turn_id": "00000000-0000-0000-0000-0000000000a2",
                "turn_index": 1,
                "origin": "human",
            },
            actor=EventActor.USER,
        ),
        _event(
            session_id,
            3,
            EventType.TURN_COMPLETED,
            {
                "turn_id": "00000000-0000-0000-0000-0000000000a2",
                "turn_index": 1,
                "closes_segment": False,
            },
        ),
    ]

    # the just-closed turn 2 extracts events strictly after turn 1's
    # close; zero-candidate turn 1 still advanced the boundary from -1.
    assert memory_extraction_window(events) == 1


# ---------------------------------------------------------------- P2-6


def _request() -> ContextMaterializationRequest:
    return ContextMaterializationRequest(
        scope=OpaqueAuthorityScope(
            authority_issuer="issuer",
            namespace_id="ns",
            allowed_session_ids=("00000000-0000-0000-0000-000000000cc1",),
        ),
        session_id=_session_id(),
        expected_session_revision=7,
        as_of=NOW,
    )


def test_truncation_without_boundary_fails_closed() -> None:
    with pytest.raises(ValueError, match="truncated_before_sequence"):
        ContextMaterialization(
            request=_request(),
            session_revision=7,
            history=(SessionHistoryMessage(6, "assistant", "hi", NOW, False),),
            history_truncated=True,
        )


def test_range_less_capsule_cannot_cover_a_truncated_prefix() -> None:
    capsule = ContextCapsule(
        capsule_id="capsule-x",
        objective="cover",
        immediate_next="next",
        source_hash="a" * 64,
        confidence=1.0,
        created_at=NOW,
    )
    request = ContextMaterializationRequest(
        scope=OpaqueAuthorityScope(
            authority_issuer="issuer",
            namespace_id="ns",
            allowed_session_ids=("00000000-0000-0000-0000-000000000cc1",),
        ),
        session_id=_session_id(),
        expected_session_revision=7,
        expected_active_capsule_id="capsule-x",
        as_of=NOW,
    )
    with pytest.raises(ValueError, match="without a source range"):
        ContextMaterialization(
            request=request,
            session_revision=7,
            history=(SessionHistoryMessage(6, "assistant", "hi", NOW, False),),
            history_truncated=True,
            truncated_before_sequence=5,
            active_capsule=capsule,
        )


# ---------------------------------------------------------------- P2-7


def test_origin_session_handoff_requires_complete_provenance() -> None:
    with pytest.raises(ValueError):
        validate_event_payload(
            EventType.USER_MESSAGE_RECEIVED,
            {"content": "seed", "origin": "session_handoff"},
        )


def test_origin_human_rejects_any_handoff_provenance() -> None:
    # automation provenance is rejected...
    with pytest.raises(ValueError):
        validate_event_payload(
            EventType.USER_MESSAGE_RECEIVED,
            {
                "content": "seed",
                "origin": "human",
                "source": "session_handoff",
                "handoff_id": "00000000-0000-0000-0000-0000000000d1",
                "principal_identity_hash": "0f" * 32,
                "actor_kind": "automation",
                "trust": "automation",
            },
        )
    # ...and so is a spoofed operator/direct_user seed (review P2).
    with pytest.raises(ValueError):
        validate_event_payload(
            EventType.USER_MESSAGE_RECEIVED,
            {
                "content": "seed",
                "origin": "human",
                "source": "session_handoff",
                "handoff_id": "00000000-0000-0000-0000-0000000000d4",
                "principal_identity_hash": "0f" * 32,
                "actor_kind": "operator",
                "trust": "operator",
            },
        )
    with pytest.raises(ValueError):
        validate_event_payload(
            EventType.USER_MESSAGE_RECEIVED,
            {
                "content": "seed",
                "origin": "human",
                "source": "session_handoff",
                "handoff_id": "00000000-0000-0000-0000-0000000000d5",
                "principal_identity_hash": "0f" * 32,
                "actor_kind": "direct_user",
                "trust": "direct_user",
            },
        )


def test_is_human_message_uses_origin_and_actor() -> None:
    session_id = _session_id()
    harness_origin_human = _event(
        session_id,
        0,
        EventType.USER_MESSAGE_RECEIVED,
        {"content": "spoof", "origin": "human"},
    )
    user_origin_handoff = _event(
        session_id,
        1,
        EventType.USER_MESSAGE_RECEIVED,
        {
            "content": "seed",
            "origin": "session_handoff",
            "source": "session_handoff",
            "handoff_id": "00000000-0000-0000-0000-0000000000d2",
            "principal_identity_hash": "0f" * 32,
            "actor_kind": "automation",
            "trust": "automation",
        },
        actor=EventActor.USER,
    )
    real_human = _event(
        session_id,
        2,
        EventType.USER_MESSAGE_RECEIVED,
        {"content": "real", "origin": "human"},
        actor=EventActor.USER,
    )
    legacy_human = _event(
        session_id,
        3,
        EventType.USER_MESSAGE_RECEIVED,
        {"content": "legacy"},
        actor=EventActor.USER,
    )

    assert not is_human_message(harness_origin_human)
    assert not is_human_message(user_origin_handoff)
    assert is_human_message(real_human)
    assert is_human_message(legacy_human)


# ---------------------------------------------------------------- P2-8


def test_turn_payloads_reject_silent_type_coercion() -> None:
    with pytest.raises(ValueError):
        validate_event_payload(
            EventType.TURN_COMPLETED,
            {"turn_id": "00000000-0000-0000-0000-0000000000e1", "turn_index": True},
        )
    with pytest.raises(ValueError):
        validate_event_payload(
            EventType.TURN_COMPLETED,
            {
                "turn_id": "00000000-0000-0000-0000-0000000000e1",
                "turn_index": 0,
                "closes_segment": 1,
            },
        )
    with pytest.raises(ValueError):
        validate_event_payload(
            EventType.TURN_COMPLETED,
            {
                "turn_id": "00000000-0000-0000-0000-0000000000e1",
                "turn_index": 0,
                "attempt_number": 1.0,
            },
        )
    with pytest.raises(ValueError):
        validate_event_payload(
            EventType.TURN_COMPLETED,
            {"turn_id": "not-a-uuid", "turn_index": 0},
        )
    with pytest.raises(ValueError):
        validate_event_payload(
            EventType.USER_MESSAGE_RECEIVED,
            {
                "content": "hi",
                "turn_id": "00000000-0000-0000-0000-0000000000e1",
                "turn_index": True,
            },
        )
    with pytest.raises(ValueError):
        validate_event_payload(
            EventType.USER_MESSAGE_RECEIVED,
            {"content": "hi", "turn_id": "not-a-uuid", "turn_index": 0},
        )


def test_legacy_turn_id_format_remains_accepted() -> None:
    payload = validate_event_payload(
        EventType.TURN_COMPLETED,
        {"turn_id": "legacy-turn:11", "turn_index": 0, "closes_segment": True},
    )
    assert payload["turn_id"] == "legacy-turn:11"
