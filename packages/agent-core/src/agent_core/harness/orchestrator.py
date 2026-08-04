from collections.abc import Callable, Mapping
from dataclasses import replace

from agent_core.domain.events import EventActor, EventType
from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.session_handoff import HandoffReason
from agent_core.domain.tools import ToolCall
from agent_core.harness.attempt_result import build_attempt_result
from agent_core.harness.hooks import (
    NoopPlanner,
    NoopVerifier,
    PlannerHook,
    VerifierHook,
)
from agent_core.harness.model_request import allowed_response_repairs
from agent_core.harness.model_step import HarnessModelStep
from agent_core.harness.models import (
    HarnessAttemptOutcome,
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

ACTIVE_PROJECTION_FOLLOW_UP_GUIDANCE = (
    "Terminal follow-up continuity: Apply the latest user follow-up before planning or "
    "requesting tools. If it resolves an open question or decision in recovered context, do "
    "not ask it again; use the recovered evidence to continue toward a self-contained answer. "
    "Tools remain available for genuinely new information required to complete the follow-up."
)


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
        validator_tool_names: frozenset[str] = frozenset(),
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
            validator_tool_names=validator_tool_names,
            event_sink=event_sink,
        )
        self._event_sink = event_sink

    def run(self, context: HarnessContext) -> HarnessAttemptResult:
        preflight = self._capability_preflight(context)
        if preflight is not None:
            return preflight
        task = replace(context.task, task_plan=context.session.task_plan)
        messages = self._model_step.build_initial_messages(
            task,
            created_at=context.attempt.started_at,
            model_gateway=self._model_gateway,
        )
        if any(
            evidence.kind == "session_handoff"
            and (evidence.metadata or {}).get("handoff_source") == "active_projection"
            and (evidence.metadata or {}).get("handoff_reason")
            == HandoffReason.INTERNAL_TERMINAL_FOLLOW_UP.value
            for evidence in task.runtime_evidence
        ):
            messages.insert(
                -1,
                SessionMessage(
                    message_id=new_message_id(),
                    role=MessageRole.SYSTEM,
                    content=ACTIVE_PROJECTION_FOLLOW_UP_GUIDANCE,
                    created_at=context.attempt.started_at,
                ),
            )
        emitted_events = HarnessEventBuffer(self._event_sink)
        compaction = self._model_step.prepare_conversation(
            messages,
            self._model_gateway,
            allow_tools=True,
            user_goal=task.user_input,
            created_at=context.attempt.started_at,
            **({"media_inputs": task.media_inputs} if task.media_inputs else {}),
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
            media_inputs=task.media_inputs,
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
        metadata: dict[str, object] = {
            "plan_summary": planner_result.summary,
            "plan_metadata": planner_result.metadata,
        }
        if completion.output_contract is not None:
            metadata["output_contract"] = dict(completion.output_contract)
        return self._tool_loop.advance(
            context,
            messages=messages,
            completion=completion,
            emitted_events=emitted_events,
            model_calls_used=1 + completion.call_metadata.response_repair_count,
            tool_calls_executed=0,
            fingerprints=set(),
            metadata=metadata,
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
        preflight = self._capability_preflight(context)
        if preflight is not None:
            return preflight
        return self._tool_loop.continue_approved(
            context,
            completion=initial_completion,
            tool_call=tool_call,
            remaining_tool_calls=remaining_tool_calls,
            conversation=conversation,
            model_calls_used=model_calls_used,
            tool_calls_executed=tool_calls_executed,
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
        preflight = self._capability_preflight(context)
        if preflight is not None:
            return preflight
        return self._tool_loop.continue_clarification(
            context,
            tool_call=tool_call,
            response=response,
            conversation=conversation,
            model_calls_used=model_calls_used,
            tool_calls_executed=tool_calls_executed,
            assistant_message=assistant_message,
        )

    @staticmethod
    def _capability_preflight(
        context: HarnessContext,
    ) -> HarnessAttemptResult | None:
        definition = context.task.agent_definition
        if definition is None:
            return None
        missing_capabilities = definition.missing_model_capabilities(
            context.task.model_capabilities
        )
        if not missing_capabilities:
            return None
        return build_attempt_result(
            outcome=HarnessAttemptOutcome.FAILED,
            summary="agent definition requires unavailable model capabilities",
            assistant_message="",
            model_calls_used=0,
            tool_calls_executed=0,
            emitted_events=[],
            metadata={
                "stop_reason": "agent_definition_model_capability_missing",
                "missing_model_capabilities": list(missing_capabilities),
            },
        )
