from agent_core.domain.events import EventType, SessionEvent
from agent_core.harness.models import (
    HarnessAttemptTrace,
    HarnessLoopResult,
    HarnessRunTrace,
    HarnessToolTrace,
)


class HarnessTraceProjector:
    def project(self, result: HarnessLoopResult) -> HarnessRunTrace:
        attempts: dict[int, _AttemptBuilder] = {}

        for event in result.events:
            attempt_number = _attempt_number(event)
            if attempt_number is None:
                continue
            builder = attempts.setdefault(
                attempt_number,
                _AttemptBuilder(attempt_number=attempt_number),
            )
            builder.apply(event)

        projected_attempts = tuple(
            builder.build()
            for _, builder in sorted(attempts.items(), key=lambda item: item[0])
        )
        return HarnessRunTrace(
            final_outcome=result.run_result.final_outcome,
            stop_reason=result.run_result.stop_reason,
            attempts=projected_attempts,
        )


class _AttemptBuilder:
    def __init__(self, *, attempt_number: int) -> None:
        self._attempt_number = attempt_number
        self._assistant_message: str | None = None
        self._pending_tool_name: str | None = None
        self._tool_arguments: dict[str, object] = {}
        self._policy_context: dict[str, object] = {}
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
            if isinstance(tool_name, str):
                self._pending_tool_name = tool_name
            if isinstance(arguments, dict):
                self._tool_arguments = dict(arguments)
            return

        if event.event_type is EventType.POLICY_DECISION_MADE:
            self._policy_context = _policy_context_from_payload(event.payload)
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
            self._tools.append(
                HarnessToolTrace(
                    tool_name=tool_name,
                    status=status,
                    arguments=(
                        dict(self._tool_arguments)
                        if tool_name == self._pending_tool_name
                        else {}
                    ),
                    output=output if isinstance(output, str) else "",
                    metadata=dict(metadata) if isinstance(metadata, dict) else {},
                    policy_decision=_string_or_none(self._policy_context.get("decision")),
                    policy_route=_string_or_none(self._policy_context.get("route")),
                    policy_target=_string_or_none(self._policy_context.get("target")),
                    policy_network_profile=_string_or_none(
                        self._policy_context.get("network_profile")
                    ),
                    policy_scope=_scope_from_context(self._policy_context),
                )
            )
            self._pending_tool_name = None
            self._tool_arguments = {}
            self._policy_context = {}

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


def _policy_context_from_payload(payload: dict[str, object]) -> dict[str, object]:
    context: dict[str, object] = {}
    for field in ("decision", "route", "target", "network_profile"):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            context[field] = value
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
