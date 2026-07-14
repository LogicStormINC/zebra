from agent_core.domain.events import EventActor, EventType
from agent_core.domain.messages import SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.tools import ToolCall
from agent_core.harness.hooks import (
    NoopPlanner,
    NoopVerifier,
    PlannerHook,
    VerifierHook,
)
from agent_core.harness.model_step import HarnessModelStep
from agent_core.harness.models import HarnessAttemptResult, HarnessContext, HarnessEventDraft
from agent_core.harness.orchestration_events import model_response_event
from agent_core.harness.selection import (
    FirstToolCallSelectionStrategy,
    ToolCallSelectionStrategy,
)
from agent_core.harness.sequential_loop import SequentialToolLoop
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
        )

    def run(self, context: HarnessContext) -> HarnessAttemptResult:
        messages = self._model_step.build_initial_messages(
            context.task,
            created_at=context.attempt.started_at,
        )
        completion = self._model_step.request_completion(
            messages,
            self._model_gateway,
            allow_tools=True,
        )
        emitted_events = [model_response_event(completion, attempt_number=context.attempt.number)]
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
            model_calls_used=1,
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
        conversation: tuple[SessionMessage, ...] = (),
        model_calls_used: int = 1,
        tool_calls_executed: int = 0,
    ) -> HarnessAttemptResult:
        return self._tool_loop.continue_approved(
            context,
            completion=initial_completion,
            tool_call=tool_call,
            conversation=conversation,
            model_calls_used=model_calls_used,
            tool_calls_executed=tool_calls_executed,
        )
