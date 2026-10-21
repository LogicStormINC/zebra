"""Typed read-only script tools; execution stays behind the native invocation service."""

from collections.abc import Callable
from hashlib import sha256

from agent_core.application.native_script import NativeScriptInvocationService
from agent_core.contracts.answer_events import AnswerCommittedPayload
from agent_core.domain.events import EventType
from agent_core.domain.runtime_bundle_json import load_bundle_json
from agent_core.domain.script_bundle import ScriptBinding
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolExecutionLocation, ToolResult
from agent_core.harness.models import HarnessEventDraft

from agent_tools.contracts import ToolContract
from agent_tools.registry import ToolRegistry


class NativeScriptTools:
    def __init__(
        self,
        service: NativeScriptInvocationService,
        bindings: tuple[ScriptBinding, ...],
        *,
        commit_answer: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        self._commit_answer = commit_answer or (lambda action: action())
        self.service = service
        self.context_binding = next((b for b in bindings if b.manifest.kind == "context"), None)
        self.verifier_binding = next((b for b in bindings if b.manifest.kind == "verifier"), None)
        self._bindings = {item.name: item for item in bindings if item.manifest.kind == "tool"}
        self.registry = ToolRegistry()
        for binding in self._bindings.values():
            fields = binding.manifest.input.fields
            self.registry.register(
                ToolContract(
                    name=binding.name,
                    description=f"Native read-only capability {binding.manifest.name}",
                    required_arguments=tuple(item.name for item in fields),
                    argument_properties={item.name: {"type": item.type} for item in fields},
                    capability_version=binding.manifest.version,
                    execution_location=ToolExecutionLocation.SANDBOX,
                    scopes=binding.scopes,
                    timeout_seconds=binding.manifest.timeout_seconds,
                    max_output_bytes=binding.manifest.max_output_bytes,
                    parallel_safe=False,
                ),
                self.execute,
            )

    def execute(self, call: ToolCall) -> ToolResult:
        binding = self._bindings[call.name]
        result = self.service.invoke(binding, call.arguments, logical_id=str(call.tool_call_id))
        output = (
            result.output_json.decode("utf-8")
            if result.output_json is not None
            else "Native read-only capability did not return an accepted result."
        )
        status = (
            ToolCallStatus.EXECUTED
            if result.observation.status == "succeeded"
            else ToolCallStatus.FAILED
        )
        contract = self.registry.get(call.name).contract
        return ToolResult(
            tool_call_id=call.tool_call_id,
            status=status,
            output=output,
            receipt=contract.receipt(status=status.value, output_bytes=len(output.encode())),
            metadata={
                "native_script": result.observation.model_dump(mode="json"),
                "execution_state": "executed",
                "retryable": False,
            },
        )

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self._bindings)

    def guard_answer_sink(
        self, sink: Callable[[HarnessEventDraft], None]
    ) -> Callable[[HarnessEventDraft], None]:
        def guarded(event: HarnessEventDraft) -> None:
            binding = self.verifier_binding
            if binding is not None and event.event_type is EventType.ANSWER_COMMITTED:
                payload = AnswerCommittedPayload.model_validate(event.payload)
                if payload.delivery_assessment.status == "complete":
                    candidate = payload.assistant_message
                    result = self.service.invoke(
                        binding,
                        {"tool_status": "completed", "tool_output": candidate},
                        logical_id="verifier:" + sha256(candidate.encode()).hexdigest(),
                    )
                    if (
                        result.output_json is None
                        or load_bundle_json(result.output_json).get("passed") is not True
                    ):
                        raise ValueError("NATIVE_SCRIPT_CONSTRAINT_REJECTED")
            sink(event)  # Passing never changes acceptance, verification or Coverage metadata.

        return guarded

    def fence_answer_sink(
        self, sink: Callable[[HarnessEventDraft], None]
    ) -> Callable[[HarnessEventDraft], None]:
        def fenced(event: HarnessEventDraft) -> None:
            if event.event_type is EventType.ANSWER_COMMITTED:
                self._commit_answer(lambda: sink(event))
            else:
                sink(event)

        return fenced
