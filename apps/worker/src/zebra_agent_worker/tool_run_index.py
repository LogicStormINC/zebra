from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.tool_runs import ToolRunRecord
from agent_core.ports.tool_run_store import ToolRunStorePort


class ToolRunIndexer:
    def __init__(self, tool_run_store: ToolRunStorePort) -> None:
        self._tool_run_store = tool_run_store

    def index_event(self, event: SessionEvent) -> ToolRunRecord | None:
        if event.event_type not in {
            EventType.TOOL_EXECUTION_COMPLETED,
            EventType.TOOL_EXECUTION_FAILED,
        }:
            return None
        record = ToolRunRecord(
            session_id=event.session_id,
            sequence=event.sequence,
            tool_name=str(event.payload["tool_name"]),
            status=str(event.payload["status"]),
            idempotency_key=event.idempotency_key,
            output=str(event.payload.get("output", "")),
            artifact_uri=_artifact_uri_from_payload(event.payload),
            created_at=event.created_at,
        )
        self._tool_run_store.upsert(record)
        return record


def _artifact_uri_from_payload(payload: dict[str, object]) -> str | None:
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        return None
    artifact_uri = metadata.get("artifact_uri")
    if not isinstance(artifact_uri, str):
        return None
    stripped = artifact_uri.strip()
    return stripped or None
