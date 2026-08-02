from pathlib import Path

import pytest
from agent_core.domain.agent_definitions import (
    AgentDefinition,
    CompletionEvidenceContract,
    CompletionEvidenceRequirement,
)
from agent_tools.agent_definitions import resolve_agent_definition_context
from agent_tools.skills_scope import build_scoped_skill_roots
from zebra_agent_api.app import create_app
from zebra_agent_api.session_payloads import parse_create_session_payload
from zebra_agent_api.task_api import TaskReadApi, create_task
from zebra_agent_config import ApiSettings, ModelSettings, ZebraAgentSettings


def test_create_payload_carries_versioned_definition_and_contract() -> None:
    parsed = parse_create_session_payload(
        {
            "prompt": "Collect typed evidence.",
            "agent_definition": {
                "agent_id": "agent-neutral",
                "version": "1.0.0",
                "completion_contract": {
                    "version": "1",
                    "required_evidence": [
                        {"evidence_id": "lookup", "typed_evidence": ["lookup.ready"]}
                    ],
                },
            },
        }
    )

    assert not hasattr(parsed, "status")
    assert isinstance(parsed["agent_definition"], AgentDefinition)
    assert parsed["agent_definition"].version == "1.0.0"


def test_create_payload_rejects_unsupported_definition_reference() -> None:
    parsed = parse_create_session_payload(
        {
            "prompt": "Collect typed evidence.",
            "agent_definition": {
                "agent_id": "agent-neutral",
                "version": "1.0.0",
                "system_prompt_ref": "remote://untrusted",
            },
        }
    )

    assert parsed.status_code == 400


def test_create_payload_rejects_client_supplied_context_digest() -> None:
    parsed = parse_create_session_payload(
        {
            "prompt": "Collect typed evidence.",
            "agent_definition": {
                "agent_id": "agent-neutral",
                "version": "1.0.0",
                "resolved_context_digest": "a" * 64,
            },
        }
    )

    assert parsed.status_code == 400


def test_api_binds_skill_digest_and_worker_resolution_fails_closed_after_change(
    tmp_path: Path,
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
    database = tmp_path / "tasks.sqlite"
    settings = ZebraAgentSettings(
        profile="test",
        database_url=str(database),
        api=ApiSettings(auth_token=None),
        model=ModelSettings(
            provider="test",
            api_key_env="TEST_API_KEY",
            base_url="https://example.test",
            model="test-model",
        ),
        skill_roots_system=(str(skills),),
        skills_state_path=str(tmp_path / "skills-state.sqlite"),
    )
    response = create_app(database, settings=settings).create_session(
        {
            "prompt": "Use the trusted guidance.",
            "workspace": str(tmp_path),
            "agent_definition": {
                "agent_id": "agent-neutral",
                "version": "1.0.0",
                "skill_refs": ["skill://evidence"],
            },
        }
    )

    assert response.status_code == 201
    payload = response.body["agent_definition"]
    assert isinstance(payload, dict)
    bound = AgentDefinition.model_validate(payload)
    assert bound.resolved_context_digest is not None
    skill_file.write_text(
        skill_file.read_text(encoding="utf-8") + "Changed." + chr(10),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="digest"):
        resolve_agent_definition_context(
            bound,
            build_scoped_skill_roots(system=[skills]),
            require_digest=True,
        )


def test_task_create_and_read_retain_definition_version_and_contract(tmp_path) -> None:
    app = create_app(tmp_path / "tasks.sqlite")
    definition = AgentDefinition(
        agent_id="agent-neutral",
        version="1.0.0",
        completion_contract=CompletionEvidenceContract(
            required_evidence=(
                CompletionEvidenceRequirement(
                    evidence_id="lookup",
                    typed_evidence=("lookup.ready",),
                ),
            )
        ),
    )

    created = create_task(
        app,
        {
            "prompt": "Collect typed evidence.",
            "workspace": str(tmp_path),
            "agent_definition": definition.model_dump(mode="json"),
        },
        idempotency_key=None,
    )

    assert created.status_code == 201
    task_id = str(created.body["task_id"])
    read = TaskReadApi(app.database_path).get(task_id)
    assert read.status_code == 200
    assert read.body["workspace"]["agent_definition"] == definition.model_dump(mode="json")
