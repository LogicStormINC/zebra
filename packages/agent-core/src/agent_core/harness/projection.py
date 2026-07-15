from dataclasses import dataclass, field

from agent_core.domain.events import EventType, SessionEvent
from agent_core.harness.models import (
    HarnessAttemptTrace,
    HarnessLoopResult,
    HarnessRunTrace,
    HarnessToolTrace,
)


class HarnessTraceProjector:
    def project(self, result: HarnessLoopResult) -> HarnessRunTrace:
        projected_attempts = self.project_events(result.events)
        return HarnessRunTrace(
            final_outcome=result.run_result.final_outcome,
            stop_reason=result.run_result.stop_reason,
            attempts=projected_attempts,
        )

    def project_events(
        self, events: tuple[SessionEvent, ...]
    ) -> tuple[HarnessAttemptTrace, ...]:
        attempts: dict[int, _AttemptBuilder] = {}

        for event in events:
            attempt_number = _attempt_number(event)
            if attempt_number is None:
                continue
            builder = attempts.setdefault(
                attempt_number,
                _AttemptBuilder(attempt_number=attempt_number),
            )
            builder.apply(event)

        return tuple(
            builder.build()
            for _, builder in sorted(attempts.items(), key=lambda item: item[0])
        )


@dataclass
class _PendingTool:
    key: str
    tool_name: str
    arguments: dict[str, object]
    policy_context: dict[str, object] = field(default_factory=dict)


class _AttemptBuilder:
    def __init__(self, *, attempt_number: int) -> None:
        self._attempt_number = attempt_number
        self._assistant_message: str | None = None
        self._pending: list[_PendingTool] = []
        self._pending_by_id: dict[str, _PendingTool] = {}
        self._legacy_sequence = 0
        self._tools: list[HarnessToolTrace] = []

    def apply(self, event: SessionEvent) -> None:
        if event.event_type is EventType.MODEL_RESPONSE_RECEIVED:
            assistant_message = event.payload.get("assistant_message")
            if isinstance(assistant_message, str):
                self._assistant_message = assistant_message
            return

        if event.event_type is EventType.TOOL_CALL_PROPOSED:
            tool_name = event.payload.get("tool_name")
            arguments = event.payload.get("arguments")
            if not isinstance(tool_name, str):
                return
            tool_call_id = _tool_call_id(event)
            key = tool_call_id or f"legacy:{self._legacy_sequence}"
            self._legacy_sequence += 1
            pending = _PendingTool(
                key=key,
                tool_name=tool_name,
                arguments=dict(arguments) if isinstance(arguments, dict) else {},
            )
            self._pending.append(pending)
            if tool_call_id is not None:
                self._pending_by_id[tool_call_id] = pending
            return

        if event.event_type is EventType.POLICY_DECISION_MADE:
            policy_pending = self._match_pending(event, without_policy=True)
            if policy_pending is not None:
                policy_pending.policy_context = _policy_context_from_payload(event.payload)
            return

        if event.event_type in {
            EventType.TOOL_EXECUTION_COMPLETED,
            EventType.TOOL_EXECUTION_FAILED,
        }:
            tool_name = event.payload.get("tool_name")
            status = event.payload.get("status")
            output = event.payload.get("output")
            metadata = event.payload.get("metadata")
            if not isinstance(tool_name, str) or not isinstance(status, str):
                return
            terminal_pending = self._match_pending(event)
            policy_context = (
                terminal_pending.policy_context if terminal_pending is not None else {}
            )
            self._tools.append(
                HarnessToolTrace(
                    tool_name=tool_name,
                    status=status,
                    arguments=(
                        dict(terminal_pending.arguments)
                        if terminal_pending is not None
                        else {}
                    ),
                    output=output if isinstance(output, str) else "",
                    metadata=dict(metadata) if isinstance(metadata, dict) else {},
                    policy_decision=_string_or_none(policy_context.get("decision")),
                    policy_route=_string_or_none(policy_context.get("route")),
                    policy_target=_string_or_none(policy_context.get("target")),
                    policy_network_profile=_string_or_none(
                        policy_context.get("network_profile")
                    ),
                    policy_scope=_scope_from_context(policy_context),
                )
            )
            if terminal_pending is not None:
                self._pending.remove(terminal_pending)
                self._pending_by_id.pop(terminal_pending.key, None)

    def _match_pending(
        self, event: SessionEvent, *, without_policy: bool = False
    ) -> _PendingTool | None:
        tool_call_id = _tool_call_id(event)
        if tool_call_id is not None:
            return self._pending_by_id.get(tool_call_id)
        tool_name = event.payload.get("tool_name")
        for pending in self._pending:
            if pending.tool_name != tool_name:
                continue
            if without_policy and pending.policy_context:
                continue
            return pending
        return None

    def build(self) -> HarnessAttemptTrace:
        return HarnessAttemptTrace(
            attempt_number=self._attempt_number,
            assistant_message=self._assistant_message,
            tools=tuple(self._tools),
        )


def _attempt_number(event: SessionEvent) -> int | None:
    raw_attempt_number = event.payload.get("attempt_number")
    if isinstance(raw_attempt_number, int) and raw_attempt_number > 0:
        return raw_attempt_number
    return None


def _tool_call_id(event: SessionEvent) -> str | None:
    value = event.payload.get("tool_call_id")
    if isinstance(value, str) and value.strip():
        return value
    return None


def _policy_context_from_payload(payload: dict[str, object]) -> dict[str, object]:
    context: dict[str, object] = {}
    for key in ("decision", "route", "target", "network_profile"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            context[key] = value
    scope = payload.get("scope")
    if isinstance(scope, list | tuple):
        normalized = [item for item in scope if isinstance(item, str) and item.strip()]
        if normalized:
            context["scope"] = normalized
    return context


def _string_or_none(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _scope_from_context(context: dict[str, object]) -> tuple[str, ...]:
    scope = context.get("scope")
    if not isinstance(scope, list):
        return ()
    return tuple(item for item in scope if isinstance(item, str) and item.strip())
