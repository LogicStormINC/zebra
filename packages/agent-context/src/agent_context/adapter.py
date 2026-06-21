from pathlib import Path

from agent_context.compiler import compile_context
from agent_context.models import ContextBudget, ContextCompileRequest
from agent_context.prompt_layout import build_prompt_layout


class LocalContextCompiler:
    def build_system_prompt(
        self,
        *,
        task_input: str,
        workspace_root: Path,
        max_tokens: int,
    ) -> str | None:
        compiled = compile_context(
            ContextCompileRequest(
                task_input=task_input,
                workspace_root=workspace_root,
                budget=ContextBudget(max_tokens=max_tokens),
            )
        )
        if not compiled.items:
            return None
        layout = build_prompt_layout(compiled)
        return layout.rendered_text
