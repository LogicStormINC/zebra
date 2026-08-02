from agent_core.domain.agent_definitions import (
    AgentDefinition,
    CompletionEvidenceContract,
    CompletionEvidenceRequirement,
)
from zebra_agent_api.app import create_app
from zebra_agent_api.session_payloads import parse_create_session_payload
from zebra_agent_api.task_api import TaskReadApi, create_task


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
