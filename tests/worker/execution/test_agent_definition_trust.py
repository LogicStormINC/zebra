from dataclasses import replace
from pathlib import Path

import pytest
import zebra_agent_worker.execution as worker_execution_module
from agent_core.domain.agent_definitions import AgentDefinition
from agent_tools import resolve_agent_definition_context
from agent_tools.skills_scope import build_scoped_skill_roots
from worker_execution_support import (
    _assistant_only_gateway,
    _build_execution_service,
    _seed_ready_session,
    _settings,
)
from zebra_agent_worker import WorkerExecutionError


def test_worker_rejects_changed_bound_skill_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skills = tmp_path / "system-skills"
    skill = skills / "evidence"
    skill.mkdir(parents=True)
    skill_file = skill / "SKILL.md"
    skill_file.write_text(
        chr(10).join(
            (
                "---",
                "name: evidence",
                "description: evidence guidance",
                "---",
                "Original guidance.",
                "",
            )
        ),
        encoding="utf-8",
    )
    roots = build_scoped_skill_roots(system=[skills])
    definition = AgentDefinition(
        agent_id="agent-neutral",
        version="1.0.0",
        skill_refs=("skill://evidence",),
    )
    context = resolve_agent_definition_context(definition, roots)
    assert context is not None
    bound = definition.model_copy(
        update={"resolved_context_digest": context.resolved_context_digest}
    )
    skill_file.write_text(
        skill_file.read_text(encoding="utf-8") + "Changed." + chr(10),
        encoding="utf-8",
    )

    database = tmp_path / "worker.sqlite"
    session_id = _seed_ready_session(database, tmp_path)
    original_recover_task = worker_execution_module.recover_task

    def recover_task_with_definition(*args, **kwargs):
        return replace(
            original_recover_task(*args, **kwargs),
            agent_definition=bound,
        )

    settings = replace(
        _settings(database),
        skill_roots_system=(str(skills),),
        skills_state_path=str(tmp_path / "skills-state.sqlite"),
    )
    monkeypatch.setattr(worker_execution_module, "recover_task", recover_task_with_definition)
    monkeypatch.setattr(
        worker_execution_module,
        "build_model_gateway",
        lambda settings: _assistant_only_gateway(settings=settings),
    )

    with pytest.raises(WorkerExecutionError, match="digest"):
        _build_execution_service(database, settings=settings).execute_session(
            session_id,
            worker_id="worker-agent-definition-trust",
        )
