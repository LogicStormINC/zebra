from __future__ import annotations

import json
from collections.abc import Callable
from hashlib import sha256

from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.tools import ToolCall

from agent_context.projection_models import (
    LEDGER_MARKER,
    PROJECTED_CALL_MARKER,
    ActiveContextProjection,
    FoldedToolExchange,
    ProtectedInstruction,
    ProtectedInstructionKind,
    ProtectedInstructionLedger,
    ToolResultTombstone,
)

_UNRESOLVED_MARKERS = (
    "approval pending",
    "approval-pending",
    "clarification pending",
    "clarification-pending",
    '"status":"failed"',
    '"status": "failed"',
    '"status":"error"',
    '"status": "error"',
    "traceback (most recent call last)",
)


def build_protected_instruction_ledger(
    messages: tuple[SessionMessage, ...],
) -> ProtectedInstructionLedger:
    entries: list[ProtectedInstruction] = []
    seen: set[str] = set()
    first_user = True
    for message in messages:
        if message.role not in {MessageRole.SYSTEM, MessageRole.USER}:
            continue
        if message.content.startswith(LEDGER_MARKER):
            for entry in _parse_ledger(message.content):
                if entry.checksum not in seen:
                    seen.add(entry.checksum)
                    entries.append(entry)
            continue
        if message.content.startswith("[Compacted completed conversation;"):
            continue
        digest = _digest(message.content)
        if digest in seen:
            continue
        seen.add(digest)
        if message.role is MessageRole.SYSTEM:
            kind = ProtectedInstructionKind.SYSTEM_RULE
        elif first_user:
            kind = ProtectedInstructionKind.USER_OBJECTIVE
            first_user = False
        else:
            kind = ProtectedInstructionKind.USER_CONSTRAINT
        entries.append(
            ProtectedInstruction(
                kind=kind,
                content=message.content,
                source_message_id=str(message.message_id),
                checksum=digest,
            )
        )
    return ProtectedInstructionLedger(entries=tuple(entries))


def build_active_context_projection(
    messages: tuple[SessionMessage, ...],
    *,
    recent_exact_exchanges: int = 3,
) -> ActiveContextProjection:
    if not 2 <= recent_exact_exchanges <= 4:
        raise ValueError("recent_exact_exchanges must be between 2 and 4")
    ledger = build_protected_instruction_ledger(messages)
    exchanges = _completed_tool_exchanges(messages)
    exact = set(range(max(0, len(exchanges) - recent_exact_exchanges), len(exchanges)))
    latest_versions: dict[str, tuple[int, str]] = {}
    for exchange_index, (_, assistant, results) in enumerate(exchanges):
        for call, result in _paired_calls(assistant, results):
            locator = _content_locator(call.name, call.arguments)
            if locator:
                latest_versions[locator] = (exchange_index, _digest(result.content))

    replacements: dict[int, tuple[SessionMessage, ...]] = {}
    consumed: set[int] = set()
    folded: list[FoldedToolExchange] = []
    for exchange_index, (start, assistant, results) in enumerate(exchanges):
        duplicate = any(
            locator and latest_versions.get(locator) != (exchange_index, _digest(result.content))
            for call, result in _paired_calls(assistant, results)
            if (locator := _content_locator(call.name, call.arguments))
        )
        if exchange_index in exact and not duplicate:
            continue
        projected, folded_exchange = _fold_exchange(assistant, results)
        replacements[start] = projected
        folded.append(folded_exchange)
        consumed.update(range(start, start + 1 + len(results)))

    projected_messages: list[SessionMessage] = []
    for index, message in enumerate(messages):
        replacement = replacements.get(index)
        if replacement is not None:
            projected_messages.extend(replacement)
        elif index not in consumed:
            projected_messages.append(message)
    return ActiveContextProjection(
        messages=tuple(projected_messages),
        protected_ledger=ledger,
        folded_exchanges=tuple(folded),
        content_versions=tuple(
            sorted((locator, digest) for locator, (_, digest) in latest_versions.items())
        ),
    )


def rehydrate_projection(
    projection: ActiveContextProjection,
    *,
    call_id: str,
    max_tokens: int,
    load_artifact: Callable[[str], str],
    policy_allows: Callable[[ToolResultTombstone], bool],
    allowed_provenance: frozenset[str] = frozenset({"tool_trace", "artifact"}),
) -> ActiveContextProjection:
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")
    exchange = next(
        (item for item in projection.folded_exchanges if call_id in item.call_ids), None
    )
    if exchange is None:
        raise KeyError(f"no folded exchange for call_id={call_id}")
    restored_results: list[SessionMessage] = []
    for result, tombstone in zip(exchange.results, exchange.tombstones, strict=True):
        if tombstone.provenance_source not in allowed_provenance:
            raise PermissionError("tombstone provenance is not allowed")
        if not policy_allows(tombstone):
            raise PermissionError("rehydration denied by policy")
        content = load_artifact(tombstone.artifact_uri)
        if _digest(content) != tombstone.checksum:
            raise ValueError("rehydrated content checksum mismatch")
        restored_results.append(result.model_copy(update={"content": content}))
    messages = _replace_projected_exchange(
        projection.messages,
        exchange,
        (exchange.assistant, *restored_results),
    )
    # Local import avoids making projection depend on conversation's summary logic.
    from agent_context.conversation import estimate_message_tokens

    if estimate_message_tokens(messages) > max_tokens:
        raise ValueError("rehydrated projection exceeds token budget")
    return ActiveContextProjection(
        messages=messages,
        protected_ledger=projection.protected_ledger,
        folded_exchanges=tuple(
            item for item in projection.folded_exchanges if item is not exchange
        ),
        content_versions=projection.content_versions,
    )


def _completed_tool_exchanges(
    messages: tuple[SessionMessage, ...],
) -> list[tuple[int, SessionMessage, tuple[SessionMessage, ...]]]:
    exchanges = []
    for index, message in enumerate(messages):
        if message.role is not MessageRole.ASSISTANT or not message.tool_calls:
            continue
        results: list[SessionMessage] = []
        cursor = index + 1
        while cursor < len(messages) and messages[cursor].role is MessageRole.TOOL:
            results.append(messages[cursor])
            cursor += 1
        expected = {call.provider_call_id or str(call.tool_call_id) for call in message.tool_calls}
        actual = {result.tool_call_id for result in results}
        if expected != actual or any(_must_remain_exact(result) for result in results):
            continue
        exchanges.append((index, message, tuple(results)))
    return exchanges


def _paired_calls(
    assistant: SessionMessage,
    results: tuple[SessionMessage, ...],
) -> tuple[tuple[ToolCall, SessionMessage], ...]:
    calls = {call.provider_call_id or str(call.tool_call_id): call for call in assistant.tool_calls}
    return tuple((calls[result.tool_call_id or ""], result) for result in results)


def _fold_exchange(
    assistant: SessionMessage,
    results: tuple[SessionMessage, ...],
) -> tuple[tuple[SessionMessage, ...], FoldedToolExchange]:
    pairs = _paired_calls(assistant, results)
    tombstones = tuple(
        ToolResultTombstone(
            tool_name=call.name,
            call_id=result.tool_call_id or "",
            status="succeeded",
            artifact_uri=_result_artifact_uri(result)
            or f"event-sha256://{_digest(result.content)}",
            checksum=_result_checksum(result),
            original_characters=len(result.content),
        )
        for call, result in pairs
    )
    projected_assistant = assistant.model_copy(
        update={"content": f"{PROJECTED_CALL_MARKER} {', '.join(call.name for call, _ in pairs)}"}
    )
    projected_results = tuple(
        result.model_copy(update={"content": tombstone.render()})
        for (_, result), tombstone in zip(pairs, tombstones, strict=True)
    )
    return (projected_assistant, *projected_results), FoldedToolExchange(
        assistant=assistant,
        results=results,
        tombstones=tombstones,
    )


def _replace_projected_exchange(
    messages: tuple[SessionMessage, ...],
    exchange: FoldedToolExchange,
    replacement: tuple[SessionMessage, ...],
) -> tuple[SessionMessage, ...]:
    call_ids = exchange.call_ids
    for index, message in enumerate(messages):
        if message.role is not MessageRole.ASSISTANT:
            continue
        ids = {call.provider_call_id or str(call.tool_call_id) for call in message.tool_calls}
        if ids == call_ids and message.content.startswith(PROJECTED_CALL_MARKER):
            return messages[:index] + replacement + messages[index + 1 + len(call_ids) :]
    raise ValueError("projected tool-call/result pair is missing")


def _must_remain_exact(message: SessionMessage) -> bool:
    if ToolResultTombstone.parse(message.content) is not None:
        return True
    normalized = message.content.casefold()
    # ponytail: SessionMessage lacks structured result status; keep suspicious results
    # exact until core exposes ToolCallStatus on conversation messages.
    return any(marker in normalized for marker in _UNRESOLVED_MARKERS)


def _content_locator(tool_name: str, arguments: dict[str, object]) -> str | None:
    if not (tool_name.endswith("read") or tool_name in {"files.read", "workspace.search"}):
        return None
    value = arguments.get("path") or arguments.get("query")
    return str(value) if value is not None else None


def _result_artifact_uri(message: SessionMessage) -> str | None:
    # CTX-ART-01: artifact URIs come only from structured metadata, not from
    # free-text scanning of tool output bodies.
    uri = message.metadata.get("artifact_uri")
    if isinstance(uri, str) and uri.strip():
        return uri.strip()
    return None


def _result_checksum(message: SessionMessage) -> str:
    checksum = message.metadata.get("output_sha256")
    if isinstance(checksum, str) and checksum.strip():
        return checksum.strip()
    return _digest(message.content)


def _digest(content: str) -> str:
    return sha256(content.encode("utf-8")).hexdigest()


def _parse_ledger(content: str) -> tuple[ProtectedInstruction, ...]:
    try:
        payload = json.loads(content.split("\n", 1)[1])
        entries = tuple(
            ProtectedInstruction(
                kind=ProtectedInstructionKind(item["kind"]),
                content=item["content"],
                source_message_id=item["source_message_id"],
                checksum=item["checksum"],
            )
            for item in payload
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, IndexError):
        return ()
    return tuple(entry for entry in entries if _digest(entry.content) == entry.checksum)
