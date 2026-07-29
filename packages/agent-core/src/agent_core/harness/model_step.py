import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from agent_core.domain.context_continuation import ProviderContinuationRef
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.identifiers import new_correlation_id, new_message_id
from agent_core.domain.messages import (
    MessageRole,
    SessionMessage,
)
from agent_core.domain.modeling import (
    ModelCompletion,
    ModelTextDelta,
    ModelToolDefinition,
)
from agent_core.domain.tools import ToolCall, ToolCallStatus, ToolResult
from agent_core.harness.context_recovery import (
    merge_recovery_messages,
    prepare_bounded_conversation,
    prepare_terminal_conversation,
)
from agent_core.harness.context_window import ContextWindowExceededError
from agent_core.harness.hooks import CompactionHook
from agent_core.harness.model_request import (
    allowed_response_repairs,
    build_context_plan,
    complete_model,
    context_window,
    with_context_plan,
)
from agent_core.harness.models import HarnessEventDraft, HarnessTask
from agent_core.harness.protocol_invariants import validate_tool_call_pairing
from agent_core.harness.provider_continuation import (
    PreparedProviderContinuation,
    continuation_event,
    prepare_provider_continuation,
)
from agent_core.ports.context_compiler import ContextCompilerPort
from agent_core.ports.conversation_compactor import (
    ConversationCompactionResult,
    ConversationCompactorPort,
)
from agent_core.ports.model_gateway import ModelGatewayPort, ModelResponseRejectedError
from agent_core.ports.provider_continuation import ProviderContinuationCompletionPort

MODEL_NATIVE_DELEGATION_GUIDANCE = (
    "Subagent delegation:\n"
    "- Answer directly when context is sufficient or evidence collection is not needed.\n"
    "- Use a normal parent tool for one direct operation or a short linear sequence.\n"
    "- Call agent.research only for bounded, independent, multi-step evidence "
    "collection whose separate context is materially useful.\n"
    "- Words such as research, search, analysis, or comparison do not require "
    "delegation by themselves.\n"
    "- Every agent.research call must include objective and a concise "
    "delegation_reason explaining why direct work is less suitable."
)


def _tool_result_content(tool_result: ToolResult) -> str:
    if tool_result.output:
        return tool_result.output
    if tool_result.status is ToolCallStatus.EXECUTED:
        return "Tool executed."
    observation: dict[str, object] = {"status": tool_result.status.value}
    for key in ("reason", "detail"):
        value = tool_result.metadata.get(key)
        if isinstance(value, str | int | float | bool):
            observation[key] = value
    return json.dumps(observation, ensure_ascii=False, sort_keys=True)


def _tool_result_status(tool_result: ToolResult) -> str:
    return "succeeded" if tool_result.status is ToolCallStatus.EXECUTED else "failed"


class HarnessModelStep:
    def __init__(
        self,
        context_compiler: ContextCompilerPort | None = None,
        *,
        available_tools: tuple[ModelToolDefinition, ...] = (),
        conversation_compactor: ConversationCompactorPort | None = None,
        conversation_token_budget: int | None = None,
        event_sink: Callable[[HarnessEventDraft], None] | None = None,
        continuation_sink: Callable[[ProviderContinuationRef, bytes | None, int | None], str | None]
        | None = None,
        provider_continuation: ProviderContinuationRef | None = None,
        compaction_hook: CompactionHook | None = None,
        attempt_number: int = 1,
    ) -> None:
        if conversation_token_budget is not None and conversation_token_budget <= 0:
            raise ValueError("conversation_token_budget must be positive")
        if attempt_number <= 0:
            raise ValueError("attempt_number must be positive")
        self._context_compiler = context_compiler
        self._available_tools = available_tools
        self._conversation_compactor = conversation_compactor
        self._conversation_token_budget = conversation_token_budget
        self._event_sink = event_sink
        self._continuation_sink = continuation_sink
        self._attempt_number = attempt_number
        self._provider_continuation = provider_continuation
        self._compaction_hook = compaction_hook
        self._recovery_messages: tuple[SessionMessage, ...] = ()

    def prepare_conversation(
        self,
        messages: list[SessionMessage],
        model_gateway: ModelGatewayPort,
        *,
        allow_tools: bool,
        user_goal: str,
        created_at: datetime,
    ) -> ConversationCompactionResult | None:
        result = prepare_bounded_conversation(
            messages,
            model_gateway,
            allow_tools=allow_tools,
            available_tools=self._available_tools,
            conversation_compactor=self._conversation_compactor,
            conversation_token_budget=self._conversation_token_budget,
            compaction_hook=self._compaction_hook,
            user_goal=user_goal,
            created_at=created_at,
        )
        if result is not None and result.recovery_messages is not None:
            recovery = merge_recovery_messages(
                self._recovery_messages,
                result.recovery_messages,
                model_gateway,
            )
            if recovery is not None:
                self._recovery_messages = recovery
        return result

    def recover_conversation(
        self,
        messages: list[SessionMessage],
        model_gateway: ModelGatewayPort,
    ) -> bool:
        recovery = merge_recovery_messages(
            self._recovery_messages,
            tuple(messages),
            model_gateway,
        )
        if recovery is None:
            return False
        self._recovery_messages = recovery
        self._provider_continuation = None
        messages[:] = self._recovery_messages
        return True

    def request_initial_completion(
        self,
        task: HarnessTask,
        model_gateway: ModelGatewayPort,
        *,
        created_at: datetime | None = None,
    ) -> ModelCompletion:
        now = created_at or datetime.now(UTC)
        messages = self.build_initial_messages(task, created_at=now, model_gateway=model_gateway)
        self.prepare_conversation(
            messages,
            model_gateway,
            allow_tools=True,
            user_goal=task.user_input,
            created_at=now,
        )
        repair_limit = allowed_response_repairs(task.max_model_calls, 0)
        return self.request_completion(
            messages, model_gateway, allow_tools=True, response_repair_limit=repair_limit
        )

    def request_completion(
        self,
        messages: list[SessionMessage],
        model_gateway: ModelGatewayPort,
        *,
        allow_tools: bool,
        response_repair_limit: int = 1,
    ) -> ModelCompletion:
        tools = self._available_tools if allow_tools else ()
        window = context_window(model_gateway)
        plan = build_context_plan(tuple(messages), tools, window, model_gateway)
        if not plan.within_budget:
            raise ContextWindowExceededError(plan)
        validate_tool_call_pairing(messages)
        if self._event_sink is None:
            if self._provider_continuation is not None and isinstance(
                model_gateway, ProviderContinuationCompletionPort
            ):
                try:
                    completion = model_gateway.complete_from_reference(
                        self._provider_continuation, messages, tools=tools
                    )
                except (
                    NotImplementedError,
                    TimeoutError,
                    ValueError,
                    ModelResponseRejectedError,
                ):
                    completion = complete_model(
                        model_gateway,
                        messages,
                        tools,
                        model_call_id="untracked",
                        on_delta=lambda _model_call_id, _delta: None,
                        response_repair_limit=response_repair_limit,
                    )
                finally:
                    self._provider_continuation = None
            else:
                completion = complete_model(
                    model_gateway,
                    messages,
                    tools,
                    model_call_id="untracked",
                    on_delta=lambda _model_call_id, _delta: None,
                    response_repair_limit=response_repair_limit,
                )
            return with_context_plan(completion, plan)
        model_call_id = str(new_correlation_id())
        self._event_sink(
            HarnessEventDraft(
                event_type=EventType.MODEL_REQUEST_STARTED,
                actor=EventActor.HARNESS,
                payload={
                    "attempt_number": self._attempt_number,
                    "model_call_id": model_call_id,
                    "estimated_input_tokens": plan.estimated_input_tokens,
                    "input_token_limit": plan.input_token_limit,
                    "model_profile": plan.profile_name,
                    "token_estimate_method": plan.estimate_method,
                    "token_breakdown": plan.token_breakdown,
                    "reserves": {
                        "output": window.max_output_tokens,
                        "reasoning": window.reasoning_reserve_tokens,
                        "compaction": window.compaction_reserve_tokens,
                        "protocol_and_emergency": window.protocol_reserve_tokens,
                    },
                },
            )
        )
        if self._provider_continuation is not None and isinstance(
            model_gateway, ProviderContinuationCompletionPort
        ):
            try:
                completion = model_gateway.complete_from_reference(
                    self._provider_continuation,
                    messages,
                    tools=tools,
                )
            except (
                NotImplementedError,
                TimeoutError,
                ValueError,
                ModelResponseRejectedError,
            ):
                self._emit_continuation_selection(
                    PreparedProviderContinuation(
                        mode="capsule_fallback",
                        reason="provider continuation request failed",
                    )
                )
                completion = complete_model(
                    model_gateway,
                    messages,
                    tools,
                    model_call_id=model_call_id,
                    on_delta=self._emit_text_delta,
                    response_repair_limit=response_repair_limit,
                )
            finally:
                self._provider_continuation = None
        else:
            completion = complete_model(
                model_gateway,
                messages,
                tools,
                model_call_id=model_call_id,
                on_delta=self._emit_text_delta,
                response_repair_limit=response_repair_limit,
            )
        planned_completion = with_context_plan(completion, plan)
        return replace(
            planned_completion,
            call_metadata=replace(
                planned_completion.call_metadata,
                model_call_id=model_call_id,
            ),
        )

    def prepare_provider_continuation(
        self,
        model_gateway: ModelGatewayPort,
        result: ConversationCompactionResult,
    ) -> None:
        if not result.compacted or result.capsule is None:
            return
        selection = prepare_provider_continuation(
            model_gateway, result.capsule, self._continuation_sink
        )
        self._provider_continuation = selection.reference
        self._emit_continuation_selection(selection)

    def _emit_continuation_selection(self, selection: PreparedProviderContinuation) -> None:
        if self._event_sink is None:
            return
        self._event_sink(continuation_event(selection, attempt_number=self._attempt_number))

    def _emit_text_delta(self, model_call_id: str, delta: ModelTextDelta) -> None:
        if self._event_sink is None:
            return
        self._event_sink(
            HarnessEventDraft(
                event_type=EventType.MODEL_RESPONSE_DELTA,
                actor=EventActor.HARNESS,
                payload={
                    "attempt_number": self._attempt_number,
                    "model_call_id": model_call_id,
                    "delta_index": delta.index,
                    "content_delta": delta.content,
                },
            )
        )

    def append_tool_exchange(
        self,
        messages: list[SessionMessage],
        *,
        completion: ModelCompletion,
        tool_call: ToolCall,
        tool_result: ToolResult,
        created_at: datetime,
    ) -> None:
        self.append_tool_batch(
            messages,
            completion=completion,
            tool_calls=(tool_call,),
        )
        self.append_tool_result(
            messages,
            tool_call=tool_call,
            tool_result=tool_result,
            created_at=created_at,
        )

    @staticmethod
    def append_tool_batch(
        messages: list[SessionMessage],
        *,
        completion: ModelCompletion,
        tool_calls: tuple[ToolCall, ...],
    ) -> None:
        if not tool_calls:
            raise ValueError("tool batch must not be empty")
        messages.append(completion.assistant_message.model_copy(update={"tool_calls": tool_calls}))

    @staticmethod
    def append_tool_result(
        messages: list[SessionMessage],
        *,
        tool_call: ToolCall,
        tool_result: ToolResult,
        created_at: datetime,
    ) -> None:
        messages.append(
            SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.TOOL,
                content=_tool_result_content(tool_result),
                created_at=created_at,
                tool_call_id=tool_call.provider_call_id or str(tool_call.tool_call_id),
                metadata={
                    **tool_result.metadata,
                    "tool_result_status": _tool_result_status(tool_result),
                },
            )
        )

    def request_tool_result_completion(
        self,
        task: HarnessTask,
        model_gateway: ModelGatewayPort,
        *,
        initial_completion: ModelCompletion,
        tool_call: ToolCall,
        tool_result: ToolResult,
        created_at: datetime | None = None,
    ) -> ModelCompletion:
        now = created_at or datetime.now(UTC)
        messages = self.build_initial_messages(task, created_at=now, model_gateway=model_gateway)
        self.append_tool_exchange(
            messages,
            completion=initial_completion,
            tool_call=tool_call,
            tool_result=tool_result,
            created_at=now,
        )
        prepare_terminal_conversation(messages, model_gateway, self, task.user_input, now)
        return self.request_completion(messages, model_gateway, allow_tools=False)

    def build_initial_messages(
        self, task: HarnessTask, *, created_at: datetime,
        model_gateway: ModelGatewayPort | None = None,
    ) -> list[SessionMessage]:
        self._recovery_messages = ()
        messages: list[SessionMessage] = []
        if self._context_compiler is not None and task.workspace_root is not None:
            active_projection = any(
                evidence.kind == "session_handoff"
                and (evidence.metadata or {}).get("handoff_source") == "active_projection"
                for evidence in task.runtime_evidence
            )
            context_budget = (
                max(
                    task.context_token_budget,
                    context_window(model_gateway).compaction_reserve_tokens,
                )
                if model_gateway is not None and active_projection
                else task.context_token_budget
            )
            system_prompt = self._context_compiler.build_system_prompt(
                task_input=task.user_input,
                workspace_root=task.workspace_root,
                max_tokens=context_budget,
                runtime_evidence=task.runtime_evidence,
                confirmed_memories=task.confirmed_memories,
                **({"attachments": task.attachments} if task.attachments else {}),
            )
            if system_prompt is not None:
                messages.append(
                    SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.SYSTEM,
                        content=system_prompt,
                        created_at=created_at,
                    )
                )
        if any(tool.name == "agent.research" for tool in self._available_tools):
            if messages:
                messages[-1] = messages[-1].model_copy(
                    update={
                        "content": (f"{messages[-1].content}\n\n{MODEL_NATIVE_DELEGATION_GUIDANCE}")
                    }
                )
            else:
                messages.append(
                    SessionMessage(
                        message_id=new_message_id(),
                        role=MessageRole.SYSTEM,
                        content=MODEL_NATIVE_DELEGATION_GUIDANCE,
                        created_at=created_at,
                    )
                )
        active_steps = tuple(
            step for step in task.task_plan.steps if step.status.value in {"pending", "in_progress"}
        )
        if active_steps:
            messages.append(
                SessionMessage(
                    message_id=new_message_id(),
                    role=MessageRole.SYSTEM,
                    content="\n".join(
                        ["Current durable task plan:"]
                        + [
                            f"- [{step.status.value}] {step.step_id}: {step.content}"
                            for step in active_steps
                        ]
                    ),
                    created_at=created_at,
                )
            )
        messages.append(
            SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.USER,
                content=task.user_input,
                created_at=created_at,
            )
        )
        return messages
