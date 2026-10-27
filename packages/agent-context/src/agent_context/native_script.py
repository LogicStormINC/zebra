"""A script Context provider contributes bounded data, never instructions/authority."""

from datetime import datetime
from pathlib import Path

from agent_core.application.native_script import (
    NativeScriptInvocationService,
    NativeScriptUnavailable,
)
from agent_core.domain.attachments import AttachmentContextInput
from agent_core.domain.messages import SessionMessage
from agent_core.domain.runtime_bundle_json import load_bundle_json
from agent_core.domain.script_bundle import ScriptBinding
from agent_core.ports.context_compiler import ConfirmedMemoryInput, RuntimeEvidenceInput
from agent_core.ports.conversation_compactor import ConversationCompactionResult

from agent_context.adapter import LocalContextCompiler


class NativeScriptContextCompiler:
    def __init__(
        self,
        base: LocalContextCompiler,
        service: NativeScriptInvocationService,
        binding: ScriptBinding,
    ) -> None:
        self._base, self._service, self._binding = base, service, binding

    def build_system_prompt(
        self,
        *,
        task_input: str,
        workspace_root: Path,
        max_tokens: int,
        runtime_evidence: tuple[RuntimeEvidenceInput, ...] = (),
        confirmed_memories: tuple[ConfirmedMemoryInput, ...] = (),
        attachments: tuple[AttachmentContextInput, ...] = (),
    ) -> str | None:
        result = self._service.invoke(
            self._binding, {"user_input": task_input}, logical_id="context"
        )
        if result.output_json is None:
            raise NativeScriptUnavailable("NATIVE_SCRIPT_CONTEXT_FAILED")
        data = load_bundle_json(result.output_json)
        evidence = RuntimeEvidenceInput(
            kind="native_script_context",
            summary=data["text"],
            metadata={"manifest_digest": self._binding.manifest.digest},
        )
        return self._base.build_system_prompt(
            task_input=task_input,
            workspace_root=workspace_root,
            max_tokens=max_tokens,
            runtime_evidence=(*runtime_evidence, evidence),
            confirmed_memories=confirmed_memories,
            attachments=attachments,
        )

    def compact_conversation(
        self,
        messages: tuple[SessionMessage, ...],
        *,
        user_goal: str,
        max_tokens: int,
        created_at: datetime,
    ) -> ConversationCompactionResult:
        return self._base.compact_conversation(
            messages, user_goal=user_goal, max_tokens=max_tokens, created_at=created_at
        )
