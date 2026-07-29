from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from urllib.parse import unquote, urlparse

from agent_core.domain.context_capsule import (
    ContextCapsule,
    ContextCapsuleValidationContext,
    ContextSourceEventRange,
    PendingToolState,
)
from agent_core.domain.events import EventType, SessionEvent
from agent_core.domain.messages import MessageRole, SessionMessage

from agent_context.projection import build_protected_instruction_ledger
from agent_context.projection_models import ProtectedInstructionKind

_TRAILING_PUNCT = "\"'),;>.]}"
_TERMINAL_ACCEPTANCE_CRITERION = (
    "Produce a final response that directly satisfies the original user objective "
    "using available evidence."
)


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
    assistant_decisions = tuple(
        message.content[:1_000]
        for message in messages
        if message.role is MessageRole.ASSISTANT and not message.tool_calls
    )[-8:]
    protected_user_constraints = tuple(
        entry.content
        for entry in build_protected_instruction_ledger(messages).entries
        if entry.kind is ProtectedInstructionKind.USER_CONSTRAINT
    )
    decisions = (*protected_user_constraints, *assistant_decisions)[-8:]
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
        acceptance_criteria=(_TERMINAL_ACCEPTANCE_CRITERION,),
        constraints=(user_goal,),
        protected_user_constraints=protected_user_constraints,
        decisions=decisions,
        decisions_and_rationale=assistant_decisions,
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


def durable_context_capsule(
    capsule: ContextCapsule,
    events: list[SessionEvent],
) -> ContextCapsule:
    if not events:
        raise ValueError("durable context capsule requires source events")
    approvals = tuple(
        _approval_state(event)
        for event in events
        if event.event_type
        in {
            EventType.POLICY_DECISION_MADE,
            EventType.APPROVAL_REQUESTED,
            EventType.APPROVAL_GRANTED,
            EventType.APPROVAL_REJECTED,
        }
    )
    protected = tuple(dict.fromkeys((*capsule.constraints, *capsule.protected_user_constraints)))
    return capsule.model_copy(
        update={
            "source_event_range": ContextSourceEventRange(
                start_sequence=events[0].sequence,
                end_sequence=events[-1].sequence,
            ),
            "protected_user_constraints": protected,
            "approvals_and_policy_state": approvals,
        }
    )


def durable_context_validation_context(
    capsule: ContextCapsule,
) -> ContextCapsuleValidationContext:
    if capsule.source_event_range is None:
        raise ValueError("durable context capsule source range is required")
    return ContextCapsuleValidationContext(
        expected_source_hash=capsule.source_hash,
        expected_source_event_range=capsule.source_event_range,
        unresolved_tool_call_ids=frozenset(tool.call_id for tool in capsule.pending_tools),
        protected_user_constraints=frozenset(capsule.protected_user_constraints),
        approval_and_policy_state=frozenset(capsule.approvals_and_policy_state),
        readable_artifact_refs=frozenset(
            ref
            for ref in capsule.referenced_artifact_refs
            if not ref.startswith("file://") or _is_readable_file_uri(ref)
        ),
    )


def _approval_state(event: SessionEvent) -> str:
    detail = event.payload.get("decision", event.payload.get("reason", "recorded"))
    return f"{event.event_type.value}:{detail}"


def _is_readable_file_uri(uri: str) -> bool:
    parsed = urlparse(uri)
    return Path(unquote(parsed.path)).is_file()
