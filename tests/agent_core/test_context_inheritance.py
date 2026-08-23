from datetime import UTC, datetime
from uuid import UUID

import pytest
from agent_core.domain.context_inheritance import (
    REQUIRED_CONTEXT_OMISSIONS,
    ContextInheritanceMode,
    DelegatedContextItem,
    DelegatedContextSnapshot,
)
from agent_core.domain.identifiers import SessionId
from pydantic import ValidationError

SESSION_ID = SessionId(UUID("00000000-0000-0000-0000-000000000101"))
MEMORY_ID = "00000000-0000-0000-0000-000000000201"


def _snapshot(
    mode: ContextInheritanceMode,
    *items: DelegatedContextItem,
) -> DelegatedContextSnapshot:
    capsule = next((item for item in items if item.kind == "capsule"), None)
    memories = tuple(item for item in items if item.kind == "memory")
    return DelegatedContextSnapshot.create(
        mode=mode,
        source_session_id=SESSION_ID,
        source_session_revision=9,
        active_capsule_id="capsule-9" if capsule is not None else None,
        memory_revisions=((MEMORY_ID, 2),) if memories else (),
        items=items,
        known_omissions=tuple(sorted(REQUIRED_CONTEXT_OMISSIONS)),
        created_at=datetime(2026, 8, 23, 12, 0, tzinfo=UTC),
    )


def test_context_modes_have_distinct_fail_closed_shapes() -> None:
    capsule = DelegatedContextItem(
        kind="capsule",
        locator="context-capsule://capsule-9",
        content="Objective: keep the verified contract.",
    )
    history = DelegatedContextItem(
        kind="history",
        locator=f"session-event://{SESSION_ID}/8",
        content="user: inspect the contract",
        source_sequence=8,
    )
    memory = DelegatedContextItem(
        kind="memory",
        locator=f"confirmed-memory://{MEMORY_ID}@2",
        content="Use the PostgreSQL authority.",
        memory_type="project_rule",
    )

    assert _snapshot(ContextInheritanceMode.CAPSULE, capsule).items == (capsule,)
    assert _snapshot(ContextInheritanceMode.FORK_TAIL, history).items == (history,)
    assert _snapshot(ContextInheritanceMode.RESUME, capsule, history, memory).items[-1] == memory

    with pytest.raises(ValidationError, match="capsule mode"):
        _snapshot(ContextInheritanceMode.CAPSULE, history)
    with pytest.raises(ValidationError, match="fork_tail mode"):
        _snapshot(ContextInheritanceMode.FORK_TAIL, capsule)
    with pytest.raises(ValidationError, match="resume mode"):
        _snapshot(ContextInheritanceMode.RESUME)


def test_snapshot_checksum_and_omissions_are_tamper_evident() -> None:
    snapshot = _snapshot(
        ContextInheritanceMode.FORK_TAIL,
        DelegatedContextItem(
            kind="history",
            locator=f"session-event://{SESSION_ID}/8",
            content="assistant: bounded evidence",
            source_sequence=8,
        ),
    )

    assert snapshot.checksum == snapshot.expected_checksum()
    with pytest.raises(ValidationError, match="checksum"):
        DelegatedContextSnapshot.model_validate(
            {**snapshot.model_dump(mode="json"), "checksum": "f" * 64}
        )
    with pytest.raises(ValidationError, match="checksum"):
        DelegatedContextSnapshot.model_validate(
            {**snapshot.model_dump(mode="json"), "checksum": "0" * 64}
        )
    with pytest.raises(ValidationError, match="known omissions"):
        DelegatedContextSnapshot.model_validate(
            {**snapshot.model_dump(mode="json"), "known_omissions": []}
        )


def test_snapshot_rejects_coerced_revisions_and_false_source_locators() -> None:
    snapshot = _snapshot(
        ContextInheritanceMode.FORK_TAIL,
        DelegatedContextItem(
            kind="history",
            locator=f"session-event://{SESSION_ID}/8",
            content="assistant: bounded evidence",
            source_sequence=8,
        ),
    )
    payload = snapshot.model_dump(mode="json")

    with pytest.raises(ValidationError):
        DelegatedContextSnapshot.model_validate({**payload, "source_session_revision": True})
    with pytest.raises(ValidationError):
        DelegatedContextSnapshot.model_validate(
            {
                **payload,
                "items": [
                    {
                        **payload["items"][0],
                        "source_sequence": True,
                    }
                ],
            }
        )
    with pytest.raises(ValidationError, match="History locator"):
        DelegatedContextSnapshot.create(
            mode=ContextInheritanceMode.FORK_TAIL,
            source_session_id=SESSION_ID,
            source_session_revision=9,
            items=(
                DelegatedContextItem(
                    kind="history",
                    locator=f"session-event://{SESSION_ID}/7",
                    content="assistant: false locator",
                    source_sequence=8,
                ),
            ),
            known_omissions=tuple(sorted(REQUIRED_CONTEXT_OMISSIONS)),
            created_at=datetime(2026, 8, 23, 12, 0, tzinfo=UTC),
        )
