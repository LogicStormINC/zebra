from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

import pytest
import zebra_agent_api.session_attachment_inputs as attachment_inputs
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelToolDefinition
from agent_storage import SQLiteArtifactPayloadStore, SQLiteEventStore
from zebra_agent_api.app import create_app
from zebra_agent_api.session_attachment_inputs import PPTX_MEDIA_TYPE, parse_attachment_inputs
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



def test_pptx_parser_extracts_visible_text_in_slide_order_with_safe_provenance() -> None:
    pptx = _pptx_bytes(
        slides=(
            ("PPTX_ATTACHMENT_MARKER_143", "First detail"),
            ("Second slide",),
        )
    )

    parsed = parse_attachment_inputs([_attachment(pptx)])

    assert parsed[0].payload == (
        b"[PPTX slide: 1]\nPPTX_ATTACHMENT_MARKER_143\nFirst detail\n\n"
        b"[PPTX slide: 2]\nSecond slide"
    )
    assert parsed[0].original_media_type == PPTX_MEDIA_TYPE
    assert parsed[0].slide_count == 2
    assert parsed[0].page_count is None
    assert parsed[0].paragraph_count is None
    assert parsed[0].worksheet_count is None
    assert parsed[0].cell_count is None


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("signature", "ZIP signature is invalid"),
        ("extension", "must end with .pptx"),
        ("missing", "missing required package parts"),
        ("empty", "no extractable visible slide text"),
        ("external", "external relationships"),
        ("embedded", "active or embedded content"),
        ("macro", "active or embedded content"),
        ("bad_target", "unsafe slide target"),
    ],
)
def test_pptx_parser_rejects_unsafe_or_unsupported_presentations(
    case: str, reason: str
) -> None:
    with pytest.raises(ValueError, match=reason):
        parse_attachment_inputs([_unsafe_case(case)])


def test_pptx_limits_fail_before_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    from zebra_agent_api import session_presentation_inputs as presentation_inputs

    pptx = _pptx_bytes(slides=(("value",),))
    monkeypatch.setattr(presentation_inputs, "MAX_PPTX_SLIDES", 0)
    with pytest.raises(ValueError, match="1 to 0 slides"):
        parse_attachment_inputs([_attachment(pptx)])

    monkeypatch.setattr(presentation_inputs, "MAX_PPTX_SLIDES", 64)
    monkeypatch.setattr(presentation_inputs, "MAX_PPTX_TEXT_BYTES", 4)
    with pytest.raises(ValueError, match="extracted text exceeds"):
        parse_attachment_inputs([_attachment(pptx)])


def test_later_pptx_message_recovers_from_extracted_bytes_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    pptx = _pptx_bytes(slides=(("PPTX_RECOVERY_143",),))
    app = create_app(database_path, settings=_settings(database_path))
    created = app.create_session({"prompt": "Wait.", "workspace": str(tmp_path)})
    _finish_first_turn(database_path, created.body["session_id"])
    appended = app.append_session_message(
        created.body["session_id"],
        {"content": "Read the slides.", "attachments": [_attachment(pptx)]},
    )
    ref = appended.body["attachments"][0]
    assert ref["slide_count"] == 1
    stored = SQLiteArtifactPayloadStore(database_path).read_payload_bytes(
        _attachment_id(ref["attachment_id"])
    )
    assert stored == b"[PPTX slide: 1]\nPPTX_RECOVERY_143"
    assert stored != pptx

    def forbidden_reparse(payload: bytes) -> tuple[bytes, int]:
        raise AssertionError(f"unexpected PPTX reparse of {len(payload)} bytes")

    monkeypatch.setattr(attachment_inputs, "_extract_pptx_text", forbidden_reparse)
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
                    content="Recovered presentation.",
                    created_at=_created_at(),
                )
            )

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: RecordingGateway(),
    )
    resumed = app.resume_session(created.body["session_id"], {"worker_id": "pptx-worker"})
    assert resumed.status_code == 200
    assert "PPTX_RECOVERY_143" in requests[0][0].content


def test_invalid_pptx_fails_before_session_mutation(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    app = create_app(database_path, settings=_settings(database_path))
    response = app.create_session(
        {
            "prompt": "Read presentation.",
            "workspace": str(tmp_path),
            "attachments": [_attachment(b"PK\x03\x04broken")],
        }
    )
    assert response.status_code == 400
    assert SQLiteEventStore(database_path).list_for_session(_session_id()) == []


def _pptx_bytes(
    *,
    slides: tuple[tuple[str, ...], ...],
    extras: dict[str, bytes] | None = None,
    external: bool = False,
    unsafe_target: bool = False,
) -> bytes:
    presentation_ns = "http://schemas.openxmlformats.org/presentationml/2006/main"
    drawing_ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
    rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    doc_rel_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    content_types = (
        b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        b'<Override PartName="/ppt/presentation.xml" '
        b'ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
        b"</Types>"
    )
    ids = "".join(
        f'<p:sldId id="{256 + index}" r:id="rId{index}"/>'
        for index in range(1, len(slides) + 1)
    )
    presentation = (
        f'<p:presentation xmlns:p="{presentation_ns}" xmlns:r="{doc_rel_ns}">'
        f"<p:sldIdLst>{ids}</p:sldIdLst></p:presentation>"
    ).encode()
    relations = []
    for index in range(1, len(slides) + 1):
        target = "../outside.xml" if unsafe_target else f"slides/slide{index}.xml"
        target_mode = ' TargetMode="External"' if external else ""
        relations.append(
            f'<Relationship Id="rId{index}" Type="{doc_rel_ns}/slide" '
            f'Target="{target}"{target_mode}/>'
        )
    relationships = (
        f'<Relationships xmlns="{rel_ns}">{"".join(relations)}</Relationships>'
    ).encode()
    output = BytesIO()
    with ZipFile(output, "w", ZIP_STORED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("ppt/presentation.xml", presentation)
        archive.writestr("ppt/_rels/presentation.xml.rels", relationships)
        for index, paragraphs in enumerate(slides, start=1):
            text = "".join(
                f"<a:p><a:r><a:t>{value}</a:t></a:r></a:p>" for value in paragraphs
            )
            slide = (
                f'<p:sld xmlns:p="{presentation_ns}" xmlns:a="{drawing_ns}">'
                f"<p:cSld><p:spTree>{text}</p:spTree></p:cSld></p:sld>"
            ).encode()
            archive.writestr(f"ppt/slides/slide{index}.xml", slide)
        for name, value in (extras or {}).items():
            archive.writestr(name, value)
    return output.getvalue()


def _attachment(payload: bytes) -> dict[str, str]:
    return {
        "file_name": "brief.pptx",
        "media_type": PPTX_MEDIA_TYPE,
        "content_base64": base64.b64encode(payload).decode("ascii"),
    }


def _unsafe_case(case: str) -> dict[str, str]:
    if case == "signature":
        return _attachment(b"not-pptx")
    if case == "extension":
        value = _attachment(_pptx_bytes(slides=(("x",),)))
        return {**value, "file_name": "brief.txt"}
    if case == "missing":
        output = BytesIO()
        with ZipFile(output, "w") as archive:
            archive.writestr("unrelated.xml", b"<root/>")
        return _attachment(output.getvalue())
    if case == "empty":
        return _attachment(_pptx_bytes(slides=((),)))
    if case == "external":
        return _attachment(_pptx_bytes(slides=(("x",),), external=True))
    if case == "embedded":
        return _attachment(
            _pptx_bytes(slides=(("x",),), extras={"ppt/embeddings/object1.bin": b"x"})
        )
    if case == "macro":
        return _attachment(
            _pptx_bytes(slides=(("x",),), extras={"ppt/vbaProject.bin": b"macro"})
        )
    return _attachment(_pptx_bytes(slides=(("x",),), unsafe_target=True))


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

    return SessionId("00000000-0000-0000-0000-000000000143")


def _created_at():
    from datetime import UTC, datetime

    return datetime(2026, 7, 17, 1, 0, tzinfo=UTC)
