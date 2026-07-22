from __future__ import annotations

import base64
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

import pytest
import zebra_agent_api.app as api_app_module
from agent_core.application import attachment_refs_from_event
from agent_core.domain.events import EventType
from agent_core.domain.identifiers import SessionId, new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelToolDefinition
from agent_storage import SQLiteArtifactPayloadStore, SQLiteEventStore
from zebra_agent_api.app import create_app
from zebra_agent_api.session_attachment_inputs import parse_attachment_inputs
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings


def test_attachment_parser_accepts_bounded_utf8_text() -> None:
    parsed = parse_attachment_inputs(
        [
            {
                "file_name": "brief.md",
                "media_type": "text/markdown",
                "content_base64": _encoded("Zebra attachment marker"),
            }
        ]
    )

    assert len(parsed) == 1
    assert parsed[0].file_name == "brief.md"
    assert parsed[0].payload == b"Zebra attachment marker"


@pytest.mark.parametrize(
    ("attachment", "reason"),
    [
        (
            {"file_name": "../secret.txt", "media_type": "text/plain", "content_base64": "QQ=="},
            "safe basename",
        ),
        (
            {"file_name": "unsafe\nname.txt", "media_type": "text/plain", "content_base64": "QQ=="},
            "safe basename",
        ),
        (
            {"file_name": "image.png", "media_type": "image/png", "content_base64": "QQ=="},
            "media_type is not supported",
        ),
        (
            {"file_name": "bad.txt", "media_type": "text/plain", "content_base64": "not base64"},
            "malformed",
        ),
        (
            {"file_name": "bad.txt", "media_type": "text/plain", "content_base64": "//4="},
            "valid UTF-8",
        ),
    ],
)
def test_attachment_parser_rejects_unsafe_inputs(
    attachment: dict[str, str],
    reason: str,
) -> None:
    with pytest.raises(ValueError, match=reason):
        parse_attachment_inputs([attachment])


def test_attachment_parser_enforces_shape_count_and_byte_budgets() -> None:
    valid = _attachment("brief.txt", "material")
    with pytest.raises(ValueError, match="at most 4"):
        parse_attachment_inputs([valid] * 5)
    with pytest.raises(ValueError, match="fields must be"):
        parse_attachment_inputs([{**valid, "unexpected": "field"}])
    with pytest.raises(ValueError, match="65536-byte limit"):
        parse_attachment_inputs(
            [{**valid, "content_base64": base64.b64encode(b"x" * 65_537).decode("ascii")}]
        )
    with pytest.raises(ValueError, match="aggregate limit"):
        parse_attachment_inputs(
            [
                _attachment("a.txt", "a" * 50_000),
                _attachment("b.txt", "b" * 50_000),
                _attachment("c.txt", "c" * 50_000),
            ]
        )


def test_queued_session_persists_attachment_without_exposing_payload(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    app = create_app(database_path, settings=_settings(database_path))

    response = app.create_session(
        {
            "prompt": "Summarize the attached brief.",
            "workspace": str(tmp_path),
            "attachments": [_attachment("brief.txt", "ATTACHMENT-QUEUE-131")],
        }
    )

    assert response.status_code == 201
    attachment = response.body["attachments"][0]
    session_id = SessionId(response.body["session_id"])
    events = SQLiteEventStore(database_path).list_for_session(session_id)
    user_event = next(
        event for event in events if event.event_type is EventType.USER_MESSAGE_RECEIVED
    )
    refs = attachment_refs_from_event(user_event)
    assert refs[0].to_mapping() == attachment
    assert "content_base64" not in user_event.payload
    assert "ATTACHMENT-QUEUE-131" not in str(user_event.payload)
    assert SQLiteArtifactPayloadStore(database_path).read_payload_bytes(
        refs[0].attachment_id
    ) == b"ATTACHMENT-QUEUE-131"

    restarted = create_app(database_path, settings=_settings(database_path))
    detail = restarted.get_session(str(session_id))
    assert detail.body["attachments"] == [attachment]
    assert all("uri" not in item for item in detail.body["attachments"])


def test_execute_session_projects_attachment_as_untrusted_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    requests: list[tuple[SessionMessage, ...]] = []

    class RecordingGateway:
        def complete(
            self,
            messages: list[SessionMessage],
            *,
            tools: tuple[ModelToolDefinition, ...] = (),
        ) -> ModelCompletion:
            assert tools
            requests.append(tuple(messages))
            return ModelCompletion(
                assistant_message=SessionMessage(
                    message_id=new_message_id(),
                    role=MessageRole.ASSISTANT,
                    content="Attachment received.",
                    created_at=_created_at(),
                )
            )

    monkeypatch.setattr(
        api_app_module,
        "build_model_gateway",
        lambda settings: RecordingGateway(),
    )
    response = create_app(database_path, settings=_settings(database_path)).create_session(
        {
            "prompt": "Read my material.",
            "workspace": str(tmp_path),
            "execute": True,
            "attachments": [_attachment("material.txt", "ATTACHMENT-CONTEXT-131")],
        }
    )

    assert response.status_code == 201
    assert requests[0][0].role is MessageRole.SYSTEM
    assert "[user_attachment] material.txt" in requests[0][0].content
    assert "Untrusted user-provided material" in requests[0][0].content
    assert "do not use workspace tools to retrieve it" in requests[0][0].content
    assert "ATTACHMENT-CONTEXT-131" in requests[0][0].content
    assert requests[0][-1].content == "Read my material."


def test_later_message_attachment_survives_worker_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    app = create_app(database_path, settings=_settings(database_path))
    created = app.create_session(
        {
            "prompt": "Wait for the updated material.",
            "workspace": str(tmp_path),
        }
    )
    session_id = created.body["session_id"]
    appended = app.append_session_message(
        session_id,
        {
            "content": "Use the replacement material.",
            "attachments": [_attachment("replacement.txt", "ATTACHMENT-RECOVERY-131")],
        },
    )
    requests: list[tuple[SessionMessage, ...]] = []

    class RecordingGateway:
        def complete(
            self,
            messages: list[SessionMessage],
            *,
            tools: tuple[ModelToolDefinition, ...] = (),
        ) -> ModelCompletion:
            requests.append(tuple(messages))
            return ModelCompletion(
                assistant_message=SessionMessage(
                    message_id=new_message_id(),
                    role=MessageRole.ASSISTANT,
                    content="Recovered attachment.",
                    created_at=_created_at(),
                )
            )

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: RecordingGateway(),
    )
    resumed = app.resume_session(session_id, {"worker_id": "attachment-worker"})

    assert appended.status_code == 201
    assert appended.body["attachments"][0]["file_name"] == "replacement.txt"
    assert resumed.status_code == 200
    assert "ATTACHMENT-RECOVERY-131" in requests[0][0].content
    assert requests[0][-1].content == "Use the replacement material."


def test_worker_fails_closed_when_attachment_payload_is_unavailable(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    app = create_app(database_path, settings=_settings(database_path))
    created = app.create_session(
        {
            "prompt": "Use the attached material.",
            "workspace": str(tmp_path),
            "attachments": [_attachment("brief.txt", "material")],
        }
    )
    attachment_id = created.body["attachments"][0]["attachment_id"]
    from agent_core.domain.identifiers import ArtifactId

    SQLiteArtifactPayloadStore(database_path).prune_payload(ArtifactId(UUID(attachment_id)))
    response = app.resume_session(created.body["session_id"], {})

    assert response.status_code == 409
    assert response.body["status"] == "execution_error"
    assert "attachment recovery failed" in response.body["reason"]


def test_worker_fails_closed_when_attachment_payload_digest_changes(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    app = create_app(database_path, settings=_settings(database_path))
    created = app.create_session(
        {
            "prompt": "Use the attached material.",
            "workspace": str(tmp_path),
            "attachments": [_attachment("brief.txt", "material")],
        }
    )
    from agent_core.domain.identifiers import ArtifactId

    attachment_id = ArtifactId(UUID(created.body["attachments"][0]["attachment_id"]))
    stored = SQLiteArtifactPayloadStore(database_path).get_payload(attachment_id)
    assert stored is not None
    # CTX-ART-02: use access_uri (file://) for filesystem operations.
    assert stored.access_uri is not None
    Path(urlparse(stored.access_uri).path).write_bytes(b"tampered")

    response = app.resume_session(created.body["session_id"], {})

    assert response.status_code == 409
    assert response.body["status"] == "execution_error"
    assert "digest does not match" in response.body["reason"]


def test_clarification_response_rejects_attachments(tmp_path: Path) -> None:
    response = create_app(tmp_path / "sessions.sqlite").append_session_message(
        "00000000-0000-0000-0000-000000000001",
        {
            "content": "A",
            "clarification_id": "clarify-1",
            "attachments": [_attachment("brief.txt", "material")],
        },
    )

    assert response.status_code == 400
    assert response.body["reason"] == "clarification responses do not accept attachments"


def _attachment(file_name: str, content: str) -> dict[str, str]:
    return {
        "file_name": file_name,
        "media_type": "text/plain",
        "content_base64": _encoded(content),
    }


def _encoded(content: str) -> str:
    return base64.b64encode(content.encode("utf-8")).decode("ascii")


def _settings(database_path: Path) -> ZebraAgentSettings:
    return ZebraAgentSettings(
        profile="test",
        database_url=str(database_path),
        api=ApiSettings(auth_token=None),
        model=ModelSettings(
            provider="test",
            api_key_env="TEST_API_KEY",
            base_url="https://example.test",
            model="test-model",
        ),
    )


def _created_at():
    from datetime import UTC, datetime

    return datetime(2026, 7, 15, 10, 0, tzinfo=UTC)
