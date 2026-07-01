
from agent_core.domain.artifact_payloads import ArtifactPayloadWrite
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.tool_runs import ToolRunRecord
from agent_core.ports.tool_run_store import ToolRunStorePort
from agent_storage import SQLiteArtifactPayloadStore


class ToolRunIndexer:
    def __init__(
        self,
        tool_run_store: ToolRunStorePort,
        artifact_payload_store: SQLiteArtifactPayloadStore | None = None,
    ) -> None:
        self._tool_run_store = tool_run_store
        self._artifact_payload_store = artifact_payload_store

    def index_event(self, event: SessionEvent) -> ToolRunRecord | None:
        if event.event_type not in {
            EventType.TOOL_EXECUTION_COMPLETED,
            EventType.TOOL_EXECUTION_FAILED,
        }:
            return None
        artifact_uri = _artifact_uri_from_payload(event.payload)
        if artifact_uri is None:
            artifact_uri = self._capture_output_payload_uri(event)
        record = ToolRunRecord(
            session_id=event.session_id,
            sequence=event.sequence,
            tool_name=str(event.payload["tool_name"]),
            status=str(event.payload["status"]),
            idempotency_key=event.idempotency_key,
            output=str(event.payload.get("output", "")),
            artifact_uri=artifact_uri,
            created_at=event.created_at,
        )
        self._tool_run_store.upsert(record)
        return record

    def _capture_output_payload_uri(self, event: SessionEvent) -> str | None:
        if self._artifact_payload_store is None:
            return None
        output = str(event.payload.get("output", ""))
        if not output.strip():
            return None
        stored = self._artifact_payload_store.store_payload(
            ArtifactPayloadWrite(
                session_id=event.session_id,
                kind="tool_output",
                mime_type="text/plain",
                payload=output.encode("utf-8"),
                file_name=_payload_file_name(str(event.payload["tool_name"]), event.sequence),
                created_at=event.created_at,
            )
        )
        return stored.uri


def _artifact_uri_from_payload(payload: dict[str, object]) -> str | None:
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        return None
    artifact_uri = metadata.get("artifact_uri")
    if not isinstance(artifact_uri, str):
        return None
    stripped = artifact_uri.strip()
    return stripped or None


def _payload_file_name(tool_name: str, sequence: int) -> str:
    safe_name = "".join(
        character if character.isalnum() else "-"
        for character in tool_name.strip().lower()
    ).strip("-")
    normalized = safe_name or "tool-output"
    return f"{normalized}-{sequence}.txt"
