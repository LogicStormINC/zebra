"""Local tool-output artifact projection composition."""

from datetime import UTC, datetime
from uuid import UUID

from agent_core.contracts.public_output import project_tool_result_evidence
from agent_core.domain.artifact_payloads import ArtifactPayloadWrite
from agent_core.domain.identifiers import SessionId
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.ports.artifact_payload_store import ArtifactPayloadStorePort
from agent_tools import ToolOutputProjector


def build_output_projector(
    store: ArtifactPayloadStorePort | None,
    *,
    current_session_id: str | None,
) -> ToolOutputProjector | None:
    if store is None:
        return None
    if current_session_id is None:
        raise ValueError("artifact output projection requires current_session_id")
    try:
        session_id = SessionId(UUID(current_session_id))
    except ValueError as exc:
        raise ValueError("current_session_id must be a UUID") from exc

    def persist(content: str, file_name: str) -> str:
        stored = store.store_payload(
            ArtifactPayloadWrite(
                session_id=session_id,
                kind="tool_output",
                mime_type="text/plain",
                payload=content.encode("utf-8"),
                file_name=file_name,
                created_at=datetime.now(UTC),
            )
        )
        return stored.uri

    return ToolOutputProjector(persist)


def project_tool_output(
    projector: ToolOutputProjector | None, tool_call: ToolCall, result: ToolResult,
) -> ToolResult:
    metadata = dict(result.metadata)
    candidates = metadata.pop("_search_candidate_output", None)
    if "_search_candidate_output" in result.metadata:
        result = result.model_copy(update={"metadata": metadata})
    # ponytail: internal, validated same-response text only; never persist arbitrary headers.
    if not (tool_call.name == "web.search" and result.status is ToolCallStatus.EXECUTED
            and isinstance(candidates, str) and len(candidates) <= 21_000
            and candidates.startswith(result.output)):
        candidates = None
    if projector is None:
        if candidates:
            result = result.model_copy(update={"metadata": {
                k: v for k, v in result.metadata.items()
                if k not in {"total_count", "has_more", "candidate_set_truncated"}
            }})
        return result
    existing_uri = result.metadata.get("artifact_uri")
    if isinstance(existing_uri, str) and existing_uri.strip() and candidates is None:
        return result
    stderr = result.metadata.get("stderr")
    if tool_call.name in {"command.run", "tests.run"} and isinstance(stderr, str):
        projected = projector.project(
            stdout=result.output,
            stderr=stderr,
            artifact_name=f"{tool_call.name.replace('.', '-')}.txt",
            provenance={
                "tool_name": tool_call.name,
                "tool_call_id": str(tool_call.tool_call_id),
            },
        )
        metadata = {**result.metadata, "stderr": "", **projected.metadata}
    else:
        projected = projector.project_text(
            candidates or result.output,
            small_output=result.output if candidates else None,
            artifact_name=f"{tool_call.name.replace('.', '-')}.txt",
            provenance={
                "tool_name": tool_call.name,
                "tool_call_id": str(tool_call.tool_call_id),
            },
        )
        metadata = {**result.metadata, **projected.metadata}
    return project_tool_result_evidence(
        result, output=projected.model_output, metadata=metadata
    )
