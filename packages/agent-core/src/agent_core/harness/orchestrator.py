from collections.abc import Callable, Mapping
from dataclasses import replace

from agent_core.domain.events import EventActor, EventType
from agent_core.domain.messages import SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.tools import ToolCall, ToolResult
from agent_core.harness.hooks import (
    NoopPlanner,
    NoopVerifier,
    PlannerHook,
    VerifierHook,
)
from agent_core.harness.model_request import allowed_response_repairs
from agent_core.harness.model_step import HarnessModelStep
from agent_core.harness.models import (
    HarnessAttemptResult,
    HarnessContext,
    HarnessEventBuffer,
    HarnessEventDraft,
)
from agent_core.harness.orchestration_events import (
    context_compacted_event,
    model_response_event,
)
from agent_core.harness.selection import (
    FirstToolCallSelectionStrategy,
    ToolCallSelectionStrategy,
)
from agent_core.harness.sequential_loop import SequentialToolLoop
from agent_core.harness.tool_resolution import ToolCallResolver
from agent_core.ports.model_gateway import ModelGatewayPort
from agent_core.ports.policy_engine import PolicyEnginePort
from agent_core.ports.tool_gateway import ToolGatewayPort


class SingleAttemptOrchestrator:
    def __init__(
        self,
        model_gateway: ModelGatewayPort,
        policy_engine: PolicyEnginePort,
        tool_gateway: ToolGatewayPort,
        *,
        model_step: HarnessModelStep | None = None,
        planner: PlannerHook | None = None,
        verifier: VerifierHook | None = None,
        tool_selector: ToolCallSelectionStrategy | None = None,
        synthesize_tool_results: bool = False,
        parallel_safe_tools: frozenset[str] = frozenset(),
        parallel_batch_limits: Mapping[str, int] | None = None,
        max_parallel_tool_calls: int = 1,
        tool_call_resolver: ToolCallResolver | None = None,
        event_sink: Callable[[HarnessEventDraft], None] | None = None,
    ) -> None:
        self._model_gateway = model_gateway
        self._model_step = model_step or HarnessModelStep()
        self._planner = planner or NoopPlanner()
        self._tool_loop = SequentialToolLoop(
            model_gateway=model_gateway,
            policy_engine=policy_engine,
            tool_gateway=tool_gateway,
            model_step=self._model_step,
            verifier=verifier or NoopVerifier(),
            tool_selector=tool_selector or FirstToolCallSelectionStrategy(),
            synthesize_tool_results=synthesize_tool_results,
            parallel_safe_tools=parallel_safe_tools,
            parallel_batch_limits=parallel_batch_limits,
            max_parallel_tool_calls=max_parallel_tool_calls,
            tool_call_resolver=tool_call_resolver,
            event_sink=event_sink,
        )
        self._event_sink = event_sink

    def run(self, context: HarnessContext) -> HarnessAttemptResult:
        task = replace(context.task, task_plan=context.session.task_plan)
        messages = self._model_step.build_initial_messages(
            task,
            created_at=context.attempt.started_at,
        )
        emitted_events = HarnessEventBuffer(self._event_sink)
        compaction = self._model_step.prepare_conversation(
            messages,
            self._model_gateway,
            allow_tools=True,
            user_goal=task.user_input,
            created_at=context.attempt.started_at,
        )
        if compaction is not None and compaction.compacted:
            emitted_events.append(
                context_compacted_event(compaction, attempt_number=context.attempt.number)
            )
            self._model_step.prepare_provider_continuation(
                self._model_gateway, compaction
            )
        completion = self._model_step.request_completion(
            messages,
            self._model_gateway,
            allow_tools=True,
            response_repair_limit=allowed_response_repairs(task.max_model_calls, 0),
        )
        emitted_events.append(
            model_response_event(completion, attempt_number=context.attempt.number)
        )
        planner_result = self._planner.plan(context)
        emitted_events.append(
            HarnessEventDraft(
                event_type=EventType.PLAN_PROPOSED,
                actor=EventActor.HARNESS,
                payload={
                    "attempt_number": context.attempt.number,
                    "summary": planner_result.summary,
                    "metadata": planner_result.metadata,
                },
            )
        )
        return self._tool_loop.advance(
            context,
            messages=messages,
            completion=completion,
            emitted_events=emitted_events,
            model_calls_used=1 + completion.call_metadata.response_repair_count,
            tool_calls_executed=0,
            fingerprints=set(),
            metadata={
                "plan_summary": planner_result.summary,
                "plan_metadata": planner_result.metadata,
            },
        )

    def continue_approved_tool_call(
        self,
        context: HarnessContext,
        *,
        initial_completion: ModelCompletion,
        tool_call: ToolCall,
        remaining_tool_calls: tuple[ToolCall, ...] = (),
        conversation: tuple[SessionMessage, ...] = (),
        model_calls_used: int = 1,
        tool_calls_executed: int = 0,
    ) -> HarnessAttemptResult:
        return self._tool_loop.continue_approved(
            context,
            completion=initial_completion,
            tool_call=tool_call,
            remaining_tool_calls=remaining_tool_calls,
            conversation=conversation,
            model_calls_used=model_calls_used,
            tool_calls_executed=tool_calls_executed,
        )

    def continue_completed_tool(
        self,
        context: HarnessContext,
        *,
        completion: ModelCompletion,
        tool_call: ToolCall,
        tool_result: ToolResult,
        conversation: tuple[SessionMessage, ...],
        model_calls_used: int,
        tool_calls_executed: int,
        assistant_message: str,
    ) -> HarnessAttemptResult:
        return self._tool_loop.continue_completed(
            context,
            completion=completion,
            tool_call=tool_call,
            tool_result=tool_result,
            conversation=conversation,
            model_calls_used=model_calls_used,
            tool_calls_executed=tool_calls_executed,
            assistant_message=assistant_message,
        )

    def continue_completed_tools(
        self,
        context: HarnessContext,
        *,
        completion: ModelCompletion,
        tool_calls: tuple[ToolCall, ...],
        tool_results: tuple[ToolResult, ...],
        conversation: tuple[SessionMessage, ...],
        model_calls_used: int,
        tool_calls_executed: int,
        assistant_message: str,
        metadata: dict[str, object] | None = None,
    ) -> HarnessAttemptResult:
        return self._tool_loop.continue_completed_batch(
            context,
            completion=completion,
            tool_calls=tool_calls,
            tool_results=tool_results,
            conversation=conversation,
            model_calls_used=model_calls_used,
            tool_calls_executed=tool_calls_executed,
            assistant_message=assistant_message,
            metadata=metadata,
        )

    def continue_clarification(
        self,
        context: HarnessContext,
        *,
        tool_call: ToolCall,
        response: str,
        conversation: tuple[SessionMessage, ...],
        model_calls_used: int,
        tool_calls_executed: int,
        assistant_message: str,
    ) -> HarnessAttemptResult:
        return self._tool_loop.continue_clarification(
            context,
            tool_call=tool_call,
            response=response,
            conversation=conversation,
            model_calls_used=model_calls_used,
            tool_calls_executed=tool_calls_executed,
            assistant_message=assistant_message,
        )
