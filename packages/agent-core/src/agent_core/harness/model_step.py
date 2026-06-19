from datetime import UTC, datetime

from agent_core.domain.identifiers import new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.modeling import ModelCompletion
from agent_core.harness.models import HarnessTask
from agent_core.ports.model_gateway import ModelGatewayPort


class HarnessModelStep:
    def request_initial_completion(
        self,
        task: HarnessTask,
        model_gateway: ModelGatewayPort,
        *,
        created_at: datetime | None = None,
    ) -> ModelCompletion:
        now = created_at or datetime.now(UTC)
        messages = [
            SessionMessage(
                message_id=new_message_id(),
                role=MessageRole.USER,
                content=task.user_input,
                created_at=now,
            )
        ]
        return model_gateway.complete(messages)
