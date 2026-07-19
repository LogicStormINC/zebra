from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from agent_core.domain.context_continuation import ProviderContinuationRef
from agent_core.domain.events import EventActor, EventType
from agent_core.domain.identifiers import new_correlation_id, new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import (
    ModelCompletion,
    ModelContextWindow,
    ModelTextDelta,
    ModelToolDefinition,
)
from agent_core.domain.tools import ToolCall, ToolResult
from agent_core.harness.context_window import ContextWindowExceededError
from agent_core.harness.hooks import CompactionHook
from agent_core.harness.model_request import (
    build_context_plan,
    complete_model,
    context_window,
    with_context_plan,
)
from agent_core.harness.models import HarnessEventDraft, HarnessTask
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
from agent_core.ports.model_gateway import (
    ModelGatewayPort,
    StreamingModelGatewayPort,
)
from agent_core.ports.provider_continuation import (
    ProviderContinuationCompletionPort,
)

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


class HarnessModelStep:
    def __init__(
        self,
        context_compiler: ContextCompilerPort | None = None,
        *,
        available_tools: tuple[ModelToolDefinition, ...] = (),
        conversation_compactor: ConversationCompactorPort | None = None,
        conversation_token_budget: int | None = None,
        event_sink: Callable[[HarnessEventDraft], None] | None = None,
        continuation_sink: Callable[
            [ProviderContinuationRef, bytes | None, int | None], str | None
        ]
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

    def prepare_conversation(
        self,
        messages: list[SessionMessage],
        model_gateway: ModelGatewayPort,
        *,
        allow_tools: bool,
        user_goal: str,
        created_at: datetime,
    ) -> ConversationCompactionResult | None:
        tools = self._available_tools if allow_tools else ()
        window = context_window(model_gateway)
        budget = min(
            self._conversation_token_budget or window.compact_at,
            window.compact_at,
        )
        result = None
        if self._conversation_compactor is not None:
            if self._compaction_hook is not None:
                self._compaction_hook.pre_compact(tuple(messages), max_tokens=budget)
            result = self._conversation_compactor.compact_conversation(
                tuple(messages),
                user_goal=user_goal,
                max_tokens=budget,
                created_at=created_at,
            )
            messages[:] = result.messages
            if self._compaction_hook is not None:
                self._compaction_hook.post_compact(result)
        attempted = (result.provenance,) if result is not None and result.compacted else ()
        plan = build_context_plan(
            tuple(messages), tools, window, model_gateway, attempted_strategies=attempted
        )
        if not plan.within_budget:
            raise ContextWindowExceededError(plan)
        return result

    def compact_conversation(
        self,
        messages: list[SessionMessage],
        *,
        user_goal: str,
        created_at: datetime,
    ) -> ConversationCompactionResult | None:
        if self._conversation_compactor is None:
            return None
        return self._conversation_compactor.compact_conversation(
            tuple(messages),
            user_goal=user_goal,
            max_tokens=self._conversation_token_budget or ModelContextWindow().input_token_limit,
            created_at=created_at,
        )

    def request_initial_completion(
        self,
        task: HarnessTask,
        model_gateway: ModelGatewayPort,
        *,
        created_at: datetime | None = None,
    ) -> ModelCompletion:
        now = created_at or datetime.now(UTC)
        messages = self.build_initial_messages(task, created_at=now)
        self.prepare_conversation(
            messages,
            model_gateway,
            allow_tools=True,
            user_goal=task.user_input,
            created_at=now,
        )
        return self.request_completion(messages, model_gateway, allow_tools=True)

    def request_completion(
        self,
        messages: list[SessionMessage],
        model_gateway: ModelGatewayPort,
        *,
        allow_tools: bool,
    ) -> ModelCompletion:
        tools = self._available_tools if allow_tools else ()
        window = context_window(model_gateway)
        plan = build_context_plan(tuple(messages), tools, window, model_gateway)
        if not plan.within_budget:
            raise ContextWindowExceededError(plan)
        if self._event_sink is None:
            if self._provider_continuation is not None and isinstance(
                model_gateway, ProviderContinuationCompletionPort
            ):
                try:
                    completion = model_gateway.complete_from_reference(
                        self._provider_continuation, messages, tools=tools
                    )
                except (NotImplementedError, TimeoutError, ValueError):
                    completion = model_gateway.complete(messages, tools=tools)
                finally:
                    self._provider_continuation = None
            else:
                completion = model_gateway.complete(messages, tools=tools)
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
            except (NotImplementedError, TimeoutError, ValueError):
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
                )
            finally:
                self._provider_continuation = None
        elif isinstance(model_gateway, StreamingModelGatewayPort):
            completion = model_gateway.complete_stream(
                messages,
                tools=tools,
                on_text_delta=lambda delta: self._emit_text_delta(
                    model_call_id,
                    delta,
                ),
            )
        else:
            completion = model_gateway.complete(messages, tools=tools)
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

    def _emit_continuation_selection(
        self, selection: PreparedProviderContinuation
    ) -> None:
        if self._event_sink is None:
            return
        self._event_sink(
            continuation_event(selection, attempt_number=self._attempt_number)
        )

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
                content=tool_result.output or f"Tool {tool_result.status.value}.",
                created_at=created_at,
                tool_call_id=tool_call.provider_call_id or str(tool_call.tool_call_id),
                metadata=dict(tool_result.metadata),
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
        messages = self.build_initial_messages(task, created_at=now)
        self.append_tool_exchange(
            messages,
            completion=initial_completion,
            tool_call=tool_call,
            tool_result=tool_result,
            created_at=now,
        )
        self.append_final_answer_instruction(messages, created_at=now)
        self.prepare_conversation(
            messages,
            model_gateway,
            allow_tools=False,
            user_goal=task.user_input,
            created_at=now,
        )
        return self.request_completion(messages, model_gateway, allow_tools=False)

    @staticmethod
    def append_final_answer_instruction(
        messages: list[SessionMessage],
        *,
        created_at: datetime,
    ) -> None:
        messages.append(
            SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.USER,
                content=(
                    "The tool budget is complete. Answer the original request using "
                    "the available tool results. Do not request or invoke another tool."
                ),
                created_at=created_at,
            )
        )

    def build_initial_messages(
        self,
        task: HarnessTask,
        *,
        created_at: datetime,
    ) -> list[SessionMessage]:
        messages: list[SessionMessage] = []
        if self._context_compiler is not None and task.workspace_root is not None:
            if task.attachments:
                system_prompt = self._context_compiler.build_system_prompt(
                    task_input=task.user_input,
                    workspace_root=task.workspace_root,
                    max_tokens=task.context_token_budget,
                    runtime_evidence=task.runtime_evidence,
                    confirmed_memories=task.confirmed_memories,
                    attachments=task.attachments,
                )
            else:
                system_prompt = self._context_compiler.build_system_prompt(
                    task_input=task.user_input,
                    workspace_root=task.workspace_root,
                    max_tokens=task.context_token_budget,
                    runtime_evidence=task.runtime_evidence,
                    confirmed_memories=task.confirmed_memories,
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
                        "content": (
                            f"{messages[-1].content}\n\n"
                            f"{MODEL_NATIVE_DELEGATION_GUIDANCE}"
                        )
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
            step
            for step in task.task_plan.steps
            if step.status.value in {"pending", "in_progress"}
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
