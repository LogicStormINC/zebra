from datetime import UTC, datetime

from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion, ModelToolDefinition
from agent_core.domain.tools import ToolCall, ToolResult
from agent_core.harness.models import HarnessTask
from agent_core.ports.context_compiler import ContextCompilerPort
from agent_core.ports.model_gateway import ModelGatewayPort


class HarnessModelStep:
    def __init__(
        self,
        context_compiler: ContextCompilerPort | None = None,
        *,
        available_tools: tuple[ModelToolDefinition, ...] = (),
    ) -> None:
        self._context_compiler = context_compiler
        self._available_tools = available_tools

    def request_initial_completion(
        self,
        task: HarnessTask,
        model_gateway: ModelGatewayPort,
        *,
        created_at: datetime | None = None,
    ) -> ModelCompletion:
        now = created_at or datetime.now(UTC)
        messages = self._build_initial_messages(task, created_at=now)
        return model_gateway.complete(messages, tools=self._available_tools)

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
        messages = self._build_initial_messages(task, created_at=now)
        messages.extend(
            (
                initial_completion.assistant_message.model_copy(
                    update={"tool_calls": (tool_call,)}
                ),
                SessionMessage(
                    message_id=new_message_id(),
                    role=MessageRole.TOOL,
                    content=tool_result.output or f"Tool {tool_result.status.value}.",
                    created_at=now,
                    tool_call_id=tool_call.provider_call_id
                    or str(tool_call.tool_call_id),
                ),
                SessionMessage(
                    message_id=new_message_id(),
                    role=MessageRole.USER,
                    content=(
                        "The requested tool has completed. Answer the original request "
                        "using its result. Do not request or invoke another tool."
                    ),
                    created_at=now,
                ),
            )
        )
        return model_gateway.complete(messages)

    def _build_initial_messages(
        self,
        task: HarnessTask,
        *,
        created_at: datetime,
    ) -> list[SessionMessage]:
        messages: list[SessionMessage] = []
        if self._context_compiler is not None and task.workspace_root is not None:
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
        messages.append(
            SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.USER,
                content=task.user_input,
                created_at=created_at,
            )
        )
        return messages
