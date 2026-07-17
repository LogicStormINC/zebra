from __future__ import annotations

import json
import re
from datetime import datetime
from hashlib import sha256

from agent_core.domain.context_capsule import ContextCapsule, PendingToolState
from agent_core.domain.messages import MessageRole, SessionMessage

_ARTIFACT_URI = re.compile(r"(?:artifact|file)://[^\s\])]+")


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
    artifact_refs = tuple(
        sorted(
            {
                uri
                for output in tool_outputs
                for uri in _ARTIFACT_URI.findall(output)
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
