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
from agent_core.domain.model_media import (
    ModelMediaInput,
    model_media_source_event_ids_metadata,
)
from agent_core.domain.modeling import (
    ModelCompletion,
    ModelInvocationPolicy,
    ModelTextDelta,
    ModelToolDefinition,
)
from agent_core.domain.tools import ToolCall, ToolResult
from agent_core.harness.capability_guidance import append_capability_guidance
from agent_core.harness.context_recovery import (
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
from agent_core.harness.model_step_completions import (
    _emit_continuation_selection,
    _emit_text_delta,
    prepare_conversation,
    recover_conversation,
)
from agent_core.harness.models import HarnessEventDraft, HarnessTask
from agent_core.harness.orchestration_events import model_request_started_payload
from agent_core.harness.protocol_invariants import validate_tool_call_pairing
from agent_core.harness.provider_continuation import (
    PreparedProviderContinuation,
    prepare_provider_continuation,
)
from agent_core.harness.reconstruction import (
    RequestReconstruction,
    prepare_guarded_dispatch,
)
from agent_core.harness.required_tool_request import selected_model_tools
from agent_core.harness.task_state_context import append_task_state_context
from agent_core.harness.tool_result_message import (
    tool_message_append_tool_batch,
    tool_message_append_tool_result,
)
from agent_core.ports.context_compiler import ContextCompilerPort
from agent_core.ports.conversation_compactor import (
    ConversationCompactionResult,
    ConversationCompactorPort,
)
from agent_core.ports.model_gateway import ModelGatewayPort, ModelResponseRejectedError
from agent_core.ports.provider_continuation import ProviderContinuationCompletionPort


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
        reconstruction: RequestReconstruction | None = None,
        plan_revision_provider: Callable[[], int] | None = None,
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
        self._reconstruction = reconstruction
        self._plan_revision_provider = plan_revision_provider
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
        media_inputs: tuple[ModelMediaInput, ...] = (),
    ) -> ConversationCompactionResult | None:
        return prepare_conversation(
            self,
            messages,
            model_gateway,
            allow_tools=allow_tools,
            user_goal=user_goal,
            created_at=created_at,
            media_inputs=media_inputs,
        )

    def recover_conversation(
        self,
        messages: list[SessionMessage],
        model_gateway: ModelGatewayPort,
        *,
        media_inputs: tuple[ModelMediaInput, ...] = (),
    ) -> bool:
        return recover_conversation(self, messages, model_gateway, media_inputs=media_inputs)

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
            user_goal=task.stable_goal,
            created_at=now,
            **({"media_inputs": task.media_inputs} if task.media_inputs else {}),
        )
        repair_limit = allowed_response_repairs(task.max_model_calls, 0)
        return self.request_completion(
            messages,
            model_gateway,
            allow_tools=True,
            media_inputs=task.media_inputs,
            response_repair_limit=repair_limit,
        )

    def request_completion(
        self,
        messages: list[SessionMessage],
        model_gateway: ModelGatewayPort,
        *,
        allow_tools: bool,
        media_inputs: tuple[ModelMediaInput, ...] = (),
        response_repair_limit: int = 1,
        required_tool_names: tuple[str, ...] = (),
        invocation_policy: ModelInvocationPolicy | None = None,
        step_kind: str = "initial",
    ) -> ModelCompletion:
        tools = selected_model_tools(
            self._available_tools,
            allow_tools=allow_tools,
            required_names=required_tool_names,
        )
        if invocation_policy is not None and not tools:
            raise ValueError("model invocation policy requires advertised tools")
        if invocation_policy is not None:
            self._provider_continuation = None
        window = context_window(model_gateway)
        plan = build_context_plan(
            tuple(messages),
            tools,
            window,
            model_gateway,
            media_inputs=media_inputs,
        )
        if not plan.within_budget:
            raise ContextWindowExceededError(plan)
        validate_tool_call_pairing(messages)
        if self._event_sink is None:
            if (
                not media_inputs
                and self._provider_continuation is not None
                and isinstance(model_gateway, ProviderContinuationCompletionPort)
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
                        media_inputs=media_inputs,
                        model_call_id="untracked",
                        on_delta=lambda _model_call_id, _delta: None,
                        response_repair_limit=response_repair_limit,
                        invocation_policy=invocation_policy,
                    )
                finally:
                    self._provider_continuation = None
            else:
                completion = complete_model(
                    model_gateway,
                    messages,
                    tools,
                    media_inputs=media_inputs,
                    model_call_id="untracked",
                    on_delta=lambda _model_call_id, _delta: None,
                    response_repair_limit=response_repair_limit,
                    invocation_policy=invocation_policy,
                    reconstruction=self._reconstruction,
                    step_kind=step_kind,
                    allow_tools=allow_tools,
                    required_tool_names=required_tool_names,
                )
            return with_context_plan(completion, plan)
        model_call_id = str(new_correlation_id())
        current_plan_revision = (
            self._plan_revision_provider() if self._plan_revision_provider else None
        )
        reconstruction_fields, response_repair_limit = prepare_guarded_dispatch(
            self._reconstruction,
            messages,
            tools,
            media_inputs=media_inputs,
            gateway=model_gateway,
            invocation_policy=invocation_policy,
            response_repair_limit=response_repair_limit,
            step_id=model_call_id,
            step_kind=step_kind,
            allow_tools=allow_tools,
            required_tool_names=required_tool_names,
            plan_revision=current_plan_revision,
        )
        self._event_sink(
            HarnessEventDraft(
                event_type=EventType.MODEL_REQUEST_STARTED,
                actor=EventActor.HARNESS,
                payload=model_request_started_payload(
                    attempt_number=self._attempt_number,
                    model_call_id=model_call_id,
                    plan=plan,
                    window=window,
                    reconstruction_fields=reconstruction_fields,
                ),
            )
        )
        if (
            not media_inputs
            and self._provider_continuation is not None
            and isinstance(model_gateway, ProviderContinuationCompletionPort)
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
                    media_inputs=media_inputs,
                    model_call_id=model_call_id,
                    on_delta=self._emit_text_delta,
                    response_repair_limit=response_repair_limit,
                    invocation_policy=invocation_policy,
                    reconstruction=self._reconstruction,
                    step_kind=step_kind,
                    allow_tools=allow_tools,
                    required_tool_names=required_tool_names,
                )
            finally:
                self._provider_continuation = None
        else:
            completion = complete_model(
                model_gateway,
                messages,
                tools,
                media_inputs=media_inputs,
                model_call_id=model_call_id,
                on_delta=self._emit_text_delta,
                response_repair_limit=response_repair_limit,
                invocation_policy=invocation_policy,
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

    def _emit_text_delta(self, model_call_id: str, delta: ModelTextDelta) -> None:
        _emit_text_delta(self, model_call_id, delta)

    def _emit_continuation_selection(self, selection: PreparedProviderContinuation) -> None:
        _emit_continuation_selection(self, selection)

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
        tool_message_append_tool_batch(
            messages,
            completion=completion,
            tool_calls=tool_calls,
        )

    @staticmethod
    def append_tool_result(
        messages: list[SessionMessage],
        *,
        tool_call: ToolCall,
        tool_result: ToolResult,
        created_at: datetime,
    ) -> None:
        tool_message_append_tool_result(
            messages,
            tool_call=tool_call,
            tool_result=tool_result,
            created_at=created_at,
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
        prepare_terminal_conversation(
            messages,
            model_gateway,
            self,
            task.stable_goal,
            now,
            media_inputs=task.media_inputs,
        )
        return self.request_completion(
            messages,
            model_gateway,
            allow_tools=False,
            media_inputs=task.media_inputs,
        )

    def build_initial_messages(
        self,
        task: HarnessTask,
        *,
        created_at: datetime,
        model_gateway: ModelGatewayPort | None = None,
    ) -> list[SessionMessage]:
        self._recovery_messages = ()
        messages: list[SessionMessage] = []
        if self._context_compiler is not None and task.workspace_root is not None:
            has_session_handoff = any(
                evidence.kind == "session_handoff" for evidence in task.runtime_evidence
            )
            context_budget = (
                max(
                    task.context_token_budget,
                    context_window(model_gateway).compaction_reserve_tokens,
                )
                if model_gateway is not None and has_session_handoff
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
        if task.agent_context is not None:
            messages.insert(
                0,
                SessionMessage(
                    message_id=new_message_id(),
                    role=MessageRole.SYSTEM,
                    content=task.agent_context.render(),
                    created_at=created_at,
                    metadata={
                        "agent_definition_id": task.agent_context.agent_id,
                        "agent_definition_version": task.agent_context.version,
                    },
                ),
            )
        append_capability_guidance(
            messages,
            self._available_tools,
            created_at=created_at,
            plan_required=task.plan_required,
        )
        append_task_state_context(messages, task, created_at=created_at)
        messages.append(
            SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.USER,
                content=task.user_input,
                created_at=created_at,
                metadata=model_media_source_event_ids_metadata(
                    media.source_message_id for media in task.media_inputs
                ),
            )
        )
        return messages
