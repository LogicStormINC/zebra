from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

import pytest
import zebra_agent_api.session_attachment_inputs as attachment_inputs
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelToolDefinition
from agent_storage import SQLiteArtifactPayloadStore, SQLiteEventStore
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from zebra_agent_api.app import create_app
from zebra_agent_api.session_attachment_inputs import (
    MAX_PDF_BYTES,
    MAX_PDF_PAGES,
    parse_attachment_inputs,
)
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings


def test_pdf_parser_extracts_bounded_text_with_safe_provenance() -> None:
    pdf = _pdf_bytes("PDF_ATTACHMENT_MARKER_140")

    parsed = parse_attachment_inputs([_pdf_attachment(pdf)])

    assert len(parsed) == 1
    assert parsed[0].payload == b"[PDF page 1]\nPDF_ATTACHMENT_MARKER_140"
    assert parsed[0].media_type == "text/plain"
    assert parsed[0].original_media_type == "application/pdf"
    assert parsed[0].original_size_bytes == len(pdf)
    assert parsed[0].original_sha256 is not None
    assert len(parsed[0].original_sha256) == 64
    assert parsed[0].page_count == 1
    assert parsed[0].extraction_status == "text_extracted"


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("signature", "signature is invalid"),
        ("extension", "must end with .pdf"),
        ("empty", "no extractable text"),
        ("encrypted", "encrypted PDF"),
        ("pages", "64-page limit"),
    ],
)
def test_pdf_parser_rejects_unsupported_or_unsafe_documents(
    case: str,
    reason: str,
) -> None:
    with pytest.raises(ValueError, match=reason):
        parse_attachment_inputs([_unsafe_pdf_case(case)])


def test_pdf_raw_byte_limit_is_checked_before_parsing() -> None:
    oversized = b"%PDF-" + b"x" * MAX_PDF_BYTES

    with pytest.raises(ValueError, match=f"{MAX_PDF_BYTES}-byte limit"):
        parse_attachment_inputs([_pdf_attachment(oversized)])


def test_pdf_parser_enforces_decoded_stream_and_extracted_text_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf = _pdf_bytes("PDF_LIMIT_MARKER_140")

    monkeypatch.setattr(attachment_inputs, "MAX_PDF_PAGE_CONTENT_BYTES", 1)
    with pytest.raises(ValueError, match="page 1 exceeds the decoded content limit"):
        parse_attachment_inputs([_pdf_attachment(pdf)])

    monkeypatch.setattr(attachment_inputs, "MAX_PDF_PAGE_CONTENT_BYTES", 1_000_000)
    monkeypatch.setattr(attachment_inputs, "MAX_PDF_TOTAL_CONTENT_BYTES", 1)
    with pytest.raises(ValueError, match="decoded content aggregate limit"):
        parse_attachment_inputs([_pdf_attachment(pdf)])

    monkeypatch.setattr(attachment_inputs, "MAX_PDF_TOTAL_CONTENT_BYTES", 1_000_000)
    monkeypatch.setattr(attachment_inputs, "MAX_ATTACHMENT_BYTES", 8)
    with pytest.raises(ValueError, match="PDF extracted text exceeds"):
        parse_attachment_inputs([_pdf_attachment(pdf)])


def test_queued_pdf_persists_only_extracted_text_and_recovers_without_reparse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    pdf = _pdf_bytes("PDF_DURABLE_RECOVERY_140")
    app = create_app(database_path, settings=_settings(database_path))
    created = app.create_session(
        {
            "prompt": "Read the PDF.",
            "workspace": str(tmp_path),
            "attachments": [_pdf_attachment(pdf)],
        }
    )

    assert created.status_code == 201
    attachment = created.body["attachments"][0]
    assert attachment["original_media_type"] == "application/pdf"
    assert attachment["original_size_bytes"] == len(pdf)
    assert attachment["page_count"] == 1
    assert "content_base64" not in attachment
    stored = SQLiteArtifactPayloadStore(database_path).read_payload_bytes(
        _attachment_id(attachment["attachment_id"])
    )
    assert stored == b"[PDF page 1]\nPDF_DURABLE_RECOVERY_140"
    assert stored != pdf

    def forbidden_reparse(payload: bytes) -> tuple[bytes, int]:
        raise AssertionError(f"unexpected PDF reparse of {len(payload)} bytes")

    monkeypatch.setattr(
        "zebra_agent_api.session_attachment_inputs._extract_pdf_text",
        forbidden_reparse,
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
                    content="Recovered PDF material.",
                    created_at=_created_at(),
                )
            )

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: RecordingGateway(),
    )
    resumed = app.resume_session(created.body["session_id"], {"worker_id": "pdf-worker"})

    assert resumed.status_code == 200
    assert "PDF_DURABLE_RECOVERY_140" in requests[0][0].content
    assert requests[0][-1].content == "Read the PDF."


def test_invalid_pdf_fails_before_session_mutation(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    app = create_app(database_path, settings=_settings(database_path))

    response = app.create_session(
        {
            "prompt": "Read the PDF.",
            "workspace": str(tmp_path),
            "attachments": [_pdf_attachment(b"%PDF-malformed")],
        }
    )

    assert response.status_code == 400
    assert SQLiteEventStore(database_path).list_for_session(_session_id()) == []
    assert app.list_sessions({}).body["count"] == 0


def _pdf_bytes(
    text: str | None,
    *,
    page_count: int = 1,
    encrypted: bool = False,
) -> bytes:
    writer = PdfWriter()
    for index in range(page_count):
        page = writer.add_blank_page(width=200, height=200)
        if text is None or index > 0:
            continue
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        content = DecodedStreamObject()
        content.set_data(f"BT /F1 12 Tf 10 100 Td ({text}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(content)
    if encrypted:
        writer.encrypt("password")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _pdf_attachment(payload: bytes) -> dict[str, str]:
    return {
        "file_name": "brief.pdf",
        "media_type": "application/pdf",
        "content_base64": base64.b64encode(payload).decode("ascii"),
    }


def _unsafe_pdf_case(case: str) -> dict[str, str]:
    if case == "signature":
        return _pdf_attachment(b"not-a-pdf")
    if case == "extension":
        return {**_pdf_attachment(_pdf_bytes("valid")), "file_name": "document.txt"}
    if case == "empty":
        return _pdf_attachment(_pdf_bytes(None))
    if case == "encrypted":
        return _pdf_attachment(_pdf_bytes("secret", encrypted=True))
    return _pdf_attachment(_pdf_bytes(None, page_count=MAX_PDF_PAGES + 1))


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

    return SessionId("00000000-0000-0000-0000-000000000140")


def _created_at():
    from datetime import UTC, datetime

    return datetime(2026, 7, 16, 14, 0, tzinfo=UTC)
