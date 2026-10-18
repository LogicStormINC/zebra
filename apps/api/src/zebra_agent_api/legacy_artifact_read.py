"""Read-only compatibility for published files predating Task binding snapshots."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from agent_core.domain.events import EventType
from agent_core.domain.host_authority import HostContextEnvelope
from agent_core.domain.identifiers import SessionId
from agent_core.domain.task_bindings import require_legacy_artifact_host_context
from agent_core.ports.event_store import BoundedSessionEventReadPort


def artifact_read_target(method: str, path: str) -> tuple[str, str | None] | None:
    parts = path.strip("/").split("/")
    if (
        method not in {"GET", "HEAD"}
        or not 3 <= len(parts) <= 5
        or parts[0] not in {"tasks", "sessions"}
        or parts[2] != "artifacts"
        or len(parts) == 5
        and parts[4] not in {"content", "download", "preview"}
    ):
        return None
    try:
        if str(UUID(parts[1])) != parts[1]:
            return None
        artifact = parts[3] if len(parts) >= 4 else None
        if artifact is not None and (
            not artifact or len(artifact) > 256 or any(ord(c) < 33 for c in artifact)
        ):
            return None
    except ValueError:
        return None
    return parts[1], artifact


def legacy_artifact_read_allowed(
    api: Any, context: HostContextEnvelope, task_id: str, artifact_id: str
) -> bool:
    reader = api.stores.events
    if not isinstance(reader, BoundedSessionEventReadPort):
        return False
    session_id = SessionId(UUID(task_id))
    # Canonical payload binding, publication and policy are still checked on the
    # ordinary detail/content path. Do not admit an internal or failed tool here.
    artifact = api.stores.artifacts.get_for_session(session_id, artifact_id)
    if (
        artifact is None
        or not _canonical_payload_uri(artifact.uri)
        or artifact.source != "tool_run"
        or artifact.metadata.get("tool_name") != "files.publish"
        or artifact.metadata.get("status") != "executed"
    ):
        return False
    page = reader.read_session_event_page(session_id, -1, limit=16, max_bytes=131072)
    prepared = [event for event in page.events if event.event_type is EventType.TASK_PREPARED]
    if len(prepared) != 1:
        return False
    try:
        source = HostContextEnvelope.model_validate(prepared[0].payload.get("host_context"))
        require_legacy_artifact_host_context(source, context, now=datetime.now(UTC))
    except ValueError:
        return False
    return True


def _canonical_payload_uri(uri: str | None) -> bool:
    if uri is None or not uri.startswith("artifact://"):
        return False
    value = uri.removeprefix("artifact://")
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False
