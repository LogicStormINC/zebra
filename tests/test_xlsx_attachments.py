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
from zebra_agent_api.session_attachment_inputs import XLSX_MEDIA_TYPE, parse_attachment_inputs
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings


def test_xlsx_parser_extracts_typed_cells_with_safe_provenance() -> None:
    xlsx = _xlsx_bytes(
        cells=(
            '<c r="A1" t="s"><v>0</v></c>'
            '<c r="B2"><v>42.5</v></c>'
            '<c r="C3" t="b"><v>1</v></c>'
            '<c r="D4" t="inlineStr"><is><t>Inline</t></is></c>'
            '<c r="E5"><f>SUM(B2)</f><v>42.5</v></c>'
        ),
        shared_strings=("XLSX_ATTACHMENT_MARKER_142",),
    )

    parsed = parse_attachment_inputs([_attachment(xlsx)])

    assert parsed[0].payload == (
        b"[XLSX sheet: Summary]\nA1=XLSX_ATTACHMENT_MARKER_142\n"
        b"B2=42.5\nC3=TRUE\nD4=Inline\nE5=42.5"
    )
    assert parsed[0].original_media_type == XLSX_MEDIA_TYPE
    assert parsed[0].worksheet_count == 1
    assert parsed[0].cell_count == 5
    assert parsed[0].page_count is None
    assert parsed[0].paragraph_count is None


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("signature", "ZIP signature is invalid"),
        ("extension", "must end with .xlsx"),
        ("missing", "missing required package parts"),
        ("empty", "no extractable worksheet values"),
        ("external", "external relationships"),
        ("connection", "active or embedded content"),
        ("macro", "active or embedded content"),
        ("bad_shared", "invalid shared-string index"),
        ("bad_cell", "invalid cell coordinate"),
        ("formula_only", "no extractable worksheet values"),
    ],
)
def test_xlsx_parser_rejects_unsafe_or_unsupported_workbooks(case: str, reason: str) -> None:
    with pytest.raises(ValueError, match=reason):
        parse_attachment_inputs([_unsafe_case(case)])


def test_xlsx_limits_fail_before_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    from zebra_agent_api import session_spreadsheet_inputs as spreadsheet_inputs

    xlsx = _xlsx_bytes(cells='<c r="A1" t="inlineStr"><is><t>value</t></is></c>')
    monkeypatch.setattr(spreadsheet_inputs, "MAX_XLSX_CELLS", 0)
    with pytest.raises(ValueError, match="0-cell limit"):
        parse_attachment_inputs([_attachment(xlsx)])

    monkeypatch.setattr(spreadsheet_inputs, "MAX_XLSX_CELLS", 10_000)
    monkeypatch.setattr(spreadsheet_inputs, "MAX_XLSX_TEXT_BYTES", 4)
    with pytest.raises(ValueError, match="extracted text exceeds"):
        parse_attachment_inputs([_attachment(xlsx)])


def test_later_xlsx_message_recovers_from_extracted_bytes_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "sessions.sqlite"
    xlsx = _xlsx_bytes(
        cells='<c r="A1" t="inlineStr"><is><t>XLSX_RECOVERY_142</t></is></c>'
    )
    app = create_app(database_path, settings=_settings(database_path))
    created = app.create_session({"prompt": "Wait.", "workspace": str(tmp_path)})
    appended = app.append_session_message(
        created.body["session_id"],
        {"content": "Read the workbook.", "attachments": [_attachment(xlsx)]},
    )
    ref = appended.body["attachments"][0]
    assert ref["worksheet_count"] == 1
    assert ref["cell_count"] == 1
    stored = SQLiteArtifactPayloadStore(database_path).read_payload_bytes(
        _attachment_id(ref["attachment_id"])
    )
    assert stored == b"[XLSX sheet: Summary]\nA1=XLSX_RECOVERY_142"
    assert stored != xlsx

    def forbidden_reparse(payload: bytes) -> tuple[bytes, int, int]:
        raise AssertionError(f"unexpected XLSX reparse of {len(payload)} bytes")

    monkeypatch.setattr(attachment_inputs, "_extract_xlsx_text", forbidden_reparse)
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
                    content="Recovered workbook.",
                    created_at=_created_at(),
                )
            )

    monkeypatch.setattr(
        "zebra_agent_worker.execution.build_model_gateway",
        lambda settings: RecordingGateway(),
    )
    resumed = app.resume_session(created.body["session_id"], {"worker_id": "xlsx-worker"})
    assert resumed.status_code == 200
    assert "XLSX_RECOVERY_142" in requests[0][0].content


def test_invalid_xlsx_fails_before_session_mutation(tmp_path: Path) -> None:
    database_path = tmp_path / "sessions.sqlite"
    app = create_app(database_path, settings=_settings(database_path))
    response = app.create_session(
        {
            "prompt": "Read workbook.",
            "workspace": str(tmp_path),
            "attachments": [_attachment(b"PK\x03\x04broken")],
        }
    )
    assert response.status_code == 400
    assert SQLiteEventStore(database_path).list_for_session(_session_id()) == []


def _xlsx_bytes(
    *,
    cells: str,
    shared_strings: tuple[str, ...] = (),
    extras: dict[str, bytes] | None = None,
    external: bool = False,
) -> bytes:
    sheet_ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    doc_rel_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    content_types = (
        b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        b'<Override PartName="/xl/workbook.xml" '
        b'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        b"</Types>"
    )
    workbook = (
        f'<workbook xmlns="{sheet_ns}" xmlns:r="{doc_rel_ns}"><sheets>'
        '<sheet name="Summary" sheetId="1" r:id="rId1"/></sheets></workbook>'
    ).encode()
    target_mode = ' TargetMode="External"' if external else ""
    target = "https://example.test/sheet.xml" if external else "worksheets/sheet1.xml"
    relationships = (
        f'<Relationships xmlns="{rel_ns}"><Relationship Id="rId1" '
        f'Type="{doc_rel_ns}/worksheet" Target="{target}"{target_mode}/></Relationships>'
    ).encode()
    worksheet = (
        f'<worksheet xmlns="{sheet_ns}"><sheetData><row>{cells}</row>'
        "</sheetData></worksheet>"
    ).encode()
    output = BytesIO()
    with ZipFile(output, "w", ZIP_STORED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)
        if shared_strings:
            items = "".join(f"<si><t>{value}</t></si>" for value in shared_strings)
            archive.writestr(
                "xl/sharedStrings.xml", f'<sst xmlns="{sheet_ns}">{items}</sst>'.encode()
            )
        for name, value in (extras or {}).items():
            archive.writestr(name, value)
    return output.getvalue()


def _attachment(payload: bytes) -> dict[str, str]:
    return {
        "file_name": "brief.xlsx",
        "media_type": XLSX_MEDIA_TYPE,
        "content_base64": base64.b64encode(payload).decode("ascii"),
    }


def _unsafe_case(case: str) -> dict[str, str]:
    if case == "signature":
        return _attachment(b"not-xlsx")
    if case == "extension":
        value = _attachment(_xlsx_bytes(cells='<c r="A1"><v>1</v></c>'))
        return {**value, "file_name": "brief.txt"}
    if case == "missing":
        output = BytesIO()
        with ZipFile(output, "w") as archive:
            archive.writestr("unrelated.xml", b"<root/>")
        return _attachment(output.getvalue())
    if case == "empty":
        return _attachment(_xlsx_bytes(cells=""))
    if case == "external":
        return _attachment(_xlsx_bytes(cells='<c r="A1"><v>1</v></c>', external=True))
    if case == "connection":
        return _attachment(
            _xlsx_bytes(
                cells='<c r="A1"><v>1</v></c>',
                extras={"xl/connections.xml": b"<x/>"},
            )
        )
    if case == "macro":
        return _attachment(
            _xlsx_bytes(
                cells='<c r="A1"><v>1</v></c>',
                extras={"xl/vbaProject.bin": b"macro"},
            )
        )
    if case == "bad_shared":
        return _attachment(_xlsx_bytes(cells='<c r="A1" t="s"><v>4</v></c>', shared_strings=("x",)))
    if case == "bad_cell":
        return _attachment(_xlsx_bytes(cells='<c r="BAD"><v>1</v></c>'))
    return _attachment(_xlsx_bytes(cells='<c r="A1"><f>1+1</f></c>'))


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

    return SessionId("00000000-0000-0000-0000-000000000142")


def _created_at():
    from datetime import UTC, datetime

    return datetime(2026, 7, 17, 0, 30, tzinfo=UTC)
