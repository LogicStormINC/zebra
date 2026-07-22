from datetime import UTC, datetime

from agent_context.capsule import build_context_capsule
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage

NOW = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)


def test_artifact_refs_come_only_from_structured_metadata_not_free_text() -> None:
    """CTX-ART-01: a URI appearing as plain text in tool output must NOT be
    promoted to a capsule artifact ref. Only structured ``artifact_uri``
    metadata is a trustworthy provenance source."""
    message = SessionMessage(
        message_id=new_message_id(),
        role=MessageRole.TOOL,
        content="Wrote payload to file:///tmp/payload.txt, then uploaded.",
        created_at=NOW,
        tool_call_id="call-1",
        metadata={"artifact_uri": "file:///tmp/metadata.txt\","},
    )
    capsule = build_context_capsule(
        (message,),
        user_goal="Verify artifact parsing",
        created_at=NOW,
    )

    # The free-text file:///tmp/payload.txt is excluded; only the structured
    # metadata ref survives, with trailing punctuation stripped.
    assert capsule.artifact_refs == ("file:///tmp/metadata.txt",)


def test_artifact_refs_empty_when_metadata_is_absent_even_if_text_contains_uri() -> None:
    """Without structured artifact_uri metadata, no refs are produced — even if
    the tool body text contains file:// URIs."""
    message = SessionMessage(
        message_id=new_message_id(),
        role=MessageRole.TOOL,
        content="Summary at file:///tmp/report.txt",
        created_at=NOW,
        tool_call_id="call-2",
    )
    capsule = build_context_capsule(
        (message,),
        user_goal="Verify artifact parsing",
        created_at=NOW,
    )

    assert capsule.artifact_refs == ()


def test_artifact_refs_skipped_when_metadata_normalizes_to_empty() -> None:
    """Metadata that is only punctuation after normalization produces no ref."""
    message = SessionMessage(
        message_id=new_message_id(),
        role=MessageRole.TOOL,
        content="done",
        created_at=NOW,
        tool_call_id="call-3",
        metadata={"artifact_uri": ",\""},
    )
    capsule = build_context_capsule(
        (message,),
        user_goal="Verify artifact parsing",
        created_at=NOW,
    )

    assert capsule.artifact_refs == ()
