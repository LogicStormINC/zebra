import pytest
from agent_core.application.mock_model import ScriptedModelGateway, ScriptedModelResponse
from agent_core.domain.agent_definitions import AgentDefinition
from agent_core.domain.identifiers import new_artifact_id, new_event_id, new_message_id
from agent_core.domain.messages import MessageRole, SessionMessage
from agent_core.domain.model_media import (
    ModelInputModality,
    ModelMediaCapabilities,
    ModelMediaInput,
)
from agent_core.domain.modeling import ModelCompletion
from agent_core.domain.sessions import SessionStatus
from agent_runtime import run_local_harness


class DeclaredMediaGateway(ScriptedModelGateway):
    def __init__(self, media_capabilities: ModelMediaCapabilities) -> None:
        super().__init__(
            responses=(
                ScriptedModelResponse(completion=_completion("Completed.")),
            )
        )
        self.media_capabilities = media_capabilities

    def bind_media_resolver(self, _media_resolver) -> None:
        pass

    def estimate_media_tokens(self, media_inputs: tuple[ModelMediaInput, ...]) -> int:
        return len(media_inputs)


@pytest.mark.parametrize(
    ("image_capable", "with_media"),
    ((True, False), (True, True), (False, True)),
)
def test_run_local_harness_uses_declared_model_media_capability(
    tmp_path,
    image_capable: bool,
    with_media: bool,
) -> None:
    gateway = DeclaredMediaGateway(
        ModelMediaCapabilities(
            input_modalities=(
                frozenset({ModelInputModality.TEXT, ModelInputModality.IMAGE})
                if image_capable
                else frozenset({ModelInputModality.TEXT})
            ),
            supports_tools_with_media=image_capable,
            max_image_count=1 if image_capable else 0,
            max_image_bytes=1_024 if image_capable else 0,
            max_total_image_bytes=1_024 if image_capable else 0,
            image_media_types=frozenset({"image/png"}) if image_capable else frozenset(),
        )
    )
    result = run_local_harness(
        prompt="Use the declared model capability.",
        title="Declared media capability",
        workspace_root=tmp_path.resolve(),
        model_gateway=gateway,
        agent_definition=AgentDefinition(
            agent_id="agent-neutral",
            version="1.0.0",
            required_model_capabilities=("image",),
        ),
        media_inputs=(_media_input(),) if with_media else (),
    )

    expected = SessionStatus.COMPLETED if image_capable else SessionStatus.FAILED
    assert result.session.status is expected
    assert bool(gateway.requests) is image_capable


def _completion(content: str) -> ModelCompletion:
    return ModelCompletion(
        assistant_message=SessionMessage(
            message_id=new_message_id(),
            role=MessageRole.ASSISTANT,
            content=content,
            created_at=_created_at(),
        )
    )


def _created_at():
    from datetime import UTC, datetime

    return datetime(2026, 8, 2, 12, 0, tzinfo=UTC)


def _media_input() -> ModelMediaInput:
    return ModelMediaInput(
        artifact_id=new_artifact_id(),
        media_type="image/png",
        sha256="a" * 64,
        size_bytes=32,
        display_name="evidence.png",
        ordinal=0,
        source_message_id=new_event_id(),
    )
