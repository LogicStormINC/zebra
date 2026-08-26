from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile, ZipInfo

import pytest
import zebra_agent_api.session_attachment_inputs as attachment_inputs
import zebra_agent_api.session_document_inputs as document_inputs
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelToolDefinition
from agent_storage import SQLiteArtifactPayloadStore, SQLiteEventStore
from zebra_agent_api.app import create_app
from zebra_agent_api.session_attachment_inputs import (
    DOCX_MEDIA_TYPE,
    MAX_DOCX_BYTES,
    parse_attachment_inputs,
)
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings


def _finish_first_turn(database_path: Path, session_id: str) -> None:
    """Close bootstrap Turn 0 so a follow-up message can be admitted."""
    from uuid import UUID

    from agent_core.application import current_turn
    from agent_core.application.session_projection import rebuild_session
    from agent_core.domain.events import EventActor, EventType, SessionEvent
    from agent_core.domain.identifiers import SessionId
    from agent_core.domain.turns import derive_turn_id
    from agent_storage import SQLiteEventStore as _Store
    from agent_storage import SQLiteProjectionStore as _Proj

    key = SessionId(UUID(str(session_id)))
    event_store = _Store(database_path)
    events = event_store.list_for_session(key)
    session = events[0].session_id
    open_turn = current_turn(events)
    turn_id = (
        open_turn.turn_id if open_turn else str(derive_turn_id(session, 0))
    )
    turn_index = open_turn.turn_index if open_turn else 0
    base = events[-1].sequence
    event_store.append(
        SessionEvent.create(
            session_id=session,
            sequence=base + 1,
            event_type=EventType.HARNESS_ATTEMPT_STARTED,
            actor=EventActor.HARNESS,
            payload={"attempt_number": 1},
        )
    )
    event_store.append(
        SessionEvent.create(
            session_id=session,
            sequence=base + 2,
            event_type=EventType.TURN_COMPLETED,
            actor=EventActor.HARNESS,
            payload={
                "turn_id": turn_id,
                "turn_index": turn_index,
                "closes_segment": False,
            },
        )
    )
    _Proj(database_path).save_session(
        rebuild_session(event_store.list_for_session(key))
    )



def test_docx_parser_extracts_body_and_table_text_with_safe_provenance() -> None:
    docx = _docx_bytes(
        "<w:p><w:r><w:t>DOCX_ATTACHMENT_MARKER_141</w:t></w:r></w:p>"
        "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Cell A</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>Cell B</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
    )

    parsed = parse_attachment_inputs([_docx_attachment(docx)])

    assert len(parsed) == 1
    assert parsed[0].payload == b"DOCX_ATTACHMENT_MARKER_141\n\nCell A\n\nCell B"
    assert parsed[0].media_type == "text/plain"
    assert parsed[0].original_media_type == DOCX_MEDIA_TYPE
    assert parsed[0].original_size_bytes == len(docx)
    assert parsed[0].original_sha256 is not None
    assert len(parsed[0].original_sha256) == 64
    assert parsed[0].page_count is None
    assert parsed[0].paragraph_count == 3
    assert parsed[0].extraction_status == "text_extracted"


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("signature", "ZIP signature is invalid"),
        ("extension", "must end with .docx"),
        ("malformed", "malformed"),
        ("missing", "missing required package parts"),
        ("empty", "no extractable body"),
        ("external", "external relationships"),
        ("macro", "macro-enabled"),
        ("embedding", "embedded objects"),
        ("altchunk", "altChunk"),
        ("entity", "declarations and entities"),
        ("unsafe_path", "unsafe package path"),
    ],
)
def test_docx_parser_rejects_unsupported_or_unsafe_documents(
    case: str,
    reason: str,
) -> None:
    with pytest.raises(ValueError, match=reason):
        parse_attachment_inputs([_unsafe_docx_case(case)])


def test_docx_raw_and_archive_limits_are_enforced_before_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oversized = b"PK\x03\x04" + b"x" * MAX_DOCX_BYTES
    with pytest.raises(ValueError, match=f"{MAX_DOCX_BYTES}-byte limit"):
        parse_attachment_inputs([_docx_attachment(oversized)])

    docx = _docx_bytes("<w:p><w:r><w:t>limit</w:t></w:r></w:p>")
    monkeypatch.setattr(document_inputs, "MAX_DOCX_ENTRIES", 1)
    with pytest.raises(ValueError, match="1-entry limit"):
        parse_attachment_inputs([_docx_attachment(docx)])

    monkeypatch.setattr(document_inputs, "MAX_DOCX_ENTRIES", 256)
    monkeypatch.setattr(document_inputs, "MAX_DOCX_TOTAL_EXPANDED_BYTES", 10)
    with pytest.raises(ValueError, match="expanded-content limit"):
        parse_attachment_inputs([_docx_attachment(docx)])


def test_docx_archive_metadata_rejects_encryption_duplicates_and_compression_bombs() -> None:
    encrypted = ZipInfo("word/document.xml")
    encrypted.flag_bits = 0x1
    encrypted.file_size = encrypted.compress_size = 1
    with pytest.raises(ValueError, match="encrypted DOCX"):
        document_inputs._validate_docx_entries([encrypted])

    duplicate_a = ZipInfo("word/document.xml")
    duplicate_b = ZipInfo("word/document.xml")
    with pytest.raises(ValueError, match="duplicate package parts"):
        document_inputs._validate_docx_entries([duplicate_a, duplicate_b])

    compressed = ZipInfo("word/document.xml")
    compressed.file_size = 101
    compressed.compress_size = 1
    with pytest.raises(ValueError, match="compression-ratio limit"):
        document_inputs._validate_docx_entries([compressed])


def test_docx_extracted_and_mixed_document_aggregate_limits_are_enforced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    docx = _docx_bytes("<w:p><w:r><w:t>bounded text</w:t></w:r></w:p>")
    monkeypatch.setattr(document_inputs, "MAX_EXTRACTED_TEXT_BYTES", 4)
    with pytest.raises(ValueError, match="DOCX extracted text exceeds"):
        parse_attachment_inputs([_docx_attachment(docx)])

    monkeypatch.setattr(document_inputs, "MAX_EXTRACTED_TEXT_BYTES", 65_536)
    monkeypatch.setattr(attachment_inputs, "MAX_DOCUMENT_TOTAL_BYTES", len(docx) * 2 - 1)
    with pytest.raises(ValueError, match="document attachments exceed"):
        parse_attachment_inputs([_docx_attachment(docx), _docx_attachment(docx)])


def test_queued_docx_persists_only_extracted_text_and_recovers_without_reparse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    docx = _docx_bytes("<w:p><w:r><w:t>DOCX_DURABLE_RECOVERY_141</w:t></w:r></w:p>")
    app = create_app(database_path, settings=_settings(database_path))
    created = app.create_session(
        {
            "prompt": "Wait for the DOCX.",
            "workspace": str(tmp_path),
        }
    )

    assert created.status_code == 201
    _finish_first_turn(database_path, created.body["session_id"])
    appended = app.append_session_message(
        created.body["session_id"],
        {
            "content": "Read the DOCX.",
            "attachments": [_docx_attachment(docx)],
        },
    )
    assert appended.status_code == 201
    attachment = appended.body["attachments"][0]
    assert attachment["original_media_type"] == DOCX_MEDIA_TYPE
    assert attachment["original_size_bytes"] == len(docx)
    assert attachment["paragraph_count"] == 1
    assert attachment["page_count"] is None
    assert "content_base64" not in attachment
    stored = SQLiteArtifactPayloadStore(database_path).read_payload_bytes(
        _attachment_id(attachment["attachment_id"])
    )
    assert stored == b"DOCX_DURABLE_RECOVERY_141"
    assert stored != docx

    def forbidden_reparse(payload: bytes) -> tuple[bytes, int]:
        raise AssertionError(f"unexpected DOCX reparse of {len(payload)} bytes")

    monkeypatch.setattr(attachment_inputs, "_extract_docx_text", forbidden_reparse)
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
                    content="Recovered DOCX material.",
                    created_at=_created_at(),
                )
            )

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: RecordingGateway(),
    )
    resumed = app.resume_session(created.body["session_id"], {"worker_id": "docx-worker"})

    assert resumed.status_code == 200
    assert "DOCX_DURABLE_RECOVERY_141" in requests[0][0].content
    assert requests[0][-1].content == "Read the DOCX."


def test_invalid_docx_fails_before_session_mutation(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    app = create_app(database_path, settings=_settings(database_path))

    response = app.create_session(
        {
            "prompt": "Read the DOCX.",
            "workspace": str(tmp_path),
            "attachments": [_docx_attachment(b"PK\x03\x04malformed")],
        }
    )

    assert response.status_code == 400
    assert SQLiteEventStore(database_path).list_for_session(_session_id()) == []
    assert app.list_sessions({}).body["count"] == 0


def _docx_bytes(
    body: str,
    *,
    extras: dict[str, bytes] | None = None,
    main_content_type: str = document_inputs._DOCX_MAIN_CONTENT_TYPE,
    document_prolog: str = '<?xml version="1.0" encoding="UTF-8"?>',
) -> bytes:
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Override PartName="/word/document.xml" '
        f'ContentType="{main_content_type}"/>'
        "</Types>"
    ).encode()
    document = (
        document_prolog
        + f'<w:document xmlns:w="{document_inputs._WORD_NS}"><w:body>{body}</w:body>'
        + "</w:document>"
    ).encode()
    output = BytesIO()
    with ZipFile(output, "w", ZIP_STORED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("word/document.xml", document)
        for name, value in (extras or {}).items():
            archive.writestr(name, value)
    return output.getvalue()


def _docx_attachment(payload: bytes) -> dict[str, str]:
    return {
        "file_name": "brief.docx",
        "media_type": DOCX_MEDIA_TYPE,
        "content_base64": base64.b64encode(payload).decode("ascii"),
    }


def _unsafe_docx_case(case: str) -> dict[str, str]:
    if case == "signature":
        return _docx_attachment(b"not-a-docx")
    if case == "extension":
        value = _docx_attachment(_docx_bytes("<w:p><w:r><w:t>x</w:t></w:r></w:p>"))
        return {**value, "file_name": "brief.txt"}
    if case == "malformed":
        return _docx_attachment(b"PK\x03\x04broken")
    if case == "missing":
        output = BytesIO()
        with ZipFile(output, "w") as archive:
            archive.writestr("unrelated.xml", b"<root/>")
        return _docx_attachment(output.getvalue())
    if case == "empty":
        return _docx_attachment(_docx_bytes("<w:p/>"))
    if case == "external":
        relationships = (
            f'<Relationships xmlns="{document_inputs._PACKAGE_REL_NS}">'
            '<Relationship Id="r1" Target="https://example.test" TargetMode="External"/>'
            "</Relationships>"
        ).encode()
        return _docx_attachment(
            _docx_bytes(
                "<w:p><w:r><w:t>x</w:t></w:r></w:p>",
                extras={"word/_rels/document.xml.rels": relationships},
            )
        )
    if case == "macro":
        return _docx_attachment(
            _docx_bytes(
                "<w:p><w:r><w:t>x</w:t></w:r></w:p>",
                main_content_type="application/vnd.ms-word.document.macroEnabled.main+xml",
            )
        )
    if case == "embedding":
        return _docx_attachment(
            _docx_bytes(
                "<w:p><w:r><w:t>x</w:t></w:r></w:p>",
                extras={"word/embeddings/object.bin": b"object"},
            )
        )
    if case == "altchunk":
        return _docx_attachment(_docx_bytes("<w:altChunk/>"))
    if case == "entity":
        return _docx_attachment(
            _docx_bytes(
                "<w:p><w:r><w:t>x</w:t></w:r></w:p>",
                document_prolog="<!DOCTYPE x [<!ENTITY x 'bad'>]>",
            )
        )
    return _docx_attachment(
        _docx_bytes(
            "<w:p><w:r><w:t>x</w:t></w:r></w:p>",
            extras={"../unsafe.xml": b"<x/>"},
        )
    )


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


def _attachment_id(value: str):
    from uuid import UUID

    from agent_core.domain.identifiers import ArtifactId

    return ArtifactId(UUID(value))


def _session_id():
    from agent_core.domain.identifiers import SessionId

    return SessionId("00000000-0000-0000-0000-000000000141")


def _created_at():
    from datetime import UTC, datetime

    return datetime(2026, 7, 16, 15, 0, tzinfo=UTC)
