from datetime import UTC, datetime

from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelToolDefinition
from agent_core.domain.tools import ToolCall, ToolResult
from agent_core.harness.models import HarnessTask
from agent_core.ports.context_compiler import ContextCompilerPort
from agent_core.ports.conversation_compactor import (
    ConversationCompactionResult,
    ConversationCompactorPort,
)
from agent_core.ports.model_gateway import ModelGatewayPort


class HarnessModelStep:
    def __init__(
        self,
        context_compiler: ContextCompilerPort | None = None,
        *,
        available_tools: tuple[ModelToolDefinition, ...] = (),
        conversation_compactor: ConversationCompactorPort | None = None,
        conversation_token_budget: int = 800,
    ) -> None:
        if conversation_token_budget <= 0:
            raise ValueError("conversation_token_budget must be positive")
        self._context_compiler = context_compiler
        self._available_tools = available_tools
        self._conversation_compactor = conversation_compactor
        self._conversation_token_budget = conversation_token_budget

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
            max_tokens=self._conversation_token_budget,
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
        return self.request_completion(messages, model_gateway, allow_tools=True)

    def request_completion(
        self,
        messages: list[SessionMessage],
        model_gateway: ModelGatewayPort,
        *,
        allow_tools: bool,
    ) -> ModelCompletion:
        return model_gateway.complete(
            messages,
            tools=self._available_tools if allow_tools else (),
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
