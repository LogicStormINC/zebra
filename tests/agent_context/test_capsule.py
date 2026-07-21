from datetime import UTC, datetime

from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_context.capsule import build_context_capsule


NOW = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)


def test_message_artifact_refs_strip_trailing_punctuation_from_embedded_and_metadata_refs() -> None:
    message = SessionMessage(
        message_id=new_message_id(),
        role=MessageRole.TOOL,
        content='Wrote payload to file:///tmp/payload.txt", then uploaded.',
        created_at=NOW,
        tool_call_id="call-1",
        metadata={"artifact_uri": "file:///tmp/metadata.txt\","},
    )
    capsule = build_context_capsule(
        (message,),
        user_goal="Verify artifact parsing",
        created_at=NOW,
    )

    assert capsule.artifact_refs == (
        "file:///tmp/metadata.txt",
        "file:///tmp/payload.txt",
    )


def test_message_artifact_refs_skip_unusable_metadata_only_when_empty_after_normalization() -> None:
    message = SessionMessage(
        message_id=new_message_id(),
        role=MessageRole.TOOL,
        content='Summary at file:///tmp/report.txt"),',
        created_at=NOW,
        tool_call_id="call-2",
        metadata={"artifact_uri": ",\""},
    )
    capsule = build_context_capsule(
        (message,),
        user_goal="Verify artifact parsing",
        created_at=NOW,
    )

    assert capsule.artifact_refs == ("file:///tmp/report.txt",)
