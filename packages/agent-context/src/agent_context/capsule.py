from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256

from agent_core.domain.context_capsule import ContextCapsule, PendingToolState
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.ports.context_compiler import RuntimeEvidenceInput
from agent_core.ports.execution_inputs import ExecutionInputEvidence

_TRAILING_PUNCT = "\"'),;>.]}"


def _normalize_artifact_ref(value: str) -> str:
    """Strip trailing punctuation from structured artifact metadata."""
    return value.strip().rstrip(_TRAILING_PUNCT)


def build_context_capsule(
    messages: tuple[SessionMessage, ...],
    *,
    user_goal: str,
    created_at: datetime,
) -> ContextCapsule:
    encoded = json.dumps(
        [message.model_dump(mode="json") for message in messages],
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")
    source_hash = sha256(encoded).hexdigest()
    completed_call_ids = {
        message.tool_call_id
        for message in messages
        if message.role is MessageRole.TOOL and message.tool_call_id is not None
    }
    pending = tuple(
        PendingToolState(
            call_id=call.provider_call_id or str(call.tool_call_id),
            name=call.name,
            arguments=dict(call.arguments),
        )
        for message in messages
        for call in message.tool_calls
        if (call.provider_call_id or str(call.tool_call_id)) not in completed_call_ids
    )
    touched_files = sorted(
        {
            value
            for message in messages
            for call in message.tool_calls
            for key, value in call.arguments.items()
            if key in {"path", "file", "cwd"} and isinstance(value, str) and value.strip()
        }
    )
    tool_names = {
        call.provider_call_id or str(call.tool_call_id): call.name
        for message in messages
        for call in message.tool_calls
    }
    tool_outputs = tuple(
        message.content for message in messages if message.role is MessageRole.TOOL
    )
    tests = tuple(
        message.content[:1_000]
        for message in messages
        if message.role is MessageRole.TOOL
        and tool_names.get(message.tool_call_id or "") == "tests.run"
    )[-5:]
    errors = tuple(
        output[:1_000]
        for output in tool_outputs
        if any(marker in output.lower() for marker in ("error", "failed", "traceback"))
    )[-5:]
    decisions = tuple(
        message.content[:1_000]
        for message in messages
        if message.role is MessageRole.ASSISTANT and not message.tool_calls
    )[-8:]
    plan = tuple(
        message.content[:1_000]
        for message in messages
        if message.role in {MessageRole.USER, MessageRole.ASSISTANT}
    )[-8:]
    # CTX-ART-01: artifact strong references come ONLY from structured tool
    # metadata (ToolOutputEnvelope / WebResultEnvelope / SearchHit), never from
    # free-text regex scanning of tool output bodies. A URI appearing inside a
    # file read, command stdout, or error traceback must NOT be promoted to a
    # capsule artifact ref.
    artifact_refs = tuple(
        sorted(
            {
                uri
                for message in messages
                if message.role is MessageRole.TOOL
                for uri in _message_artifact_refs(message)
            }
        )
    )
    immediate_next = plan[-1] if plan else user_goal
    return ContextCapsule(
        capsule_id=f"ctxcap-{source_hash[:24]}",
        objective=user_goal,
        constraints=(user_goal,),
        decisions=decisions,
        plan=plan,
        touched_files=tuple(touched_files),
        tests=tests,
        errors=errors,
        pending_tools=pending,
        artifact_refs=artifact_refs,
        immediate_next=immediate_next,
        source_hash=source_hash,
        confidence=0.9 if messages else 0.5,
        created_at=created_at,
    )


def _message_artifact_refs(message: SessionMessage) -> tuple[str, ...]:
    """Collect artifact refs from structured metadata only.

    CTX-ART-01: free-text URI scanning is intentionally removed. Only the
    ``artifact_uri`` metadata field — set by ToolOutputProjector, web envelopes,
    and search pipeline — is a trustworthy provenance source.
    """
    metadata_uri = message.metadata.get("artifact_uri")
    if isinstance(metadata_uri, str):
        normalized = _normalize_artifact_ref(metadata_uri)
        if normalized:
            return (normalized,)
    return ()


def execution_evidence_context(evidence: ExecutionInputEvidence) -> RuntimeEvidenceInput:
    """Expose admitted closed receipts as data, never as active lifecycle authority."""
    from agent_context.projection_models import ToolResultTombstone

    capsule = evidence.capsule
    tools = tuple(
        ToolResultTombstone(
            tool_name=tool.tool_name,
            call_id=tool.call_id,
            status=tool.status,
            artifact_uri=tool.artifact_uri,
            checksum=tool.output_sha256,
            original_characters=tool.output_characters,
        ).render()
        + "\nArguments: "
        + json.dumps(tool.arguments, sort_keys=True, ensure_ascii=False)
        for tool in evidence.tools
    )
    return RuntimeEvidenceInput(
        kind="execution_receipt_evidence",
        summary=capsule.objective,
        details=(*capsule.protected_user_constraints, *capsule.decisions, *tools),
        metadata={
            "capsule_id": capsule.capsule_id,
            "profile": capsule.profile,
            "source_hash": capsule.source_hash,
            "source_event_range": (
                capsule.source_event_range.model_dump() if capsule.source_event_range else None
            ),
            "closing_event_id": str(evidence.closing_event_id),
            "run_event_id": str(evidence.run_event_id),
            "archived_model_requests": evidence.model_request_count,
            "archived_model_responses": evidence.model_response_count,
            "known_omissions": list(capsule.known_omissions),
            "instruction_boundary": "data",
            "current_run_budget_authority": False,
        },
    )
